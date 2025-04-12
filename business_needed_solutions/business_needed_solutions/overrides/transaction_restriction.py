# transaction_restriction.py
import frappe
from frappe import _

def validate_transaction_modification(doc, method):
    """
    Validate if the user has permission to submit transaction documents
    based on BNS Settings configuration.
    """
    # Check BNS Settings without requiring permissions
    restrict_transaction_entry = frappe.db.get_single_value("BNS Settings", "restrict_transaction_entry")
    
    if not restrict_transaction_entry:
        return
    
    # List of doctypes to restrict
    restricted_doctypes = [
        "Sales Invoice",
        "Delivery Note",
        "Purchase Invoice",
        "Purchase Receipt",
        "Journal Entry",
        "Payment Entry"
    ]
    
    if doc.doctype not in restricted_doctypes:
        return
    
    # Check if user has any override roles defined in settings
    user_roles = set(frappe.get_roles())
    
    # Get the allowed roles from BNS Settings
    override_roles_data = frappe.db.get_all(
        "Has Role",
        filters={
            "parenttype": "BNS Settings",
            "parentfield": "transaction_restriction_override_roles"
        },
        fields=["role"],
        ignore_permissions=True
    )
    
    # Extract the role names from the data
    override_roles = {d.role for d in override_roles_data}
    
    # Check if user has any of the override roles
    if override_roles and user_roles.intersection(override_roles):
        return
    
    # If we reach here, the transaction restriction is enabled and user is not authorized
    frappe.throw(_(
        "Submitting transaction documents has been restricted for now. "
        "You may save as draft, but only authorized users can submit."
    ), title=_("Submission Permission Error"))

def validate_order_modification(doc, method):
    """
    Validate if the user has permission to submit order documents
    based on BNS Settings configuration.
    """
    # Check BNS Settings without requiring permissions
    restrict_order_entry = frappe.db.get_single_value("BNS Settings", "restrict_order_entry")
    
    if not restrict_order_entry:
        return
    
    # List of doctypes to restrict
    restricted_doctypes = [
        "Sales Order",
        "Payment Request",
        "Purchase Order"
    ]
    
    if doc.doctype not in restricted_doctypes:
        return
    
    # Check if user has any override roles defined in settings
    user_roles = set(frappe.get_roles())
    
    # Get the allowed roles from BNS Settings
    override_roles_data = frappe.db.get_all(
        "Has Role",
        filters={
            "parenttype": "BNS Settings",
            "parentfield": "order_restriction_override_roles"
        },
        fields=["role"],
        ignore_permissions=True
    )
    
    # Extract the role names from the data
    override_roles = {d.role for d in override_roles_data}
    
    # Check if user has any of the override roles
    if override_roles and user_roles.intersection(override_roles):
        return
    
    # If we reach here, the order restriction is enabled and user is not authorized
    frappe.throw(_(
        "Submitting order documents has been restricted for now. "
        "You may save as draft, but only authorized users can submit."
    ), title=_("Submission Permission Error")) 