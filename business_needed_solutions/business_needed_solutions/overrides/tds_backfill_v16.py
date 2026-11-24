"""TDS on submitted Purchase Invoices, ERPNext v16 (Tax Withholding Entries).

v16 keeps TDS in each invoice's `tax_withholding_entries` table. An invoice's category
lives on each item row (from the Item's purchase category, else the Supplier's). When
an invoice deducts TDS for earlier invoices that were under the threshold, its own
entries point at them and their entries are marked as settled by it. So one invoice's
TDS depends on every earlier invoice of the same PAN in the year, and the entries link
the invoices together.

That is why this module does not reimplement v16's rules. It replays them. For one PAN
and one fiscal year:

1. Every Tax Withholding Entry of the year's invoices is deleted (inside a savepoint).
2. The invoices are taken in posting order. Each gets its target categories (the
   mode / overrides), then ERPNext's own PurchaseTaxWithholding works out its entries
   and TDS rows from the entries already replayed before it, exactly as a submit would,
   and its submit-time adjustments settle the earlier invoices' entries.
3. An invoice that may not change (filed quarter, frozen period, cash-paid, foreign
   currency, write-off, internal, opening, entries overridden by hand) gets its own
   entries back as they were at its submit, so the invoices after it see it unchanged.

A preview rolls the savepoint back. An apply replays again in its own transaction,
checks the result is the one previewed, then saves each changed invoice's TDS rows,
totals and item categories and rebuilds its ledger (tds_backfill._rebuild_gl), cutting
payments back only when they would exceed the new total. A PAN's year is applied as one
transaction: entries link its invoices, so it is all or nothing.

The year is refused as a whole when TDS entries outside its Purchase Invoices touch it
(TDS on a Payment Entry or Journal Entry, an Over Withheld advance, entries linking
another year), or when a category's rate period runs past the fiscal year.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate

from business_needed_solutions.business_needed_solutions.overrides import auto_paid_supplier

PI = "Purchase Invoice"
PI_ITEM = "Purchase Invoice Item"
TAX_ROW = "Purchase Taxes and Charges"
TWE = "Tax Withholding Entry"
DEFAULTS = "__defaults__"  # override value: each row takes its Item's, else its Supplier's, category

# Entry fields that say what an entry is; names, idx and timestamps are left out.
_ENTRY_KEYS = (
	"party_type", "party", "tax_id", "tax_withholding_category", "tax_withholding_group", "tax_rate",
	"taxable_amount", "lower_deduction_certificate", "status", "currency", "conversion_rate",
	"withholding_doctype", "withholding_name", "taxable_doctype", "taxable_name", "taxable_date",
	"withholding_date", "under_withheld_reason", "withholding_amount", "company",
)
_SP = "bns_tds_v16_replay"


def supported() -> bool:
	return frappe.get_meta(PI).has_field("tax_withholding_entries")


def _tb():
	from business_needed_solutions.business_needed_solutions.overrides import tds_backfill

	return tds_backfill


# --------------------------------------------------------------------------------------
# Reading the year
# --------------------------------------------------------------------------------------


def _load_year(parties, company, fy_start, fy_end):
	meta = frappe.get_meta(PI)
	fields = [
		"name", "supplier", "posting_date", "posting_time", "is_return", "return_against", "apply_tds",
		"is_opening", "is_paid", "write_off_amount", "conversion_rate", "currency", "party_account_currency",
		"credit_to", "base_net_total", "grand_total", "rounded_total", "outstanding_amount",
		"override_tax_withholding_entries", "ignore_tax_withholding_threshold",
	]
	fields += [f for f in ("is_internal_supplier", "is_bns_internal_supplier", "update_outstanding_for_self")
			   if meta.has_field(f)]
	docs = frappe.get_all(
		PI,
		filters={"docstatus": 1, "company": company, "supplier": ["in", parties],
				 "posting_date": ["between", [fy_start, fy_end]]},
		fields=fields,
		order_by="posting_date asc, posting_time asc, name asc",
	)
	if not docs:
		return []
	names = [d.name for d in docs]
	rows = {}
	for r in frappe.get_all(
		PI_ITEM, filters={"parent": ["in", names], "parenttype": PI},
		fields=["name", "parent", "idx", "item_code", "item_name", "base_net_amount", "apply_tds",
				"tax_withholding_category"],
		order_by="parent, idx",
	):
		rows.setdefault(r.parent, []).append(r)
	tds = {}
	for r in frappe.get_all(
		TAX_ROW, filters={"parent": ["in", names], "parenttype": PI, "is_tax_withholding_account": 1},
		fields=["name", "parent", "account_head", "base_tax_amount_after_discount_amount as amount"],
		order_by="parent, idx",
	):
		tds.setdefault(r.parent, []).append(r)
	entries = {}
	for e in frappe.get_all(TWE, filters={"parent": ["in", names], "parenttype": PI, "docstatus": 1},
							fields=["*"], order_by="parent, idx"):
		entries.setdefault(e.parent, []).append(e)

	auto_paid = set()
	if frappe.get_meta("Supplier").has_field("bns_auto_paid_supplier"):
		auto_paid = set(frappe.get_all("Supplier", filters={"name": ["in", parties], "bns_auto_paid_supplier": 1},
									   pluck="name"))
	for d in docs:
		d.posting_date = getdate(d.posting_date)
		d.rows = rows.get(d.name, [])
		d.tds_rows = tds.get(d.name, [])
		d.current_tds = flt(sum(flt(r.amount) for r in d.tds_rows), 2)
		d.current_accounts = sorted({r.account_head for r in d.tds_rows})
		d.current_by_account = _by_account(d.tds_rows)
		d.entries = entries.get(d.name, [])
		d.current_category = _categories(d.rows, d.apply_tds)
		d.has_advance_tax = False
		d.auto_paid = bool(cint(d.is_paid) and d.supplier in auto_paid
						   and not cint(d.get("is_bns_internal_supplier")))
	return docs


def _by_account(tds_rows):
	out = {}
	for r in tds_rows:
		out[r.account_head] = flt(out.get(r.account_head, 0) + flt(r.amount), 2)
	return {k: v for k, v in out.items() if abs(v) >= 0.005}


def _categories(rows, apply_tds, key="tax_withholding_category"):
	"""The categories an invoice deducts under: its rows' categories, when TDS is on."""
	if not cint(apply_tds):
		return ""
	return ", ".join(sorted({r.get(key) for r in rows if cint(r.apply_tds) and r.get(key)}))


