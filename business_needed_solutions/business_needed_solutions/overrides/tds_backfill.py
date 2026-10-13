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

Gated by BNS Settings `enable_tds_category_fixables` + `tds_backfill_roles` (System
Manager always allowed). Frozen accounting periods are refused. PREVIEW first.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate


def _feature_enabled() -> bool:
    # Merged toggle: one BNS Settings switch governs both the dashboard TDS
    # Category Fixables and the per-PI TDS backfill API.
    return bool(frappe.db.get_single_value("BNS Settings", "enable_tds_category_fixables", cache=True))


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
    # Answers False rather than throwing: every submitted Purchase Invoice form
    # asks this to decide whether to draw the button.
    if frappe.session.user == "Guest":
        return False
    if not _feature_enabled():
        return False
    # Only a System Manager may ask about somebody else; anyone else gets the
    # answer for themselves, whatever `user` the request carried.
    if user and user != frappe.session.user and "System Manager" not in frappe.get_roles():
        user = None
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
    if _is_internal_transfer(pi):
        # A branch of the same company is not a deductee: the "supplier" shares
        # our PAN, and withholding on it only moves money between our own books.
        return {"changed": False, "reason": _("Internal transfer - TDS does not apply.")}
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


BACKFILL_REMARK = "TDS backfill"
REMAP_REMARK = "TDS account remap"

_HEADER_TOTAL_FIELDS = (
    "taxes_and_charges_added", "base_taxes_and_charges_added",
    "taxes_and_charges_deducted", "base_taxes_and_charges_deducted",
    "total_taxes_and_charges", "base_total_taxes_and_charges",
    "grand_total", "base_grand_total",
    "rounding_adjustment", "base_rounding_adjustment",
    "rounded_total", "base_rounded_total",
)


def _is_internal_transfer(pi) -> bool:
    """A purchase from a branch of the same legal entity (BNS internal supplier,
    ERPNext internal supplier, or simply a supplier carrying the company's PAN)."""
    if cint(pi.get("is_bns_internal_supplier")) or cint(pi.get("is_internal_supplier")):
        return True
    supplier_pan = (frappe.db.get_value("Supplier", pi.supplier, "pan") or "").strip().upper()
    company_pan = (frappe.db.get_value("Company", pi.company, "pan") or "").strip().upper()
    return bool(supplier_pan) and supplier_pan == company_pan


def _backfill_gl_rows(name, remark=None):
    """The two legs the backfill posted for this PI that are still live. With
    `remark`, the live legs of one of our other postings instead."""
    return frappe.get_all(
        "GL Entry",
        filters={
            "voucher_type": "Purchase Invoice", "voucher_no": name,
            "remarks": remark or BACKFILL_REMARK, "is_cancelled": 0,
        },
        fields=["*"],
        order_by="creation asc, name asc",
    )


@frappe.whitelist()
def reverse_tds_backfill(name):
    """Undo a TDS backfill on a submitted PI. Same gate as applying one."""
    _bns_require_write()
    if not can_backfill_tds():
        frappe.throw(
            _("You are not permitted to reverse a TDS backfill (feature disabled or role missing)."),
            frappe.PermissionError,
        )
    return reverse_tds_backfill_on_pi(name)


