# Why:
# The Common Party square-off posts a balanced contra Journal Entry against
# the Customer's Debtors account and the linked Supplier's Creditors account.
# That fixes the GL totals but the underlying Sales Invoices and Purchase
# Invoices on each side still show their original outstanding_amount — they
# stay "open" in ERPNext's Accounts Receivable / Payable reports.
#
# This module wraps ERPNext's Payment Reconciliation tool so that:
#   (a) BEFORE the square-off we FIFO-match any stray Payment Entries against
#       their invoices, so the crossed-balance calculation sees the true net.
#   (b) AFTER the square-off we run Payment Reconciliation again, which picks
#       up the newly posted contra JV (it has party_type/party on its legs,
#       so PR treats it as a payment) and FIFO-allocates its debit/credit
#       lines against the open Sales / Purchase Invoices on each side.
#
# Net effect: one button on BNS Dashboard (or one scheduled tick) moves the
# ledger from "crossed balances on raw GL" all the way to "specific invoices
# closed, Balance Sheet correct, Accounts Receivable report empty for that
# party".
#
# FIFO is built into ERPNext's allocate_entries() — verified in
# erpnext/accounts/doctype/payment_reconciliation/payment_reconciliation.py
# lines 149-152 (payments sorted by posting_date) and 376-378 (invoices
# sorted by posting_date) before the allocation loop.

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate, now_datetime, nowdate

from erpnext.accounts.party import get_party_account


_PARTY_TYPES = ("Customer", "Supplier")


def _list_companies_for_reconcile():
	"""Indirection so tests can monkey-patch without mocking frappe.get_all."""
	return frappe.get_all("Company", pluck="name")


def _fiscal_years_back(years: int):
	today = getdate(nowdate())
	earliest = frappe.db.sql(
		"""select year_start_date from `tabFiscal Year`
		where %(d)s between year_start_date and year_end_date and disabled = 0
		order by year_start_date desc limit 1""",
		{"d": today},
		as_dict=False,
	)
	if not earliest:
		return None
	start = getdate(earliest[0][0])
	for _ in range(max(0, years - 1)):
		prev = frappe.db.sql(
			"""select year_start_date from `tabFiscal Year`
			where year_end_date < %(d)s and disabled = 0
			order by year_end_date desc limit 1""",
			{"d": start},
			as_dict=False,
		)
		if not prev:
			break
		start = getdate(prev[0][0])
	return start


def _resolve_window(window_setting, company):
	"""Map BNS Settings 'common_party_reconcile_window' to (from_date, to_date).

	- 'All time' -> (None, None)
	- 'Last 2 Fiscal Years' -> (start of FY two back, today)
	- 'Since Accounting Rewrite Cutoff' -> (accounting rewrite cutoff date, today)
	"""
	label = (window_setting or "All time").strip()
	if label == "All time":
		return None, None
	if label == "Last 2 Fiscal Years":
		start = _fiscal_years_back(2)
		return (start, getdate(nowdate())) if start else (None, None)
	if label == "Since Accounting Rewrite Cutoff":
		try:
			from business_needed_solutions.bns_branch_accounting.utils import (
				_get_accounting_rewrite_cutoff_date,
			)

			cutoff = _get_accounting_rewrite_cutoff_date()
			if cutoff:
				return getdate(cutoff), getdate(nowdate())
		except Exception:
			pass
		return None, None
	return None, None


def _party_account_has_balance(party_type, party, account, company):
	"""Cheap pre-filter: signed balance on party account. Non-zero -> candidate."""
	gle = frappe.qb.DocType("GL Entry")
	q = (
		frappe.qb.from_(gle)
		.select(Sum(gle.debit - gle.credit).as_("bal"))
		.where(gle.is_cancelled == 0)
		.where(gle.company == company)
		.where(gle.account == account)
		.where(gle.party_type == party_type)
		.where(gle.party == party)
	)
	row = q.run(as_dict=True)
	return flt(row[0].bal) if row and row[0].bal is not None else 0.0


