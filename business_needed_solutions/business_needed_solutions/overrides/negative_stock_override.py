"""
Business Needed Solutions - Negative Stock Cutoff

Adds a date-gated negative-stock restriction on top of ERPNext's Stock Settings.

Behaviour:
    - posting_date > cutoff_date      → BLOCKED for everyone (no role bypass).
    - posting_date ≤ cutoff_date      → BLOCKED unless user has an override role.
    - Feature OFF / no cutoff set     → no-op (ERPNext's own rules apply).

Why this layer instead of a custom before_submit balance check?
    A document-level pre-flight that re-derives "current stock" from `Bin`
    diverges from ERPNext's authoritative ledger semantics:

        * Multi-leg Material Transfers through an In-Transit warehouse:
          row 1 (+50 to In-Transit) and row 2 (-50 from In-Transit) net to
          zero on the warehouse, but Bin.actual_qty reads 0 BEFORE the
          submit, so a naive shortfall check fires.
        * Future SLEs may go negative after this insertion even when the
          current balance looks fine.
        * Serial / Batch / SBB bundles, reposts, repacks all have edge
          cases that ERPNext already handles.

    The right hook is Stock Ledger Entry `validate`. By the time row 2's SLE
    validates, row 1's SLE is already inserted (ERPNext processes SLEs in
    idx order, locking the row), so `get_previous_sle` returns the running
    balance including intra-doc movements. `get_future_sle_with_negative_qty`
    catches downstream impact. This is exactly the algorithm ERPNext uses in
    `validate_negative_qty_in_future_sle` — we just invoke it independently
    of `Stock Settings.allow_negative_stock`.

Concurrency:
    ERPNext acquires row-level locks on Bin / Stock Ledger Entry during the
    submit transaction. Our hook runs inside that transaction, so the
    "lock → simulate → submit or throw" sequence the user wants is provided
    by ERPNext's existing transactional flow.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate
from erpnext.stock.stock_ledger import (
	NegativeStockError,
	get_previous_sle,
	get_future_sle_with_negative_qty,
	get_future_sle_with_negative_batch_qty,
	is_negative_with_precision,
)


def validate_sle_negative_stock_cutoff(doc, method=None):
	"""
	doc_event: Stock Ledger Entry `validate`.

	Runs once per SLE row. When the BNS cutoff rule applies for this
	row's posting_date and the current user, enforce negative-stock
	prevention using ERPNext's own helpers.
	"""
	if doc.is_cancelled:
		return

	if not _should_restrict(doc.posting_date):
		return

	if flt(doc.actual_qty) >= 0 and doc.voucher_type != "Stock Reconciliation":
		# Only outgoing SLEs (and stock recos) can deplete a warehouse.
		return

	# Stock Reconciliation with a positive bundle qty is a non-issue.
	if (
		doc.voucher_type == "Stock Reconciliation"
		and flt(doc.actual_qty) < 0
		and doc.serial_and_batch_bundle
		and flt(frappe.db.get_value("Stock Reconciliation Item", doc.voucher_detail_no, "qty")) > 0
	):
		return

	args = _sle_args(doc)

	# Step 1 — would this SLE itself drive the warehouse negative once
	# the previous SLE balance and the current actual_qty are combined?
	previous = get_previous_sle(args) or {}
	current_balance = flt(previous.get("qty_after_transaction"))
	reserved = _get_reserved_stock(doc)
	qty_after_current = flt(current_balance + flt(doc.actual_qty) - reserved, _precision())

	if qty_after_current < 0 and abs(qty_after_current) > _diff_threshold():
		_throw(
			abs(qty_after_current),
			doc.item_code,
			doc.warehouse,
			doc.posting_date,
			doc.posting_time,
			doc.voucher_type,
			doc.voucher_no,
		)

	# Step 2 — would any FUTURE SLE go negative because of this insertion?
	neg_sle = get_future_sle_with_negative_qty(args)
	if is_negative_with_precision(neg_sle):
		row = neg_sle[0]
		_throw(
			abs(row["qty_after_transaction"]),
			doc.item_code,
			doc.warehouse,
			row["posting_date"],
			row["posting_time"],
			row["voucher_type"],
			row["voucher_no"],
		)

	# Step 3 — batch-level check (legacy batch_no or Serial & Batch Bundle).
	if doc.batch_no:
		_check_batch(args, doc.batch_no)
	elif doc.serial_and_batch_bundle:
		_check_sbb_batches(args, doc.serial_and_batch_bundle)


def _should_restrict(posting_date):
	"""Cutoff + role policy. See module docstring."""
	if frappe.flags.get("through_repost_item_valuation"):
		return False

	if not cint(
		frappe.db.get_single_value("BNS Settings", "allow_negative_stock_override", cache=True)
	):
		return False

	cutoff = frappe.db.get_single_value(
		"BNS Settings", "negative_stock_cutoff_date", cache=True
	)
	if not cutoff or not posting_date:
		return False

	if getdate(posting_date) > getdate(cutoff):
		return True  # past cutoff: no bypass, ever

	override_roles = _get_override_roles()
	if override_roles:
		user_roles = set(frappe.get_roles(frappe.session.user))
		if override_roles & user_roles:
			return False

	return True


def _get_override_roles():
	"""Cached set of roles allowed to bypass on or before the cutoff."""
	cache_key = "_bns_negative_stock_override_roles"
	if cache_key not in frappe.flags:
		roles = frappe.get_all(
			"Has Role",
			filters={
				"parenttype": "BNS Settings",
				"parentfield": "negative_stock_override_roles",
			},
			pluck="role",
		)
		frappe.flags[cache_key] = set(roles)
	return frappe.flags[cache_key]


def _sle_args(doc):
	"""Build the args dict expected by ERPNext's stock_ledger helpers."""
	from erpnext.stock.utils import get_combine_datetime

	args = frappe._dict(
		{
			"item_code": doc.item_code,
			"warehouse": doc.warehouse,
			"actual_qty": flt(doc.actual_qty),
			"posting_date": doc.posting_date,
			"posting_time": doc.posting_time,
			"voucher_type": doc.voucher_type,
			"voucher_no": doc.voucher_no,
			"voucher_detail_no": doc.voucher_detail_no,
			"batch_no": doc.batch_no,
			"serial_and_batch_bundle": doc.serial_and_batch_bundle,
			"name": doc.name,
			"sle": doc.name,
		}
	)
	args["posting_datetime"] = doc.posting_datetime or get_combine_datetime(
		doc.posting_date, doc.posting_time
	)
	return args