def reverse_tds_backfill_on_pi(name, allow_native=False):
    """Exact inverse of backfill_tds_on_pi, step for step and by the same means.

    Forward did: (1) unreconcile payments, (2) append the TDS row and let ERPNext
    recompute totals, persist row + header, (3) post two GL legs through
    make_gl_entries (which also wrote a Payment Ledger Entry), (4) refresh
    outstanding. So this (3') reverses those two legs through ERPNext's own
    make_reverse_gl_entries - which delinks the Payment Ledger Entry too -
    (2') deletes the row and lets ERPNext recompute the totals without it, and
    (4') refreshes outstanding. Payments unreconciled in step 1 are NOT re-linked:
    which payment belongs where is the accountant's call, and the audit log of
    the original backfill names them.

    Only a TDS row the backfill added is touched, unless `allow_native` is set: a
    row booked at submit has no "TDS backfill" GL behind it, and is refused here
    and removed only by the supplier-wide redo, which posts the opposite pair.
    An invoice the backfill merely flagged (nothing was due) has its flags cleared.
    """
    from erpnext.accounts.general_ledger import make_reverse_gl_entries

    pi = frappe.get_doc("Purchase Invoice", name)
    if pi.docstatus != 1:
        frappe.throw(_("Purchase Invoice {0} is not submitted.").format(name))
    _check_not_frozen(pi.posting_date)

    tds_row = _existing_tds_row(pi)
    gl_rows = _backfill_gl_rows(name)

    if tds_row and not gl_rows and not allow_native:
        return {"changed": False, "reason": _("TDS row was not added by a backfill; cancel and amend instead.")}
    if pi.get("advance_tax"):
        # TDS already withheld on an advance and allocated here. Unpicking that is
        # a Payment Entry question, not an invoice one.
        return {"changed": False, "reason": _("TDS on this invoice is allocated from an advance; fix by hand.")}
    if not tds_row and gl_rows:
        frappe.throw(_("{0} has backfill GL but no TDS row. Needs a manual look.").format(name))
    if not tds_row and not cint(pi.apply_tds) and not pi.tax_withholding_category:
        return {"changed": False, "reason": _("No backfilled TDS on this invoice.")}

    tds_amt = 0.0
    if tds_row:
        tds_amt = flt(tds_row.base_tax_amount or tds_row.tax_amount)
        old_grand = flt(pi.grand_total)

        if gl_rows:
            posted = sum(flt(g.credit) for g in gl_rows)
            if len(gl_rows) != 2 or abs(posted - tds_amt) > 0.01:
                frappe.throw(
                    _("{0}: backfill GL ({1} rows, {2}) does not match the TDS row ({3}). Needs a manual look.")
                    .format(name, len(gl_rows), posted, tds_amt)
                )
            # 3') the two GL legs, and with them the Payment Ledger Entry. If the
            # TDS was later moved to another account, that pair goes with them -
            # left behind it would be a transfer of an amount that no longer exists.
            make_reverse_gl_entries(gl_entries=gl_rows + _backfill_gl_rows(name, REMAP_REMARK))
        else:
            # Booked at submit: the TDS is inside the invoice's own GL, so there
            # is nothing of ours to cancel. Post the opposite pair instead - the
            # supplier is owed the amount again, and TDS payable gives it back.
            _post_incremental_tds_gl(pi, tds_row.account_head, tds_amt, removing=True)

        # 2') the row, then ERPNext's own totals without it
        frappe.db.delete("Purchase Taxes and Charges", {"name": tds_row.name})
        frappe.db.delete("Tax Withheld Vouchers", {"parent": name, "parenttype": "Purchase Invoice"})
        pi = frappe.get_doc("Purchase Invoice", name)
        pi.apply_tds = 0
        pi.tax_withholding_category = None
        pi.calculate_taxes_and_totals()
        updates = {f: flt(pi.get(f)) for f in _HEADER_TOTAL_FIELDS}
    else:
        old_grand = flt(pi.grand_total)
        updates = {}

    updates["apply_tds"] = 0
    updates["tax_withholding_category"] = None
    frappe.db.set_value("Purchase Invoice", name, updates, update_modified=True)

    # 4') outstanding from the whole party ledger of this voucher. No account
    # filter: an internal invoice's payable sits in the internal creditor account,
    # not in `credit_to`, and filtering on `credit_to` is what left these invoices
    # showing minus-the-TDS as their outstanding.
    if tds_row:
        from erpnext.accounts.utils import update_voucher_outstanding

        update_voucher_outstanding("Purchase Invoice", name, None, "Supplier", pi.supplier)

    frappe.db.commit()
    new_grand = flt(frappe.db.get_value("Purchase Invoice", name, "grand_total"))
    frappe.log_error(
        message=(
            "TDS backfill REVERSED %s: tds=%s grand %s->%s by %s"
            % (name, tds_amt, old_grand, new_grand, frappe.session.user)
        ),
        title="BNS TDS Backfill Reversed",
    )
    return {
        "changed": True,
        "tds_reversed": tds_amt,
        "new_grand_total": new_grand,
        "new_outstanding": flt(frappe.db.get_value("Purchase Invoice", name, "outstanding_amount")),
    }


def _current_fy(company):
    from erpnext.accounts.utils import get_fiscal_year
    from frappe.utils import today

    fy = get_fiscal_year(today(), company=company)
    return fy[1], fy[2]


def _default_company(company=None):
    return (
        company
        or frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )


@frappe.whitelist()
def get_suppliers_needing_tds_redo(company=None):
    """Suppliers whose TDS category was REMOVED or CHANGED after TDS had already
    gone onto their invoices this fiscal year. Each one is offered a redo."""
    _bns_require_read()
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


@frappe.whitelist()
def redo_supplier_tds(supplier, company=None):
    """Redo TDS on every current-fiscal-year invoice of one supplier, to match the
    supplier's category as it stands NOW: no category -> TDS comes off; a different
    category -> TDS comes off and is applied afresh. Runs in the background."""
    _bns_require_write()
    if not can_backfill_tds():
        frappe.throw(
            _("You are not permitted to redo TDS (feature disabled or role missing)."),
            frappe.PermissionError,
        )
    if not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier {0} does not exist.").format(supplier))
    company = _default_company(company)
    frappe.enqueue(
        _redo_supplier_tds,
        queue="long",
        timeout=3600,
        job_id=f"bns_tds_redo::{company}::{supplier}",
        deduplicate=True,
        supplier=supplier,
        company=company,
        user=frappe.session.user,
    )
    return {"status": "queued", "supplier": supplier}


