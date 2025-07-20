# submission_restriction.py
import frappe
from frappe import _

# Define document categories and their associated doctypes
DOCUMENT_CATEGORIES = {
    "stock": {
        "doctypes": [
            "Stock Entry",
            "Stock Reconciliation",
            "Sales Invoice",  # Only when update_stock is enabled
            "Purchase Invoice",  # Only when update_stock is enabled
            "Delivery Note",
            "Purchase Receipt"
        ],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted. You may save as draft, but only authorized users can submit.")
    },
    "transaction": {
        "doctypes": [
            "Sales Invoice",
            "Delivery Note", 
            "Purchase Invoice",
            "Purchase Receipt",
            "Journal Entry",
            "Payment Entry"
        ],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted. You may save as draft, but only authorized users can submit.")
    },
    "order": {
        "doctypes": [
            "Sales Order",
            "Purchase Order",
            "Payment Request"
        ],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted. You may save as draft, but only authorized users can submit.")
    }
}

def validate_submission_permission(doc, method):
    """
    Unified validation function for submission restrictions across all document types.
    
    This function replaces the separate stock_restriction and transaction_restriction
    validation functions with a single, cleaner implementation.
    """
    # Check if submission restriction is enabled
    restrict_submission = frappe.db.get_single_value("BNS Settings", "restrict_submission")
    
    if not restrict_submission:
        return
    
    # Find which category this document belongs to
    document_category = get_document_category(doc.doctype)
    
    if not document_category:
        return
    
    # Special handling for Sales/Purchase Invoice with stock updates
    if doc.doctype in ["Sales Invoice", "Purchase Invoice"] and not doc.update_stock:
        # If update_stock is not enabled, treat as transaction, not stock
        if document_category == "stock":
            document_category = "transaction"
    
    # Check if user has override permissions
    if has_override_permission(document_category):
        return
    
    # If we reach here, the restriction is enabled and user is not authorized
    category_config = DOCUMENT_CATEGORIES[document_category]
    error_message = category_config["error_message"].format(doctype=doc.doctype)
    
    frappe.throw(error_message, title=_("Submission Permission Error"))

def get_document_category(doctype):
    """
    Determine which category a document type belongs to.
    
    Args:
        doctype (str): The document type to categorize
        
    Returns:
        str: The category name ('stock', 'transaction', 'order') or None if not categorized
    """
    for category, config in DOCUMENT_CATEGORIES.items():
        if doctype in config["doctypes"]:
            return category
    return None

def has_override_permission(category):
    """
    Check if the current user has override permissions for the given category.
    
    Args:
        category (str): The document category to check permissions for
        
    Returns:
        bool: True if user has override permission, False otherwise
    """
    # Get user roles
    user_roles = set(frappe.get_roles())
    
    # Get override roles from BNS Settings
    override_roles_data = frappe.db.get_all(
        "Has Role",
        filters={
            "parenttype": "BNS Settings",
            "parentfield": DOCUMENT_CATEGORIES[category]["override_field"]
        },
        fields=["role"],
        ignore_permissions=True
    )
    
    # Extract role names
    override_roles = {d.role for d in override_roles_data}
    
    # Check if user has any of the override roles
    return bool(override_roles and user_roles.intersection(override_roles))

# Legacy function names for backward compatibility
def validate_stock_modification(doc, method):
    """
    Legacy function for stock modification validation.
    Now redirects to the unified validation function.
    """
    validate_submission_permission(doc, method)

def validate_transaction_modification(doc, method):
    """
    Legacy function for transaction modification validation.
    Now redirects to the unified validation function.
    """
    validate_submission_permission(doc, method)

def validate_order_modification(doc, method):
    """
    Legacy function for order modification validation.
    Now redirects to the unified validation function.
    """
    validate_submission_permission(doc, method) 