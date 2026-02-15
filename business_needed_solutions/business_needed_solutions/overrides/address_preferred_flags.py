"""
Override Address to force is_primary_address and is_shipping_address to 0
when BNS Settings suppresses Preferred Billing & Shipping Address.
"""

import frappe


def enforce_suppress_preferred_address(doc, method=None):
    """
    When Suppress Preferred Billing & Shipping Address is enabled in BNS Settings,
    force is_primary_address and is_shipping_address to 0 on every Address save.
    """
    try:
        settings = frappe.get_single("BNS Settings")
        if not settings.get("suppress_preferred_billing_shipping_address"):
            return
    except Exception:
        return

    if hasattr(doc, "is_primary_address"):
        doc.is_primary_address = 0
    if hasattr(doc, "is_shipping_address"):
        doc.is_shipping_address = 0
