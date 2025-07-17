# warehouse_validation.py
import frappe
from frappe import _

def validate_warehouse_restriction(doc, method):
    """
    Validate if the same warehouse restriction is enabled in BNS Settings
    and prevent same warehouse in source and target for all stock entry types.
    """
    # Check BNS Settings without requiring permissions
    restrict_same_warehouse = frappe.db.get_single_value("BNS Settings", "restrict_same_warehouse")
    
    if not restrict_same_warehouse:
        return
    
    # Validate each item in the stock entry
    for item in doc.get("items", []):
        if item.s_warehouse and item.t_warehouse and item.s_warehouse == item.t_warehouse:
            frappe.throw(_(
                "Row {0}: Source and target warehouse cannot be same ({1}). "
                "This restriction is enabled in BNS Settings."
            ).format(item.idx, frappe.bold(item.s_warehouse)), 
            title=_("Same Warehouse Restriction")) 