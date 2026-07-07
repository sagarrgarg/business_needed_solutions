"""Role-gated editing of posting date/time on SUBMITTED stock/accounting vouchers.

Motivation: when purchases are keyed in the evening but goods were available all
day, the day's sales post BEFORE the receipt in stock-ledger order, driving items
negative and distorting FIFO valuation (a receipt that lands into a still-negative
balance discards its incoming rate). Fixing the receipt's posting time to before
the day's issues re-orders the ledger so stock is never negative intraday.

This lets an authorised role change posting_date/posting_time after submit and
then fully rebuilds the ledgers: the voucher's SLE and GL are DELETED and RE-
CREATED fresh at the new posting time, and downstream entries repost. It uses
ERPNext's native Repost Item Valuation (based_on="Transaction" with
recreate_stock_ledgers) so we never hand-patch ledger rows.

Gated by the BNS Settings toggle 'Allow Editing Posting Time After Submit' + the
configured roles (System Manager always allowed). Frozen periods are refused.
"""

import frappe
from frappe import _
from frappe.utils import getdate

# Vouchers whose posting order actually drives stock valuation.
ALLOWED_DOCTYPES = {
    "Purchase Receipt",
    "Purchase Invoice",
    "Delivery Note",
    "Sales Invoice",
    "Stock Entry",
}


def _feature_enabled() -> bool:
    return bool(frappe.db.get_single_value("BNS Settings", "enable_posting_time_edit", cache=True))


def _get_editor_roles():
    """Cached set of roles allowed to edit posting time after submit."""
    cache_key = "_bns_posting_time_edit_roles"
    if cache_key not in frappe.flags:
        frappe.flags[cache_key] = set(
            frappe.get_all(
                "Has Role",
                filters={"parenttype": "BNS Settings", "parentfield": "posting_time_edit_roles"},
                pluck="role",
            )
        )
    return frappe.flags[cache_key]


@frappe.whitelist()
def can_edit_posting_time(user: str = None) -> bool:
    """True when the feature is ON and the user has an allowed role (System
    Manager is always allowed). Whitelisted so the form can toggle the button."""
    if not _feature_enabled():
        return False
    roles = set(frappe.get_roles(user or frappe.session.user))
    if "System Manager" in roles:
        return True
    return bool(_get_editor_roles() & roles)


def _check_not_frozen(posting_date) -> None:
    """Refuse dates inside the frozen accounting period unless the user holds the
    Accounts-Settings frozen-accounts-modifier role."""
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


@frappe.whitelist()
def bns_update_posting_time(doctype: str, docname: str, posting_date: str, posting_time: str):
    """Change posting_date/posting_time on a submitted voucher, then rebuild its
    ledgers: SLE and GL are deleted and recreated fresh at the new posting time,
    and downstream entries repost.

    Gated by the BNS Settings toggle + configured roles; frozen periods refused.
    The teardown/rebuild is delegated to ERPNext's Repost Item Valuation
    (based_on="Transaction", recreate_stock_ledgers=1), which sets the voucher to
    docstatus 2 -> update_stock_ledger (delete SLE) -> docstatus 1 ->
    update_stock_ledger (recreate SLE), then reposts SLE valuation and GL.
    """
    if doctype not in ALLOWED_DOCTYPES:
        frappe.throw(_("Posting-time edit is not supported for {0}.").format(doctype))
    if not can_edit_posting_time():
        frappe.throw(
            _("You are not permitted to edit posting time after submit "
              "(feature disabled or role missing)."),
            frappe.PermissionError,
        )

    doc = frappe.get_doc(doctype, docname)
    if doc.docstatus != 1:
        frappe.throw(_("{0} {1} is not submitted.").format(doctype, docname))

    from erpnext.stock.utils import get_combine_datetime

    old_date = doc.posting_date
    old_time = doc.get("posting_time") or "00:00:00"
    new_date = getdate(posting_date)
    new_time = posting_time or "00:00:00"

    _check_not_frozen(old_date)
    _check_not_frozen(new_date)

    old_dt = get_combine_datetime(old_date, old_time)
    new_dt = get_combine_datetime(new_date, new_time)
    if old_dt == new_dt:
        return {"changed": False}

    # 1) Move the voucher header to the new posting datetime. The reposting job
    #    reloads the doc, so recreate uses this new time.
    frappe.db.set_value(
        doctype, docname,
        {"posting_date": new_date, "posting_time": new_time, "set_posting_time": 1},
        update_modified=True,
    )

    # 2) Delete + recreate SLE and GL (native), reposting from the EARLIER of the
    #    two datetimes so the ledger re-sorts whichever direction the time moved.
    start_date, start_time = (old_date, old_time) if old_dt < new_dt else (new_date, new_time)
    riv = frappe.new_doc("Repost Item Valuation")
    riv.based_on = "Transaction"
    riv.voucher_type = doctype
    riv.voucher_no = docname
    riv.recreate_stock_ledgers = 1
    riv.posting_date = start_date
    riv.posting_time = start_time
    riv.company = doc.company
    riv.allow_zero_rate = 1
    riv.flags.ignore_permissions = True
    riv.flags.ignore_links = True
    riv.save()
    riv.submit()

    frappe.db.commit()
    frappe.log_error(
        message=(
            "%s %s posting datetime %s %s -> %s %s by %s ; repost %s"
            % (doctype, docname, old_date, old_time, new_date, new_time,
               frappe.session.user, riv.name)
        ),
        title="BNS Posting Time Edit",
    )
    return {
        "changed": True,
        "old": "%s %s" % (old_date, old_time),
        "new": "%s %s" % (new_date, new_time),
        "repost": riv.name,
    }