def _entry_sig(e):
	return tuple(
		round(flt(e.get(k)), 2) if k in ("taxable_amount", "withholding_amount", "tax_rate", "conversion_rate")
		else cstr(e.get(k) or "") for k in _ENTRY_KEYS
	)


def _entries_sig(entries):
	return sorted(_entry_sig(e) for e in entries)


# --------------------------------------------------------------------------------------
# What each invoice should carry
# --------------------------------------------------------------------------------------


def _default_category(row, supplier, cache):
	key = ("item", row.item_code)
	if key not in cache:
		cache[key] = frappe.db.get_value("Item", row.item_code, "purchase_tax_withholding_category") if (
			row.item_code and frappe.get_meta("Item").has_field("purchase_tax_withholding_category")) else None
	if cache[key]:
		return cache[key]
	key = ("supplier", supplier)
	if key not in cache:
		cache[key] = frappe.db.get_value("Supplier", supplier, "tax_withholding_category")
	return cache[key] or None


def _targets(d, mode, supplier, override, cache):
	"""(row categories {row: category}, header apply_tds) the invoice should carry."""
	cats = {r.name: r.tax_withholding_category for r in d.rows}
	apply = cint(d.apply_tds)
	use_defaults = (mode == "defaults") or (mode == "supplier" and d.supplier == supplier)
	if override is not None:
		use_defaults = False
		if isinstance(override, dict):
			for row, cat in override.items():
				if row in cats:
					cats[row] = cat or None
			apply = 1 if any(cats.get(r.name) and cint(r.apply_tds) for r in d.rows) else 0
		elif override == DEFAULTS:
			use_defaults = True
		elif override:
			cats = {r.name: override for r in d.rows}
			apply = 1
		else:
			apply = 0
	if use_defaults:
		cats = {r.name: _default_category(r, d.supplier, cache) for r in d.rows}
		apply = 1 if any(cats[r.name] and cint(r.apply_tds) for r in d.rows) else 0
	return cats, apply


def _frozen_reason(d):
	"""Why this invoice keeps its own entries and ledger as they are, whatever it would get."""
	if d.internal:
		return _("Internal purchase (same PAN); left as it is.")
	if d.is_opening == "Yes":
		return _("Opening invoice; left as it is.")
	if cint(d.override_tax_withholding_entries):
		return _("Its Tax Withholding Entries were set by hand; left as they are.")
	return None