def _redo_supplier_tds(supplier, company, user=None):
    """Worker. Two passes, and the order is the point.

    ERPNext's threshold is cumulative over the supplier's year, and it reads the
    invoices that already carry TDS. So every invoice is cleared FIRST, newest to
    oldest, and only then is TDS applied again, oldest to newest - otherwise an
    invoice is judged against a year that is half old category and half new.
    If anything fails to clear, nothing is re-applied: a partial year would give
    wrong amounts that look right.
    """
    fy_start, fy_end = _current_fy(company)
    base = {"supplier": supplier, "company": company, "docstatus": 1,
            "posting_date": ["between", [fy_start, fy_end]]}
    all_pis = frappe.get_all("Purchase Invoice", filters=base, fields=["name", "apply_tds", "tax_withholding_category"],
                             order_by="posting_date asc, name asc")
    category = frappe.db.get_value("Supplier", supplier, "tax_withholding_category")

    removed, removed_amt, applied, applied_amt, errors = 0, 0.0, 0, 0.0, []

    for row in reversed(all_pis):
        try:
            res = reverse_tds_backfill_on_pi(row.name, allow_native=True)
            if res.get("changed"):
                removed += 1
                removed_amt += flt(res.get("tds_reversed"))
            elif cint(row.apply_tds) or row.tax_withholding_category:
                # still flagged and we could not clear it - say why, and stop short
                errors.append({"purchase_invoice": row.name, "error": cstr(res.get("reason"))})
        except Exception as e:
            frappe.db.rollback()
            errors.append({"purchase_invoice": row.name, "error": cstr(e)})

    reapplied = bool(category) and not errors
    if reapplied:
        for row in all_pis:
            try:
                res = backfill_tds_on_pi(row.name)
                if res.get("changed"):
                    applied += 1
                    applied_amt += flt(res.get("tds_amount"))
            except Exception as e:
                frappe.db.rollback()
                errors.append({"purchase_invoice": row.name, "error": cstr(e)})

    frappe.db.commit()
    summary = {
        "supplier": supplier, "category": category or "", "invoices": len(all_pis),
        "removed": removed, "removed_amount": flt(removed_amt, 2),
        "applied": applied, "applied_amount": flt(applied_amt, 2),
        "reapplied": reapplied,
        "error_count": len(errors), "errors": errors[:50],
    }
    frappe.log_error(message=frappe.as_json(summary), title="BNS TDS Redo")
    frappe.publish_realtime("bns_tds_redo_complete", summary, user=user)
    return summary


def _category_account(category, company):
    return frappe.db.get_value(
        "Tax Withholding Account", {"parent": category, "company": company}, "account"
    )


def remap_tds_account_on_pi(name):
    """Move one invoice's TDS to the account its category is mapped to NOW.

    The Tax Withholding Category's account was corrected after invoices had been
    booked on the old one. Nothing about the tax changes - not the amount, not the
    supplier's balance, not outstanding - so this is the smallest thing that is
    still true everywhere: the tax row names the new account, and one pair on the
    invoice's own date carries the amount from the old account to the new. A later
    ledger repost rebuilds from the row and lands on the new account by itself.
    """
    from erpnext.accounts.general_ledger import make_gl_entries

    pi = frappe.get_doc("Purchase Invoice", name)
    if pi.docstatus != 1:
        return {"changed": False, "reason": _("Not submitted")}
    tds_row = _existing_tds_row(pi)
    if not tds_row:
        return {"changed": False, "reason": _("No TDS row")}
    if not pi.tax_withholding_category:
        return {"changed": False, "reason": _("No TDS Category on the invoice")}
    new_account = _category_account(pi.tax_withholding_category, pi.company)
    old_account = tds_row.account_head
    if not new_account:
        return {"changed": False, "reason": _("Category has no account for this company")}
    if new_account == old_account:
        return {"changed": False, "reason": _("Already on the mapped account")}
    _check_not_frozen(pi.posting_date)

    amt = flt(tds_row.base_tax_amount or tds_row.tax_amount)
    booked = flt(frappe.db.sql(
        """
        SELECT IFNULL(SUM(credit - debit), 0) FROM `tabGL Entry`
        WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s
            AND account = %s AND is_cancelled = 0
        """,
        (name, old_account),
    )[0][0])
    if abs(booked - amt) > 0.01:
        frappe.throw(
            _("{0}: {1} holds {2} for this invoice, the TDS row says {3}. Needs a manual look.")
            .format(name, old_account, booked, amt)
        )

    gl = [
        pi.get_gl_dict({
            "account": old_account, "against": new_account,
            "debit": amt, "debit_in_account_currency": amt,
            "cost_center": tds_row.cost_center or pi.get("cost_center"),
            "remarks": REMAP_REMARK,
        }),
        pi.get_gl_dict({
            "account": new_account, "against": old_account,
            "credit": amt, "credit_in_account_currency": amt,
            "cost_center": tds_row.cost_center or pi.get("cost_center"),
            "remarks": REMAP_REMARK,
        }),
    ]
    make_gl_entries(gl, merge_entries=False)
    frappe.db.set_value(
        "Purchase Taxes and Charges", tds_row.name, "account_head", new_account, update_modified=False
    )
    frappe.db.commit()
    return {"changed": True, "amount": amt, "from_account": old_account, "to_account": new_account}


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