def _get_reserved_stock(doc):
	"""Reserved stock from Bin — matches ERPNext's diff calculation."""
	from erpnext.stock.utils import get_or_make_bin

	bin_name = get_or_make_bin(doc.item_code, doc.warehouse)
	return flt(frappe.db.get_value("Bin", bin_name, "reserved_stock"))


def _precision():
	return cint(frappe.db.get_default("float_precision")) or 2


def _diff_threshold():
	"""Same threshold ERPNext uses in validate_negative_stock."""
	prec = _precision()
	return 0.0001 if prec <= 4 else 10 ** (-prec)


def _check_batch(args, batch_no):
	batch_args = dict(args)
	batch_args["batch_no"] = batch_no
	neg = get_future_sle_with_negative_batch_qty(batch_args)
	if is_negative_with_precision(neg, is_batch=True):
		row = neg[0]
		_throw_batch(
			abs(row["cumulative_total"]),
			batch_no,
			args["warehouse"],
			row["posting_date"],
			row["posting_time"],
			row["voucher_type"],
			row["voucher_no"],
		)


def _check_sbb_batches(args, bundle_id):
	from erpnext.stock.serial_batch_bundle import get_batch_nos

	for batch_no in (get_batch_nos(bundle_id) or {}):
		_check_batch(args, batch_no)


def _throw(deficit, item_code, warehouse, posting_date, posting_time, voucher_type, voucher_no):
	cutoff = frappe.db.get_single_value(
		"BNS Settings", "negative_stock_cutoff_date", cache=True
	)
	cutoff_label = frappe.format_value(cutoff, {"fieldtype": "Date"}) if cutoff else ""
	msg = _(
		"{0} units of {1} needed in {2} on {3} {4} for {5} to complete this transaction."
	).format(
		frappe.bold(deficit),
		frappe.get_desk_link("Item", item_code, show_title_with_name=True),
		frappe.get_desk_link("Warehouse", warehouse),
		posting_date,
		posting_time or "",
		frappe.get_desk_link(voucher_type, voucher_no),
	)
	msg += "<br><br>" + _(
		"Blocked by BNS negative-stock cutoff ({0})."
	).format(cutoff_label)
	frappe.throw(msg, NegativeStockError, title=_("Insufficient Stock"))


def _throw_batch(deficit, batch_no, warehouse, posting_date, posting_time, voucher_type, voucher_no):
	cutoff = frappe.db.get_single_value(
		"BNS Settings", "negative_stock_cutoff_date", cache=True
	)
	cutoff_label = frappe.format_value(cutoff, {"fieldtype": "Date"}) if cutoff else ""
	msg = _(
		"{0} units of {1} needed in {2} on {3} {4} for {5} to complete this transaction."
	).format(
		frappe.bold(deficit),
		frappe.get_desk_link("Batch", batch_no),
		frappe.get_desk_link("Warehouse", warehouse),
		posting_date,
		posting_time or "",
		frappe.get_desk_link(voucher_type, voucher_no),
	)
	msg += "<br><br>" + _(
		"Blocked by BNS negative-stock cutoff ({0})."
	).format(cutoff_label)
	frappe.throw(msg, NegativeStockError, title=_("Insufficient Stock for Batch"))