def _ledger_block(d, company, filed_upto, frozen_upto, allow_filed):
	tb = _tb()
	if frozen_upto and getdate(d.posting_date) <= frozen_upto:
		return _("In the frozen accounting period (up to {0}).").format(frozen_upto)
	if filed_upto and getdate(d.posting_date) <= filed_upto and not (allow_filed and tb._is_system_manager()):
		return _("TDS return already filed for {0} (BNS Settings: filed up to {1}).").format(
			tb._quarter(d.posting_date), filed_upto)
	if cint(d.is_paid) and not d.get("auto_paid"):
		return _("Cash-paid invoice (Is Paid); fix by hand.")
	if flt(d.write_off_amount):
		return _("Invoice has a write-off; fix by hand.")
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	if (d.party_account_currency and d.party_account_currency != company_currency) or flt(d.conversion_rate) != 1:
		return _("Foreign-currency invoice; fix by hand.")
	return None


# --------------------------------------------------------------------------------------
# Year-level refusals
# --------------------------------------------------------------------------------------


def _year_problems(docs, parties, company, fy_start, fy_end):
	names = {d.name for d in docs}
	problems = []
	outside = frappe.db.sql(
		"""SELECT DISTINCT parenttype, parent FROM `tabTax Withholding Entry`
		   WHERE docstatus = 1 AND company = %(c)s AND party_type = 'Supplier' AND party IN %(p)s
			 AND NOT (parenttype = 'Purchase Invoice' AND parent IN %(n)s)
			 AND (status = 'Over Withheld'
				  OR taxable_date BETWEEN %(s)s AND %(e)s OR withholding_date BETWEEN %(s)s AND %(e)s)
		   LIMIT 5""",
		{"c": company, "p": tuple(parties), "n": tuple(names) or ("",), "s": fy_start, "e": fy_end},
	)
	for parenttype, parent in outside:
		problems.append(_("TDS entries on {0} {1} touch this year; fix by hand.").format(_(parenttype), parent))
	for d in docs:
		for e in d.entries:
			for kind in ("taxable", "withholding"):
				dt, dn = e.get(f"{kind}_doctype"), e.get(f"{kind}_name")
				if dn and not (dt == PI and dn in names):
					problems.append(_("{0} has a TDS entry linking {1} {2}, outside this year; fix by hand.").format(
						d.name, _(dt or ""), dn))
			if e.status == "Over Withheld":
				problems.append(_("{0} has an Over Withheld TDS entry; fix by hand.").format(d.name))
			if e.status == "Duplicate" and e.taxable_name != d.name:
				problems.append(_("{0} has an unexpected settled TDS entry; fix by hand.").format(d.name))
	return sorted(set(problems))


def _rate_problem(category, company, posting_date, fy_start, fy_end, cache):
	key = ("rate", category, str(posting_date))
	if key in cache:
		return cache[key]
	problem = None
	if not frappe.db.exists("Tax Withholding Category", category):
		problem = _("Tax Withholding Category {0} does not exist.").format(category)
	else:
		doc = frappe.get_cached_doc("Tax Withholding Category", category)
		if not any(a.company == company for a in doc.accounts):
			problem = _("{0} has no account for company {1}.").format(category, company)
		rate = next((r for r in doc.rates if getdate(r.from_date) <= getdate(posting_date) <= getdate(r.to_date)), None)
		if not problem and not rate:
			problem = _("{0} has no rate for {1}.").format(category, posting_date)
		elif not problem and (getdate(rate.from_date) < fy_start or getdate(rate.to_date) > fy_end):
			problem = _("{0}'s rate period {1} to {2} runs past the fiscal year; fix by hand.").format(
				category, rate.from_date, rate.to_date)
	cache[key] = problem
	return problem


# --------------------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------------------


def _pre_image(entries, name):
	"""An invoice's entries as they stood right after its own submit: entries a later
	invoice settled (marked Duplicate) go back to Under Withheld."""
	out = []
	for e in entries:
		row = {k: e.get(k) for k in _ENTRY_KEYS}
		row.update(lower_deduction_certificate=e.get("lower_deduction_certificate"),
				   created_by_migration=e.get("created_by_migration"))
		if e.status == "Duplicate" and e.taxable_name == name:
			row.update(withholding_doctype="", withholding_name="", withholding_date=None,
					   withholding_amount=0, under_withheld_reason="", status="Under Withheld")
		out.append(row)
	return out


