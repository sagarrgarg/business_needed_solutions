# auto_transit_validation.py
import frappe
from frappe import _

def auto_set_transit_for_material_transfer(doc, method):
    """
    Automatically set 'Add to Transit' to 1 for Material Transfer type Stock Entries
    based on BNS Settings configuration.
    """
    # Check BNS Settings without requiring permissions
    auto_transit_material_transfer = frappe.db.get_single_value("BNS Settings", "auto_transit_material_transfer")
    
    if not auto_transit_material_transfer:
        return
    
    # Only apply to Material Transfer entries that are not outgoing stock entries
    if (doc.stock_entry_type == "Material Transfer" and 
        doc.purpose == "Material Transfer" and 
        not doc.outgoing_stock_entry):
        
        # Set add_to_transit to 1
        doc.add_to_transit = 1 