# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""
Stock ledger chain check and repair.

Every Stock Ledger Entry should satisfy
    stock_value_difference == stock_value - previous row's stock_value
within its item-warehouse, in ERPNext's posting order. The old BNS transfer-rate sync wrote
stock_value_difference by hand and broke this on internal receipts; a repost that dies halfway
can break it too. A break hides every later break in the same item-warehouse, so the repair
reposts from the FIRST break of each pair.

The repair only queues Repost Item Valuation entries. ERPNext's scheduler runs queued reposts
one at a time, oldest posting first, so this never runs alongside ERPNext's own hourly repost.
Run it again after the queue drains: a receiver whose sender was broken gets a fresh transfer
rate from the sender's repost (and the BNS after-repost sync queues its repost), and anything
still broken shows up then.

    bench --site <site> execute \
        business_needed_solutions.bns_branch_accounting.ledger_chain_repair.find_chain_breaks
    bench --site <site> execute \
        business_needed_solutions.bns_branch_accounting.ledger_chain_repair.repair_chain_breaks \
        --kwargs "{'dry_run': 0}"
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate

REPOST_ITEM_VALUATION = "Repost Item Valuation"
DEFAULT_TOLERANCE = 0.01  # one paisa


def find_chain_breaks(
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	from_date: str | None = None,
	tolerance: float = DEFAULT_TOLERANCE,
) -> list[dict]:
	"""The first row per item-warehouse where difference != step, oldest first.

	The previous value is taken over the pair's whole history, so ``from_date`` only limits
	which breaks are reported, never how they are computed.
	"""
	conditions = ["is_cancelled = 0"]
	values = {"tolerance": flt(tolerance)}
	for field, value in (("company", company), ("item_code", item_code), ("warehouse", warehouse)):
		if value:
			conditions.append(f"{field} = %({field})s")
			values[field] = value
	outer = ""
	if from_date:
		outer = "AND posting_date >= %(from_date)s"
		values["from_date"] = getdate(from_date)

	rows = frappe.db.sql(
		f"""
		SELECT name, company, item_code, warehouse, posting_date, posting_time, voucher_type,
			voucher_no, actual_qty, stock_value_difference, stock_value, prev_value
		FROM (
			SELECT name, company, item_code, warehouse, posting_date, posting_time, creation,
				voucher_type, voucher_no, actual_qty, stock_value_difference, stock_value,
				-- MariaDB's LAG takes no default argument: the first row's previous value is 0.
				COALESCE(LAG(stock_value, 1) OVER (
					PARTITION BY item_code, warehouse
					ORDER BY posting_date, posting_time, creation, name
				), 0) AS prev_value
			FROM `tabStock Ledger Entry`
			WHERE {" AND ".join(conditions)}
		) chain
		WHERE ABS(stock_value_difference - (stock_value - prev_value)) > %(tolerance)s
			{outer}
		ORDER BY posting_date, posting_time, creation, name
		""",
		values,
		as_dict=True,
	)

	first_breaks: dict[tuple, dict] = {}
	for row in rows:
		key = (row.item_code, row.warehouse)
		if key in first_breaks:
			continue
		row.expected_difference = flt(flt(row.stock_value) - flt(row.prev_value), 9)
		row.gap = flt(flt(row.stock_value_difference) - row.expected_difference, 9)
		first_breaks[key] = row
	return list(first_breaks.values())


def repair_chain_breaks(
	company: str | None = None,
	item_code: str | None = None,
	warehouse: str | None = None,
	from_date: str | None = None,
	tolerance: float = DEFAULT_TOLERANCE,
	dry_run: int = 1,
) -> dict:
	"""Queue one Item-and-Warehouse Repost Item Valuation per broken pair, from its first break.

	Read-only when ``dry_run`` is set (the default). Pairs that already have a pending repost
	starting at or before the break are skipped: that repost re-prices the break anyway.
	"""
	frappe.only_for("System Manager")
	dry_run = cint(dry_run)
	breaks = find_chain_breaks(company, item_code, warehouse, from_date, tolerance)

	from erpnext.controllers.stock_controller import create_repost_item_valuation_entry

	queued, skipped = [], []
	for brk in breaks:
		entry = {
			"item_code": brk.item_code,
			"warehouse": brk.warehouse,
			"posting_date": str(brk.posting_date),
			"posting_time": str(brk.posting_time),
			"voucher": f"{brk.voucher_type} {brk.voucher_no}",
			"gap": brk.gap,
		}
		if _pending_repost_covers(brk):
			skipped.append(entry)
			continue
		if not dry_run:
			create_repost_item_valuation_entry(
				{
					"based_on": "Item and Warehouse",
					"item_code": brk.item_code,
					"warehouse": brk.warehouse,
					"posting_date": brk.posting_date,
					"posting_time": brk.posting_time,
					"company": brk.company,
					"allow_zero_rate": 1,
				}
			)
		queued.append(entry)

	# No explicit commit: bench execute and web requests commit on success, and a failure
	# part-way leaves nothing half-queued.
	return {
		"dry_run": dry_run,
		"breaks": len(breaks),
		("would_queue" if dry_run else "queued"): queued,
		"skipped_pending": skipped,
	}