def _absorb_migrated(name, entries, company, fy_start, fy_end):
	"""Entries migrated from v15 keep the whole cumulative deduction on the deducting
	invoice's own row (withholding more than its own taxable x rate), and leave the
	earlier invoices it covered Under Withheld. Restoring such an invoice as it is would
	let the next invoice deduct those again. So the excess is turned into v16's own
	shape: rows on this invoice that settle the earliest open entries of the category.
	The invoice's TDS does not change."""
	out = []
	taken = {}
	for row in entries:
		rate = flt(row.get("tax_rate"))
		excess = flt(row.get("withholding_amount")) - flt(row.get("taxable_amount")) * rate / 100
		if (row.get("status") != "Settled" or rate <= 0 or excess <= 0.5
				or row.get("taxable_name") != name or row.get("withholding_name") != name):
			out.append(row)
			continue
		remaining = excess * 100 / rate
		party_filter = ("tax_id", row.get("tax_id")) if row.get("tax_id") else ("party", row.get("party"))
		open_rows = frappe.get_all(TWE, filters={
			"docstatus": 1, "status": "Under Withheld", "company": company, "party_type": "Supplier",
			"tax_withholding_category": row.get("tax_withholding_category"), party_filter[0]: party_filter[1],
			"taxable_date": ["between", [fy_start, fy_end]], "taxable_name": ["!=", name],
			"taxable_amount": [">", 0],
		}, fields=["name", "taxable_doctype", "taxable_name", "taxable_date", "taxable_amount"],
			order_by="taxable_date asc, creation asc")
		row = dict(row)
		for u in open_rows:
			if remaining <= 0.005:
				break
			free = flt(u.taxable_amount) - taken.get(u.name, 0)
			take = min(free, remaining)
			if take <= 0.005:
				continue
			taken[u.name] = taken.get(u.name, 0) + take
			remaining -= take
			tax = flt(take * rate / 100, 2)
			out.append(dict(row, taxable_doctype=u.taxable_doctype, taxable_name=u.taxable_name,
							taxable_date=u.taxable_date, taxable_amount=flt(take, 2), withholding_amount=tax,
							status="Settled", created_by_migration=0))
			row["withholding_amount"] = flt(flt(row["withholding_amount"]) - tax, 2)
		out.append(row)
	return out


def _insert_entries(doc, entries):
	"""Put entries on a submitted invoice and run its submit-time adjustments."""
	from erpnext.accounts.doctype.tax_withholding_entry.tax_withholding_entry import PurchaseTaxWithholding

	doc.set("tax_withholding_entries", [])
	for values in entries:
		doc.append("tax_withholding_entries", values)
	for idx, e in enumerate(doc.tax_withholding_entries, start=1):
		e.parent, e.parenttype, e.parentfield, e.docstatus, e.idx = doc.name, PI, "tax_withholding_entries", 1, idx
		e.name = None
		e.db_insert()
	PurchaseTaxWithholding(doc).on_submit()


def _recompute(doc, cats, apply):
	"""ERPNext's own TDS for this invoice, against the entries replayed so far. In memory."""
	from erpnext.accounts.doctype.tax_withholding_entry.tax_withholding_entry import PurchaseTaxWithholding

	for row in doc.items:
		if row.name in cats:
			row.tax_withholding_category = cats[row.name]
	doc.apply_tds = apply
	doc.set("tax_withholding_entries", [])
	# As on save: totals first (item-wise tax feeds a Gross Total basis), then TDS.
	doc.calculate_taxes_and_totals()
	PurchaseTaxWithholding(doc).on_validate()
	doc.taxes = [t for t in doc.taxes if not (cint(t.is_tax_withholding_account) and not flt(t.tax_amount))]
	for idx, t in enumerate(doc.taxes, start=1):
		t.idx = idx
	doc.calculate_taxes_and_totals()
	return doc


