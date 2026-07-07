"""Backfill TDS (Tax Withholding) onto already-SUBMITTED Purchase Invoices.

Old PIs entered without apply_tds can't be fixed by cancel+amend, because a
re-submit re-books Input GST/ITC and india_compliance blocks that for filed
periods. TDS, however, is income-tax withholding -- entirely separate from GST --
so we add it SURGICALLY: compute the amount with ERPNext's own cumulative logic,
add the TDS tax row, recompute totals, and post ONLY the incremental TDS GL
(Dr Creditors / Cr TDS payable). GST/Input-Tax legs are never touched, so ITC is
not re-posted and the compliance block never fires.

Paid / partly-paid PIs are UNRECONCILED first (native Unreconcile Payment) so the
outstanding is free before TDS reduces it. The category comes from the supplier's
`tax_withholding_category`.

Gated by BNS Settings `enable_tds_backfill` + `tds_backfill_roles` (System Manager
always allowed). Frozen accounting periods are refused. PREVIEW first.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


def _feature_enabled() -> bool:
    return bool(frappe.db.get_single_value("BNS Settings", "enable_tds_backfill", cache=True))


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
    if not _feature_enabled():
        return False
    roles = set(frappe.get_roles(user or frappe.session.user))
    return "System Manager" in roles or bool(_get_roles() & roles)


def _check_not_frozen(posting_date) -> None:
    frozen = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
    if not frozen or not posting_date:
        return
    if getdate(posting_date) <= getdate(frozen):
        modifier = frappe.db.get_single_value("Accounts Settings", "frozen_accounts_modifier")
        if not (modifier and modifier in frappe.get_roles()):
            frappe.throw(
                _("Posting date {0} is within the frozen accounting period (up to {1}).").format(
                    posting_date, frozen
                ),
                title=_("Accounting Period Frozen"),
            )


def _existing_tds_row(pi):
    """The invoice's current tax-withholding row, if any (already has TDS)."""
    for t in pi.get("taxes") or []:
        if cint(t.get("is_tax_withholding_account")):
            return t
    return None


def _resolve_category(pi):
    cat = frappe.db.get_value("Supplier", pi.supplier, "tax_withholding_category")
    if not cat:
        frappe.throw(
            _("Supplier {0} has no Tax Withholding Category set.").format(pi.supplier),
            title=_("No TDS Category"),
        )
    return cat


def _compute_tds(pi, category):
    """Return (tax_row, tds_amount) using ERPNext's own cumulative TDS logic.
    tds_amount is the base-currency withholding for THIS invoice (0 if the
    threshold isn't crossed)."""
    from erpnext.accounts.doctype.tax_withholding_category.tax_withholding_category import (
        get_party_tax_withholding_details,
    )

    # get_party_tax_withholding_details reads apply_tds/category off the doc.
    pi.apply_tds = 1
    pi.tax_withholding_category = category
    result = get_party_tax_withholding_details(pi, category)
    tax_row = result[0] if isinstance(result, (list, tuple)) else result
    tds_amount = flt((tax_row or {}).get("tax_amount"))
    return tax_row, tds_amount


def _paying_vouchers(pi_name):
    """Payment/JE vouchers currently reconciled against this PI (to unreconcile)."""
    rows = frappe.get_all(
        "Payment Ledger Entry",
        filters={"against_voucher_no": pi_name, "voucher_no": ["!=", pi_name], "delinked": 0},
        fields=["voucher_type", "voucher_no", "company"],
        distinct=True,
    )
    seen, out = set(), []
    for r in rows:
        key = (r.voucher_type, r.voucher_no)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


@frappe.whitelist()
def preview_tds_backfill(name):
    """Read-only: what backfilling TDS on this PI would do. Never writes."""
    _bns_require_read()
    pi = frappe.get_doc("Purchase Invoice", name)
    info = {
        "name": name,
        "supplier": pi.supplier,
        "posting_date": str(pi.posting_date),
        "grand_total": flt(pi.grand_total),
        "outstanding_amount": flt(pi.outstanding_amount),
        "already_has_tds": bool(_existing_tds_row(pi)),
        "paying_vouchers": [],
        "tds_amount": 0.0,
        "new_grand_total": flt(pi.grand_total),
        "new_outstanding": flt(pi.outstanding_amount),
        "warnings": [],
    }
    if info["already_has_tds"]:
        info["warnings"].append("Invoice already carries a tax-withholding row.")
        return info

    category = frappe.db.get_value("Supplier", pi.supplier, "tax_withholding_category")
    if not category:
        info["warnings"].append("Supplier has no Tax Withholding Category.")
        return info
    info["category"] = category

    _tax_row, tds = _compute_tds(pi, category)
    info["tds_amount"] = flt(tds)
    if tds <= 0:
        info["warnings"].append("Computed TDS is 0 (cumulative threshold not crossed).")
    info["new_grand_total"] = flt(pi.grand_total) - flt(tds)
    info["new_outstanding"] = flt(pi.outstanding_amount) - flt(tds)

    pv = _paying_vouchers(name)
    info["paying_vouchers"] = [{"type": r.voucher_type, "name": r.voucher_no} for r in pv]
    if pv:
        info["warnings"].append(
            f"{len(pv)} payment/JE allocation(s) will be UNRECONCILED first."
        )
    return info


