# item_validation.py
import frappe
from frappe import _

def validate_expense_account_for_non_stock_items(doc, method):
    """
    Validate that non-stock items have at least one expense account in Item Defaults
    based on BNS Settings configuration.
    """
    # Check BNS Settings without requiring permissions
    enforce_expense_account = frappe.db.get_single_value("BNS Settings", "enforce_expense_account_for_non_stock_items")
    
    if not enforce_expense_account:
        return
    
    # Only apply to Item doctype
    if doc.doctype != "Item":
        return
    
    # Check if item is not a stock item
    if doc.is_stock_item:
        return
    
    # Check if there's at least one expense account in item defaults
    has_expense_account = False
    
    if doc.item_defaults:
        for item_default in doc.item_defaults:
            if item_default.get("expense_account"):
                has_expense_account = True
                break
    
    if not has_expense_account:
        frappe.throw(_(
            "Since 'Maintain Stock' is disabled, at least one Expense Account is required in Item Defaults."
        ), title=_("Missing Expense Account")) 