def _replay(plan, docs, targets, ctx):
	"""Run the year. Leaves the replayed entries in the database (the caller rolls back
	or keeps them). Fills each d with what it ends up with."""
	tb = _tb()
	names = [d.name for d in docs]
	frappe.db.delete(TWE, {"parenttype": PI, "parent": ["in", names]})
	for d in docs:
		doc = frappe.get_doc(PI, d.name)
		d._doc = None
		reason = _frozen_reason(d)
		cats, apply = targets[d.name]
		d.category = _categories([frappe._dict(r, tax_withholding_category=cats.get(r.name)) for r in d.rows], apply)
		if reason:
			d.keep_reason = reason
			_insert_entries(doc, _absorb_migrated(d.name, _pre_image(d.entries, d.name), plan.company,
												  ctx.fy_start, ctx.fy_end))
			continue

		snap = tb._snapshot(doc)
		_recompute(doc, cats, apply)
		problem = tb._compare_snapshot(snap, doc)
		new_rows = [t for t in doc.taxes if cint(t.is_tax_withholding_account)]
		d.target_by_account = _by_account([frappe._dict(account_head=t.account_head,
														amount=t.base_tax_amount_after_discount_amount)
										   for t in new_rows])
		d.target_tds = flt(sum(d.target_by_account.values()), 2)
		d.target_accounts = sorted(d.target_by_account)
		d.target_account = ", ".join(d.target_accounts) or None
		d.taxable = flt(sum(flt(e.taxable_amount) for e in doc.tax_withholding_entries
							if e.taxable_name == d.name), 2)
		money = _money_changes(d)
		if money and ctx.scope == "account" and abs(d.target_tds - d.current_tds) >= 0.005:
			problem = problem or _("The TDS amount would change too; use Recalculate instead of re-map.")
		if money and not problem:
			problem = _ledger_block(d, plan.company, ctx.filed_upto, ctx.frozen_upto, ctx.allow_filed)
		if problem and money:
			d.blocked = problem
			_insert_entries(frappe.get_doc(PI, d.name), _absorb_migrated(
				d.name, _pre_image(d.entries, d.name), plan.company, ctx.fy_start, ctx.fy_end))
			continue
		new_entries = [{k: e.get(k) for k in _ENTRY_KEYS + ("lower_deduction_certificate",)}
					   for e in doc.tax_withholding_entries]
		_insert_entries(doc, new_entries)
		if money:
			d._doc = doc
		d._cats, d._apply = cats, apply


def _money_changes(d):
	accounts = set(d.current_by_account) | set(d.target_by_account)
	return any(abs(flt(d.current_by_account.get(a)) - flt(d.target_by_account.get(a))) >= 0.005 for a in accounts)


def _flag_changes(d):
	if getattr(d, "_cats", None) is None:
		return False
	if cint(d.apply_tds) != cint(d._apply):
		return True
	return any(cstr(r.tax_withholding_category or "") != cstr(d._cats.get(r.name) or "") for r in d.rows)


# --------------------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------------------


def plan_supplier_year(supplier, company, date=None, mode="keep", overrides=None, scope="all",
					   allow_filed=False, keep=False):
	"""Work out TDS for the year of `supplier` (and suppliers sharing its PAN) the way
	ERPNext v16 does at submit. Never writes unless `keep` (apply), and then only the
	Tax Withholding Entries; the caller saves the invoices."""
	tb = _tb()
	overrides = dict(overrides or {})
	fy_start, fy_end = tb._fiscal_year(company, date)
	parties = tb._parties(supplier)
	plan = frappe._dict(
		supplier=supplier, supplier_name=frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier,
		company=company, fiscal_year_start=str(fy_start), fiscal_year_end=str(fy_end), mode=mode, scope=scope,
		overrides=overrides, parties=parties, problems=[], warnings=[], docs=[], v16=True,
	)
	docs = _load_year(parties, company, fy_start, fy_end)
	if not docs:
		return plan
	by_name = {d.name: d for d in docs}
	unknown = [n for n in overrides if n not in by_name]
	if unknown:
		frappe.throw(_("{0} is not an invoice of {1} in this fiscal year.").format(", ".join(unknown), supplier))

	company_pan = (frappe.db.get_value("Company", company, "pan") or "").strip().upper()
	supplier_pans = {}
	if frappe.get_meta("Supplier").has_field("pan"):
		supplier_pans = {r.name: (r.pan or "").strip().upper()
						 for r in frappe.get_all("Supplier", filters={"name": ["in", parties]}, fields=["name", "pan"])}
	cache = {}
	targets = {}
	for d in docs:
		d.internal = tb._is_internal(d, company_pan, supplier_pans)
		override = overrides.get(d.name)
		if override is None and cint(d.is_return) and d.return_against in overrides:
			override = overrides[d.return_against]  # a debit note follows the invoice it returns
		targets[d.name] = _targets(d, mode, supplier, override, cache)
		d.update(target_tds=d.current_tds, target_accounts=d.current_accounts,
				 target_account=", ".join(d.current_accounts) or None, target_by_account=d.current_by_account,
				 taxable=0.0, blocked=None, action="none", category=d.current_category)

	plan.problems = _year_problems(docs, parties, company, fy_start, fy_end)
	for d in docs:
		if d.internal or d.is_opening == "Yes":
			continue
		cats, apply = targets[d.name]
		if not apply:
			continue
		for cat in {c for r in d.rows if cint(r.apply_tds) for c in [cats.get(r.name)] if c}:
			problem = _rate_problem(cat, company, d.posting_date, fy_start, fy_end, cache)
			if problem:
				plan.problems.append(problem)
	plan.problems = sorted(set(plan.problems))
	plan.docs = docs
	if plan.problems:
		plan.token = tb._plan_token([plan])
		return plan

	ctx = frappe._dict(scope=scope, allow_filed=allow_filed, filed_upto=tb._filed_upto(),
					   frozen_upto=tb._frozen_upto(company), fy_start=fy_start, fy_end=fy_end)
	frappe.db.savepoint(_SP)
	try:
		_replay(plan, docs, targets, ctx)
		final = {}
		for e in frappe.get_all(TWE, filters={"parenttype": PI, "parent": ["in", list(by_name)], "docstatus": 1},
								fields=["*"]):
			final.setdefault(e.parent, []).append(e)
	except Exception as e:
		frappe.db.rollback(save_point=_SP)
		frappe.log_error(title=f"BNS TDS v16 replay failed: {supplier}")
		plan.problems.append(_("ERPNext could not replay this year's TDS: {0}").format(cstr(e)))
		for d in docs:
			d.action, d.blocked, d._doc = "none", None, None
		plan.token = tb._plan_token([plan])
		return plan
	if not keep:
		frappe.db.rollback(save_point=_SP)

	filed_upto = ctx.filed_upto
	challan_cache = {}
	for d in docs:
		d.final_entries = final.get(d.name, [])
		d.entries_changed = _entries_sig(d.final_entries) != _entries_sig(d.entries)
		d.sig = hashlib.sha1(json.dumps(_entries_sig(d.final_entries), default=str).encode()).hexdigest()[:12]
		if d.blocked:
			d.action = "ledger"
		elif d.get("_doc") is not None:
			d.action = "ledger"
		elif _flag_changes(d) or d.entries_changed:
			d.action = "flags"
		if d.action == "ledger":
			d.quarter = tb._quarter(d.posting_date)
			d.filed = bool(filed_upto and getdate(d.posting_date) <= filed_upto)
			delta = flt(d.target_tds) - flt(d.current_tds)
			d.months_late = tb._months_late(d.posting_date) if delta > 0 else 0
			d.late_interest = flt(delta * tb._LATE_INTEREST_RATE / 100 * d.months_late, 2) if delta > 0 else 0
			d.challans = tb._challans_for_month(set(d.current_accounts) | set(d.target_accounts),
												d.posting_date, challan_cache)
			if not d.blocked:
				_preview_ledger(d)
	plan.token = tb._plan_token([plan])
	return plan


