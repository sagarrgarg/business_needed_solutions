# value_difference_validation.py
import frappe
from frappe import _

def validate_value_difference(doc, method):
    """
    Validate if Stock Entry has value difference and restrict based on BNS Settings configuration.
    """
    # Check BNS Settings without requiring permissions
    restrict_value_difference = frappe.db.get_single_value("BNS Settings", "restrict_value_difference")
    
    if not restrict_value_difference:
        return
    
    # Only apply to Stock Entry
    if doc.doctype != "Stock Entry":
        return
    
    # Check if there's any value difference in the stock entry
    has_value_difference = False
    
    # Check the main value_difference field in the Stock Entry doctype
    if doc.get("value_difference") and abs(flt(doc.value_difference)) > 0:
        has_value_difference = True
    
    if not has_value_difference:
        return
    
    # Check if user has any override roles defined in settings
    user_roles = set(frappe.get_roles())
    
    # Get the allowed roles from BNS Settings
    override_roles_data = frappe.db.get_all(
        "Has Role",
        filters={
            "parenttype": "BNS Settings",
            "parentfield": "value_difference_override_roles"
        },
        fields=["role"],
        ignore_permissions=True
    )
    
    # Extract the role names from the data
    override_roles = {d.role for d in override_roles_data}
    
    # Check if user has any of the override roles
    if override_roles and user_roles.intersection(override_roles):
        return
    
    # If we reach here, the value difference restriction is enabled and user is not authorized
    frappe.throw(_(
        "Stock Entries with value difference are not allowed. "
        "Please ensure all items have zero value difference or contact an authorized user."
    ), title=_("Value Difference Restriction Error"))

def flt(value, precision=None):
    """Convert to float, return 0.0 if conversion fails"""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0 