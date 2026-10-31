"""TDS on already-submitted Purchase Invoices: backfill, change category, redo, re-map.

Old invoices entered without TDS can't be fixed by cancel + amend: a re-submit re-books
Input GST and India Compliance blocks that for filed periods. So the tax is changed on
the submitted invoice itself, in two steps.

1. Plan, read-only. TDS is worked out for a supplier's whole fiscal year at once, in
   posting order, by the rules ERPNext v15 applies at submit (single and cumulative
   threshold, tax only on the excess, round-off). Debit notes reduce the running total.
   The result for an invoice depends only on the invoices dated before it, never on
   which of them happen to carry TDS right now, so the order the tool runs in does
   not matter.
2. Apply, per invoice whose TDS or TDS account actually changes. The TDS row and the
   header totals are saved on the invoice. Then its ledger is rebuilt the way Repost
   Accounting Ledger does it: delete the invoice's GL and Payment Ledger rows and make
   them again from the document. So there are no contra pairs, and the invoice's own
   payable row stays linked. Payments stay allocated; only when they exceed the new
   invoice total is the newest one cut back to fit.

Every write path needs the token from a preview of the same plan. An invoice is refused
when the rebuild would move any line other than TDS, the supplier and round-off (stock,
GST and expense lines never move), in a frozen period, in a quarter marked filed in BNS
Settings (a System Manager may override), or when it is foreign-currency, cash-paid,
written off, or has TDS adjusted from an advance.

A debit note's ledger is never changed: it lowers the TDS base of the invoices after it.
Its category fields are set to those of the invoice it returns (header only), so ERPNext
counts it the same way; changing a debit note's category changes that invoice's.

Who may use it: BNS Settings `enable_tds_category_fixables` on, a role listed in
`tds_backfill_roles` (System Manager always allowed), and write permission on each
Purchase Invoice that changes. The same check draws the button and guards every endpoint.

ERPNext v16 keeps TDS in Tax Withholding Entries instead; there
the tools stay off (no button, no dashboard section, endpoints refuse).
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_first_day, get_last_day, getdate, add_months, today

from business_needed_solutions.business_needed_solutions.compat import get_frozen_accounts_settings

PI = "Purchase Invoice"
TAX_ROW = "Purchase Taxes and Charges"

# Header fields that a TDS change recomputes and that are saved back on the invoice.
_HEADER_TOTAL_FIELDS = (
    "taxes_and_charges_added", "base_taxes_and_charges_added",
    "taxes_and_charges_deducted", "base_taxes_and_charges_deducted",
    "total_taxes_and_charges", "base_total_taxes_and_charges",
    "grand_total", "base_grand_total",
    "rounding_adjustment", "base_rounding_adjustment",
    "rounded_total", "base_rounded_total",
    "in_words", "base_in_words",
    "apply_tds", "tax_withholding_category",
    "tax_withholding_net_total", "base_tax_withholding_net_total",
)

# Lines on the invoice's own voucher that a TDS change may move. Anything else refuses.
_LATE_INTEREST_RATE = 1.0  # % per month or part of a month, section 201(1A)(i)
_INLINE_LIMIT = 20  # more invoice changes than this run in the background


# --------------------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------------------

def _feature_enabled() -> bool:
    # One BNS Settings switch governs the dashboard TDS tools and the per-invoice button.
    if not _tax_withholding_on_invoice():
        return False
    return bool(frappe.db.get_single_value("BNS Settings", "enable_tds_category_fixables", cache=True))


def _tax_withholding_on_invoice() -> bool:
    """These tools implement ERPNext v15's tax withholding, which keeps the category on
    the invoice. v16 moved it to Tax Withholding Entries and removed Purchase Invoice
    `tax_withholding_category`; the tools are not ported to that, so they stay off."""
    return frappe.get_meta(PI).has_field("tax_withholding_category")


def _get_roles():
    key = "_bns_tds_backfill_roles"
    if key not in frappe.flags:
        frappe.flags[key] = set(
            frappe.get_all(
                "Has Role",
                filters={"parenttype": "BNS Settings", "parentfield": "tds_backfill_roles"},
                pluck="role",
            )
        )
    return frappe.flags[key]


@frappe.whitelist()
def can_backfill_tds(user: str = None) -> bool:
    # Answers False rather than throwing: every submitted Purchase Invoice form asks
    # this to decide whether to draw the button.
    if frappe.session.user == "Guest":
        return False
    if not _feature_enabled():
        return False
    # Only a System Manager may ask about somebody else.
    if user and user != frappe.session.user and "System Manager" not in frappe.get_roles():
        user = None
    roles = set(frappe.get_roles(user or frappe.session.user))
    return "System Manager" in roles or bool(_get_roles() & roles)


def _require_tool(write=False):
    """The same check as the Change TDS Category button: the tools are on, the user holds
    a TDS role from BNS Settings (or System Manager), and may read, or for a change write,
    Purchase Invoices. Write paths also check every invoice they change (_require_write_on)."""
    if not can_backfill_tds():
        frappe.throw(
            _("TDS tools are disabled, or your role is not listed under TDS roles in BNS Settings."),
            frappe.PermissionError,
        )
    ptype = "write" if write else "read"
    if not frappe.has_permission(PI, ptype):
        frappe.throw(
            _("You need {0} permission on Purchase Invoice to use the TDS tools.").format(_(ptype)),
            frappe.PermissionError,
        )


def _require_write_on(plans):
    """Every invoice the plan would change must be one the user may write."""
    denied = sorted({d.name for p in plans for d in p.docs
                     if d.action in ("ledger", "flags") and not d.blocked
                     and not frappe.has_permission(PI, "write", doc=d.name)})
    if denied:
        shown = ", ".join(denied[:10]) + (_(" and {0} more").format(len(denied) - 10) if len(denied) > 10 else "")
        frappe.throw(
            _("You don't have write permission on these Purchase Invoices: {0}").format(shown),
            frappe.PermissionError,
        )


def _is_system_manager():
    return "System Manager" in frappe.get_roles()


def _commit():
    # Tests run inside one transaction and roll it back at the end.
    if not frappe.flags.in_test:
        frappe.db.commit()


# --------------------------------------------------------------------------------------
# Small readers
# --------------------------------------------------------------------------------------

def _fiscal_year(company, date=None):
    from erpnext.accounts.utils import get_fiscal_year

    fy = get_fiscal_year(date or today(), company=company, as_dict=True)
    return getdate(fy.year_start_date), getdate(fy.year_end_date)


def _current_fy(company):
    return _fiscal_year(company)


def _default_company(company=None):
    return (
        company
        or frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )


def _filed_upto():
    if not frappe.get_meta("BNS Settings").has_field("tds_filed_upto"):
        return None
    value = frappe.db.get_single_value("BNS Settings", "tds_filed_upto")
    # v15 reads an empty Date single back as 0001-01-01
    value = getdate(value) if value else None
    return value if value and value.year > 1900 else None


def _frozen_upto(company):
    frozen, modifier = get_frozen_accounts_settings(company)
    if not frozen:
        return None
    if modifier and modifier in frappe.get_roles():
        return None
    return getdate(frozen)


def _quarter(date):
    m = getdate(date).month
    return "Q1" if 4 <= m <= 6 else "Q2" if 7 <= m <= 9 else "Q3" if 10 <= m <= 12 else "Q4"


def _months_late(posting_date):
    """Months, or part of a month, from the invoice date to today: the period that
    interest under section 201(1A)(i) runs for TDS deducted only now."""
    from dateutil.relativedelta import relativedelta

    start, end = getdate(posting_date), getdate(today())
    if end <= start:
        return 0
    rd = relativedelta(end, start)
    return rd.years * 12 + rd.months + (1 if rd.days else 0)


def normal_round(number):
    """ERPNext's own rounding for TDS (halves go up)."""
    whole = int(number)
    return whole + (1 if number - whole >= 0.5 else 0)


