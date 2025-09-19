# Copyright (c) 2025, Sagar Ratan Garg and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from business_needed_solutions.business_needed_solutions.report.stock_ledger_negative_episodes.stock_ledger_negative_episodes import (
    get_stock_ledger_data,
    find_negative_episodes
)

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {
            "label": _("Item Code"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 140
        },
        {
            "label": _("Warehouse"),
            "fieldname": "warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 140
        },
        {
            "label": _("Negative Qty"),
            "fieldname": "negative_qty",
            "fieldtype": "Float",
            "width": 100
        },
        {
            "label": _("Episode Start"),
            "fieldname": "episode_start",
            "fieldtype": "Datetime",
            "width": 150
        },
        {
            "label": _("Episode End"),
            "fieldname": "episode_end",
            "fieldtype": "Datetime",
            "width": 150
        },
        {
            "label": _("BOM Check"),
            "fieldname": "bom_check",
            "fieldtype": "Data",
            "width": 90
        },
        {
            "label": _("BOM Status"),
            "fieldname": "bom_status",
            "fieldtype": "Data",
            "width": 140
        },
        {
            "label": _("Alternative Warehouse"),
            "fieldname": "alternative_warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 140
        },
        {
            "label": _("Suggested Fix"),
            "fieldname": "suggested_fix",
            "fieldtype": "Data",
            "width": 200
        }
    ]

def get_data(filters):
    if not filters:
        filters = {}
    
    # Ensure we have the required date filters
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("Please select From Date and To Date"))
        
    # Get negative episodes from base report
    stock_ledger_data = get_stock_ledger_data(filters)
    
    if not stock_ledger_data:
        return []
        
    episodes = find_negative_episodes(stock_ledger_data)
    
    # Process each episode to add resolution suggestions
    resolution_data = []
    for episode in episodes:
        resolution = analyze_episode(episode)
        if resolution:
            resolution_data.append(resolution)
    
    return resolution_data

def analyze_episode(episode):
    item_code = episode.get("item_code")
    warehouse = episode.get("warehouse")
    min_qty = abs(episode.get("min_balance", 0))
    stock_uom = episode.get("stock_uom")
    
    if not (item_code and warehouse and min_qty and stock_uom):
        return None
    
    try:
        item = frappe.get_doc("Item", item_code)
    except frappe.DoesNotExistError:
        frappe.msgprint(_("Item {0} not found").format(item_code))
        return None
        
    # Convert min_qty to stock UOM if needed
    if stock_uom != item.stock_uom:
        min_qty = convert_to_stock_qty(min_qty, stock_uom, item.stock_uom, item_code)
    
    # Initialize resolution data
    resolution = {
        "item_code": item_code,
        "warehouse": warehouse,
        "negative_qty": min_qty,
        "episode_start": episode.get("episode_start"),  # Changed from start_time to episode_start
        "episode_end": episode.get("episode_end"),      # Changed from end_time to episode_end
        "bom_check": "No",
        "bom_status": "Not Applicable",
        "alternative_warehouse": "",
        "suggested_fix": ""
    }
    
    # Check for active BOM first as preferred solution
    default_bom = get_default_bom(item_code)
    
    if default_bom:
        resolution["bom_check"] = "Yes"
        bom_analysis = analyze_bom_availability(default_bom, min_qty, warehouse)
        resolution["bom_status"] = bom_analysis["status"]
        
        if bom_analysis["can_produce"]:
            resolution["suggested_fix"] = "Produce via BOM"
            return resolution
        elif bom_analysis["partial_qty"] > 0:
            resolution["suggested_fix"] = f"Partial production possible ({flt(bom_analysis['partial_qty'], 2)} {item.stock_uom or frappe.db.get_value('Item', item_code, 'stock_uom')})"
            return resolution
    
    # If BOM not possible or not available, check other options
    if item.is_purchase_item:
        # Check other warehouses first
        alt_warehouse = find_alternative_warehouse(item_code, min_qty, warehouse)
        if alt_warehouse:
            resolution["alternative_warehouse"] = alt_warehouse
            resolution["suggested_fix"] = "Stock transfer"
        else:
            resolution["suggested_fix"] = "Purchase missing"
    else:
        resolution["suggested_fix"] = "Opening stock missing"
    
    # If no clear resolution found
    if not resolution["suggested_fix"]:
        resolution["suggested_fix"] = "Manual reconciliation required"
    
    return resolution