def _pending_repost_covers(brk) -> bool:
	pending = frappe.get_all(
		REPOST_ITEM_VALUATION,
		filters={
			"docstatus": 1,
			"status": ("in", ("Queued", "In Progress")),
			"based_on": "Item and Warehouse",
			"item_code": brk.item_code,
			"warehouse": brk.warehouse,
		},
		fields=["posting_date", "posting_time"],
	)
	break_at = (getdate(brk.posting_date), str(brk.posting_time))
	return any((getdate(p.posting_date), str(p.posting_time)) <= break_at for p in pending)


def find_unconserved_transfer_receipts(
	company: str | None = None,
	from_date: str | None = None,
	tolerance: float = DEFAULT_TOLERANCE,
) -> list[dict]:
	"""BNS internal receipts whose value difference is not qty x incoming (transfer) rate.

	After the in-engine conservation these are the rows where full conservation would have
	needed an invalid rate (e.g. a zero-cost transfer into a negative bin that ends positive):
	the remainder stays in the receipt and therefore in Stock-in-Transit, for review.
	Only receipts on or after the Accounting Rewrite cutoff are checked; earlier ones were
	never transfer-priced.
	"""
	from business_needed_solutions.bns_branch_accounting.utils import _get_accounting_rewrite_cutoff_date

	cutoff = _get_accounting_rewrite_cutoff_date()
	if not cutoff:
		return []
	start = max(getdate(cutoff), getdate(from_date)) if from_date else getdate(cutoff)

	values = {"tolerance": flt(tolerance), "start": start, "company": company}
	company_condition = "AND sle.company = %(company)s" if company else ""
	# Scope mirrors the transfer-rate lookups: PRs linked to a BNS source (DN or SI), and
	# update-stock PIs from a BNS internal supplier.
	scopes = (
		(
			"Purchase Receipt",
			"(doc.is_bns_internal_supplier = 1 OR IFNULL(doc.bns_inter_company_reference, '') != '')",
		),
		("Purchase Invoice", "(doc.is_bns_internal_supplier = 1 AND doc.update_stock = 1)"),
	)

	rows = []
	for voucher_type, scope in scopes:
		meta = frappe.get_meta(voucher_type)
		if not (meta.has_field("is_bns_internal_supplier") and meta.has_field("bns_inter_company_reference")):
			continue
		rows += frappe.db.sql(
			f"""
			SELECT sle.name, sle.voucher_type, sle.voucher_no, sle.item_code, sle.warehouse,
				sle.posting_date, sle.actual_qty, sle.incoming_rate, sle.stock_value_difference,
				sle.qty_after_transaction,
				ROUND(sle.stock_value_difference - sle.actual_qty * sle.incoming_rate, 6) AS residual
			FROM `tabStock Ledger Entry` sle
			JOIN `tab{voucher_type}` doc ON doc.name = sle.voucher_no
			WHERE sle.voucher_type = %(voucher_type)s
				AND sle.is_cancelled = 0 AND sle.actual_qty > 0
				AND sle.posting_date >= %(start)s {company_condition}
				AND doc.docstatus = 1 AND {scope}
				AND ABS(sle.stock_value_difference - sle.actual_qty * sle.incoming_rate) > %(tolerance)s
			ORDER BY sle.posting_date, sle.posting_time, sle.creation
			""",
			{**values, "voucher_type": voucher_type},
			as_dict=True,
		)
	return rows