def _rupee(value):
    return normal_round(abs(flt(value))) * (1 if flt(value) >= 0 else -1)


def _parties(supplier):
    """The supplier and every other supplier with the same PAN, as ERPNext groups them."""
    if frappe.get_meta("Supplier").has_field("pan"):
        pan = (frappe.db.get_value("Supplier", supplier, "pan") or "").strip()
        if pan:
            return frappe.get_all("Supplier", filters={"pan": pan}, pluck="name") or [supplier]
    return [supplier]


def _category_rule(category, company, posting_date, cache):
    key = (category, company, str(posting_date))
    if key in cache:
        return cache[key]
    rule = frappe._dict(category=category, problem=None)
    if not frappe.db.exists("Tax Withholding Category", category):
        rule.problem = _("Tax Withholding Category {0} does not exist.").format(category)
        cache[key] = rule
        return rule
    doc = frappe.get_cached_doc("Tax Withholding Category", category)
    rule.account = next((a.account for a in doc.accounts if a.company == company), None)
    rate = next(
        (r for r in doc.rates if getdate(r.from_date) <= getdate(posting_date) <= getdate(r.to_date)),
        None,
    )
    rule.update(
        description=doc.category_name or category,
        tax_on_excess=cint(doc.tax_on_excess_amount),
        round_off=cint(doc.round_off_tax_amount),
        party_ledger=cint(doc.consider_party_ledger_amount),
    )
    if not rule.account:
        rule.problem = _("{0} has no account for company {1}.").format(category, company)
    elif not rate:
        rule.problem = _("{0} has no rate for {1}.").format(category, posting_date)
    else:
        rule.update(
            rate=flt(rate.tax_withholding_rate),
            threshold=flt(rate.single_threshold),
            cumulative=flt(rate.cumulative_threshold),
        )
    cache[key] = rule
    return rule


def _is_internal(doc, company_pan, supplier_pans):
    """A purchase from a branch of the same legal entity: no deductee, no TDS."""
    if cint(doc.get("is_bns_internal_supplier")) or cint(doc.get("is_internal_supplier")):
        return True
    pan = supplier_pans.get(doc.supplier)
    return bool(pan) and pan == company_pan


def _cost_center(pi):
    # ERPNext's own choice for the TDS row (tax_withholding_category.get_cost_center).
    if pi.get("taxes"):
        for t in pi.taxes:
            if t.cost_center:
                return t.cost_center
    return frappe.get_cached_value("Company", pi.company, "cost_center")


# --------------------------------------------------------------------------------------
# Plan (read-only)
# --------------------------------------------------------------------------------------

def plan_supplier_year(supplier, company, date=None, mode="keep", overrides=None,
                       scope="all", allow_filed=False):
    """Work out TDS for every invoice of `supplier` (and suppliers sharing its PAN) in the
    fiscal year containing `date`, and what would change. Never writes.

    mode      "keep": each invoice keeps its own category (its category when apply_tds
              is on, none otherwise). "supplier": the supplier's invoices take the
              supplier's category as it stands now (the redo).
    overrides {invoice: category or ""} on top of the mode ("" takes TDS off).
    scope     "all", or "account" to move TDS to the category's account and change no
              amount (the re-map).
    """
    overrides = {k: (v or None) for k, v in (overrides or {}).items()}
    fy_start, fy_end = _fiscal_year(company, date)
    parties = _parties(supplier)
    plan = frappe._dict(
        supplier=supplier,
        supplier_name=frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier,
        company=company, fiscal_year_start=str(fy_start), fiscal_year_end=str(fy_end),
        mode=mode, scope=scope, overrides=overrides, parties=parties,
        problems=[], warnings=[], docs=[],
    )
    if not _tax_withholding_on_invoice():
        plan.problems.append(_("This ERPNext version keeps TDS in Tax Withholding Entries; not supported."))
        return plan

    docs = _load_year(parties, company, fy_start, fy_end)
    if not docs:
        return plan
    by_name = {d.name: d for d in docs}
    unknown = [n for n in overrides if n not in by_name]
    if unknown:
        frappe.throw(_("{0} is not an invoice of {1} in this fiscal year.").format(", ".join(unknown), supplier))

    company_pan = (frappe.db.get_value("Company", company, "pan") or "").strip().upper()
    supplier_info = {
        r.name: r for r in frappe.get_all(
            "Supplier", filters={"name": ["in", parties]},
            fields=["name", "tax_withholding_category"]
            + (["pan"] if frappe.get_meta("Supplier").has_field("pan") else []),
        )
    }
    supplier_pans = {k: (v.get("pan") or "").strip().upper() for k, v in supplier_info.items()}

    # 1) the category each invoice ends up in
    for d in docs:
        d.internal = _is_internal(d, company_pan, supplier_pans)
        if d.internal or d.is_opening == "Yes":
            d.category = d.current_category if cint(d.apply_tds) else None
            continue
        if d.name in overrides:
            d.category = overrides[d.name]
        elif mode == "supplier" and d.supplier == supplier:
            d.category = supplier_info[supplier].tax_withholding_category or None
        else:
            d.category = d.current_category if cint(d.apply_tds) else None
            # A TDS row with apply_tds off (added by hand or by a tax template) is
            # left alone unless the user asked for this invoice or for a redo.
            d.keep_as_is = bool(d.current_tds and not d.category)
    for d in docs:
        if cint(d.is_return) and not d.internal and d.is_opening != "Yes":
            original = by_name.get(d.return_against)
            if original is not None:
                d.category = original.category
            elif d.name not in overrides and not d.category:
                d.category = supplier_info[d.supplier].tax_withholding_category or None

    # 2) TDS per category, in posting order
    cache = {}
    groups = {}
    for d in docs:
        d.update(target_tds=d.current_tds, target_account=None, rate=None, withheld=[], description=None,
                 warnings=[], blocked=None, action="none")
        if d.category and not d.internal and d.is_opening != "Yes":
            groups.setdefault(d.category, []).append(d)

    for category, group in groups.items():
        problem = _group_problem(category, company, parties, supplier_pans, fy_start, fy_end)
        rule0 = _category_rule(category, company, group[0].posting_date, cache)
        if rule0.get("party_ledger"):
            problem = problem or _("{0} counts party ledger amounts; fix by hand.").format(category)
        if rule0.problem:
            problem = problem or rule0.problem
        if rule0.account and not rule0.round_off:
            plan.warnings.append(
                _("{0} does not round TDS to whole rupees (Round Off Tax Amount is off).").format(category)
            )
        cumulative, deducted, pending = 0.0, False, []
        for d in group:
            if problem:
                d.blocked = problem
                continue
            if cint(d.is_return):
                cumulative += d.taxable
                pending.append(d)
                continue
            rule = _category_rule(category, company, d.posting_date, cache)
            if rule.problem:
                d.blocked = rule.problem
                continue
            d.rate, d.target_account, d.description = rule.rate, rule.account, rule.description
            if deducted:
                amount = d.taxable * rule.rate / 100
            else:
                single = rule.threshold and d.taxable >= rule.threshold
                crossed = rule.cumulative and (cumulative + d.taxable) >= rule.cumulative
                amount = 0.0
                if single or crossed:
                    base = cumulative + d.taxable
                    if crossed and rule.tax_on_excess:
                        base -= rule.cumulative
                    amount = base * rule.rate / 100 if base > 0 else 0.0
                    d.withheld = [
                        {"voucher_type": PI, "voucher_name": p.name, "taxable_amount": p.taxable}
                        for p in pending
                    ]
                cumulative += d.taxable
                pending.append(d)
            amount = normal_round(amount) if rule.round_off else flt(amount, 2)
            d.target_tds = amount
            if amount > 0:
                deducted = True

    # 3) what changes
    filed_upto = _filed_upto()
    frozen_upto = _frozen_upto(company)
    challan_cache = {}
    for d in docs:
        _decide(d, scope, cache, company)
        if d.action == "ledger":
            d.blocked = d.blocked or _ledger_block(d, company, filed_upto, frozen_upto, allow_filed)
            d.quarter = _quarter(d.posting_date)
            d.filed = bool(filed_upto and getdate(d.posting_date) <= filed_upto)
            delta = flt(d.target_tds) - flt(d.current_tds)
            d.months_late = _months_late(d.posting_date) if delta > 0 else 0
            d.late_interest = flt(delta * _LATE_INTEREST_RATE / 100 * d.months_late, 2) if delta > 0 else 0
            d.challans = _challans_for_month(
                {d.target_account, *d.current_accounts} - {None}, d.posting_date, challan_cache
            )
            if not d.blocked:
                _preview_ledger(d)

    plan.docs = docs
    plan.token = _plan_token([plan])
    return plan