@frappe.whitelist()
def get_tds_account_remap_summary(company=None):
    """Current-fiscal-year invoices whose TDS sits on an account other than the
    one their category is mapped to now, grouped by category and account."""
    _bns_require_read()
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
    return {
        "count": sum(cint(g["invoices"]) for g in groups),
        "amount": flt(sum(g["amount"] for g in groups), 2),
        "groups": groups,
        "company": company,
    }


@frappe.whitelist()
def remap_tds_accounts(company=None):
    """Re-map every such invoice of the current fiscal year. Background job."""
    _bns_require_write()
    if not can_backfill_tds():
        frappe.throw(
            _("You are not permitted to re-map TDS accounts (feature disabled or role missing)."),
            frappe.PermissionError,
        )
    company = _default_company(company)
    frappe.enqueue(
        _remap_tds_accounts,
        queue="long",
        timeout=3600,
        job_id=f"bns_tds_remap::{company}",
        deduplicate=True,
        company=company,
        user=frappe.session.user,
    )
    return {"status": "queued"}


def _remap_tds_accounts(company, user=None):
    fy_start, fy_end = _current_fy(company)
    names = frappe.db.sql(
        "SELECT pi.name " + _REMAP_FROM + " ORDER BY pi.posting_date, pi.name",
        {"company": company, "fy_start": fy_start, "fy_end": fy_end},
        pluck=True,
    )
    done, amount, errors = 0, 0.0, []
    for name in names:
        try:
            res = remap_tds_account_on_pi(name)
            if res.get("changed"):
                done += 1
                amount += flt(res.get("amount"))
        except Exception as e:
            frappe.db.rollback()
            errors.append({"purchase_invoice": name, "error": cstr(e)})
    frappe.db.commit()
    summary = {
        "invoices": len(names), "remapped": done, "amount": flt(amount, 2),
        "error_count": len(errors), "errors": errors[:50],
    }
    frappe.log_error(message=frappe.as_json(summary), title="BNS TDS Account Remap")
    frappe.publish_realtime("bns_tds_remap_complete", summary, user=user)
    return summary


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
    # `round_off_applicable_accounts_for_tax_withholding` is NOT persisted: ERPNext
    # sets it on the in-memory doc only (when the category has "Round Off Tax
    # Amount"), there is no such column, and writing it threw 1054 for every
    # round-off category. The rounding it drives is already in the totals above.
    frappe.db.set_value("Purchase Invoice", pi.name, updates, update_modified=True)


def _post_incremental_tds_gl(pi, tds_account, tds_amt, removing=False):
    """Post ONLY the TDS legs: Dr Creditors(party) / Cr TDS payable. GST/expense
    legs stay as-is, so Input Tax / ITC is never re-posted. `removing` posts the
    same pair the other way round, for a TDS row that was booked at submit."""
    from erpnext.accounts.general_ledger import make_gl_entries

    if removing:
        gl = [
            pi.get_gl_dict(
                {
                    "account": pi.credit_to,
                    "party_type": "Supplier",
                    "party": pi.supplier,
                    "against": tds_account,
                    "credit": tds_amt,
                    "credit_in_account_currency": tds_amt,
                    "against_voucher": pi.name,
                    "against_voucher_type": "Purchase Invoice",
                    "cost_center": pi.get("cost_center"),
                    "remarks": _("TDS removal"),
                },
            ),
            pi.get_gl_dict(
                {
                    "account": tds_account,
                    "against": pi.supplier,
                    "debit": tds_amt,
                    "debit_in_account_currency": tds_amt,
                    "cost_center": pi.get("cost_center"),
                    "remarks": _("TDS removal"),
                },
            ),
        ]
        make_gl_entries(gl, merge_entries=False)
        return

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
