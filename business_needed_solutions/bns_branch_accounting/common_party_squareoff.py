# Why:
# Custom Pure AR/AP Summary reports already net balances across linked
# Customer<->Supplier (Party Link). Balance Sheet, Trial Balance, General
# Ledger and native AR/AP reports read raw GL Entry and have zero Party Link
# awareness — so a common party XYZ with 100 Dr on Debtors and 100 Cr on
# Creditors shows both lines inflated even though the economic net is zero.
# ERPNext's process_common_party_accounting only fires on Sales/Purchase
# Invoice submit, missing Payment Entries and direct Journal Entries — which
# is exactly the scenario our accountants hit (bank receipt on wrong side).
#
# This module posts a balanced contra Journal Entry per linked pair where the
# party accounts carry opposite-signed balances, so the raw GL reflects the
# netted reality and every downstream report corrects itself without overrides.

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate, now_datetime, nowdate

import erpnext
from erpnext.accounts.party import get_party_account


_PARTY_ROLES = ("Customer", "Supplier")


def _active_party_links():
	return frappe.get_all(
		"Party Link",
		fields=["name", "primary_role", "primary_party", "secondary_role", "secondary_party"],
	)


def _get_party_signed_balance(party_type, party, account, company, as_of_date=None):
	"""Signed GL balance (debit - credit) for party on its party account."""
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
	if as_of_date:
		q = q.where(gle.posting_date <= getdate(as_of_date))
	row = q.run(as_dict=True)
	return flt(row[0].bal) if row and row[0].bal is not None else 0.0


def _pair_key(primary_type, primary, secondary_type, secondary):
	return f"{primary_type}:{primary}|{secondary_type}:{secondary}"


def compute_linked_party_net_positions(company, as_of_date=None):
	"""Return the list of linked pairs that need a contra JV.

	Each entry is a dict ready to feed into square_off_linked_party(). Only
	pairs whose party accounts carry opposite-signed balances are returned;
	the square_off_amount is min(|primary_balance|, |secondary_balance|).
	"""
	if not company:
		frappe.throw(_("Company is required"))

	links = _active_party_links()
	pairs = []
	seen_keys = set()

	for pl in links:
		if pl.primary_role not in _PARTY_ROLES or pl.secondary_role not in _PARTY_ROLES:
			continue
		try:
			primary_account = get_party_account(pl.primary_role, pl.primary_party, company)
			secondary_account = get_party_account(pl.secondary_role, pl.secondary_party, company)
		except Exception:
			continue
		if not primary_account or not secondary_account:
			continue

		primary_balance = _get_party_signed_balance(
			pl.primary_role, pl.primary_party, primary_account, company, as_of_date
		)
		secondary_balance = _get_party_signed_balance(
			pl.secondary_role, pl.secondary_party, secondary_account, company, as_of_date
		)

		# Only crossed: one side positive (Dr), the other negative (Cr).
		if primary_balance == 0 or secondary_balance == 0:
			continue
		if primary_balance * secondary_balance >= 0:
			continue

		square_amount = min(abs(primary_balance), abs(secondary_balance))
		if square_amount <= 0:
			continue

		key = _pair_key(pl.primary_role, pl.primary_party, pl.secondary_role, pl.secondary_party)
		if key in seen_keys:
			continue
		seen_keys.add(key)

		pairs.append(
			{
				"pair_key": key,
				"party_link": pl.name,
				"primary_party_type": pl.primary_role,
				"primary_party": pl.primary_party,
				"primary_account": primary_account,
				"primary_balance": primary_balance,
				"secondary_party_type": pl.secondary_role,
				"secondary_party": pl.secondary_party,
				"secondary_account": secondary_account,
				"secondary_balance": secondary_balance,
				"square_off_amount": square_amount,
				"company": company,
			}
		)

	return pairs


def _default_cost_center(company):
	configured = frappe.db.get_single_value("BNS Settings", "common_party_squareoff_cost_center")
	if configured:
		return configured
	return erpnext.get_default_cost_center(company)


def _build_leg(account, party_type, party, debit, credit, cost_center):
	# One Journal Entry accounts row — party-linked so GL carries the party
	# reference and the outstanding reconciles cleanly.
	return {
		"account": account,
		"party_type": party_type,
		"party": party,
		"cost_center": cost_center,
		"debit_in_account_currency": debit,
		"debit": debit,
		"credit_in_account_currency": credit,
		"credit": credit,
	}