def _load_year(parties, company, fy_start, fy_end):
    meta = frappe.get_meta(PI)
    fields = [
        "name", "supplier", "posting_date", "posting_time", "is_return", "return_against",
        "apply_tds", "tax_withholding_category as current_category", "is_opening", "is_paid",
        "write_off_amount", "conversion_rate", "currency", "party_account_currency",
        "credit_to", "base_net_total", "grand_total", "outstanding_amount",
        "taxes_and_charges_deducted", "base_tax_withholding_net_total",
    ]
    fields += [f for f in ("is_internal_supplier", "is_bns_internal_supplier") if meta.has_field(f)]
    docs = frappe.get_all(
        PI,
        filters={
            "docstatus": 1, "company": company, "supplier": ["in", parties],
            "posting_date": ["between", [fy_start, fy_end]],
        },
        fields=fields,
        order_by="posting_date asc, posting_time asc, name asc",
    )
    if not docs:
        return []
    names = [d.name for d in docs]

    taxable = {}
    if frappe.get_meta("Purchase Invoice Item").has_field("apply_tds"):
        for parent, amount in frappe.db.sql(
            """SELECT parent, SUM(base_net_amount) FROM `tabPurchase Invoice Item`
               WHERE parenttype = 'Purchase Invoice' AND parent IN %(n)s AND apply_tds = 1
               GROUP BY parent""",
            {"n": names},
        ):
            taxable[parent] = flt(amount)
    rows = frappe.db.sql(
        """SELECT parent, name, account_head, base_tax_amount_after_discount_amount AS amount
           FROM `tabPurchase Taxes and Charges`
           WHERE parenttype = 'Purchase Invoice' AND parent IN %(n)s AND is_tax_withholding_account = 1
           ORDER BY idx""",
        {"n": names}, as_dict=True,
    )
    tds_rows = {}
    for r in rows:
        tds_rows.setdefault(r.parent, []).append(r)
    advance_tax = set()
    if frappe.db.exists("DocType", "Advance Tax"):
        advance_tax = set(frappe.db.sql_list(
            "SELECT DISTINCT parent FROM `tabAdvance Tax` WHERE parenttype = 'Purchase Invoice' AND parent IN %(n)s",
            {"n": names},
        ))

    item_level = frappe.get_meta("Purchase Invoice Item").has_field("apply_tds")
    for d in docs:
        d.posting_date = getdate(d.posting_date)
        d.taxable = flt(taxable.get(d.name, 0.0) if item_level else d.base_net_total, 2)
        d.tds_rows = tds_rows.get(d.name, [])
        d.current_tds = flt(sum(flt(r.amount) for r in d.tds_rows), 2)
        d.current_accounts = sorted({r.account_head for r in d.tds_rows})
        d.has_advance_tax = d.name in advance_tax
    return docs


def _group_problem(category, company, parties, supplier_pans, fy_start, fy_end):
    """Cases this tool does not model: they are left to be fixed by hand."""
    pans = [p for p in supplier_pans.values() if p]
    if pans and frappe.db.exists("DocType", "Lower Deduction Certificate"):
        if frappe.db.exists("Lower Deduction Certificate", {
            "pan_no": ["in", pans], "tax_withholding_category": category, "company": company,
            "valid_from": ["<=", fy_end], "valid_upto": [">=", fy_start],
        }):
            return _("A Lower Deduction Certificate applies under {0}; fix by hand.").format(category)
    if frappe.db.exists("Payment Entry", {
        "party_type": "Supplier", "party": ["in", parties], "docstatus": 1, "company": company,
        "apply_tax_withholding_amount": 1, "tax_withholding_category": category,
        "posting_date": ["between", [fy_start, fy_end]],
    }):
        return _("TDS under {0} was also deducted on a Payment Entry this year; fix by hand.").format(category)
    if frappe.get_meta("Journal Entry").has_field("apply_tds") and frappe.db.sql(
        """SELECT 1 FROM `tabJournal Entry` j JOIN `tabJournal Entry Account` ja ON ja.parent = j.name
           WHERE j.docstatus = 1 AND j.company = %(c)s AND j.apply_tds = 1
             AND j.tax_withholding_category = %(cat)s AND ja.party IN %(p)s
             AND j.posting_date BETWEEN %(s)s AND %(e)s LIMIT 1""",
        {"c": company, "cat": category, "p": parties, "s": fy_start, "e": fy_end},
    ):
        return _("TDS under {0} was also deducted on a Journal Entry this year; fix by hand.").format(category)
    return None


def _decide(d, scope, cache, company):
    """Set d.action: "ledger" (TDS amount or account changes), "flags" (only the
    invoice's category / apply_tds / TDS base change) or "none"."""
    if d.internal or d.is_opening == "Yes" or d.get("keep_as_is"):
        d.target_tds = d.current_tds
        return
    if cint(d.is_return):
        # A debit note only lowers the TDS base of the invoices after it; its own ledger
        # is never changed here. Its category fields are set to the category it follows
        # (the invoice it returns), because ERPNext counts a debit note in later invoices'
        # TDS only when it carries apply_tds and that category. One with its own TDS row
        # is left alone.
        d.target_tds = d.current_tds
        if not d.blocked and not d.current_tds and scope != "account" and _flags_change(d):
            d.action = "flags"
        return
    if d.blocked:
        # The category's year could not be worked out; nothing is changed, and the
        # preview lists the invoice with the reason.
        d.target_tds = d.current_tds
        return
    if scope == "account":
        d.target_tds = d.current_tds
        if not d.current_tds or not d.category:
            return
        if d.target_account and d.current_accounts != [d.target_account]:
            d.action = "ledger"
        return
    if not d.category:
        d.target_tds, d.target_account = 0.0, None
    if _amount_changes(d, cache, company) or (
        d.target_tds > 0 and d.target_account and d.current_accounts != [d.target_account]
    ):
        d.action = "ledger"
    elif _flags_change(d):
        d.action = "flags"


def _amount_changes(d, cache, company):
    if d.category:
        rule = _category_rule(d.category, company, d.posting_date, cache)
        if rule.get("round_off"):
            return abs(flt(d.target_tds) - flt(d.current_tds)) >= 0.005
    return _rupee(d.target_tds) != _rupee(d.current_tds)


def _flags_change(d):
    want_apply = 1 if d.category else 0
    if cint(d.apply_tds) != want_apply:
        return True
    if d.category and cstr(d.current_category or "") != cstr(d.category):
        return True
    return bool(d.category and abs(flt(d.base_tax_withholding_net_total) - d.taxable) >= 0.01)