def reconcile_single_party(
	company: str,
	party_type: str,
	party: str,
	window=None,
	include_advances: bool = True,
	ignore_permissions: bool = True,
) -> dict:
	"""Run ERPNext's Payment Reconciliation tool for exactly one party.

	Returns a summary dict: {party, account, reconciled_rows, skipped_reason, error}.
	Wrapped in try/except — a single bad party never kills a batch caller.
	"""
	# Why: use a savepoint so PR's cancel-and-rewrite-PE-references cycle can
	# fail on one party without dragging the whole batch into a rollback.
	sp = frappe.db.savepoint("bns_reconcile_single_party")
	try:
		if party_type not in _PARTY_TYPES:
			return {"party": party, "skipped_reason": f"unsupported party_type {party_type}"}
		try:
			account = get_party_account(party_type, party, company)
		except Exception as exc:
			return {"party": party, "skipped_reason": f"get_party_account failed: {exc}"}
		if not account:
			return {"party": party, "skipped_reason": "no party account"}

		# Cheap pre-filter: if the party account has zero signed balance there
		# are no matched/unmatched halves to worry about — nothing to do.
		if _party_account_has_balance(party_type, party, account, company) == 0:
			return {"party": party, "account": account, "skipped_reason": "zero balance"}

		from_date, to_date = (None, None)
		if window:
			from_date, to_date = _resolve_window(window, company)

		pr = frappe.new_doc("Payment Reconciliation")
		pr.company = company
		pr.party_type = party_type
		pr.party = party
		pr.receivable_payable_account = account
		if from_date:
			pr.from_invoice_date = from_date
			pr.from_payment_date = from_date
		if to_date:
			pr.to_invoice_date = to_date
			pr.to_payment_date = to_date
		if ignore_permissions:
			pr.flags.ignore_permissions = True

		pr.get_unreconciled_entries()

		payments = list(pr.payments or [])
		if not include_advances:
			payments = [p for p in payments if not getattr(p, "is_advance", 0)]

		if not pr.invoices or not payments:
			return {
				"party": party,
				"account": account,
				"skipped_reason": "no invoices or no payments to match",
				"invoices": len(pr.invoices or []),
				"payments": len(payments),
			}

		pr.allocate_entries(
			frappe._dict(
				{
					"invoices": [x.as_dict() for x in pr.invoices],
					"payments": [p.as_dict() for p in payments],
				}
			)
		)

		allocation_rows = len(pr.allocation or [])
		if allocation_rows == 0:
			return {
				"party": party,
				"account": account,
				"skipped_reason": "allocate_entries produced zero rows",
			}

		pr.reconcile()
		return {
			"party": party,
			"account": account,
			"reconciled_rows": allocation_rows,
			"invoices_touched": len(pr.invoices or []),
			"payments_touched": len(payments),
		}
	except Exception as exc:
		frappe.db.rollback(save_point=sp)
		frappe.log_error(
			title=f"BNS auto reconcile failed for {party_type} {party}",
			message=frappe.get_traceback(),
		)
		return {"party": party, "error": str(exc)}


def _iter_parties_for_scope(company, scope, party_types):
	"""Yield (party_type, party) tuples according to the reconciliation scope."""
	scope = (scope or "All Customers + All Suppliers").strip()
	seen = set()

	if scope == "Only Party-Linked Parties":
		links = frappe.get_all(
			"Party Link",
			fields=["primary_role", "primary_party", "secondary_role", "secondary_party"],
		)
		for link in links:
			for role_field, party_field in (
				("primary_role", "primary_party"),
				("secondary_role", "secondary_party"),
			):
				role = link.get(role_field)
				p = link.get(party_field)
				if role in party_types and p and (role, p) not in seen:
					seen.add((role, p))
					yield role, p
		return

	if scope == "Only Parties With Crossed Balances":
		# Defer the import — common_party_squareoff imports us for the pre/post
		# hook wrap, so we must not import it at module load time.
		from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
			compute_linked_party_net_positions,
		)

		pairs = compute_linked_party_net_positions(company)
		for pair in pairs:
			for role_field, party_field in (
				("primary_party_type", "primary_party"),
				("secondary_party_type", "secondary_party"),
			):
				role = pair.get(role_field)
				p = pair.get(party_field)
				if role in party_types and p and (role, p) not in seen:
					seen.add((role, p))
					yield role, p
		return

	# Default: every active Customer and every active Supplier.
	if "Customer" in party_types:
		for name in frappe.get_all("Customer", filters={"disabled": 0}, pluck="name"):
			key = ("Customer", name)
			if key not in seen:
				seen.add(key)
				yield "Customer", name
	if "Supplier" in party_types:
		for name in frappe.get_all("Supplier", filters={"disabled": 0}, pluck="name"):
			key = ("Supplier", name)
			if key not in seen:
				seen.add(key)
				yield "Supplier", name