@frappe.whitelist()
def apply_tds_backfill(name):
    """Backfill TDS on a submitted PI: unreconcile payments, add the TDS tax row,
    recompute totals, post the incremental TDS GL (no GST re-post), and refresh
    the supplier outstanding. Role-gated; frozen periods refused."""
    _bns_require_write()
    if not can_backfill_tds():
        frappe.throw(
            _("You are not permitted to backfill TDS (feature disabled or role missing)."),
            frappe.PermissionError,
        )

    return backfill_tds_on_pi(name)


def backfill_tds_on_pi(name):
    """Core TDS backfill on a submitted PI. NO permission gate -- every caller
    (the whitelisted apply_tds_backfill, and the BNS Dashboard TDS fixer) applies
    its own gate first. Adds the TDS row, recomputes/persists totals (including
    taxes_and_charges_deducted), posts only the incremental TDS GL, and refreshes
    outstanding. Returns a result dict; never throws for the 'already has TDS' or
    'nothing due' cases -- those are normal outcomes when sweeping many PIs."""
    pi = frappe.get_doc("Purchase Invoice", name)
    if pi.docstatus != 1:
        frappe.throw(_("Purchase Invoice {0} is not submitted.").format(name))
    _check_not_frozen(pi.posting_date)
    if _existing_tds_row(pi):
        return {"changed": False, "reason": _("Already has a tax-withholding row.")}

    category = _resolve_category(pi)
    _tax_row, tds = _compute_tds(pi, category)
    if flt(tds) <= 0:
        # No TDS due (cumulative threshold not crossed). Mark as processed so the
        # invoice drops off the "needs fix" list -- no TDS row, no GL posted.
        frappe.db.set_value(
            "Purchase Invoice", name,
            {"apply_tds": 1, "tax_withholding_category": category},
            update_modified=True,
        )
        frappe.db.commit()
        return {
            "changed": True, "tds_amount": 0.0,
            "reason": _("No TDS due (threshold not crossed); marked as applied."),
        }

    # 1) unreconcile any payment/JE allocated against this PI
    unrec = _unreconcile_paying_vouchers(pi)

    # 2) add the TDS row + recompute totals (ERPNext's own logic), then persist.
    pi = frappe.get_doc("Purchase Invoice", name)  # reload post-unreconcile
    pi.apply_tds = 1
    pi.tax_withholding_category = category
    old_grand = flt(pi.grand_total)
    pi.set_tax_withholding()  # appends TDS row + calculate_taxes_and_totals
    tds_row = _existing_tds_row(pi)
    if not tds_row or flt(tds_row.tax_amount) <= 0:
        return {"changed": False, "reason": "TDS row not produced."}
    tds_amt = flt(tds_row.base_tax_amount or tds_row.tax_amount)
    tds_account = tds_row.account_head

    _persist_tds_row_and_totals(pi, tds_row)

    # 3) incremental GL only: Dr Creditors(party) / Cr TDS payable -- no GST touched
    _post_incremental_tds_gl(pi, tds_account, tds_amt)

    # 4) refresh outstanding from the (now TDS-reduced) party ledger
    _update_outstanding(pi)

    frappe.db.commit()
    frappe.log_error(
        message=(
            "TDS backfill %s: category=%s tds=%s grand %s->%s unreconciled=%s by %s"
            % (name, category, tds_amt, old_grand, flt(pi.grand_total),
               [f"{u['type']} {u['name']}" for u in unrec], frappe.session.user)
        ),
        title="BNS TDS Backfill",
    )
    return {
        "changed": True,
        "tds_amount": tds_amt,
        "tds_account": tds_account,
        "unreconciled": unrec,
        "new_grand_total": flt(pi.grand_total),
    }


