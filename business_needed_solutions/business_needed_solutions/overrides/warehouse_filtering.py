# warehouse_filtering.py
import frappe
from frappe import _

def validate_warehouse_filtering(doc, method):
    """
    Validate warehouse filtering based on BNS Settings and stock entry type.
    
    Rules:
    1. If auto_transit_material_transfer is enabled:
       - For new Material Transfer entries: target warehouse must be transit type
       - For new Material Transfer entries: source warehouse cannot be transit type
    2. If outgoing_stock_entry is set (receipt from transit):
       - Source warehouse must be transit type
       - Target warehouse must be the custom_for_which_warehouse_to_transfer from outgoing entry
    """
    # Check BNS Settings without requiring permissions
    auto_transit_material_transfer = frappe.db.get_single_value("BNS Settings", "auto_transit_material_transfer")
    
    if not auto_transit_material_transfer:
        return
    
    # Only apply to Material Transfer entries
    if doc.stock_entry_type != "Material Transfer" or doc.purpose != "Material Transfer":
        return
    
    # Rule 2: If this is a receipt from transit (outgoing_stock_entry is set)
    if doc.outgoing_stock_entry:
        validate_receipt_from_transit(doc)
    else:
        # Rule 1: If this is a new Material Transfer entry
        validate_new_material_transfer(doc)

def validate_receipt_from_transit(doc):
    """
    Validate warehouse selection for receipt from transit entries.
    """
    # Get the outgoing stock entry to find the target warehouse
    outgoing_entry = frappe.get_doc("Stock Entry", doc.outgoing_stock_entry)
    target_warehouse = outgoing_entry.get("custom_for_which_warehouse_to_transfer")
    
    if not target_warehouse:
        frappe.throw(_(
            "Outgoing Stock Entry {0} does not have 'For Which Warehouse to Transfer' set. "
            "Please set the target warehouse in the outgoing entry first."
        ).format(doc.outgoing_stock_entry), title=_("Missing Target Warehouse"))
    
    # Validate source warehouse (must be transit type)
    if doc.from_warehouse:
        source_warehouse_type = frappe.db.get_value("Warehouse", doc.from_warehouse, "warehouse_type")
        if source_warehouse_type != "Transit":
            frappe.throw(_(
                "Source warehouse '{0}' must be a transit warehouse for receipt from transit entries."
            ).format(doc.from_warehouse), title=_("Invalid Source Warehouse"))
    
    # Validate target warehouse (must match the custom field from outgoing entry)
    if doc.to_warehouse and doc.to_warehouse != target_warehouse:
        frappe.throw(_(
            "Target warehouse must be '{0}' as specified in the outgoing stock entry."
        ).format(target_warehouse), title=_("Invalid Target Warehouse"))
    
    # Auto-set target warehouse if not set
    if not doc.to_warehouse:
        doc.to_warehouse = target_warehouse
    
    # Validate items
    for item in doc.get("items", []):
        # Source warehouse validation for items
        if item.s_warehouse:
            source_warehouse_type = frappe.db.get_value("Warehouse", item.s_warehouse, "warehouse_type")
            if source_warehouse_type != "Transit":
                frappe.throw(_(
                    "Row {0}: Source warehouse '{1}' must be a transit warehouse for receipt from transit entries."
                ).format(item.idx, item.s_warehouse), title=_("Invalid Source Warehouse"))
        
        # Target warehouse validation for items
        if item.t_warehouse and item.t_warehouse != target_warehouse:
            frappe.throw(_(
                "Row {0}: Target warehouse must be '{1}' as specified in the outgoing stock entry."
            ).format(item.idx, target_warehouse), title=_("Invalid Target Warehouse"))
        
        # Auto-set target warehouse for items if not set
        if not item.t_warehouse:
            item.t_warehouse = target_warehouse

def validate_new_material_transfer(doc):
    """
    Validate warehouse selection for new Material Transfer entries.
    """
    # Validate source warehouse (cannot be transit type)
    if doc.from_warehouse:
        source_warehouse_type = frappe.db.get_value("Warehouse", doc.from_warehouse, "warehouse_type")
        if source_warehouse_type == "Transit":
            frappe.throw(_(
                "Source warehouse '{0}' cannot be a transit warehouse for new Material Transfer entries."
            ).format(doc.from_warehouse), title=_("Invalid Source Warehouse"))
    
    # Validate target warehouse (must be transit type)
    if doc.to_warehouse:
        target_warehouse_type = frappe.db.get_value("Warehouse", doc.to_warehouse, "warehouse_type")
        if target_warehouse_type != "Transit":
            frappe.throw(_(
                "Target warehouse '{0}' must be a transit warehouse for new Material Transfer entries."
            ).format(doc.to_warehouse), title=_("Invalid Target Warehouse"))
    
    # Validate items
    for item in doc.get("items", []):
        # Source warehouse validation for items
        if item.s_warehouse:
            source_warehouse_type = frappe.db.get_value("Warehouse", item.s_warehouse, "warehouse_type")
            if source_warehouse_type == "Transit":
                frappe.throw(_(
                    "Row {0}: Source warehouse '{1}' cannot be a transit warehouse for new Material Transfer entries."
                ).format(item.idx, item.s_warehouse), title=_("Invalid Source Warehouse"))
        
        # Target warehouse validation for items
        if item.t_warehouse:
            target_warehouse_type = frappe.db.get_value("Warehouse", item.t_warehouse, "warehouse_type")
            if target_warehouse_type != "Transit":
                frappe.throw(_(
                    "Row {0}: Target warehouse '{1}' must be a transit warehouse for new Material Transfer entries."
                ).format(item.idx, item.t_warehouse), title=_("Invalid Target Warehouse")) 