def reconcile_all_parties(
	company: str,
	window=None,
	include_advances: bool = True,
	party_types=_PARTY_TYPES,
	scope=None,
	party_filter=None,
) -> dict:
	"""Batch runner. Iterate parties per scope; call reconcile_single_party.

	If `party_filter` is supplied, it must be a set/iterable of
	``(party_type, party)`` tuples — the iterator yields only those parties.
	Used by the dashboard "Run Reconciliation" button when the accountant has
	selected a subset of rows from the preview table.

	Returns summary: {company, scope, window, reconciled, skipped, errors,
	total_invoices_touched, total_allocations}.
	"""
	started_at = now_datetime()
	summary = {
		"company": company,
		"scope": scope,
		"window": window,
		"started_at": str(started_at),
		"reconciled_parties": [],
		"skipped_parties": 0,
		"errors": [],
		"total_invoices_touched": 0,
		"total_allocations": 0,
	}

	filter_set = None
	if party_filter is not None:
		filter_set = {tuple(x) for x in party_filter if x}

	for party_type, party in _iter_parties_for_scope(company, scope, party_types):
		if filter_set is not None and (party_type, party) not in filter_set:
			continue
		result = reconcile_single_party(
			company=company,
			party_type=party_type,
			party=party,
			window=window,
			include_advances=include_advances,
		)
		if result.get("error"):
			summary["errors"].append({"party_type": party_type, "party": party, "error": result["error"]})
			continue
		if result.get("skipped_reason"):
			summary["skipped_parties"] += 1
			continue
		rows = int(result.get("reconciled_rows") or 0)
		if rows > 0:
			summary["reconciled_parties"].append(
				{
					"party_type": party_type,
					"party": party,
					"account": result.get("account"),
					"reconciled_rows": rows,
				}
			)
			summary["total_allocations"] += rows
			summary["total_invoices_touched"] += int(result.get("invoices_touched") or 0)

	summary["finished_at"] = str(now_datetime())
	return summary


def get_reconciliation_candidates(company: str, scope=None, limit: int = 500) -> list[dict]:
	"""Diagnostic preview for the BNS Dashboard.

	Returns parties that currently have a non-zero signed balance on their party
	account — the cheap signal that they have unreconciled activity. No side
	effects, no new Payment Reconciliation docs.
	"""
	out: list[dict] = []
	for party_type, party in _iter_parties_for_scope(company, scope, _PARTY_TYPES):
		if len(out) >= limit:
			break
		try:
			account = get_party_account(party_type, party, company)
		except Exception:
			continue
		if not account:
			continue
		bal = _party_account_has_balance(party_type, party, account, company)
		if bal == 0:
			continue
		out.append(
			{
				"party_type": party_type,
				"party": party,
				"account": account,
				"signed_balance": bal,
			}
		)
	return out


def stamp_reconcile_last_run(run_dt=None):
	"""Update the read-only stamp on BNS Settings."""
	try:
		frappe.db.set_single_value(
			"BNS Settings", "common_party_reconcile_last_run_on", run_dt or now_datetime()
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="BNS auto reconcile: stamp last_run failed",
			message=frappe.get_traceback(),
		)