def _ledger_block(d, company, filed_upto, frozen_upto, allow_filed):
    if frozen_upto and getdate(d.posting_date) <= frozen_upto:
        return _("In the frozen accounting period (up to {0}).").format(frozen_upto)
    if filed_upto and getdate(d.posting_date) <= filed_upto and not (allow_filed and _is_system_manager()):
        return _("TDS return already filed for {0} (BNS Settings: filed up to {1}).").format(
            _quarter(d.posting_date), filed_upto
        )
    if d.has_advance_tax:
        return _("TDS on this invoice is adjusted from an advance; fix by hand.")
    if cint(d.is_paid):
        return _("Cash-paid invoice (Is Paid); fix by hand.")
    if flt(d.write_off_amount):
        return _("Invoice has a write-off; fix by hand.")
    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    if (d.party_account_currency and d.party_account_currency != company_currency) or flt(d.conversion_rate) != 1:
        return _("Foreign-currency invoice; fix by hand.")
    if len(d.tds_rows) > 1:
        return _("Invoice has more than one TDS row; fix by hand.")
    return None


def _challans_for_month(accounts, posting_date, cache):
    """TDS already paid out of these accounts for the invoice's month: payments and
    journals debiting them from the 1st of that month to the end of the next (the
    challan for a month is due by the 7th of the next)."""
    if not accounts:
        return 0.0
    start = get_first_day(posting_date)
    end = get_last_day(add_months(start, 1))
    key = (tuple(sorted(accounts)), str(start))
    if key not in cache:
        cache[key] = flt(frappe.db.sql(
            """SELECT IFNULL(SUM(debit), 0) FROM `tabGL Entry`
               WHERE account IN %(a)s AND is_cancelled = 0
                 AND voucher_type IN ('Journal Entry', 'Payment Entry')
                 AND posting_date BETWEEN %(s)s AND %(e)s""",
            {"a": tuple(accounts), "s": start, "e": end},
        )[0][0], 2)
    return cache[key]


