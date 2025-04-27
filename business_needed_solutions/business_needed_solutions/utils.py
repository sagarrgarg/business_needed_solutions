import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.contacts.doctype.address.address import get_company_address
from erpnext.accounts.doctype.sales_invoice.sales_invoice import update_address, update_taxes

@frappe.whitelist()
def make_bns_internal_purchase_receipt(source_name, target_doc=None):
    """
    Create a Purchase Receipt from a Delivery Note for internal customers
    """
    dn = frappe.get_doc("Delivery Note", source_name)
    
    # Check if the delivery note is for an internal customer
    if not dn.get("is_bns_internal_customer"):
        frappe.throw(_("Delivery Note is not for an internal customer"))
    
    # Get the company that the customer represents
    represents_company = frappe.db.get_value("Customer", dn.customer, "bns_represents_company")
    if not represents_company:
        frappe.throw(_("No company is assigned to the internal customer"))

    def set_missing_values(source, target):
        target.run_method("set_missing_values")

        # Set up taxes based on the target company's tax template
        if target.get("taxes_and_charges") and not target.get("taxes"):
            from erpnext.controllers.accounts_controller import get_taxes_and_charges
            taxes = get_taxes_and_charges("Purchase Taxes and Charges Template", target.taxes_and_charges)
            for tax in taxes:
                target.append("taxes", tax)
                
        if not target.get("items"):
            frappe.throw(_("All items have already been received"))
        
        # Clear doc level warehouses
        target.rejected_warehouse = None
        target.set_warehouse = None
        
        # Clear accounting dimensions at document level
        target.cost_center = None
        if hasattr(target, 'location'):
            target.location = None
        if hasattr(target, 'project'):
            target.project = None

    def update_details(source_doc, target_doc, source_parent):
        target_doc.company = represents_company
        
        # Find supplier that represents the delivery note's company
        supplier = frappe.get_all(
            "Supplier",
            filters={
                "is_bns_internal_supplier": 1,
                "bns_represents_company": dn.company
            },
            limit=1
        )
        
        if not supplier:
            frappe.throw(_("No supplier found representing the company {0}").format(dn.company))
            
        target_doc.supplier = supplier[0].name
        target_doc.buying_price_list = source_doc.selling_price_list
        target_doc.is_internal_supplier = 1
        target_doc.bns_inter_company_reference = source_doc.name
        
        # After creating the Purchase Receipt, update the Delivery Note with a reference to it
        frappe.db.set_value("Delivery Note", source_doc.name, "bns_inter_company_reference", target_doc.name)
        
        # Update the status and per_billed for the Delivery Note
        frappe.db.set_value("Delivery Note", source_doc.name, {
            "status": "BNS Internally Transferred",
            "per_billed": 100
        })
        
        # Handle addresses - Swap addresses as per internal transfer logic:
        # Customer address in Delivery Note becomes Company address in Purchase Receipt
        # Company address in Delivery Note becomes Supplier address in Purchase Receipt
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        update_address(
            target_doc, "shipping_address", "shipping_address_display", source_doc.customer_address
        )
        update_address(
            target_doc, "billing_address", "billing_address_display", source_doc.customer_address
        )
        
        # Handle taxes
        update_taxes(
            target_doc,
            party=target_doc.supplier,
            party_type="Supplier",
            company=target_doc.company,
            doctype=target_doc.doctype,
            party_address=target_doc.supplier_address,
            company_address=target_doc.shipping_address,
        )

    def update_item(source, target, source_parent):
        target.received_qty = 0
        target.qty = source.qty
        target.stock_qty = source.stock_qty
        target.purchase_order = source.purchase_order
        target.purchase_order_item = source.purchase_order_item
        
        # Clear accounting fields to let system auto-populate
        target.expense_account = None
        target.cost_center = None
        
        # Clear warehouse field at item level
        target.warehouse = None
        target.rejected_warehouse = None
        
        # Clear other accounting dimensions
        if hasattr(target, 'location'):
            target.location = None
        if hasattr(target, 'project'):
            target.project = None
        
        if source.get("use_serial_batch_fields"):
            target.set("use_serial_batch_fields", 1)

    # Map fields from Delivery Note to Purchase Receipt
    doclist = get_mapped_doc(
        "Delivery Note",
        source_name,
        {
            "Delivery Note": {
                "doctype": "Purchase Receipt",
                "field_map": {
                    "name": "delivery_note",
                },
                "field_no_map": ["set_warehouse", "rejected_warehouse", "cost_center", "project", "location"],
                "validation": {"docstatus": ["=", 1]},
                "postprocess": update_details,
            },
            "Delivery Note Item": {
                "doctype": "Purchase Receipt Item",
                "field_map": {
                    "name": "delivery_note_item",
                    "target_warehouse": "from_warehouse",
                    "serial_no": "serial_no",
                    "batch_no": "batch_no",
                    "purchase_order": "purchase_order",
                    "purchase_order_item": "purchase_order_item",
                },
                "field_no_map": ["warehouse", "rejected_warehouse", "expense_account", "cost_center", "project", "location"],
                "postprocess": update_item,
            },
        },
        target_doc,
        set_missing_values,
    )

    return doclist

def update_delivery_note_status_for_bns_internal(doc, method=None):
    """
    Update the status of a Delivery Note to "BNS Internally Transferred" 
    when submitted for a BNS internal customer
    """
    if not doc.is_bns_internal_customer or doc.docstatus != 1:
        return
    
    # Update the status to "BNS Internally Transferred"
    frappe.db.set_value("Delivery Note", doc.name, "status", "BNS Internally Transferred")
    
    # Set per_billed to 100% to indicate it's fully billed
    frappe.db.set_value("Delivery Note", doc.name, "per_billed", 100)
    
    # Clear the doctype cache to reflect the changes
    frappe.clear_cache(doctype="Delivery Note")

def update_purchase_receipt_status_for_bns_internal(doc, method=None):
    """
    Update the status of a Purchase Receipt to "BNS Internally Transferred" 
    when submitted for a BNS internal supplier
    """
    # Check if this has a BNS inter-company reference or is an internal supplier
    if doc.docstatus != 1 or (not doc.bns_inter_company_reference and not doc.is_internal_supplier):
        return
    
    # Update the status to "BNS Internally Transferred"
    frappe.db.set_value("Purchase Receipt", doc.name, "status", "BNS Internally Transferred")
    
    # Set per_billed to 100% to indicate it's fully billed
    frappe.db.set_value("Purchase Receipt", doc.name, "per_billed", 100)
    
    # Clear the doctype cache to reflect the changes
    frappe.clear_cache(doctype="Purchase Receipt") 