"""
BNS Branch Accounting - Billing Location

Handles billing_location for BNS internal customers:
- Sets customer_address from Location's linked_address
- Clears/sets GST fields (billing_address_gstin, gst_category, place_of_supply)
- Lock validation: allow change in draft, block after submit
"""

from frappe.contacts.doctype.address.address import get_address_display

import frappe
from frappe import _


def validate_billing_location(doc, method=None):
    """
    Entry point for validate hook: handle BNS internal customer billing_location
    and lock validation (allow change in draft, block after submit).
    """
    handle_billing_location_for_internal_customer(doc)
    validate_billing_location_lock(doc)


def handle_billing_location_for_internal_customer(doc):
    """
    For BNS internal customer: require billing_location and set customer_address from
    Location's linked_address. Customer address is driven by billing location.
    Clear billing_address_gstin, gst_category, place_of_supply until billing_location is set.
    """
    sales_doctypes_with_customer = ["Sales Invoice", "Sales Order", "Delivery Note"]
    if doc.doctype not in sales_doctypes_with_customer:
        return
    if not hasattr(doc, "customer_address"):
        return

    is_internal = doc.get("is_bns_internal_customer") or False
    if not is_internal and doc.customer:
        try:
            if frappe.db.has_column("Customer", "is_bns_internal_customer"):
                is_internal = frappe.db.get_value(
                    "Customer", doc.customer, "is_bns_internal_customer"
                ) or False
        except Exception:
            pass

    if not is_internal:
        return

    billing_location = doc.get("billing_location")
    if not billing_location:
        _clear_billing_gst_fields(doc)
        frappe.throw(
            _("For BNS internal customer, Billing Location is required to set Customer Address.")
        )

    loc = frappe.get_doc("Location", billing_location)
    if loc.is_group:
        frappe.throw(_("Billing Location must be a leaf location (not a group)."))
    if not loc.linked_address:
        frappe.throw(_("Selected Billing Location must have a Linked Address."))

    doc.customer_address = loc.linked_address
    if hasattr(doc, "address_display"):
        doc.address_display = get_address_display(loc.linked_address)

    _set_billing_gst_fields_from_address(doc, loc.linked_address)


def validate_billing_location_lock(doc):
    """
    Allow billing_location changes only in draft state.
    Block after document is submitted.
    """
    if not hasattr(doc, "billing_location"):
        return
    if doc.is_new():
        return
    if doc.docstatus == 0:
        return

    old = frappe.get_doc(doc.doctype, doc.name)
    if doc.billing_location != old.get("billing_location"):
        frappe.throw(
            _("Field 'billing_location' cannot be changed after document is submitted.")
        )


def _clear_billing_gst_fields(doc):
    """Clear billing_address_gstin, gst_category, place_of_supply."""
    for field in ("billing_address_gstin", "gst_category", "place_of_supply"):
        if hasattr(doc, field):
            doc.set(field, "")


def _set_billing_gst_fields_from_address(doc, address_name):
    """Set billing_address_gstin, gst_category, place_of_supply from Address."""
    if not address_name:
        return
    fields = ["gstin", "country", "state", "gst_state", "gst_state_number"]
    if frappe.db.has_column("Address", "gst_category"):
        fields.append("gst_category")
    try:
        addr = frappe.db.get_value("Address", address_name, fields, as_dict=True)
    except Exception:
        return
    if not addr:
        return
    if hasattr(doc, "billing_address_gstin"):
        doc.billing_address_gstin = addr.get("gstin") or ""
    if hasattr(doc, "gst_category") and "gst_category" in addr:
        doc.gst_category = addr.get("gst_category") or ""
    if hasattr(doc, "place_of_supply"):
        doc.place_of_supply = _get_place_of_supply_from_address(address_name) or ""


def _get_place_of_supply_from_address(address_name):
    """Get place of supply from address. Tries location_based_series if available."""
    if not address_name:
        return None
    try:
        from location_based_series.utils import get_place_of_supply_from_address
        return get_place_of_supply_from_address(address_name)
    except ImportError:
        return None


@frappe.whitelist()
def get_linked_address_for_location(location_name):
    """Get linked_address from Location. Used by billing_location to set customer_address."""
    if not location_name:
        return None
    return frappe.db.get_value("Location", location_name, "linked_address")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def billing_location_query(doctype, txt, searchfield, start, page_len, filters, **kwargs):
    """Query for billing_location: only leaf locations (is_group=0)."""
    filters_dict = {"is_group": 0}
    if txt:
        filters_dict["name"] = ["like", f"%{txt}%"]
    return frappe.get_all(
        "Location",
        filters=filters_dict,
        fields=["name", "location_name"],
        order_by="name",
        limit_start=start,
        limit_page_length=page_len,
        as_list=True,
    )
