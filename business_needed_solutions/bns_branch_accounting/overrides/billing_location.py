"""
BNS Branch Accounting - Billing Location → Customer Address

On validate: if billing_location is set and customer is BNS internal, resolve the
Location's linked_address and overwrite customer_address + address_display
(+ billing_address_gstin, gst_category, place_of_supply from address). Mirrors
location_based_series' pattern of setting company_address from location. For
outside customers, billing_location is left as-is and customer_address remains
editable.
"""

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_address_display

from business_needed_solutions.bns_branch_accounting.utils import is_bns_internal_customer


def set_customer_address_from_billing_location(doc, method=None):
    """Set customer_address and GST fields from billing_location.linked_address on save (BNS customers only)."""
    if not doc.get("billing_location"):
        return
    if not is_bns_internal_customer(doc):
        return

    linked_address = frappe.db.get_value(
        "Location", doc.billing_location, "linked_address"
    )
    if not linked_address:
        frappe.throw(
            _("Billing Location {0} does not have a Linked Address.").format(
                frappe.bold(doc.billing_location)
            )
        )

    doc.customer_address = linked_address
    doc.address_display = get_address_display(linked_address)

    # GST fields from address (SI, DN have these from India Compliance)
    addr = frappe.db.get_value(
        "Address",
        linked_address,
        ["gstin", "gst_category", "gst_state_number", "gst_state"],
        as_dict=True,
    )
    if addr:
        if addr.gstin:
            if doc.meta.has_field("customer_gstin"):
                doc.customer_gstin = addr.gstin
            if doc.meta.has_field("billing_address_gstin"):
                doc.billing_address_gstin = addr.gstin
        if addr.gst_category and doc.meta.has_field("gst_category"):
            doc.gst_category = addr.gst_category
        if doc.meta.has_field("place_of_supply"):
            _set_place_of_supply_from_address(doc, addr, linked_address)


def _set_place_of_supply_from_address(doc, addr, address_name):
    """Set place_of_supply from address. Uses India Compliance if available, else address fields."""
    try:
        from india_compliance.gst_india.utils import get_place_of_supply

        # Build party_details for get_place_of_supply (doc has customer_address, billing_address_gstin set)
        place_of_supply = get_place_of_supply(doc, doc.doctype)
        if place_of_supply:
            doc.place_of_supply = place_of_supply
    except ImportError:
        # Fallback: derive from address gstin or gst_state
        if addr.gstin and len(addr.gstin) >= 2:
            state_code = addr.gstin[:2]
            state_name = frappe.db.get_value("State", {"gst_state_number": state_code}, "state")
            if state_name:
                doc.place_of_supply = f"{state_code}-{state_name}"
        elif addr.gst_state_number and addr.gst_state:
            doc.place_of_supply = f"{addr.gst_state_number}-{addr.gst_state}"