def square_off_linked_party(pair, posting_date=None, cost_center=None, remark=None, submit=True):
	"""Post one balanced contra JV between the primary and secondary party."""
	company = pair["company"]
	amount = flt(pair["square_off_amount"])
	if amount <= 0:
		frappe.throw(_("Square off amount must be positive"))

	posting_date = getdate(posting_date or nowdate())
	cost_center = cost_center or _default_cost_center(company)

	primary_debit = amount if pair["primary_balance"] < 0 else 0.0
	primary_credit = amount if pair["primary_balance"] > 0 else 0.0
	secondary_debit = amount if pair["secondary_balance"] < 0 else 0.0
	secondary_credit = amount if pair["secondary_balance"] > 0 else 0.0

	jv = frappe.new_doc("Journal Entry")
	jv.voucher_type = "Journal Entry"
	jv.posting_date = posting_date
	jv.company = company
	jv.is_system_generated = 1
	jv.user_remark = remark or (
		f"BNS Common Party square-off: "
		f"{pair['primary_party_type']} {pair['primary_party']} \u2194 "
		f"{pair['secondary_party_type']} {pair['secondary_party']} "
		f"for {frappe.utils.fmt_money(amount, currency=erpnext.get_company_currency(company))}"
	)

	jv.append(
		"accounts",
		_build_leg(
			pair["primary_account"],
			pair["primary_party_type"],
			pair["primary_party"],
			primary_debit,
			primary_credit,
			cost_center,
		),
	)
	jv.append(
		"accounts",
		_build_leg(
			pair["secondary_account"],
			pair["secondary_party_type"],
			pair["secondary_party"],
			secondary_debit,
			secondary_credit,
			cost_center,
		),
	)

	jv.flags.ignore_permissions = True
	jv.save()
	if submit:
		jv.submit()
	return jv


def square_off_all_common_parties(
	company,
	as_of_date=None,
	pairs=None,
	dry_run=False,
	posting_date=None,
	cost_center=None,
	remark=None,
):
	"""Batch runner. Returns a summary dict with posted/skipped/errors."""
	if pairs is None:
		pairs = compute_linked_party_net_positions(company, as_of_date=as_of_date)

	result = {"posted": [], "skipped": [], "errors": [], "dry_run": bool(dry_run)}
	if dry_run:
		result["pairs"] = pairs
		return result

	for pair in pairs:
		sp = frappe.db.savepoint("bns_common_party_squareoff")
		try:
			# Re-read balances inside the savepoint to catch races where another
			# request (auto-hook or parallel manual post) has already squared off
			# this pair. Skip if it's no longer crossed or the amount has shrunk.
			live = _refresh_pair_balances(pair)
			if live is None:
				result["skipped"].append({"pair_key": pair["pair_key"], "reason": "no_longer_crossed"})
				continue
			jv = square_off_linked_party(
				live,
				posting_date=posting_date or as_of_date,
				cost_center=cost_center,
				remark=remark,
			)
			result["posted"].append(
				{"pair_key": live["pair_key"], "journal_entry": jv.name, "amount": live["square_off_amount"]}
			)
		except Exception as exc:
			frappe.db.rollback(save_point=sp)
			result["errors"].append({"pair_key": pair["pair_key"], "error": str(exc)})
	return result


def _refresh_pair_balances(pair):
	"""Re-read live GL balances for a pair and recompute square_off_amount.
	Returns a fresh pair dict, or None if the pair is no longer crossed."""
	primary_balance = _get_party_signed_balance(
		pair["primary_party_type"], pair["primary_party"], pair["primary_account"], pair["company"]
	)
	secondary_balance = _get_party_signed_balance(
		pair["secondary_party_type"], pair["secondary_party"], pair["secondary_account"], pair["company"]
	)
	if primary_balance == 0 or secondary_balance == 0:
		return None
	if primary_balance * secondary_balance >= 0:
		return None
	amount = min(abs(primary_balance), abs(secondary_balance))
	if amount <= 0:
		return None
	refreshed = dict(pair)
	refreshed["primary_balance"] = primary_balance
	refreshed["secondary_balance"] = secondary_balance
	refreshed["square_off_amount"] = amount
	return refreshed


# -------------------------------------------------------------------
# Scheduled auto square-off + whitelisted helpers
# -------------------------------------------------------------------


_SCHEDULE_INTERVAL_DAYS = {
	"Weekly": 7,
	"Monthly": 28,
	"Quarterly": 90,
	"Yearly": 365,
}


