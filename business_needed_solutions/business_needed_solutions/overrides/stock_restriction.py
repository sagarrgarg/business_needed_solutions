# stock_restriction.py
import frappe
from frappe import _

def validate_stock_modification(doc, method):
    """
    Validate if the user has permission to submit stock entries
    based on BNS Settings configuration.
    """
    
    # Check BNS Settings without requiring permissions
    # restrict_stock_entry = frappe.db.get_value("BNS Settings", None, "restrict_stock_entry")
    restrict_stock_entry = frappe.db.get_single_value("BNS Settings", "restrict_stock_entry")

    
    if not restrict_stock_entry:
        return
    
    # For Sales/Purchase Invoice, only validate if update_stock is enabled
    if doc.doctype in ["Sales Invoice", "Purchase Invoice"] and not doc.update_stock:
        return
    
    # Check if user has any override roles defined in settings
    user_roles = set(frappe.get_roles())
    
    # Get the allowed roles from BNS Settings
    override_roles_data = frappe.db.get_all(
        "Has Role",
        filters={
            "parenttype": "BNS Settings",
            "parentfield": "stock_restriction_override_roles"
        },
        fields=["role"],
        ignore_permissions=True
    )
    
    # Extract the role names from the data
    override_roles = {d.role for d in override_roles_data}
    
    # Check if user has any of the override roles
    if override_roles and user_roles.intersection(override_roles):
        return
    
    # If we reach here, the stock restriction is enabled and user is not authorized
    frappe.throw(_(
        "Adding stock transactions has been restricted for now. "
        "You may save as draft, but only authorized users can submit."
    ), title=_("Submission Permission Error"))