def repair_tds_totals_on_pi(name):
    """Fix an invoice that already carries a TDS row but whose header split fields
    (taxes_and_charges_deducted / added) were never persisted by the old backfill.
    Recomputes the split from the existing tax rows -- no new row, no GL change."""
    pi = frappe.get_doc("Purchase Invoice", name)
    if not _existing_tds_row(pi):
        return {"changed": False, "reason": _("No TDS row to repair.")}
    added = sum(flt(t.tax_amount) for t in pi.taxes if t.add_deduct_tax == "Add")
    base_added = sum(flt(t.base_tax_amount) for t in pi.taxes if t.add_deduct_tax == "Add")
    deducted = sum(flt(t.tax_amount) for t in pi.taxes if t.add_deduct_tax == "Deduct")
    base_deducted = sum(flt(t.base_tax_amount) for t in pi.taxes if t.add_deduct_tax == "Deduct")
    if flt(pi.taxes_and_charges_deducted) == deducted and cint(pi.apply_tds):
        return {"changed": False, "reason": _("Totals already correct.")}
    frappe.db.set_value(
        "Purchase Invoice", name,
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
    frappe.db.commit()
    return {"changed": True, "taxes_and_charges_deducted": deducted}


def _unreconcile_paying_vouchers(pi):
    from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
        create_unreconcile_doc_for_selection,
    )
    import json

    pv = _paying_vouchers(pi.name)
    if not pv:
        return []
    selections = [
        {
            "company": r.company or pi.company,
            "voucher_type": r.voucher_type,
            "voucher_no": r.voucher_no,
            "against_voucher_type": "Purchase Invoice",
            "against_voucher_no": pi.name,
        }
        for r in pv
    ]
    create_unreconcile_doc_for_selection(json.dumps(selections))
    return [{"type": r.voucher_type, "name": r.voucher_no} for r in pv]


def _persist_tds_row_and_totals(pi, tds_row):
    """Insert the new TDS child row and db_set the recomputed header totals on the
    submitted PI. Only the appended TDS row is new; the GST rows above it are
    unchanged (their running totals precede the TDS deduction)."""
    tds_row.parent = pi.name
    tds_row.parenttype = "Purchase Invoice"
    tds_row.parentfield = "taxes"
    tds_row.docstatus = 1  # child of a submitted parent
    if not tds_row.get("idx"):
        tds_row.idx = len(pi.get("taxes") or [])
    tds_row.db_insert()

    header_fields = [
        "taxes_and_charges_added", "base_taxes_and_charges_added",
        "taxes_and_charges_deducted", "base_taxes_and_charges_deducted",
        "total_taxes_and_charges", "base_total_taxes_and_charges",
        "grand_total", "base_grand_total",
        "rounding_adjustment", "base_rounding_adjustment",
        "rounded_total", "base_rounded_total",
        "outstanding_amount",
    ]
    updates = {f: pi.get(f) for f in header_fields if pi.get(f) is not None}
    # Persist the flags too, else the DB shows apply_tds=0 with a TDS row present
    # -- which also excludes this PI from ERPNext's cumulative query (it filters
    # apply_tds=1) for later invoices in the FY.
    updates["apply_tds"] = 1
    updates["tax_withholding_category"] = pi.get("tax_withholding_category")
    if pi.get("round_off_applicable_accounts_for_tax_withholding"):
        updates["round_off_applicable_accounts_for_tax_withholding"] = pi.get(
            "round_off_applicable_accounts_for_tax_withholding"
        )
    frappe.db.set_value("Purchase Invoice", pi.name, updates, update_modified=True)


def _post_incremental_tds_gl(pi, tds_account, tds_amt):
    """Post ONLY the TDS legs: Dr Creditors(party) / Cr TDS payable. GST/expense
    legs stay as-is, so Input Tax / ITC is never re-posted."""
    from erpnext.accounts.general_ledger import make_gl_entries

    gl = [
        pi.get_gl_dict(
            {
                "account": pi.credit_to,
                "party_type": "Supplier",
                "party": pi.supplier,
                "against": tds_account,
                "debit": tds_amt,
                "debit_in_account_currency": tds_amt,
                "against_voucher": pi.name,
                "against_voucher_type": "Purchase Invoice",
                "cost_center": pi.get("cost_center"),
                "remarks": _("TDS backfill"),
            },
        ),
        pi.get_gl_dict(
            {
                "account": tds_account,
                "against": pi.supplier,
                "credit": tds_amt,
                "credit_in_account_currency": tds_amt,
                "cost_center": pi.get("cost_center"),
                "remarks": _("TDS backfill"),
            },
        ),
    ]
    make_gl_entries(gl, merge_entries=False)


def _update_outstanding(pi):
    from erpnext.accounts.utils import update_voucher_outstanding

    update_voucher_outstanding(
        "Purchase Invoice", pi.name, pi.credit_to, "Supplier", pi.supplier
    )


def _bns_require_read():
    from business_needed_solutions.bns_branch_accounting.utils import _bns_require_accounts_read

    _bns_require_accounts_read()


def _bns_require_write():
    from business_needed_solutions.bns_branch_accounting.utils import _bns_require_accounts_write

    _bns_require_accounts_write()