def _plan_token(plans):
    """Fingerprint of everything a plan would write. Apply recomputes the plan and
    refuses if it differs from the one that was previewed."""
    rows = []
    for plan in plans:
        for d in plan.docs:
            if d.action in ("ledger", "flags") and not d.blocked:
                rows.append([d.name, d.action, flt(d.current_tds, 2), flt(d.target_tds, 2),
                             d.target_account or "", d.category or "", d.current_accounts])
    return hashlib.sha1(json.dumps(rows, default=str).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------------------
# One invoice: rebuild in memory, check, write
# --------------------------------------------------------------------------------------

def _build(d):
    """The invoice as it would be after the change, in memory. Returns (pi, problem,
    moved) where `moved` lists the GL lines that change, by account."""
    pi = frappe.get_doc(PI, d.name)
    snap = _snapshot(pi)
    rows = [t for t in pi.taxes if cint(t.is_tax_withholding_account)]
    d._row_names = [t.name for t in rows]
    if flt(d.target_tds) > 0:
        row = rows[0] if rows else pi.append("taxes", {})
        row.update({
            "category": "Total", "charge_type": "Actual", "add_deduct_tax": "Deduct",
            "account_head": d.target_account, "description": d.description or d.target_account,
            "tax_amount": flt(d.target_tds) / flt(pi.conversion_rate or 1),
            "is_tax_withholding_account": 1, "rate": 0, "row_id": None,
            "included_in_print_rate": 0, "cost_center": row.get("cost_center") or _cost_center(pi),
        })
        for extra in rows[1:]:
            pi.remove(extra)
    else:
        for r in rows:
            pi.remove(r)
    pi.apply_tds = 1 if d.category else 0
    pi.tax_withholding_category = d.category or None
    pi.set("tax_withheld_vouchers", d.withheld)
    pi.calculate_taxes_and_totals()

    problem = _compare_snapshot(snap, pi)
    if problem:
        return pi, problem, []

    allowed = {pi.credit_to, d.target_account, *d.current_accounts,
               frappe.get_cached_value("Company", pi.company, "round_off_account")} - {None}
    before = _live_gl_net(pi.name)
    after = _gl_net(pi.get_gl_entries())
    moved = []
    for key in sorted(set(before) | set(after)):
        old, new = flt(before.get(key), 2), flt(after.get(key), 2)
        if abs(old - new) >= 0.01:
            moved.append({"account": key[0], "party": key[2], "before": old, "after": new,
                          "allowed": key[0] in allowed})
    bad = [m for m in moved if not m["allowed"]]
    if bad:
        return pi, _("Rebuilding the ledger would also move {0}; refused.").format(
            ", ".join(m["account"] for m in bad)
        ), moved
    d._new_gl = after
    return pi, None, moved


def _snapshot(pi):
    return {
        "net": (flt(pi.net_total), flt(pi.base_net_total)),
        "items": {i.name: (flt(i.base_net_amount), flt(i.base_amount)) for i in pi.items},
        "taxes": {
            t.name: (t.account_head, flt(t.base_tax_amount_after_discount_amount))
            for t in pi.taxes if not cint(t.is_tax_withholding_account)
        },
    }


def _compare_snapshot(snap, pi):
    after = _snapshot(pi)
    if any(abs(a - b) >= 0.01 for a, b in zip(snap["net"], after["net"])):
        return _("Recalculating the invoice changes its net total; refused.")
    for name, values in snap["items"].items():
        if any(abs(a - b) >= 0.01 for a, b in zip(values, after["items"].get(name, (0, 0)))):
            return _("Recalculating the invoice changes item amounts; refused.")
    for name, (account, amount) in snap["taxes"].items():
        if name not in after["taxes"] or abs(after["taxes"][name][1] - amount) >= 0.01:
            return _("Recalculating the invoice changes the {0} line; refused.").format(account)
    return None


def _gl_net(gl_entries):
    net = {}
    for g in gl_entries or []:
        key = (g.get("account"), g.get("party_type") or "", g.get("party") or "")
        net[key] = net.get(key, 0.0) + flt(g.get("debit")) - flt(g.get("credit"))
    return net


def _live_gl_net(name):
    rows = frappe.db.sql(
        """SELECT account, IFNULL(party_type, '') AS party_type, IFNULL(party, '') AS party,
                  SUM(debit) - SUM(credit) AS net
           FROM `tabGL Entry` WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s
             AND is_cancelled = 0
           GROUP BY account, party_type, party""",
        name, as_dict=True,
    )
    return {(r.account, r.party_type, r.party): flt(r.net) for r in rows}


def _allocations(name):
    """Payments and journals allocated against the invoice: [{voucher_type, voucher_no,
    amount, posting_date}], amount > 0 meaning it reduces what is owed."""
    rows = frappe.db.sql(
        """SELECT voucher_type, voucher_no, MAX(posting_date) AS posting_date,
                  -SUM(amount) AS amount
           FROM `tabPayment Ledger Entry`
           WHERE against_voucher_type = 'Purchase Invoice' AND against_voucher_no = %s
             AND voucher_no != %s AND delinked = 0
           GROUP BY voucher_type, voucher_no
           ORDER BY MAX(posting_date) DESC, voucher_no DESC""",
        (name, name), as_dict=True,
    )
    return [r for r in rows if abs(flt(r.amount)) >= 0.005]


def _plan_caps(d, pi):
    """Which allocations must shrink so payments do not exceed the new invoice total.
    Newest first. Returns (caps, problem)."""
    payable = -flt(d._new_gl.get((pi.credit_to, "Supplier", pi.supplier)), 2)
    allocations = _allocations(pi.name)
    excess = flt(sum(flt(a.amount) for a in allocations) - payable, 2)
    caps = []
    if excess <= 0.005:
        return caps, None, excess
    for a in allocations:
        if excess <= 0.005:
            break
        if a.voucher_type not in ("Payment Entry", "Journal Entry") or flt(a.amount) <= 0:
            continue
        cut = min(flt(a.amount), excess)
        caps.append({"voucher_type": a.voucher_type, "voucher_no": a.voucher_no,
                     "allocated": flt(a.amount, 2), "new_allocated": flt(a.amount - cut, 2)})
        excess = flt(excess - cut, 2)
    if excess > 0.005:
        return caps, _("Debit notes against this invoice exceed its new total; fix by hand."), excess
    return caps, None, excess


def _preview_ledger(d):
    try:
        pi, problem, moved = _build(d)
    except Exception as e:
        d.blocked = _("Could not rebuild the invoice: {0}").format(cstr(e))
        return
    d.moved = moved
    if problem:
        d.blocked = problem
        return
    caps, problem, _excess = _plan_caps(d, pi)
    d.caps = caps
    if problem:
        d.blocked = problem
    d.new_grand_total = flt(pi.rounded_total or pi.grand_total, 2)
    d.old_grand_total = flt(d.grand_total, 2)


def _apply_doc(d):
    """Write one planned change. Raises on anything unexpected; the caller rolls back."""
    frappe.db.get_value(PI, d.name, "name", for_update=True)
    live = frappe.db.sql(
        """SELECT name, account_head, base_tax_amount_after_discount_amount AS amount
           FROM `tabPurchase Taxes and Charges`
           WHERE parenttype = 'Purchase Invoice' AND parent = %s AND is_tax_withholding_account = 1""",
        d.name, as_dict=True,
    )
    if abs(flt(sum(flt(r.amount) for r in live), 2) - flt(d.current_tds, 2)) >= 0.005 or sorted(
        {r.account_head for r in live}
    ) != d.current_accounts:
        frappe.throw(_("{0} changed since the preview. Preview again.").format(d.name))

    before = frappe.db.get_value(
        PI, d.name,
        ["apply_tds", "tax_withholding_category", "grand_total", "rounded_total", "outstanding_amount"],
        as_dict=True,
    )
    if d.action == "flags":
        frappe.db.set_value(PI, d.name, {
            "apply_tds": 1 if d.category else 0,
            "tax_withholding_category": d.category or None,
            "tax_withholding_net_total": d.taxable if d.category else flt(d.base_tax_withholding_net_total),
            "base_tax_withholding_net_total": d.taxable if d.category else flt(d.base_tax_withholding_net_total),
        }, update_modified=True)
        _comment(d, before, None)
        return {"purchase_invoice": d.name, "action": "flags"}

    pi, problem, _moved = _build(d)
    if problem:
        frappe.throw(problem)
    caps, problem, _excess = _plan_caps(d, pi)
    if problem:
        frappe.throw(problem)

    if caps:
        _unreconcile(pi, caps)
    _persist(pi, d)
    _rebuild_gl(pi.name)
    if caps:
        _reallocate(pi.name, caps)

    from erpnext.accounts.utils import update_voucher_outstanding

    update_voucher_outstanding(PI, pi.name, pi.credit_to, "Supplier", pi.supplier)
    _verify(d)
    after = frappe.db.get_value(PI, d.name, ["grand_total", "rounded_total", "outstanding_amount"], as_dict=True)
    _comment(d, before, after, caps)
    return {
        "purchase_invoice": d.name, "action": "ledger",
        "tds_before": flt(d.current_tds), "tds_after": flt(d.target_tds),
        "account": d.target_account, "payments_cut": caps,
        "outstanding_after": flt(after.outstanding_amount),
    }


def _persist(pi, d):
    # tax rows: the TDS row is the only one that changes; others may only move up a place
    keep = {t.name for t in pi.taxes if t.name}
    for name in d._row_names:
        if name not in keep:
            frappe.db.delete(TAX_ROW, {"name": name})
    for t in pi.taxes:
        if cint(t.is_tax_withholding_account):
            t.parent, t.parenttype, t.parentfield, t.docstatus = pi.name, PI, "taxes", 1
            if t.name and t.name in d._row_names:
                t.db_update()
            else:
                t.name = None
                t.db_insert()
        elif frappe.db.get_value(TAX_ROW, t.name, "idx") != t.idx:
            frappe.db.set_value(TAX_ROW, t.name, "idx", t.idx, update_modified=False)

    if frappe.db.exists("DocType", "Tax Withheld Vouchers"):
        frappe.db.delete("Tax Withheld Vouchers", {"parent": pi.name, "parenttype": PI})
        for r in pi.get("tax_withheld_vouchers") or []:
            r.parent, r.parenttype, r.parentfield, r.docstatus = pi.name, PI, "tax_withheld_vouchers", 1
            r.name = None
            r.db_insert()

    meta = frappe.get_meta(PI)
    updates = {f: pi.get(f) for f in _HEADER_TOTAL_FIELDS if meta.has_field(f)}
    updates["tax_withholding_category"] = d.category or None
    updates["apply_tds"] = 1 if d.category else 0
    frappe.db.set_value(PI, pi.name, updates, update_modified=True)


def _rebuild_gl(name):
    """Repost Accounting Ledger for one invoice: drop its GL and payment ledger rows,
    then make them again from the saved document. Payments' own rows are not touched,
    so their allocations against the invoice stay."""
    for table in ("GL Entry", "Payment Ledger Entry", "Advance Payment Ledger Entry"):
        if frappe.db.exists("DocType", table):
            frappe.db.delete(table, {"voucher_type": PI, "voucher_no": name})
    previous = frappe.flags.through_repost_accounting_ledger
    frappe.flags.through_repost_accounting_ledger = True
    try:
        doc = frappe.get_doc(PI, name)
        doc.flags.ignore_permissions = True
        if hasattr(doc, "force_set_against_expense_account"):
            doc.force_set_against_expense_account()
        doc.make_gl_entries()
    finally:
        frappe.flags.through_repost_accounting_ledger = previous


def _verify(d):
    totals = frappe.db.sql(
        """SELECT IFNULL(SUM(debit), 0), IFNULL(SUM(credit), 0) FROM `tabGL Entry`
           WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s AND is_cancelled = 0""",
        d.name,
    )[0]
    if abs(flt(totals[0]) - flt(totals[1])) >= 0.01:
        frappe.throw(_("{0}: debit and credit differ after the rebuild.").format(d.name))
    live = _live_gl_net(d.name)
    for key in set(live) | set(d._new_gl):
        if abs(flt(live.get(key)) - flt(d._new_gl.get(key))) >= 0.01:
            account = key[0]
            if account != frappe.get_cached_value("Company", frappe.db.get_value(PI, d.name, "company"), "round_off_account"):
                frappe.throw(_("{0}: {1} came out different from the preview.").format(d.name, account))
    own = frappe.db.count("Payment Ledger Entry", {
        "voucher_type": PI, "voucher_no": d.name, "against_voucher_no": d.name, "delinked": 0,
    })
    if not own:
        frappe.throw(_("{0}: the invoice's own payable row is missing after the rebuild.").format(d.name))


def _unreconcile(pi, caps):
    from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
        create_unreconcile_doc_for_selection,
    )

    for c in caps:
        if c["voucher_type"] == "Journal Entry":
            rows = frappe.get_all(
                "Journal Entry Account",
                filters={"parent": c["voucher_no"], "reference_type": PI, "reference_name": pi.name},
                fields=["name", "debit_in_account_currency", "credit_in_account_currency"],
            )
            if len(rows) != 1:
                frappe.throw(_("{0} is split over several lines for {1}; fix by hand.").format(c["voucher_no"], pi.name))
            c["voucher_detail_no"] = rows[0].name
    create_unreconcile_doc_for_selection(json.dumps([
        {"company": pi.company, "voucher_type": c["voucher_type"], "voucher_no": c["voucher_no"],
         "against_voucher_type": PI, "against_voucher_no": pi.name}
        for c in caps
    ]))


