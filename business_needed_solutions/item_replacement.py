import frappe
from frappe import _

# Import original methods to wrap them
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note as original_make_delivery_note
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt as original_make_purchase_receipt
from erpnext.stock.doctype.material_request.material_request import make_purchase_order as original_make_purchase_order

def get_replacement_item(old_item_code):
    """
    Returns the mapped new item code if replacement is enabled and mapping exists.
    Returns None otherwise.
    """
    settings = frappe.get_single("Item Replacement Settings")
    if not settings.enable_item_replacement:
        return None
        
    for row in settings.get("replacements", []):
        if row.old_item == old_item_code and row.enabled:
            return row.new_item
            
    return None

def swap_items_in_mapped_doc(doc, source_ref_field):
    """
    Iterates over target doc items, looks up the source item, and swaps it if configured.
    source_ref_field is the fieldname where the source row ID is stored (e.g. 'so_detail', 'po_detail')
    """
    for item in doc.get("items"):
        source_id = item.get(source_ref_field)
        if not source_id:
            continue
            
        replacement = get_replacement_item(item.item_code)
        if replacement:
            # We found a valid replacement mapping!
            item.item_code = replacement
            # Fetch new item details to pre-fill the UI properly
            new_item_details = frappe.db.get_value("Item", replacement, 
                ["item_name", "description", "stock_uom"], as_dict=True)
            if new_item_details:
                item.item_name = new_item_details.item_name
                item.description = new_item_details.description
                item.stock_uom = new_item_details.stock_uom
                item.uom = new_item_details.stock_uom

@frappe.whitelist()
def make_delivery_note(*args, **kwargs):
    # Call original method
    doc = original_make_delivery_note(*args, **kwargs)
    # Swap items
    swap_items_in_mapped_doc(doc, "so_detail")
    return doc

@frappe.whitelist()
def make_purchase_receipt(*args, **kwargs):
    doc = original_make_purchase_receipt(*args, **kwargs)
    swap_items_in_mapped_doc(doc, "po_detail")
    return doc

@frappe.whitelist()
def make_purchase_order(*args, **kwargs):
    doc = original_make_purchase_order(*args, **kwargs)
    swap_items_in_mapped_doc(doc, "material_request_item")
    return doc

def validate_item_replacement(doc, method):
    """
    Hooked to doc_events 'validate' for Delivery Note, Purchase Receipt, and Purchase Order.
    Ensures that if the item_code is different from the source document, it is a strictly allowed mapping.
    """
    if doc.doctype == "Delivery Note":
        source_dt = "Sales Order Item"
        ref_field = "so_detail"
    elif doc.doctype == "Purchase Receipt":
        source_dt = "Purchase Order Item"
        ref_field = "po_detail"
    elif doc.doctype == "Purchase Order":
        source_dt = "Material Request Item"
        ref_field = "material_request_item"
    else:
        return

    settings = frappe.get_single("Item Replacement Settings")
    
    for item in doc.get("items"):
        source_id = item.get(ref_field)
        if not source_id:
            continue
            
        # Get source item code
        source_item_code = frappe.db.get_value(source_dt, source_id, "item_code")
        if not source_item_code:
            continue
            
        if item.item_code != source_item_code:
            # The item code has been swapped. We must validate it!
            if not settings.enable_item_replacement:
                frappe.throw(_("Item replacement is not allowed because Item Replacement Mode is disabled. Source Item: {0}, Target Item: {1}").format(
                    frappe.bold(source_item_code), frappe.bold(item.item_code)
                ))
            
            allowed_replacement = get_replacement_item(source_item_code)
            if item.item_code != allowed_replacement:
                frappe.throw(_("Item replacement is not allowed.<br><br>Source Item: {0}<br>Selected Item: {1}<br><br>No active replacement mapping exists for this item.").format(
                    frappe.bold(source_item_code), frappe.bold(item.item_code)
                ))