def find_batch_receipts_at_wrong_rate(
	company: str | None = None,
	from_date: str | None = None,
	voucher_types: tuple = ("Purchase Receipt", "Purchase Invoice"),
) -> list[dict]:
	"""BNS internal receipts (PR, update-stock PI) whose serial/batch bundle is not priced at
	the transfer rate.

	Before the bundle patch, ERPNext priced these bundles at the receipt's own valuation rate
	(the invoice rate) while the SLE showed the transfer rate, so the stock value was wrong
	although every document matched. Each voucher is listed once with the value gap
	(transfer value - booked value). Only receipts on or after the Accounting Rewrite cutoff.
	"""
	from business_needed_solutions.bns_branch_accounting.utils import (
		_bundle_entries_off_rate,
		_get_accounting_rewrite_cutoff_date,
		_get_bns_transfer_rate_for_sle,
	)

	cutoff = _get_accounting_rewrite_cutoff_date()
	if not cutoff:
		return []
	start = max(getdate(cutoff), getdate(from_date)) if from_date else getdate(cutoff)
	company_condition = "AND sle.company = %(company)s" if company else ""
	rows = frappe.db.sql(
		f"""
		SELECT sle.name, sle.voucher_type, sle.voucher_no, sle.voucher_detail_no, sle.item_code,
			sle.warehouse, sle.posting_date, sle.actual_qty, sle.stock_value_difference,
			sle.serial_and_batch_bundle
		FROM `tabStock Ledger Entry` sle
		WHERE sle.voucher_type IN %(voucher_types)s
			AND sle.is_cancelled = 0 AND sle.actual_qty > 0
			AND IFNULL(sle.serial_and_batch_bundle, '') != ''
			AND sle.posting_date >= %(start)s {company_condition}
		ORDER BY sle.posting_date, sle.posting_time, sle.creation
		""",
		{"start": start, "company": company, "voucher_types": tuple(voucher_types)},
		as_dict=True,
	)
	out: dict[tuple, dict] = {}
	for r in rows:
		rate = _get_bns_transfer_rate_for_sle(r)
		if rate is None:
			continue
		if not _bundle_entries_off_rate(r.serial_and_batch_bundle, rate):
			continue
		entries = frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": r.serial_and_batch_bundle},
			fields=["qty", "incoming_rate"],
		)
		gap = flt(flt(r.actual_qty) * flt(rate) - flt(r.stock_value_difference), 2)
		key = (r.voucher_type, r.voucher_no)
		voucher = out.setdefault(key, {
			"voucher_type": r.voucher_type, "voucher_no": r.voucher_no,
			"posting_date": r.posting_date, "rows": 0, "gap": 0.0, "items": [],
		})
		voucher["rows"] += 1
		voucher["gap"] = flt(voucher["gap"] + gap, 2)
		voucher["items"].append({
			"item_code": r.item_code, "qty": flt(r.actual_qty), "transfer_rate": flt(rate),
			"bundle_rates": sorted({flt(e.incoming_rate, 2) for e in entries}),
			"booked": flt(r.stock_value_difference, 2), "gap": gap,
		})
	return list(out.values())


def repair_batch_receipts_at_wrong_rate(
	company: str | None = None, from_date: str | None = None, dry_run: int = 1
) -> dict:
	"""Queue one Transaction Repost Item Valuation per receipt found by
	find_batch_receipts_at_wrong_rate. The repost re-prices the bundle at the transfer rate
	(bundle patch), revalues every later row and rebuilds GL; the BNS after-repost hooks
	rewrite the transfer GL. dry_run (default) only lists them.

	    bench --site <site> execute \
	        business_needed_solutions.bns_branch_accounting.ledger_chain_repair.repair_batch_receipts_at_wrong_rate \
	        --kwargs "{'dry_run': 0}"
	"""
	from business_needed_solutions.bns_branch_accounting.transfer_value_conservation import (
		queue_transfer_rate_repost,
	)

	found = find_batch_receipts_at_wrong_rate(company=company, from_date=from_date)
	result = {
		"dry_run": bool(cint(dry_run)), "vouchers": len(found),
		"gap": flt(sum(v["gap"] for v in found), 2), "queued": [], "not_queued": [], "found": found,
	}
	if cint(dry_run):
		return result
	for v in found:
		if queue_transfer_rate_repost(v["voucher_type"], v["voucher_no"], context="batch_bundle_rate_repair"):
			result["queued"].append(v["voucher_no"])
		else:
			result["not_queued"].append(v["voucher_no"])
	if not frappe.flags.in_test:
		frappe.db.commit()
	return result
