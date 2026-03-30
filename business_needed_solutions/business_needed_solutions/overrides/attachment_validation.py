"""
Business Needed Solutions - Purchase Document Attachment Validation

Enforces mandatory attachments (supplier invoice, e-Waybill) on Purchase Receipt
and Purchase Invoice before submission via dedicated Attach fields on the doctype.

When a PI is created from a PR, the PI is exempt because the attachments are
expected on the PR.  Builty/LR attachment is always optional.

Toggle: BNS Settings > Stock & Inventory > Enforce Purchase Document Attachments
"""

import frappe
from frappe import _, bold
from frappe.utils import flt
from typing import Optional
import logging

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

    if doc.doctype == "Purchase Receipt":
        _require_supplier_invoice(doc)
        if _is_ewaybill_required(doc):
            _require_ewaybill(doc)

    elif doc.doctype == "Purchase Invoice":
        if _has_linked_purchase_receipt(doc):
            return
        _require_supplier_invoice(doc)
        if _is_ewaybill_required(doc):
            _require_ewaybill(doc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_attachment_validation_enabled() -> bool:
    """Check if the toggle is on in BNS Settings."""
    try:
        return bool(
            frappe.db.get_single_value("BNS Settings", "enforce_purchase_document_attachments")
        )
    except Exception:
        return False


def _require_supplier_invoice(doc) -> None:
    """Throw if the bns_supplier_invoice_attachment field is empty."""
    if not doc.get("bns_supplier_invoice_attachment"):
        frappe.throw(
            _(
                "Supplier Invoice attachment is mandatory to submit {0} {1}. "
                "Please attach the supplier invoice in the 'Purchase Document Attachments' section."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("Supplier Invoice Required"),
        )


def _is_ewaybill_required(doc) -> bool:
    """
    Return True when the document needs an e-Waybill attachment.

    Conditions (all must be true):
      1. GST Settings has enable_e_waybill turned on.
      2. The document contains stock items (PR always does; PI only when
         update_stock is on or at least one line item is a stock item).
      3. abs(base_grand_total) >= e_waybill_threshold from GST Settings.
    """
    try:
        enable_ewaybill = frappe.db.get_single_value("GST Settings", "enable_e_waybill")
        if not enable_ewaybill:
            return False
    except Exception:
        return False

    if doc.doctype == "Purchase Invoice" and not _has_stock_items(doc):
        return False

    threshold = _get_ewaybill_threshold()
    if threshold <= 0:
        return False

    return abs(flt(doc.base_grand_total)) >= threshold


def _has_stock_items(doc) -> bool:
    """Check whether a Purchase Invoice involves stock items."""
    if doc.get("update_stock"):
        return True

    for item in doc.items or []:
        is_stock = frappe.get_cached_value("Item", item.item_code, "is_stock_item")
        if is_stock:
            return True

    return False


def _require_ewaybill(doc) -> None:
    """Throw if the bns_ewaybill_attachment field is empty."""
    if not doc.get("bns_ewaybill_attachment"):
        frappe.throw(
            _(
                "e-Waybill attachment is mandatory to submit {0} {1} "
                "(net total exceeds the e-Waybill threshold). "
                "Please attach the e-Waybill in the 'Purchase Document Attachments' section."
            ).format(bold(doc.doctype), bold(doc.name)),
            title=_("e-Waybill Required"),
        )


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
def check_ewaybill_applicability(doctype, base_grand_total, update_stock=0, items_json=None):
    """
    Client-callable endpoint to determine whether the e-Waybill field should be
    visible/mandatory for the current document state.

    Returns dict: {"required": bool, "threshold": float}
    """
    if not _is_attachment_validation_enabled():
        return {"required": False, "threshold": 0}

    try:
        enable_ewaybill = frappe.db.get_single_value("GST Settings", "enable_e_waybill")
        if not enable_ewaybill:
            return {"required": False, "threshold": 0}
    except Exception:
        return {"required": False, "threshold": 0}

    threshold = _get_ewaybill_threshold()
    if threshold <= 0:
        return {"required": False, "threshold": 0}

    has_stock = True
    if doctype == "Purchase Invoice":
        if not int(update_stock or 0):
            has_stock = False
            if items_json:
                import json
                try:
                    items = json.loads(items_json) if isinstance(items_json, str) else items_json
                except (json.JSONDecodeError, TypeError):
                    items = []
                for item in items:
                    item_code = item.get("item_code")
                    if item_code and frappe.get_cached_value("Item", item_code, "is_stock_item"):
                        has_stock = True
                        break

    if not has_stock:
        return {"required": False, "threshold": threshold}

    required = abs(flt(base_grand_total)) >= threshold
    return {"required": required, "threshold": threshold}
