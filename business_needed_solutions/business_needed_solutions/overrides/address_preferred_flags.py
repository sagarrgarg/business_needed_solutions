"""
Override Address to suppress is_primary_address and is_shipping_address
when BNS Settings has Suppress Preferred Billing & Shipping Address enabled.
"""

import frappe


def enforce_suppress_preferred_address(doc, method=None):
    """
    Force is_primary_address and is_shipping_address to 0 on every Address save
    when BNS Settings.suppress_preferred_billing_shipping_address is enabled.

    Args:
        doc: Address document
        method: Hook method name
    """
    try:
        settings = frappe.get_single("BNS Settings")
        if not settings.get("suppress_preferred_billing_shipping_address"):
            return
    except Exception as e:
        frappe.log_error(
            title="BNS Address Preferred Flags: Failed to read BNS Settings",
            message=str(e),
        )
        return

    if hasattr(doc, "is_primary_address"):
        doc.is_primary_address = 0
    if hasattr(doc, "is_shipping_address"):
        doc.is_shipping_address = 0


@frappe.whitelist()
def clear_existing_address_flags():
    """
    Bulk update all Address records to set is_primary_address=0 and is_shipping_address=0.
    Use this as a backdate fix when enabling Suppress Preferred Billing & Shipping Address
    in BNS Settings, so existing addresses are cleared of their preferred flags.
    """
    frappe.only_for("System Manager")
    count_result = frappe.db.sql(
        """
        SELECT COUNT(*) FROM tabAddress
        WHERE is_primary_address = 1 OR is_shipping_address = 1
        """
    )
    count = count_result[0][0] if count_result else 0
    if count > 0:
        frappe.db.sql(
            """
            UPDATE tabAddress
            SET is_primary_address = 0, is_shipping_address = 0
            WHERE is_primary_address = 1 OR is_shipping_address = 1
            """
        )
        frappe.db.commit()
    return {"updated": count}