def _preview_ledger(d):
	tb = _tb()
	pi = d._doc
	allowed = {pi.credit_to, *d.target_accounts, *d.current_accounts,
			   frappe.get_cached_value("Company", pi.company, "round_off_account")} - {None}
	if d.get("auto_paid"):
		auto_paid_supplier.set_paid_amounts(pi)
		pi.calculate_taxes_and_totals()
		if pi.cash_bank_account:
			allowed.add(pi.cash_bank_account)
	try:
		after = tb._gl_net(pi.get_gl_entries())
	except Exception as e:
		d.blocked = _("Could not rebuild the invoice: {0}").format(cstr(e))
		return
	before = tb._live_gl_net(pi.name)
	moved = []
	for key in sorted(set(before) | set(after)):
		old, new = flt(before.get(key), 2), flt(after.get(key), 2)
		if abs(old - new) >= 0.01:
			moved.append({"account": key[0], "party": key[2], "before": old, "after": new,
						  "allowed": key[0] in allowed})
	d.moved = moved
	bad = [m for m in moved if not m["allowed"]]
	if bad:
		d.blocked = _("Rebuilding the ledger would also move {0}; refused.").format(
			", ".join(m["account"] for m in bad))
		return
	d._new_gl = after
	d.against = _against(d)
	if d.against != d.name:
		# A debit note settles the invoice it returns: its payable line counts there.
		key = (pi.credit_to, "Supplier", pi.supplier)
		more = flt(after.get(key)) - flt(before.get(key))
		left = flt(frappe.db.get_value(PI, d.against, "outstanding_amount"))
		d.caps = []
		if more > 0.005 and left + 0.005 < more:
			d.blocked = _("The debit note would take {0} below zero; fix by hand.").format(d.against)
	elif cint(d.is_return):
		# A debit note with its own outstanding: the supplier owes us (negative payable).
		# Refunds already allocated against it must still fit its new total.
		key = (pi.credit_to, "Supplier", pi.supplier)
		owed = -flt(after.get(key), 2)
		refunded = flt(sum(flt(a.amount) for a in tb._allocations(pi.name)), 2)
		d.caps = []
		if owed - refunded > 0.005 and refunded < 0:
			d.blocked = _("Refunds against this debit note exceed its new total; fix by hand.")
	else:
		caps, problem, _excess = tb._plan_caps(d, pi)
		d.caps = caps
		if problem:
			d.blocked = problem
	d.new_grand_total = flt(pi.rounded_total or pi.grand_total, 2)
	d.old_grand_total = flt(d.rounded_total or d.grand_total, 2)
	if d.get("auto_paid"):
		d.new_paid_amount = flt(pi.paid_amount, 2)