def _reallocate(name, caps):
    """Allocate each cut payment again, up to its new share."""
    from erpnext.accounts.utils import reconcile_against_document

    pi = frappe.get_doc(PI, name)
    for c in caps:
        if flt(c["new_allocated"]) <= 0:
            continue
        if c["voucher_type"] == "Payment Entry":
            unallocated = flt(frappe.db.get_value("Payment Entry", c["voucher_no"], "unallocated_amount"))
            detail, dr_or_cr = None, "debit_in_account_currency"
        else:
            detail = c["voucher_detail_no"]
            row = frappe.db.get_value("Journal Entry Account", detail,
                                      ["debit_in_account_currency", "credit_in_account_currency"], as_dict=True)
            dr_or_cr = "debit_in_account_currency" if flt(row.debit_in_account_currency) else "credit_in_account_currency"
            unallocated = flt(row.get(dr_or_cr))
        reconcile_against_document([frappe._dict({
            "voucher_type": c["voucher_type"], "voucher_no": c["voucher_no"], "voucher_detail_no": detail,
            "against_voucher_type": PI, "against_voucher": name,
            "account": pi.credit_to, "party_type": "Supplier", "party": pi.supplier,
            "is_advance": None, "dr_or_cr": dr_or_cr,
            "unreconciled_amount": unallocated, "unadjusted_amount": unallocated,
            "allocated_amount": flt(c["new_allocated"]),
            "grand_total": flt(pi.grand_total), "outstanding_amount": flt(pi.outstanding_amount),
            "exchange_rate": 1, "difference_amount": 0, "difference_account": None,
            "cost_center": pi.get("cost_center"),
        })])


def _comment(d, before, after, caps=None):
    fmt = lambda v: frappe.format_value(flt(v), {"fieldtype": "Currency"})  # noqa: E731
    lines = [
        _("TDS changed by BNS ({0}).").format(frappe.session.user),
        _("Category: {0} → {1}").format(before.tax_withholding_category or "—", d.category or "—"),
        _("TDS: {0} → {1} on {2}").format(fmt(d.current_tds), fmt(d.target_tds),
                                          d.target_account or ", ".join(d.current_accounts) or "—"),
    ]
    if after:
        lines.append(_("Grand total: {0} → {1}; outstanding: {2} → {3}").format(
            fmt(before.rounded_total or before.grand_total), fmt(after.rounded_total or after.grand_total),
            fmt(before.outstanding_amount), fmt(after.outstanding_amount),
        ))
    for c in caps or []:
        lines.append(_("{0} {1}: allocation {2} → {3}").format(
            c["voucher_type"], c["voucher_no"], fmt(c["allocated"]), fmt(c["new_allocated"])))
    frappe.get_doc({
        "doctype": "Comment", "comment_type": "Info", "reference_doctype": PI,
        "reference_name": d.name, "content": "<br>".join(frappe.utils.escape_html(x) for x in lines),
    }).insert(ignore_permissions=True)


# --------------------------------------------------------------------------------------
# Running plans
# --------------------------------------------------------------------------------------

def run_plans(plans):
    """Apply the plans' changes in posting order, one invoice per transaction. Stops a
    supplier's year at its first failure: later invoices were planned assuming the
    earlier ones changed."""
    done, errors, skipped = [], [], []
    for plan in plans:
        for d in plan.docs:
            if d.action not in ("ledger", "flags"):
                continue
            if d.blocked:
                skipped.append({"purchase_invoice": d.name, "reason": cstr(d.blocked)})
                continue
            frappe.db.savepoint("bns_tds")
            try:
                done.append(_apply_doc(d))
                _commit()
            except Exception as e:
                frappe.db.rollback(save_point="bns_tds")
                errors.append({"purchase_invoice": d.name, "error": cstr(e)})
                frappe.log_error(title=f"BNS TDS change failed: {d.name}")
                break
    summary = {
        "changed": len([x for x in done if x["action"] == "ledger"]),
        "flagged": len([x for x in done if x["action"] == "flags"]),
        "tds_before": flt(sum(x.get("tds_before", 0) for x in done), 2),
        "tds_after": flt(sum(x.get("tds_after", 0) for x in done), 2),
        "payments_cut": [c for x in done for c in x.get("payments_cut", [])],
        "skipped": skipped, "error_count": len(errors), "errors": errors[:50],
        "results": done[:500],
    }
    frappe.log_error(message=frappe.as_json(summary), title="BNS TDS Change")
    _commit()
    return summary


def _plans_from_specs(specs, allow_filed):
    return [
        plan_supplier_year(
            s["supplier"], s["company"], date=s.get("date"), mode=s.get("mode", "keep"),
            overrides=s.get("overrides"), scope=s.get("scope", "all"), allow_filed=allow_filed,
        )
        for s in specs
    ]


def _apply_specs(specs, token, allow_filed=False, event=None, user=None):
    plans = _plans_from_specs(specs, allow_filed)
    if not token or _plan_token(plans) != token:
        frappe.throw(_("The invoices changed since the preview. Preview again before applying."),
                     title=_("Preview is out of date"))
    _require_write_on(plans)  # again here: a queued run happens later, as the same user
    summary = run_plans(plans)
    summary["remaining"] = _remap_leftovers(specs) if any(s.get("scope") == "account" for s in specs) else None
    if event:
        frappe.publish_realtime(event, summary, user=user or frappe.session.user)
    return summary


def _dispatch(specs, token, allow_filed, event, plans):
    _require_write_on(plans)
    count = _change_count(plans)
    if count > _INLINE_LIMIT and not frappe.flags.in_test:
        frappe.enqueue(
            _apply_specs, queue="long", timeout=3600,
            specs=specs, token=token, allow_filed=allow_filed, event=event, user=frappe.session.user,
        )
        return {"status": "queued", "count": count}
    return {"status": "done", "summary": _apply_specs(specs, token, allow_filed)}


def _view(plans, extra=None):
    """What a preview returns: the plans with only the invoices worth showing."""
    out = {"token": _plan_token(plans), "filed_upto": str(_filed_upto() or ""),
           "can_override_filed": _is_system_manager(), "plans": []}
    total = {"changes": 0, "ledger_changes": 0, "flag_changes": 0, "blocked": 0,
             "tds_before": 0.0, "tds_after": 0.0, "late_interest": 0.0}
    for plan in plans:
        rows = []
        for d in plan.docs:
            if d.action == "none" and not d.blocked:
                continue
            row = {k: d.get(k) for k in (
                "name", "supplier", "posting_date", "is_return", "taxable", "current_category",
                "category", "current_tds", "target_tds", "current_accounts", "target_account",
                "action", "blocked", "quarter", "filed", "months_late", "late_interest", "challans",
                "caps", "moved", "old_grand_total", "new_grand_total",
            )}
            row["posting_date"] = str(d.posting_date)
            rows.append(row)
            if d.blocked:
                total["blocked"] += 1
            elif d.action != "none":
                total["changes"] += 1
                total["ledger_changes" if d.action == "ledger" else "flag_changes"] += 1
                total["tds_before"] += flt(d.current_tds)
                total["tds_after"] += flt(d.target_tds)
                total["late_interest"] += flt(d.get("late_interest"))
        out["plans"].append({
            "supplier": plan.supplier, "supplier_name": plan.supplier_name, "company": plan.company,
            "fiscal_year_start": plan.fiscal_year_start, "fiscal_year_end": plan.fiscal_year_end,
            "problems": plan.problems, "warnings": sorted(set(plan.warnings)), "rows": rows,
            "year_tds": flt(sum(flt(d.target_tds) for d in plan.docs if not cint(d.is_return)), 2),
        })
    out["summary"] = {k: flt(v, 2) if isinstance(v, float) else v for k, v in total.items()}
    out.update(extra or {})
    if not frappe.flags.in_test:
        frappe.db.rollback()  # previews never leave anything behind
    return out