def _schedule_is_due(schedule, last_run_on, now):
	# Why: per-Payment-Entry auto-hook was too invasive — fires on every PE,
	# invisible side-effects to the user, hard to audit. Scheduled run happens
	# on a predictable cadence so accountants know when contras get posted.
	# Interval-based (not calendar-pinned) so the first run after enabling
	# happens immediately rather than waiting for the next Apr 1.
	if schedule not in _SCHEDULE_INTERVAL_DAYS:
		return False
	if not last_run_on:
		return True
	last = getdate(last_run_on)
	today = getdate(now)
	delta_days = (today - last).days
	return delta_days >= _SCHEDULE_INTERVAL_DAYS[schedule]


def _list_companies_for_schedule():
	"""Indirection so tests can patch it without mocking the whole frappe.get_all."""
	return frappe.get_all("Company", pluck="name")


def _run_reconcile(company, window, scope, include_advances):
	"""Lazy-import wrapper so common_party_reconciliation can safely import us
	back (for the 'Only Parties With Crossed Balances' scope).
	Returns the full summary dict from reconcile_all_parties, or a stub on error."""
	try:
		from business_needed_solutions.bns_branch_accounting.common_party_reconciliation import (
			reconcile_all_parties,
		)

		return reconcile_all_parties(
			company=company,
			window=window,
			include_advances=include_advances,
			scope=scope,
		)
	except Exception:
		frappe.log_error(
			title=f"BNS auto reconcile wrap failed for {company}",
			message=frappe.get_traceback(),
		)
		return {"reconciled_parties": [], "errors": ["exception"], "total_allocations": 0}


def scheduled_squareoff_run():
	"""Daily scheduler tick. Runs auto square-off across every company when the
	configured interval has elapsed since last run. Never raises — failures go to
	Error Log so the scheduler keeps ticking."""
	try:
		settings = frappe.get_single("BNS Settings")
	except Exception:
		frappe.log_error(title="BNS scheduled square-off: settings load failed", message=frappe.get_traceback())
		return

	schedule = getattr(settings, "common_party_squareoff_schedule", None) or "Disabled"
	last_run_on = getattr(settings, "common_party_squareoff_last_run_on", None)
	now = now_datetime()

	if not _schedule_is_due(schedule, last_run_on, now):
		return

	cost_center = getattr(settings, "common_party_squareoff_cost_center", None) or None

	# Why: the square-off on its own only moves GL balances between Debtors and
	# Creditors — it does not close the underlying Sales / Purchase Invoices.
	# Running Payment Reconciliation BEFORE clears any pre-existing unlinked
	# invoice/payment pairs so the crossed-balance calc sees the real net, and
	# running it AFTER FIFO-allocates the fresh contra JV's legs against the
	# oldest open invoices on each side. Both steps are gated independently so
	# accountants can tune behaviour without code changes.
	reconcile_before = bool(getattr(settings, "common_party_reconcile_before_squareoff", 0))
	reconcile_after = bool(getattr(settings, "common_party_reconcile_after_squareoff", 0))
	reconcile_window = getattr(settings, "common_party_reconcile_window", None) or "All time"
	reconcile_scope = getattr(settings, "common_party_reconcile_scope", None) or "All Customers + All Suppliers"
	reconcile_include_advances = bool(getattr(settings, "common_party_reconcile_include_advances", 1))

	companies = _list_companies_for_schedule()
	summary = {
		"schedule": schedule,
		"ran_at": str(now),
		"reconcile_before": reconcile_before,
		"reconcile_after": reconcile_after,
		"reconcile_window": reconcile_window,
		"reconcile_scope": reconcile_scope,
		"by_company": {},
	}
	posted_total = 0
	error_total = 0

	for company in companies:
		company_summary = {"posted": 0, "errors": 0, "skipped": 0}
		try:
			if reconcile_before:
				pre = _run_reconcile(
					company, reconcile_window, reconcile_scope, reconcile_include_advances
				)
				company_summary["reconcile_before"] = {
					"reconciled_parties": len(pre.get("reconciled_parties", [])),
					"total_allocations": pre.get("total_allocations", 0),
					"errors": len(pre.get("errors", [])),
				}

			pairs = compute_linked_party_net_positions(company)
			if pairs:
				result = square_off_all_common_parties(
					company,
					pairs=pairs,
					posting_date=None,  # uses today
					cost_center=cost_center,
					remark=f"BNS scheduled ({schedule}) square-off",
				)
				company_summary["posted"] = len(result.get("posted", []))
				company_summary["errors"] = len(result.get("errors", []))
				company_summary["skipped"] = len(result.get("skipped", []))
				posted_total += len(result.get("posted", []))
				error_total += len(result.get("errors", []))

			if reconcile_after:
				post = _run_reconcile(
					company, reconcile_window, reconcile_scope, reconcile_include_advances
				)
				company_summary["reconcile_after"] = {
					"reconciled_parties": len(post.get("reconciled_parties", [])),
					"total_allocations": post.get("total_allocations", 0),
					"errors": len(post.get("errors", [])),
				}

			summary["by_company"][company] = company_summary
		except Exception:
			error_total += 1
			summary["by_company"][company] = {"error": "exception, see Error Log"}
			frappe.log_error(
				title=f"BNS scheduled square-off failed for {company}",
				message=frappe.get_traceback(),
			)

	# Stamp both last-run timestamps if the reconciliation pre/post actually ran.
	if reconcile_before or reconcile_after:
		try:
			frappe.db.set_single_value("BNS Settings", "common_party_reconcile_last_run_on", now)
		except Exception:
			frappe.log_error(
				title="BNS scheduled reconcile: stamp last_run failed",
				message=frappe.get_traceback(),
			)

	# Stamp last run even if everything was a no-op; otherwise a misconfigured
	# company would pin the scheduler and never let any other company run.
	try:
		frappe.db.set_single_value("BNS Settings", "common_party_squareoff_last_run_on", now)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="BNS scheduled square-off: last_run stamp failed", message=frappe.get_traceback())

	if posted_total or error_total:
		frappe.logger().info(
			f"[BNS] scheduled square-off {schedule}: posted={posted_total} errors={error_total} summary={summary}"
		)