def get_default_bom(item_code):
    """Get default active BOM for an item"""
    bom = frappe.get_all(
        "BOM",
        filters={
            "item": item_code,
            "is_active": 1,
            "is_default": 1
        },
        limit=1
    )
    return bom[0].name if bom else None

def analyze_bom_availability(bom_no, required_qty, warehouse):
    """
    Analyze if BOM items are available in stock.
    All quantities are converted to respective stock UOMs for accurate comparison.
    """
    bom = frappe.get_doc("BOM", bom_no)
    all_available = True
    partial_available = False
    max_possible_qty = float('inf')
    shortage_items = []
    
    # Get item's stock UOM
    item_stock_uom = frappe.db.get_value("Item", bom.item, "stock_uom")
    
    # Convert required_qty to item's stock UOM if different
    if bom.uom != item_stock_uom:
        required_qty = convert_to_stock_qty(required_qty, bom.uom, item_stock_uom, bom.item)
    
    for item in bom.items:
        # Calculate required quantity in item's stock UOM
        required_item_qty = (required_qty * item.stock_qty) / bom.quantity
        
        # Get available quantity in stock UOM
        bin_qty = get_bin_qty(item.item_code, warehouse)
        
        if bin_qty < required_item_qty:
            all_available = False
            shortage_items.append({
                "item_code": item.item_code,
                "required_qty": required_item_qty,
                "available_qty": bin_qty,
                "shortage": required_item_qty - bin_qty
            })
            
            # Calculate maximum possible quantity based on this component
            possible_qty = (bin_qty * bom.quantity) / item.stock_qty
            max_possible_qty = min(max_possible_qty, possible_qty)
        else:
            partial_available = True
    
    status = "All inputs available" if all_available else \
             "Partial production possible" if partial_available and max_possible_qty > 0 else \
             "Shortage list"
    
    return {
        "status": status,
        "can_produce": all_available,
        "partial_qty": max_possible_qty if not all_available and max_possible_qty > 0 else 0,
        "shortages": shortage_items
    }

def convert_to_stock_qty(qty, from_uom, to_uom, item_code):
    """Convert quantity from one UOM to another"""
    if from_uom == to_uom:
        return qty
        
    conversion_factor = frappe.db.get_value(
        "UOM Conversion Detail",
        {"parent": item_code, "uom": from_uom},
        "conversion_factor"
    )
    
    if not conversion_factor:
        frappe.throw(_("UOM Conversion factor not found for item {0} from {1} to {2}").format(
            item_code, from_uom, to_uom
        ))
    
    return flt(qty * conversion_factor)

def get_bin_qty(item_code, warehouse, uom=None):
    """Get actual stock quantity from bin in specified UOM"""
    bin_qty = frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": warehouse},
        "actual_qty"
    ) or 0
    
    if uom:
        item_stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
        if uom != item_stock_uom:
            bin_qty = convert_to_stock_qty(bin_qty, item_stock_uom, uom, item_code)
    
    return flt(bin_qty)

def find_alternative_warehouse(item_code, required_qty, current_warehouse):
    """Find alternative warehouse with sufficient stock"""
    bins = frappe.get_all(
        "Bin",
        filters={
            "item_code": item_code,
            "warehouse": ["!=", current_warehouse],
            "actual_qty": [">=", required_qty]
        },
        fields=["warehouse", "actual_qty"],
        order_by="actual_qty desc",
        limit=1
    )
    return bins[0].warehouse if bins else ""
