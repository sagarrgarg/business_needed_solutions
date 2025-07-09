# stock_update_validation.py
import frappe
from frappe import _

def validate_stock_update_or_reference(doc, method):
    """
    Validate if either update_stock is enabled or all items are referenced 
    from Purchase Receipt or Delivery Note based on BNS Settings configuration.
    """
    # Check BNS Settings without requiring permissions
    enforce_stock_update_or_reference = frappe.db.get_single_value("BNS Settings", "enforce_stock_update_or_reference")
    
    if not enforce_stock_update_or_reference:
        return
    
    # Only apply to Sales Invoice and Purchase Invoice
    if doc.doctype not in ["Sales Invoice", "Purchase Invoice"]:
        return
    
    # If update_stock is enabled, no need to check references
    if doc.update_stock:
        return
    
    # For Purchase Invoice, check if any items are NOT referenced from Purchase Receipt
    if doc.doctype == "Purchase Invoice":
        has_non_referenced = False
        for item in doc.items:
            # Fetch maintain_stock for the item
            maintain_stock = frappe.db.get_value("Item", item.item_code, "is_stock_item")
            if not maintain_stock:
                continue  # Skip non-stock items
            if not item.get("purchase_receipt") and not item.get("purchase_receipt_item"):
                has_non_referenced = True
                break
        if has_non_referenced:
            frappe.throw(_(
                "When 'Update Stock' is not checked, all stock items must be referenced from a Purchase Receipt."
            ), title=_("Validation Error"))
    # For Sales Invoice, check if any items are NOT referenced from Delivery Note
    elif doc.doctype == "Sales Invoice":
        has_non_referenced = False
        for item in doc.items:
            # Fetch maintain_stock for the item
            maintain_stock = frappe.db.get_value("Item", item.item_code, "is_stock_item")
            if not maintain_stock:
                continue  # Skip non-stock items
            if not item.get("delivery_note") and not item.get("dn_detail"):
                has_non_referenced = True
                break
        if has_non_referenced:
            frappe.throw(_(
                "When 'Update Stock' is not checked, all stock items must be referenced from a Delivery Note."
            ), title=_("Validation Error")) 