def _find_crossed_pair_for_party(party_type, party, company):
	link = frappe.db.get_value(
		"Party Link",
		filters={"primary_role": party_type, "primary_party": party},
		fieldname=["primary_role", "primary_party", "secondary_role", "secondary_party"],
		as_dict=True,
	) or frappe.db.get_value(
		"Party Link",
		filters={"secondary_role": party_type, "secondary_party": party},
		fieldname=["primary_role", "primary_party", "secondary_role", "secondary_party"],
		as_dict=True,
	)
	if not link:
		return None
	if link.primary_role not in _PARTY_ROLES or link.secondary_role not in _PARTY_ROLES:
		return None

	primary_account = get_party_account(link.primary_role, link.primary_party, company)
	secondary_account = get_party_account(link.secondary_role, link.secondary_party, company)
	if not primary_account or not secondary_account:
		return None

	primary_balance = _get_party_signed_balance(
		link.primary_role, link.primary_party, primary_account, company
	)
	secondary_balance = _get_party_signed_balance(
		link.secondary_role, link.secondary_party, secondary_account, company
	)
	if primary_balance == 0 or secondary_balance == 0:
		return None
	if primary_balance * secondary_balance >= 0:
		return None

	amount = min(abs(primary_balance), abs(secondary_balance))
	if amount <= 0:
		return None

	return {
		"pair_key": _pair_key(link.primary_role, link.primary_party, link.secondary_role, link.secondary_party),
		"primary_party_type": link.primary_role,
		"primary_party": link.primary_party,
		"primary_account": primary_account,
		"primary_balance": primary_balance,
		"secondary_party_type": link.secondary_role,
		"secondary_party": link.secondary_party,
		"secondary_account": secondary_account,
		"secondary_balance": secondary_balance,
		"square_off_amount": amount,
		"company": company,
	}


@frappe.whitelist()
def check_linked_party_opposite_balance(party_type, party, company):
	# Thin wrapper consumed by the client-side warning dialog.
	# Gated by both (a) BNS Settings flag, (b) caller must have read on Payment Entry
	# AND on the party record — the response leaks party outstanding balances, so it
	# must not be reachable by users who can't already see the underlying documents.
	if not frappe.db.get_single_value("BNS Settings", "common_party_warning_on_wrong_side"):
		return {"has_crossed": False}
	if not frappe.has_permission("Payment Entry", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if party_type not in _PARTY_ROLES:
		return {"has_crossed": False}
	if not frappe.has_permission(party_type, "read", doc=party):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	pair = _find_crossed_pair_for_party(party_type, party, company)
	if not pair:
		return {"has_crossed": False}
	return {
		"has_crossed": True,
		"linked_party_type": pair["secondary_party_type"]
		if pair["primary_party"] == party and pair["primary_party_type"] == party_type
		else pair["primary_party_type"],
		"linked_party": pair["secondary_party"]
		if pair["primary_party"] == party and pair["primary_party_type"] == party_type
		else pair["primary_party"],
		"square_off_amount": pair["square_off_amount"],
		"primary_balance": pair["primary_balance"],
		"secondary_balance": pair["secondary_balance"],
	}
