"""
Business Needed Solutions - Utility Functions

This module contains utility functions for the BNS app, including:
- Internal purchase receipt creation from delivery notes
- Status updates for internal transfers
- GST validation and billing calculations
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.contacts.doctype.address.address import get_company_address
from erpnext.accounts.doctype.sales_invoice.sales_invoice import update_address, update_taxes
from typing import Optional, Dict, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)


class BNSInternalTransferError(Exception):
    """Custom exception for BNS internal transfer operations."""
    pass


class BNSValidationError(Exception):
    """Custom exception for BNS validation operations."""
    pass


@frappe.whitelist()
def make_bns_internal_purchase_receipt(source_name: str, target_doc: Optional[Dict] = None) -> Dict:
    """
    Create a Purchase Receipt from a Delivery Note for internal customers.
    
    Args:
        source_name (str): Name of the source Delivery Note
        target_doc (Optional[Dict]): Target document for mapping
        
    Returns:
        Dict: Mapped Purchase Receipt document
        
    Raises:
        BNSValidationError: If validation fails
        BNSInternalTransferError: If internal transfer setup fails
    """
    try:
        dn = frappe.get_doc("Delivery Note", source_name)
        
        # Validate delivery note for internal customer
        _validate_internal_delivery_note(dn)
        
        # Get representing company
        represents_company = _get_representing_company(dn.customer)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Delivery Note",
            source_name,
            _get_delivery_note_mapping(),
            target_doc,
            _set_missing_values,
        )
        
        # Update delivery note with reference (this needs to be done after the document is created)
        _update_delivery_note_reference(dn.name, doclist.name)
        
        logger.info(f"Successfully created internal Purchase Receipt from Delivery Note {source_name}")
        return doclist
        
    except Exception as e:
        logger.error(f"Error creating internal Purchase Receipt: {str(e)}")
        raise


def _validate_internal_delivery_note(dn) -> None:
    """Validate that the delivery note is for an internal customer."""
    if not dn.get("is_bns_internal_customer"):
        raise BNSValidationError(_("Delivery Note is not for an internal customer"))


def _get_representing_company(customer: str) -> str:
    """Get the company that the customer represents."""
    represents_company = frappe.db.get_value("Customer", customer, "bns_represents_company")
    if not represents_company:
        raise BNSValidationError(_("No company is assigned to the internal customer"))
    return represents_company


def _get_delivery_note_mapping() -> Dict[str, Any]:
    """Get the mapping configuration for Delivery Note to Purchase Receipt."""
    return {
        "Delivery Note": {
            "doctype": "Purchase Receipt",
            "field_map": {
                "name": "delivery_note",
            },
            "field_no_map": ["set_warehouse", "rejected_warehouse", "cost_center", "project", "location"],
            "validation": {"docstatus": ["=", 1]},
            "postprocess": _update_details,
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
            "postprocess": _update_item,
        },
    }


def _set_missing_values(source, target) -> None:
    """Set missing values for the target Purchase Receipt."""
    target.run_method("set_missing_values")

    # Set up taxes based on the target company's tax template
    if target.get("taxes_and_charges") and not target.get("taxes"):
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        taxes = get_taxes_and_charges("Purchase Taxes and Charges Template", target.taxes_and_charges)
        for tax in taxes:
            target.append("taxes", tax)
            
    if not target.get("items"):
        raise BNSValidationError(_("All items have already been received"))
    
    # Clear document level warehouses and accounting dimensions
    _clear_document_level_fields(target)


def _clear_document_level_fields(target) -> None:
    """Clear warehouse and accounting dimension fields at document level."""
    target.rejected_warehouse = None
    target.set_warehouse = None
    target.cost_center = None
    
    # Clear optional fields if they exist
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)


def _update_details(source_doc, target_doc, source_parent) -> None:
    """Update details for the Purchase Receipt."""
    # Handle case where source_parent might be None (when called as postprocess)
    if source_parent is None:
        # This is being called as a postprocess function, so we need to get the data differently
        # The source_doc is the Delivery Note, and target_doc is the Purchase Receipt
        represents_company = _get_representing_company(source_doc.customer)
        target_doc.company = represents_company
        
        # Find supplier representing the delivery note's company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        target_doc.is_internal_supplier = 1
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Handle addresses
        _update_addresses(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes(target_doc)
    else:
        # This is being called from the main function with proper parameters
        target_doc.company = source_parent.get("represents_company")
        
        # Find supplier representing the delivery note's company
        supplier = _find_internal_supplier(source_parent.company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        target_doc.is_internal_supplier = 1
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Update delivery note with reference
        _update_delivery_note_reference(source_doc.name, target_doc.name)
        
        # Handle addresses
        _update_addresses(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes(target_doc)


def _find_internal_supplier(company: str) -> str:
    """Find supplier that represents the given company."""
    supplier = frappe.get_all(
        "Supplier",
        filters={
            "is_bns_internal_supplier": 1,
            "bns_represents_company": company
        },
        limit=1
    )
    
    if not supplier:
        raise BNSInternalTransferError(_("No supplier found representing the company {0}").format(company))
        
    return supplier[0].name


def _update_delivery_note_reference(dn_name: str, pr_name: str) -> None:
    """Update delivery note with purchase receipt reference and status."""
    frappe.db.set_value("Delivery Note", dn_name, {
        "bns_inter_company_reference": pr_name,
        "status": "BNS Internally Transferred",
        "per_billed": 100
    })


def _update_addresses(target_doc, source_doc) -> None:
    """Update addresses for internal transfer."""
    # For Purchase Receipt, don't swap shipping/dispatch addresses
    if target_doc.doctype == "Purchase Receipt":
        # Company address becomes supplier address
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        # Keep shipping address as is
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.shipping_address_name)
        # Keep dispatch address as is
        if source_doc.dispatch_address_name:
            update_address(target_doc, "dispatch_address", "dispatch_address_display", source_doc.dispatch_address_name)
        # Customer address becomes billing address
        update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
    else:
        # For other doctypes, use the original swapping logic
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.customer_address)
        update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)


def _update_taxes(target_doc) -> None:
    """Update taxes for the purchase receipt."""
    update_taxes(
        target_doc,
        party=target_doc.supplier,
        party_type="Supplier",
        company=target_doc.company,
        doctype=target_doc.doctype,
        party_address=target_doc.supplier_address,
        company_address=target_doc.shipping_address,
    )


def _update_item(source, target, source_parent) -> None:
    """Update item details for the purchase receipt item."""
    target.received_qty = 0
    target.qty = source.qty
    target.stock_qty = source.stock_qty
    target.purchase_order = source.purchase_order
    target.purchase_order_item = source.purchase_order_item
    
    # Clear accounting fields to let system auto-populate
    _clear_item_level_fields(target)
    
    if source.get("use_serial_batch_fields"):
        target.set("use_serial_batch_fields", 1)


def _clear_item_level_fields(target) -> None:
    """Clear accounting and warehouse fields at item level."""
    # Clear accounting fields
    target.expense_account = None
    target.cost_center = None
    
    # Clear warehouse fields
    target.warehouse = None
    target.rejected_warehouse = None
    
    # Clear other accounting dimensions
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)





def update_delivery_note_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Delivery Note to "BNS Internally Transferred" 
    when submitted for a BNS internal customer.
    
    Args:
        doc: The Delivery Note document
        method (Optional[str]): The method being called
    """
    if not _should_update_internal_status(doc, "is_bns_internal_customer"):
        return

    try:
        per_billed = _calculate_per_billed(doc)
        _update_document_status(doc, "Delivery Note", per_billed)
        logger.info(f"Updated Delivery Note {doc.name} status to BNS Internally Transferred")
        
    except Exception as e:
        logger.error(f"Error updating Delivery Note status: {str(e)}")
        raise