def _change_count(plans):
    return sum(1 for p in plans for d in p.docs if d.action in ("ledger", "flags") and not d.blocked)


# --------------------------------------------------------------------------------------
# Change one invoice's TDS category (the button on the Purchase Invoice)
# --------------------------------------------------------------------------------------

def _return_original(pi, fy_start, fy_end):
    """For a debit note: the invoice it returns, when that invoice is in the same fiscal
    year (the debit note then takes its category). None otherwise."""
    if not cint(pi.get("is_return")) or not pi.get("return_against"):
        return None
    original = frappe.db.get_value(
        PI, pi.return_against,
        ["name", "docstatus", "company", "posting_date", "apply_tds", "tax_withholding_category"],
        as_dict=True,
    )
    if (original and original.docstatus == 1 and original.company == pi.company
            and fy_start <= getdate(original.posting_date) <= fy_end):
        return original
    return None


def _invoice_spec(name, category):
    if not frappe.db.exists(PI, name):
        frappe.throw(_("Purchase Invoice {0} not found.").format(name))
    pi = frappe.db.get_value(
        PI, name, ["docstatus", "supplier", "company", "posting_date", "is_return", "return_against"], as_dict=True
    )
    if pi.docstatus != 1:
        frappe.throw(_("Purchase Invoice {0} is not submitted.").format(name))
    frappe.has_permission(PI, "write", doc=name, throw=True)
    fy_start, fy_end = _current_fy(pi.company)
    if not (fy_start <= getdate(pi.posting_date) <= fy_end):
        frappe.throw(_("TDS category can be changed only on invoices of the current fiscal year."),
                     title=_("Not this year"))
    if category and not frappe.db.exists("Tax Withholding Category", category):
        frappe.throw(_("Tax Withholding Category {0} not found.").format(category))
    # A debit note takes the category of the invoice it returns, so the change goes there.
    original = _return_original(pi, fy_start, fy_end)
    target = original.name if original else name
    return {"supplier": pi.supplier, "company": pi.company, "date": str(pi.posting_date),
            "mode": "keep", "overrides": {target: category or ""}}


@frappe.whitelist()
def preview_tds_category_change(name, category=None, allow_filed=0):
    """Read-only: what changing this invoice's TDS category would do, across the
    supplier's year (later invoices can change with it)."""
    _require_tool()
    spec = _invoice_spec(name, category)
    plans = _plans_from_specs([spec], cint(allow_filed))
    current = frappe.db.get_value(PI, name, ["tax_withholding_category", "apply_tds"], as_dict=True)
    return _view(plans, {"invoice": name, "category": category or "",
                         "current_category": current.tax_withholding_category if cint(current.apply_tds) else ""})


@frappe.whitelist()
def apply_tds_category_change(name, category=None, token=None, allow_filed=0):
    _require_tool(write=True)
    spec = _invoice_spec(name, category)
    plans = _plans_from_specs([spec], cint(allow_filed))
    return _dispatch([spec], token, cint(allow_filed), "bns_tds_apply_complete", plans)


# Older entry points, kept for callers of the API: backfill = the supplier's category,
# reverse = no category. Both go through the same plan and need its token.

@frappe.whitelist()
def preview_tds_backfill(name):
    category = frappe.db.get_value("Supplier", frappe.db.get_value(PI, name, "supplier"), "tax_withholding_category")
    return preview_tds_category_change(name, category)


@frappe.whitelist()
def apply_tds_backfill(name, token=None):
    category = frappe.db.get_value("Supplier", frappe.db.get_value(PI, name, "supplier"), "tax_withholding_category")
    return apply_tds_category_change(name, category, token)


@frappe.whitelist()
def reverse_tds_backfill(name, token=None):
    return apply_tds_category_change(name, None, token)


# --------------------------------------------------------------------------------------
# Redo a supplier's year
# --------------------------------------------------------------------------------------

@frappe.whitelist()
def get_suppliers_needing_tds_redo(company=None):
    """Suppliers whose TDS category was REMOVED or CHANGED after TDS had already gone
    onto their invoices this fiscal year. Each one is offered a redo."""
    _require_tool()
    if not can_backfill_tds():
        return {"count": 0, "suppliers": []}
    company = _default_company(company)
    fy_start, fy_end = _current_fy(company)
    rows = frappe.db.sql(
        """
        SELECT
            pi.supplier,
            MAX(pi.supplier_name) AS supplier_name,
            IFNULL(MAX(s.tax_withholding_category), '') AS supplier_category,
            GROUP_CONCAT(DISTINCT NULLIF(pi.tax_withholding_category, '') SEPARATOR ', ') AS invoice_categories,
            COUNT(*) AS invoices,
            SUM((
                SELECT IFNULL(SUM(t.base_tax_amount), 0)
                FROM `tabPurchase Taxes and Charges` t
                WHERE t.parent = pi.name AND t.parenttype = 'Purchase Invoice'
                    AND t.is_tax_withholding_account = 1
            )) AS tds_amount
        FROM `tabPurchase Invoice` pi
        INNER JOIN `tabSupplier` s ON s.name = pi.supplier
        WHERE
            pi.docstatus = 1
            AND pi.company = %(company)s
            AND pi.posting_date BETWEEN %(fy_start)s AND %(fy_end)s
            AND (
                (
                    IFNULL(pi.tax_withholding_category, '') != IFNULL(s.tax_withholding_category, '')
                    AND IFNULL(pi.tax_withholding_category, '') != ''
                )
                OR (IFNULL(s.tax_withholding_category, '') = '' AND pi.apply_tds = 1)
            )
        GROUP BY pi.supplier
        ORDER BY supplier_name
        LIMIT 500
        """,
        {"company": company, "fy_start": fy_start, "fy_end": fy_end},
        as_dict=True,
    )
    for r in rows:
        r["reason"] = _("Category removed") if not r["supplier_category"] else _("Category changed")
        r["tds_amount"] = flt(r["tds_amount"], 2)
    return {
        "count": len(rows), "suppliers": rows, "company": company,
        "fiscal_year_start": str(fy_start), "fiscal_year_end": str(fy_end),
    }


def _redo_spec(supplier, company):
    if not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier {0} does not exist.").format(supplier))
    return {"supplier": supplier, "company": _default_company(company), "mode": "supplier"}


@frappe.whitelist()
def preview_supplier_tds(supplier, company=None, allow_filed=0):
    """Read-only: this fiscal year's TDS for the supplier under its category as it is
    now, against what is booked. Also the check for wrong amounts on any supplier."""
    _require_tool()
    spec = _redo_spec(supplier, company)
    return _view(_plans_from_specs([spec], cint(allow_filed)))


@frappe.whitelist()
def redo_supplier_tds(supplier, company=None, token=None, allow_filed=0):
    """Apply the previewed redo: only invoices whose TDS changes are touched."""
    _require_tool(write=True)
    spec = _redo_spec(supplier, company)
    plans = _plans_from_specs([spec], cint(allow_filed))
    return _dispatch([spec], token, cint(allow_filed), "bns_tds_redo_complete", plans)


# --------------------------------------------------------------------------------------
# Re-map TDS to the category's current account
# --------------------------------------------------------------------------------------

def _category_account(category, company):
    return frappe.db.get_value("Tax Withholding Account", {"parent": category, "company": company}, "account")


_REMAP_FROM = """
    FROM `tabPurchase Invoice` pi
    INNER JOIN `tabPurchase Taxes and Charges` t
        ON t.parent = pi.name AND t.parenttype = 'Purchase Invoice' AND t.is_tax_withholding_account = 1
    INNER JOIN `tabTax Withholding Account` a
        ON a.parent = pi.tax_withholding_category AND a.company = pi.company
    WHERE
        pi.docstatus = 1
        AND pi.company = %(company)s
        AND pi.posting_date BETWEEN %(fy_start)s AND %(fy_end)s
        AND a.account != t.account_head
"""