# --------------------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------------------


def _against(d):
	"""The invoice a payable line of `d` is booked against (ERPNext's make_supplier_gl_entry)."""
	if cint(d.is_return) and d.return_against and not cint(d.get("update_outstanding_for_self")):
		return d.return_against
	return d.name


def _verify(d):
	tb = _tb()
	totals = frappe.db.sql(
		"""SELECT IFNULL(SUM(debit), 0), IFNULL(SUM(credit), 0) FROM `tabGL Entry`
		   WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s AND is_cancelled = 0""", d.name)[0]
	if abs(flt(totals[0]) - flt(totals[1])) >= 0.01:
		frappe.throw(_("{0}: debit and credit differ after the rebuild.").format(d.name))
	live = tb._live_gl_net(d.name)
	round_off = frappe.get_cached_value("Company", frappe.db.get_value(PI, d.name, "company"), "round_off_account")
	for key in set(live) | set(d._new_gl):
		if abs(flt(live.get(key)) - flt(d._new_gl.get(key))) >= 0.01 and key[0] != round_off:
			frappe.throw(_("{0}: {1} came out different from the preview.").format(d.name, key[0]))
	if not frappe.db.count("Payment Ledger Entry", {"voucher_type": PI, "voucher_no": d.name,
													"against_voucher_no": d.against, "delinked": 0}):
		frappe.throw(_("{0}: its payable row is missing after the rebuild.").format(d.name))


def _plan_sig(plan):
	return _tb()._plan_token([plan])


def apply_plan(spec, expected_sig, allow_filed):
	"""Replay the year for real and save it, as one transaction. Returns the results."""
	frappe.db.savepoint("bns_tds_v16_apply")
	try:
		plan = plan_supplier_year(
			spec["supplier"], spec["company"], date=spec.get("date"), mode=spec.get("mode", "keep"),
			overrides=spec.get("overrides"), scope=spec.get("scope", "all"), allow_filed=allow_filed, keep=True,
		)
		if plan.problems:
			frappe.throw("; ".join(plan.problems))
		if _plan_sig(plan) != expected_sig:
			frappe.throw(_("The invoices of {0} changed since the preview. Preview again.").format(plan.supplier_name))
		done, skipped = [], []
		for d in plan.docs:
			if d.action == "none":
				continue
			if d.blocked:
				skipped.append({"purchase_invoice": d.name, "reason": cstr(d.blocked)})
				continue
			frappe.has_permission(PI, "write", doc=d.name, throw=True)
			done.append(_save_doc(d))
	except Exception:
		frappe.db.rollback(save_point="bns_tds_v16_apply")
		raise
	return done, skipped


def _save_doc(d):
	tb = _tb()
	before = frappe.db.get_value(PI, d.name, ["grand_total", "rounded_total", "outstanding_amount", "paid_amount"],
								 as_dict=True)
	for r in d.rows:
		want = d._cats.get(r.name)
		if cstr(r.tax_withholding_category or "") != cstr(want or ""):
			frappe.db.set_value(PI_ITEM, r.name, "tax_withholding_category", want or None, update_modified=False)
	if d.action == "flags":
		if cint(d.apply_tds) != cint(d._apply):
			frappe.db.set_value(PI, d.name, "apply_tds", d._apply, update_modified=True)
		_comment(d, before, None)
		return {"purchase_invoice": d.name, "action": "flags"}

	pi = d._doc
	caps = d.get("caps") or []
	if caps:
		tb._unreconcile(pi, caps)
	_persist(pi, d)
	tb._rebuild_gl(pi.name)
	if caps:
		tb._reallocate(pi.name, caps)
	from erpnext.accounts.utils import update_voucher_outstanding

	update_voucher_outstanding(PI, d.against, pi.credit_to, "Supplier", pi.supplier)
	if d.against != pi.name:
		update_voucher_outstanding(PI, pi.name, pi.credit_to, "Supplier", pi.supplier)
	_verify(d)
	auto_paid_supplier.assert_auto_paid_settled(d.name)
	after = frappe.db.get_value(PI, d.name, ["grand_total", "rounded_total", "outstanding_amount", "paid_amount"],
								as_dict=True)
	_comment(d, before, after, caps)
	out = {"purchase_invoice": d.name, "action": "ledger", "tds_before": flt(d.current_tds),
		   "tds_after": flt(d.target_tds), "account": d.target_account, "payments_cut": caps,
		   "outstanding_after": flt(after.outstanding_amount)}
	if d.get("auto_paid"):
		out.update(paid_before=flt(before.paid_amount), paid_after=flt(after.paid_amount))
	return out