def update_purchase_receipt_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Purchase Receipt to "BNS Internally Transferred" 
    when submitted for a BNS internal supplier.
    
    Args:
        doc: The Purchase Receipt document
        method (Optional[str]): The method being called
    """
    if not _should_update_internal_status(doc, "is_internal_supplier", check_reference=True):
        return

    try:
        per_billed = _calculate_per_billed(doc)
        _update_document_status(doc, "Purchase Receipt", per_billed)
        logger.info(f"Updated Purchase Receipt {doc.name} status to BNS Internally Transferred")
        
    except Exception as e:
        logger.error(f"Error updating Purchase Receipt status: {str(e)}")
        raise


def _should_update_internal_status(doc, field_name: str, check_reference: bool = False) -> bool:
    """Check if the document status should be updated for internal transfers."""
    if doc.docstatus != 1:
        return False
        
    if check_reference:
        return bool(doc.bns_inter_company_reference or getattr(doc, field_name, False))
    
    return bool(getattr(doc, field_name, False))


def _calculate_per_billed(doc) -> int:
    """Calculate the per_billed value based on GSTIN comparison."""
    per_billed = 100
    billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
    company_gstin = getattr(doc, 'company_gstin', None)
    
    if billing_address_gstin is not None and company_gstin is not None:
        if billing_address_gstin != company_gstin:
            per_billed = 0
            
    return per_billed


def _update_document_status(doc, doctype: str, per_billed: int) -> None:
    """Update document status and per_billed value."""
    frappe.db.set_value(doctype, doc.name, {
        "status": "BNS Internally Transferred",
        "per_billed": per_billed
    })
    frappe.clear_cache(doctype=doctype) 