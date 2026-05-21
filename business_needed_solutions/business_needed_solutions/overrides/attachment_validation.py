"""
Business Needed Solutions - Purchase Document Attachment Validation

Enforces mandatory attachments (supplier invoice, e-Waybill) on Purchase Receipt
and Purchase Invoice before submission via dedicated Attach fields on the doctype.

When a PI is created from a PR, the PI is exempt because the attachments are
expected on the PR.  Builty/LR attachment is always optional.

BNS internal supplier: no attachment validation; fields are hidden in the client
(see purchase_attachment_fields.js). External supplier restores normal rules.

Toggle: BNS Settings > Stock & Inventory > Enforce Purchase Document Attachments
"""

import json
import logging
from typing import Optional

import frappe
from frappe import _, bold
from frappe.utils import cint, flt

logger = logging.getLogger(__name__)


def validate_purchase_attachments(doc, method: Optional[str] = None) -> None:
    """
    before_submit hook for Purchase Receipt and Purchase Invoice.

    Validates that the required attach fields (supplier invoice, and e-Waybill
    when applicable) are filled before allowing submission.

    Args:
        doc: The PR or PI document being submitted.
        method: Frappe hook method name (unused).
    """
    if not _is_attachment_validation_enabled():
        return

    if _is_before_attachment_cutoff(doc):
        return

    if doc.get("is_return"):
        return

    if _is_bns_internal_supplier_scope(doc):
        return

    if doc.doctype == "Purchase Receipt":
        _require_supplier_invoice(doc)
        _require_supplier_invoice_details(doc)
        if _is_ewaybill_required(doc):
            _require_ewaybill(doc)

    elif doc.doctype == "Purchase Invoice":
        if _has_linked_purchase_receipt(doc):
            return
        _require_supplier_invoice(doc)
        _require_supplier_invoice_details(doc)
        if _is_ewaybill_required(doc):
            _require_ewaybill(doc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_attachment_validation_enabled() -> bool:
    """Check if the toggle is on in BNS Settings."""
    try:
        return bool(cint(
            frappe.db.get_single_value("BNS Settings", "enforce_purchase_document_attachments")
        ))
    except Exception:
        return False


def _is_before_attachment_cutoff(doc) -> bool:
    """Return True if the document's posting date is BEFORE the cutoff date,
    meaning it is exempt from attachment enforcement."""
    try:
        cutoff = frappe.db.get_single_value("BNS Settings", "purchase_attachment_cutoff_date")
        if not cutoff:
            return False  # No cutoff → enforce on all dates
        posting_date = doc.get("posting_date")
        if not posting_date:
            return False  # No posting date → enforce (safer default)
        from frappe.utils import getdate
        return getdate(posting_date) < getdate(cutoff)
    except Exception:
        return False


def _is_bns_internal_supplier_scope(doc) -> bool:
    """
    True when PR/PI supplier is a BNS internal branch supplier.

    Uses the document flag when set; otherwise reads Supplier master so drafts
    stay consistent after changing supplier before save.
    """
    if doc.doctype not in ("Purchase Receipt", "Purchase Invoice"):
        return False
    if cint(doc.get("is_bns_internal_supplier")):
        return True
    supplier = doc.get("supplier")
    if not supplier:
        return False
    return bool(cint(frappe.db.get_value("Supplier", supplier, "is_bns_internal_supplier")))


def _require_supplier_invoice(doc) -> None:
    """Throw if the bns_supplier_invoice_attachment field is empty."""
    if not doc.get("bns_supplier_invoice_attachment"):
        frappe.throw(
            _(
                "Supplier Invoice attachment is mandatory to submit {0} {1}. "
                "Please attach the supplier invoice."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("Supplier Invoice Required"),
        )


def _supplier_skips_invoice_details(supplier) -> bool:
    """Per-supplier opt-out of the bill_no/bill_date enforcement."""
    if not supplier:
        return False
    return bool(cint(
        frappe.db.get_value("Supplier", supplier, "bns_skip_supplier_invoice_details")
    ))


def _require_supplier_invoice_details(doc) -> None:
    """
    Throw if bill_no or bill_date is missing, unless the supplier has opted
    out via bns_skip_supplier_invoice_details on the Supplier master.
    """
    if _supplier_skips_invoice_details(doc.get("supplier")):
        return

    if not doc.get("bill_no"):
        frappe.throw(
            _(
                "Supplier Invoice No is mandatory to submit {0} {1}."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("Supplier Invoice No Required"),
        )

    if not doc.get("bill_date"):
        frappe.throw(
            _(
                "Supplier Invoice Date is mandatory to submit {0} {1}."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("Supplier Invoice Date Required"),
        )


def _is_ewaybill_required(doc) -> bool:
    """
    Return True when the document needs an e-Waybill attachment.

    BNS transport mode takes priority:
      - "By Hand" or "By Lorry"  →  e-Waybill not required (even over threshold).
      - "By e-Waybill" or blank  →  fall through to the threshold rule.

    Threshold conditions (all must be true):
      1. GST Settings has enable_e_waybill turned on.
      2. At least one line item is a stock item (goods). update_stock alone
         does not count — non-stock-only PIs must not require e-Waybill.
      3. abs(base_grand_total) >= e_waybill_threshold from GST Settings.
      4. Supplier GST category is not "Unregistered".
    """
    mode = (doc.get("bns_mode_of_transport") or "").strip()
    if mode in ("By Hand", "By Lorry"):
        return False

    if _is_unregistered_supplier(doc):
        return False

    try:
        enable_ewaybill = frappe.db.get_single_value("GST Settings", "enable_e_waybill")
        if not cint(enable_ewaybill):
            return False
    except Exception:
        return False

    threshold = _get_ewaybill_threshold()
    if threshold <= 0:
        return False

    if not _has_stock_items(doc):
        return False

    return abs(flt(doc.base_grand_total)) >= threshold


def _has_stock_items(doc) -> bool:
    """True if at least one row references an Item with is_stock_item set."""
    for item in doc.items or []:
        code = item.get("item_code")
        if not code:
            continue
        if cint(frappe.get_cached_value("Item", code, "is_stock_item")):
            return True
    return False


def _require_ewaybill(doc) -> None:
    """Throw if the bns_ewaybill_attachment or bns_ewaybill_date field is empty."""
    if not doc.get("bns_ewaybill_attachment"):
        frappe.throw(
            _(
                "e-Waybill attachment is mandatory to submit {0} {1} "
                "(net total exceeds the e-Waybill threshold). "
                "Please attach the e-Waybill."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("e-Waybill Required"),
        )

    if not doc.get("bns_ewaybill_date"):
        frappe.throw(
            _(
                "e-Waybill Date is mandatory to submit {0} {1}. "
                "Please fill the date printed on the e-Waybill."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("e-Waybill Date Required"),
        )


def _is_unregistered_supplier(doc) -> bool:
    """True when the document's GST category is Unregistered."""
    return (doc.get("gst_category") or "").strip().lower() == "unregistered"


def _has_linked_purchase_receipt(doc) -> bool:
    """Return True if any PI item references a Purchase Receipt."""
    for item in doc.items or []:
        if item.get("purchase_receipt"):
            return True
    return False


def _get_ewaybill_threshold() -> float:
    """Fetch e_waybill_threshold from GST Settings (default 0)."""
    try:
        return flt(
            frappe.db.get_single_value("GST Settings", "e_waybill_threshold") or 0
        )
    except Exception:
        return 0


@frappe.whitelist()
def check_ewaybill_applicability(
    doctype,
    base_grand_total,
    update_stock=0,
    items_json=None,
    is_bns_internal_supplier=0,
    supplier=None,
    gst_category=None,
    posting_date=None,
    mode_of_transport=None,
):
    """
    Client-callable endpoint to determine whether the e-Waybill field should be
    visible/mandatory for the current document state.

    For PI/PR, requires at least one stock item row (``update_stock`` is ignored
    for that check; kept only for API compatibility).

    ``mode_of_transport`` is the BNS transport mode field — when set to
    "By Hand" or "By Lorry" the e-Waybill is not required regardless of
    threshold.

    Returns dict: {"required": bool, "threshold": float}
    """
    # Frontend-only helper — still require the caller to be an authenticated
    # desk user with at least read on the doctype they're asking about.
    if frappe.session.user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if doctype and not frappe.has_permission(doctype, "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if not _is_attachment_validation_enabled():
        return {"required": False, "threshold": 0}

    if posting_date:
        from frappe.utils import getdate
        cutoff = frappe.db.get_single_value("BNS Settings", "purchase_attachment_cutoff_date")
        if cutoff and getdate(posting_date) < getdate(cutoff):
            return {"required": False, "threshold": 0}

    if (mode_of_transport or "").strip() in ("By Hand", "By Lorry"):
        return {"required": False, "threshold": _get_ewaybill_threshold()}

    if cint(is_bns_internal_supplier):
        return {"required": False, "threshold": _get_ewaybill_threshold()}
    if supplier and cint(frappe.db.get_value("Supplier", supplier, "is_bns_internal_supplier")):
        return {"required": False, "threshold": _get_ewaybill_threshold()}

    if (gst_category or "").strip().lower() == "unregistered":
        return {"required": False, "threshold": _get_ewaybill_threshold()}

    try:
        enable_ewaybill = frappe.db.get_single_value("GST Settings", "enable_e_waybill")
        if not cint(enable_ewaybill):
            return {"required": False, "threshold": 0}
    except Exception:
        return {"required": False, "threshold": 0}

    threshold = _get_ewaybill_threshold()
    if threshold <= 0:
        return {"required": False, "threshold": 0}

    has_stock = True
    if doctype in ("Purchase Invoice", "Purchase Receipt"):
        items = []
        if items_json:
            try:
                items = json.loads(items_json) if isinstance(items_json, str) else items_json
            except (json.JSONDecodeError, TypeError):
                items = []
        has_stock = False
        for item in items:
            item_code = item.get("item_code") if isinstance(item, dict) else None
            if item_code and cint(frappe.get_cached_value("Item", item_code, "is_stock_item")):
                has_stock = True
                break

    if not has_stock:
        return {"required": False, "threshold": threshold}

    required = abs(flt(base_grand_total)) >= threshold
    return {"required": required, "threshold": threshold}