def _persist(pi, d):
	tb = _tb()
	old = {r.name for r in d.tds_rows}
	for t in pi.taxes:
		if cint(t.is_tax_withholding_account):
			t.parent, t.parenttype, t.parentfield, t.docstatus = pi.name, PI, "taxes", 1
			if t.name and t.name in old:
				t.db_update()
				old.discard(t.name)
			else:
				t.name = None
				t.db_insert()
		elif frappe.db.get_value(TAX_ROW, t.name, "idx") != t.idx:
			frappe.db.set_value(TAX_ROW, t.name, "idx", t.idx, update_modified=False)
	for name in old:
		frappe.db.delete(TAX_ROW, {"name": name})

	# Item-wise tax breakup: made again from the recalculated invoice, as a save does.
	if frappe.get_meta(PI).has_field("item_wise_tax_details"):
		from erpnext.controllers.taxes_and_totals import process_item_wise_tax_details

		frappe.db.delete("Item Wise Tax Detail", {"parenttype": PI, "parent": pi.name})
		pi.docstatus = 1
		pi.update_item_wise_tax_details = True
		process_item_wise_tax_details(pi)

	meta = frappe.get_meta(PI)
	updates = {f: pi.get(f) for f in tb._HEADER_TOTAL_FIELDS if meta.has_field(f)}
	updates["apply_tds"] = cint(d._apply)
	if d.get("auto_paid"):
		updates.update(paid_amount=pi.paid_amount, base_paid_amount=pi.base_paid_amount, outstanding_amount=0)
	frappe.db.set_value(PI, pi.name, updates, update_modified=True)


def _comment(d, before, after, caps=None):
	fmt = lambda v: frappe.format_value(flt(v), {"fieldtype": "Currency"})  # noqa: E731
	lines = [
		_("TDS recalculated by BNS ({0}).").format(frappe.session.user),
		_("Category: {0} → {1}").format(d.current_category or "—", d.category or "—"),
	]
	if after:
		lines.append(_("TDS: {0} → {1} on {2}").format(fmt(d.current_tds), fmt(d.target_tds),
													   d.target_account or ", ".join(d.current_accounts) or "—"))
		lines.append(_("Grand total: {0} → {1}; outstanding: {2} → {3}").format(
			fmt(before.rounded_total or before.grand_total), fmt(after.rounded_total or after.grand_total),
			fmt(before.outstanding_amount), fmt(after.outstanding_amount)))
		if d.get("auto_paid"):
			lines.append(_("Paid amount (auto-paid supplier): {0} → {1}").format(
				fmt(before.paid_amount), fmt(after.paid_amount)))
	else:
		lines.append(_("Tax Withholding Entries and categories updated; no ledger change."))
	for c in caps or []:
		lines.append(_("{0} {1}: allocation {2} → {3}").format(
			c["voucher_type"], c["voucher_no"], fmt(c["allocated"]), fmt(c["new_allocated"])))
	frappe.get_doc({
		"doctype": "Comment", "comment_type": "Info", "reference_doctype": PI, "reference_name": d.name,
		"content": "<br>".join(frappe.utils.escape_html(x) for x in lines),
	}).insert(ignore_permissions=True)


def run_plans(plans, specs, allow_filed):
	"""Apply each PAN-year as one transaction, in the order given."""
	tb = _tb()
	done, errors, skipped = [], [], []
	for plan, spec in zip(plans, specs):
		if plan.problems:
			skipped.append({"purchase_invoice": plan.supplier_name, "reason": "; ".join(plan.problems)})
			continue
		if not any(d.action != "none" for d in plan.docs):
			continue
		try:
			changed, left = apply_plan(spec, _plan_sig(plan), allow_filed)
			done += changed
			skipped += left
			tb._commit()
		except Exception as e:
			errors.append({"purchase_invoice": plan.supplier_name, "error": cstr(e)})
			frappe.log_error(title=f"BNS TDS v16 apply failed: {plan.supplier}")
	return done, errors, skipped