def _remap_specs(company):
    fy_start, fy_end = _current_fy(company)
    suppliers = frappe.db.sql(
        "SELECT DISTINCT pi.supplier " + _REMAP_FROM + " ORDER BY pi.supplier",
        {"company": company, "fy_start": fy_start, "fy_end": fy_end}, pluck=True,
    )
    return [{"supplier": s, "company": company, "mode": "keep", "scope": "account"} for s in suppliers]


def _old_accounts(company):
    fy_start, fy_end = _current_fy(company)
    return frappe.db.sql(
        "SELECT DISTINCT t.account_head " + _REMAP_FROM,
        {"company": company, "fy_start": fy_start, "fy_end": fy_end}, pluck=True,
    )


def _challans_on(accounts, company):
    """Payments and journals that hit these TDS accounts this fiscal year: the challans
    a re-map of invoices alone would leave behind."""
    if not accounts:
        return []
    fy_start, fy_end = _current_fy(company)
    return frappe.db.sql(
        """SELECT voucher_type, voucher_no, posting_date, account,
                  SUM(debit) - SUM(credit) AS amount
           FROM `tabGL Entry`
           WHERE account IN %(a)s AND company = %(c)s AND is_cancelled = 0
             AND voucher_type IN ('Journal Entry', 'Payment Entry')
             AND posting_date BETWEEN %(s)s AND %(e)s
           GROUP BY voucher_type, voucher_no, posting_date, account
           ORDER BY posting_date, voucher_no""",
        {"a": tuple(accounts), "c": company, "s": fy_start, "e": fy_end}, as_dict=True,
    )


def _remap_leftovers(specs):
    company = specs[0]["company"] if specs else None
    if not company:
        return None
    accounts = sorted({a for s in specs for a in (s.get("old_accounts") or [])})
    challans = _challans_on(accounts, company)
    return {
        "old_accounts": accounts,
        "challans": challans,
        "challan_amount": flt(sum(flt(c.amount) for c in challans), 2),
        "done": not challans,
    }


@frappe.whitelist()
def get_tds_account_remap_summary(company=None):
    """Current-fiscal-year invoices whose TDS sits on an account other than the one
    their category is mapped to now, grouped by category and account, plus the
    challans already paid out of those old accounts."""
    _require_tool()
    if not can_backfill_tds():
        return {"count": 0, "groups": []}
    company = _default_company(company)
    fy_start, fy_end = _current_fy(company)
    groups = frappe.db.sql(
        """
        SELECT
            pi.tax_withholding_category AS category,
            t.account_head AS old_account,
            a.account AS new_account,
            COUNT(*) AS invoices,
            SUM(t.base_tax_amount) AS amount
        """ + _REMAP_FROM + """
        GROUP BY pi.tax_withholding_category, t.account_head, a.account
        ORDER BY pi.tax_withholding_category, t.account_head
        """,
        {"company": company, "fy_start": fy_start, "fy_end": fy_end},
        as_dict=True,
    )
    for g in groups:
        g["amount"] = flt(g["amount"], 2)
    challans = _challans_on(sorted({g.old_account for g in groups}), company)
    return {
        "count": sum(cint(g["invoices"]) for g in groups),
        "amount": flt(sum(g["amount"] for g in groups), 2),
        "groups": groups,
        "challans": challans,
        "challan_amount": flt(sum(flt(c.amount) for c in challans), 2),
        "company": company,
    }


@frappe.whitelist()
def preview_tds_remap(company=None, allow_filed=0):
    _require_tool()
    company = _default_company(company)
    specs = _remap_specs(company)
    old = _old_accounts(company)
    challans = _challans_on(old, company)
    return _view(_plans_from_specs(specs, cint(allow_filed)), {
        "old_accounts": old, "challans": challans,
        "challan_amount": flt(sum(flt(c.amount) for c in challans), 2),
    })


@frappe.whitelist()
def remap_tds_accounts(company=None, token=None, allow_filed=0):
    """Apply the previewed re-map. The summary lists the challans still on the old
    accounts; the re-map is not done until they are moved too (by hand: cancel and
    amend each with the new account, same date, amount and bank reference)."""
    _require_tool(write=True)
    company = _default_company(company)
    specs = _remap_specs(company)
    old = _old_accounts(company)
    for s in specs:
        s["old_accounts"] = old
    plans = _plans_from_specs(specs, cint(allow_filed))
    return _dispatch(specs, token, cint(allow_filed), "bns_tds_remap_complete", plans)


# --------------------------------------------------------------------------------------
# Header-only repair (no GL)
# --------------------------------------------------------------------------------------

def _existing_tds_row(pi):
    """The invoice's current tax-withholding row, if any."""
    for t in pi.get("taxes") or []:
        if cint(t.get("is_tax_withholding_account")):
            return t
    return None


def repair_tds_totals_on_pi(name):
    """Fix an invoice that carries a TDS row but whose header split fields
    (taxes_and_charges_deducted / added) were never saved by the old backfill.
    Recomputes the split from the existing tax rows -- no new row, no GL change."""
    pi = frappe.get_doc(PI, name)
    if not _existing_tds_row(pi):
        return {"changed": False, "reason": _("No TDS row to repair.")}
    added = sum(flt(t.tax_amount) for t in pi.taxes if t.add_deduct_tax == "Add")
    base_added = sum(flt(t.base_tax_amount) for t in pi.taxes if t.add_deduct_tax == "Add")
    deducted = sum(flt(t.tax_amount) for t in pi.taxes if t.add_deduct_tax == "Deduct")
    base_deducted = sum(flt(t.base_tax_amount) for t in pi.taxes if t.add_deduct_tax == "Deduct")
    if flt(pi.taxes_and_charges_deducted) == deducted and cint(pi.apply_tds):
        return {"changed": False, "reason": _("Totals already correct.")}
    frappe.db.set_value(
        PI, name,
        {
            "taxes_and_charges_added": added,
            "base_taxes_and_charges_added": base_added,
            "taxes_and_charges_deducted": deducted,
            "base_taxes_and_charges_deducted": base_deducted,
            "total_taxes_and_charges": added - deducted,
            "base_total_taxes_and_charges": base_added - base_deducted,
            "apply_tds": 1,
        },
        update_modified=True,
    )
    _commit()
    return {"changed": True, "taxes_and_charges_deducted": deducted}


@frappe.whitelist()
def get_tds_category_button(name):
    """Whether to draw the Change TDS Category button on this invoice, and what to
    offer: only for submitted invoices of the current fiscal year."""
    if not can_backfill_tds():
        return {"show": False}
    pi = frappe.db.get_value(
        PI, name,
        ["docstatus", "company", "posting_date", "supplier", "apply_tds", "tax_withholding_category",
         "is_return", "return_against"],
        as_dict=True,
    )
    if not pi or pi.docstatus != 1:
        return {"show": False}
    fy_start, fy_end = _current_fy(pi.company)
    if not (fy_start <= getdate(pi.posting_date) <= fy_end):
        return {"show": False}
    if not frappe.has_permission(PI, "write", doc=name):
        return {"show": False}
    # A debit note follows the invoice it returns: the dialog offers that invoice's category.
    original = _return_original(pi, fy_start, fy_end)
    source = original or pi
    return {
        "show": True,
        "is_return": cint(pi.is_return),
        "follows": original.name if original else "",
        "current_category": source.tax_withholding_category if cint(source.apply_tds) else "",
        "supplier_category": frappe.db.get_value("Supplier", pi.supplier, "tax_withholding_category") or "",
    }
