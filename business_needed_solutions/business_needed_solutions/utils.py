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
    
    # Clear tax template and taxes
    target.taxes_and_charges = None
    target.taxes = []
            
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
    """
    Update details for the Purchase Receipt from Delivery Note.
    
    TRANSFER UNDER SAME GSTIN:
    - is_bns_internal_customer = 1
    - status = "BNS Internally Transferred" (set on submit)
    - supplier_delivery_note = DN name
    - per_billed = 100% (set on submit)
    """
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
        
        # Set supplier_delivery_note = DN name (TRANSFER UNDER SAME GSTIN)
        target_doc.supplier_delivery_note = source_doc.name
        
        # Set is_bns_internal_customer = 1 (TRANSFER UNDER SAME GSTIN)
        target_doc.is_bns_internal_customer = 1
        
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
        
        # Set supplier_delivery_note = DN name (TRANSFER UNDER SAME GSTIN)
        target_doc.supplier_delivery_note = source_doc.name
        
        # Set is_bns_internal_customer = 1 (TRANSFER UNDER SAME GSTIN)
        target_doc.is_bns_internal_customer = 1
        
        # Update delivery note with reference
        _update_delivery_note_reference(source_doc.name, target_doc.name)
        
        # Handle addresses
        _update_addresses(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes(target_doc)


def _find_internal_supplier(company: str) -> str:
    """Find supplier that represents the given company."""
    # First try to find supplier with bns_represents_company
    supplier = frappe.get_all(
        "Supplier",
        filters={
            "is_bns_internal_supplier": 1,
            "bns_represents_company": company
        },
        limit=1
    )
    
    # If not found, try with represents_company as fallback
    if not supplier:
        supplier = frappe.get_all(
            "Supplier",
            filters={
                "is_bns_internal_supplier": 1,
                "represents_company": company
            },
            limit=1
        )
    
    if not supplier:
        raise BNSInternalTransferError(_("No supplier found for Inter Company Transactions which represents company {0}").format(company))
        
    return supplier[0].name


def _update_delivery_note_reference(dn_name: str, pr_name: str) -> None:
    """Update delivery note with purchase receipt reference."""
    # Do NOT update status here - it's handled by on_submit hook
    frappe.db.set_value("Delivery Note", dn_name, {
        "bns_inter_company_reference": pr_name
    })


def _update_addresses(target_doc, source_doc) -> None:
    """Update addresses for internal transfer."""
    # For Purchase Receipt, don't swap shipping/dispatch addresses
    if target_doc.doctype == "Purchase Receipt":
        # Company address becomes supplier address
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        # Keep shipping address as is
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.shipping_address_name)
        # Customer address becomes billing address
        update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
        # Explicitly clear dispatch address and templates for BNS internal transfers
        target_doc.dispatch_address = None
        target_doc.dispatch_address_name = None
        target_doc.dispatch_address_display = None
        target_doc.dispatch_address_template = None
        target_doc.shipping_address_template = None
    else:
        # For other doctypes, use the original swapping logic
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.customer_address)
        update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
        # Explicitly clear dispatch address and templates for BNS internal transfers
        target_doc.dispatch_address = None
        target_doc.dispatch_address_name = None
        target_doc.dispatch_address_display = None
        target_doc.dispatch_address_template = None
        target_doc.shipping_address_template = None


def _update_taxes(target_doc) -> None:
    """Update taxes for the purchase receipt."""
    # Clear tax template and taxes - we don't want automatic tax assignment
    target_doc.taxes_and_charges = None
    target_doc.taxes = []


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
    Update the status of a Delivery Note based on GSTIN match.
    
    TRANSFER UNDER SAME GSTIN:
    - is_bns_internal_customer = 1
    - status = "BNS Internally Transferred"
    - per_billed = 100%
    
    TRANSFER UNDER DIFFERENT GSTIN:
    - is_bns_internal_customer = 0
    - status = "To Bill"
    
    Args:
        doc: The Delivery Note document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return
    
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return
    
    # Check if customer is BNS internal
    is_bns_internal = doc.get("is_bns_internal_customer") or False
    if not is_bns_internal:
        customer_internal = frappe.db.get_value("Customer", doc.customer, "is_bns_internal_customer")
        if not customer_internal:
            return
    
    try:
        # Check GSTIN match
        billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
        company_gstin = getattr(doc, 'company_gstin', None)
        
        if billing_address_gstin is not None and company_gstin is not None:
            if billing_address_gstin == company_gstin:
                # SAME GSTIN - Set as internal transfer
                per_billed = 100
                doc.db_set("status", "BNS Internally Transferred", update_modified=False)
                doc.db_set("per_billed", per_billed, update_modified=False)
                doc.db_set("is_bns_internal_customer", 1, update_modified=False)
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Updated Delivery Note {doc.name} status to BNS Internally Transferred (same GSTIN)")
            else:
                # DIFFERENT GSTIN - Set as To Bill
                doc.db_set("status", "To Bill", update_modified=False)
                doc.db_set("is_bns_internal_customer", 0, update_modified=False)
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Updated Delivery Note {doc.name} status to To Bill (different GSTIN)")
        
    except Exception as e:
        logger.error(f"Error updating Delivery Note status: {str(e)}")
        raise


def update_purchase_receipt_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Purchase Receipt based on is_bns_internal_customer.
    
    TRANSFER UNDER SAME GSTIN (from DN):
    - is_bns_internal_customer = 1
    - status = "BNS Internally Transferred"
    - per_billed = 100%
    
    TRANSFER UNDER DIFFERENT GSTIN (from SI):
    - is_bns_internal_customer = 0
    - status = "To Bill"
    
    Args:
        doc: The Purchase Receipt document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return
    
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return

    try:
        # Check if PR is from DN (same GSTIN) or SI (different GSTIN)
        # Check supplier_delivery_note to determine source
        is_bns_internal = doc.get("is_bns_internal_customer") or False
        
        # If supplier_delivery_note exists, check if it's a DN or SI
        if doc.supplier_delivery_note:
            # Check if supplier_delivery_note is a DN
            dn_exists = frappe.db.exists("Delivery Note", doc.supplier_delivery_note)
            if dn_exists:
                # From DN - same GSTIN
                is_bns_internal = True
                # Ensure represents_company is set
                dn_customer = frappe.db.get_value("Delivery Note", doc.supplier_delivery_note, "customer")
                if dn_customer:
                    represents_company = frappe.db.get_value("Customer", dn_customer, "bns_represents_company")
                    if represents_company:
                        doc.represents_company = represents_company
            else:
                # Check if it's a Sales Invoice
                si_exists = frappe.db.exists("Sales Invoice", doc.supplier_delivery_note)
                if si_exists:
                    # From SI - different GSTIN
                    is_bns_internal = False
                    # Ensure represents_company is set from SI's customer
                    si_customer = frappe.db.get_value("Sales Invoice", doc.supplier_delivery_note, "customer")
                    if si_customer:
                        represents_company = frappe.db.get_value("Customer", si_customer, "bns_represents_company")
                        if represents_company:
                            doc.represents_company = represents_company
        
        # Update is_bns_internal_customer field
        if is_bns_internal != doc.get("is_bns_internal_customer"):
            doc.is_bns_internal_customer = is_bns_internal
        
        if is_bns_internal:
            # TRANSFER UNDER SAME GSTIN - from DN
            per_billed = 100
            doc.db_set("status", "BNS Internally Transferred", update_modified=False)
            doc.db_set("per_billed", per_billed, update_modified=False)
            doc.db_set("is_bns_internal_customer", 1, update_modified=False)
            if doc.represents_company:
                doc.db_set("represents_company", doc.represents_company, update_modified=False)
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to BNS Internally Transferred (from DN)")
        else:
            # TRANSFER UNDER DIFFERENT GSTIN - from SI
            # Status should remain "To Bill" (default), but ensure it's set
            if doc.status != "To Bill":
                doc.db_set("status", "To Bill", update_modified=False)
            doc.db_set("is_bns_internal_customer", 0, update_modified=False)
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to To Bill (from SI)")
        
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
    update_fields = {
        "status": "BNS Internally Transferred"
    }
    
    # Only set per_billed for doctypes that have this field (Delivery Note, Purchase Receipt)
    if doctype in ["Delivery Note", "Purchase Receipt"]:
        update_fields["per_billed"] = per_billed
    
    frappe.db.set_value(doctype, doc.name, update_fields)
    frappe.clear_cache(doctype=doctype)


@frappe.whitelist()
def make_bns_internal_purchase_invoice(source_name: str, target_doc: Optional[Dict] = None) -> Dict:
    """
    Create a Purchase Invoice from a Sales Invoice for internal customers when GST differs.
    
    Args:
        source_name (str): Name of the source Sales Invoice
        target_doc (Optional[Dict]): Target document for mapping
        
    Returns:
        Dict: Mapped Purchase Invoice document
        
    Raises:
        BNSValidationError: If validation fails
        BNSInternalTransferError: If internal transfer setup fails
    """
    try:
        si = frappe.get_doc("Sales Invoice", source_name)
        
        # Validate sales invoice for internal customer
        _validate_internal_sales_invoice(si)
        
        # Get representing company
        represents_company = _get_representing_company_from_customer(si.customer)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Sales Invoice",
            source_name,
            _get_sales_invoice_mapping(),
            target_doc,
            _set_missing_values_pi,
        )
        
        # Update sales invoice with reference (this needs to be done after the document is created)
        _update_sales_invoice_reference(si.name, doclist.name)
        
        logger.info(f"Successfully created internal Purchase Invoice from Sales Invoice {source_name}")
        return doclist
        
    except Exception as e:
        logger.error(f"Error creating internal Purchase Invoice: {str(e)}")
        raise


def _validate_internal_sales_invoice(si) -> None:
    """Validate that the sales invoice is for an internal customer with different GST."""
    # Check if customer is BNS internal (only check is_bns_internal_customer)
    is_bns_internal = si.get("is_bns_internal_customer") or False
    if not is_bns_internal:
        # Check customer's is_bns_internal_customer field
        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Sales Invoice is not for a BNS internal customer"))
    
    # Validate GST mismatch condition
    billing_address_gstin = getattr(si, 'billing_address_gstin', None)
    company_gstin = getattr(si, 'company_gstin', None)
    
    if billing_address_gstin is None or company_gstin is None:
        raise BNSValidationError(_("GSTIN information is missing. Cannot create internal Purchase Invoice."))
    
    if billing_address_gstin == company_gstin:
        raise BNSValidationError(_("GSTINs are the same. Use Delivery Note/Purchase Receipt flow instead."))


def _get_representing_company_from_customer(customer: str) -> str:
    """Get the company that the customer represents."""
    represents_company = frappe.db.get_value("Customer", customer, "bns_represents_company")
    if not represents_company:
        raise BNSValidationError(_("No company is assigned to the internal customer"))
    return represents_company


def _get_sales_invoice_mapping() -> Dict[str, Any]:
    """Get the mapping configuration for Sales Invoice to Purchase Invoice."""
    mapping = {
        "Sales Invoice": {
            "doctype": "Purchase Invoice",
            "field_map": {},
            "field_no_map": [
                "set_warehouse", "cost_center", "project", "location", "bill_no", "bill_date",
                "dispatch_address", "dispatch_address_name", "dispatch_address_display", 
                "dispatch_address_template", "shipping_address_template"
            ],
            "validation": {"docstatus": ["=", 1]},
            "postprocess": _update_details_pi,
        },
        "Sales Invoice Item": {
            "doctype": "Purchase Invoice Item",
            "field_map": {
                "name": "sales_invoice_item",
            },
            "field_no_map": ["expense_account", "cost_center", "project", "location"],
            "postprocess": _update_item_pi,
        },
    }
    
    # Add warehouse, serial_no, batch_no mapping if update_stock is enabled
    # Note: We'll check this in postprocess, but prepare the mapping structure
    return mapping


def _set_missing_values_pi(source, target) -> None:
    """Set missing values for the target Purchase Invoice."""
    target.run_method("set_missing_values")
    
    # Clear tax template and taxes
    target.taxes_and_charges = None
    target.taxes = []
            
    if not target.get("items"):
        raise BNSValidationError(_("All items have already been received"))
    
    # Clear document level warehouses and accounting dimensions
    _clear_document_level_fields_pi(target)


def _clear_document_level_fields_pi(target) -> None:
    """Clear warehouse and accounting dimension fields at document level."""
    target.set_warehouse = None
    target.cost_center = None
    
    # Clear optional fields if they exist
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)


def _update_details_pi(source_doc, target_doc, source_parent) -> None:
    """
    Update details for the Purchase Invoice from Sales Invoice.
    
    TRANSFER UNDER DIFFERENT GSTIN:
    - is_bns_internal_supplier = 1
    - supplier_invoice_number (bill_no) = SI name
    """
    # Handle case where source_parent might be None (when called as postprocess)
    if source_parent is None:
        # This is being called as a postprocess function, so we need to get the data differently
        # The source_doc is the Sales Invoice, and target_doc is the Purchase Invoice
        represents_company = _get_representing_company_from_customer(source_doc.customer)
        target_doc.company = represents_company
        
        # Find supplier representing the sales invoice's company
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set is_bns_internal_supplier for BNS internal transfers
        # Use bns_inter_company_reference instead of inter_company_invoice_reference to avoid ERPNext validation
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
        # Set supplier_invoice_number (bill_no) = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.bill_no = source_doc.name
        
        # Handle addresses
        _update_addresses_pi(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes_pi(target_doc)
    else:
        # This is being called from the main function with proper parameters
        target_doc.company = source_parent.get("represents_company")
        
        # Find supplier representing the sales invoice's company
        supplier = _find_internal_supplier(source_parent.company)
        target_doc.supplier = supplier
        
        # Set internal transfer fields
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set is_bns_internal_supplier for BNS internal transfers
        # Use bns_inter_company_reference instead of inter_company_invoice_reference to avoid ERPNext validation
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
        # Set supplier_invoice_number (bill_no) = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.bill_no = source_doc.name
        
        # Update sales invoice with reference
        _update_sales_invoice_reference(source_doc.name, target_doc.name)
        
        # Handle addresses
        _update_addresses_pi(target_doc, source_doc)
        
        # Handle taxes
        _update_taxes_pi(target_doc)


def _update_addresses_pi(target_doc, source_doc) -> None:
    """Update addresses for internal transfer Purchase Invoice."""
    # Company address becomes supplier address
    update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
    # Customer address becomes billing address
    update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
    # Shipping address
    if source_doc.shipping_address_name:
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.shipping_address_name)
    
    # Explicitly clear dispatch address and templates for BNS internal transfers
    target_doc.dispatch_address = None
    target_doc.dispatch_address_name = None
    target_doc.dispatch_address_display = None
    target_doc.dispatch_address_template = None
    target_doc.shipping_address_template = None


def _update_taxes_pi(target_doc) -> None:
    """Update taxes for the purchase invoice."""
    # Clear tax template and taxes - we don't want automatic tax assignment
    target_doc.taxes_and_charges = None
    target_doc.taxes = []


def _update_item_pi(source, target, source_parent) -> None:
    """Update item details for the purchase invoice item."""
    target.qty = source.qty
    target.stock_qty = source.stock_qty if hasattr(source, 'stock_qty') else source.qty
    
    # Map serial_no and batch_no if they exist (for stock items)
    if source.get("serial_no"):
        target.serial_no = source.serial_no
    if source.get("batch_no"):
        target.batch_no = source.batch_no
    
    # Clear accounting fields to let system auto-populate
    _clear_item_level_fields_pi(target)
    
    if source.get("use_serial_batch_fields"):
        target.set("use_serial_batch_fields", 1)


def _clear_item_level_fields_pi(target) -> None:
    """Clear accounting and warehouse fields at item level."""
    # Clear accounting fields
    target.expense_account = None
    target.cost_center = None
    
    # Clear warehouse fields
    target.warehouse = None
    
    # Clear other accounting dimensions
    for field in ['location', 'project']:
        if hasattr(target, field):
            setattr(target, field, None)


def _update_sales_invoice_reference(si_name: str, pi_name: str) -> None:
    """Update sales invoice with purchase invoice reference."""
    # Do NOT update status here - it's handled by on_submit hook
    frappe.db.set_value("Sales Invoice", si_name, {
        "bns_inter_company_reference": pi_name
    })


@frappe.whitelist()
def make_bns_internal_purchase_receipt_from_si(source_name: str, target_doc: Optional[Dict] = None) -> Dict:
    """
    Create a Purchase Receipt from a Sales Invoice for internal customers when update_stock is enabled.
    
    Args:
        source_name (str): Name of the source Sales Invoice
        target_doc (Optional[Dict]): Target document for mapping
        
    Returns:
        Dict: Mapped Purchase Receipt document
        
    Raises:
        BNSValidationError: If validation fails
        BNSInternalTransferError: If internal transfer setup fails
    """
    try:
        si = frappe.get_doc("Sales Invoice", source_name)
        
        # Check if SI is made from Delivery Note (check items for delivery_note reference)
        has_dn_reference = False
        if si.items:
            has_dn_reference = any(item.get("delivery_note") for item in si.items if item.get("delivery_note"))
        
        # Validate sales invoice for internal customer
        # Only require update_stock if SI is NOT made from DN
        if not has_dn_reference and not si.get("update_stock"):
            raise BNSValidationError(_("Sales Invoice must have 'Update Stock' enabled to create Purchase Receipt, or must be created from a Delivery Note"))
        
        _validate_internal_sales_invoice(si)
        
        # Get representing company
        represents_company = _get_representing_company_from_customer(si.customer)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Sales Invoice",
            source_name,
            _get_sales_invoice_to_pr_mapping(),
            target_doc,
            _set_missing_values_pr_from_si,
        )
        
        # Update sales invoice with PR reference
        _update_sales_invoice_pr_reference(si.name, doclist.name)
        
        logger.info(f"Successfully created internal Purchase Receipt from Sales Invoice {source_name}")
        return doclist
        
    except Exception as e:
        logger.error(f"Error creating internal Purchase Receipt from Sales Invoice: {str(e)}")
        raise


def _get_sales_invoice_to_pr_mapping() -> Dict[str, Any]:
    """Get the mapping configuration for Sales Invoice to Purchase Receipt."""
    return {
        "Sales Invoice": {
            "doctype": "Purchase Receipt",
            "field_map": {},
            "field_no_map": [
                "set_warehouse", "rejected_warehouse", "cost_center", "project", "location",
                "dispatch_address", "dispatch_address_name", "dispatch_address_display", 
                "dispatch_address_template", "shipping_address_template"
            ],
            "validation": {"docstatus": ["=", 1]},
            "postprocess": _update_details_pr_from_si,
        },
        "Sales Invoice Item": {
            "doctype": "Purchase Receipt Item",
            "field_map": {
                "warehouse": "from_warehouse",
                "serial_no": "serial_no",
                "batch_no": "batch_no",
            },
            "field_no_map": ["warehouse", "rejected_warehouse", "expense_account", "cost_center", "project", "location"],
            "postprocess": _update_item_pr_from_si,
        },
    }


def _set_missing_values_pr_from_si(source, target) -> None:
    """Set missing values for the target Purchase Receipt from Sales Invoice."""
    target.run_method("set_missing_values")
    
    # Clear tax template and taxes
    target.taxes_and_charges = None
    target.taxes = []
            
    if not target.get("items"):
        raise BNSValidationError(_("All items have already been received"))
    
    # Clear document level warehouses and accounting dimensions
    _clear_document_level_fields(target)


def _update_details_pr_from_si(source_doc, target_doc, source_parent) -> None:
    """
    Update details for the Purchase Receipt from Sales Invoice.
    
    TRANSFER UNDER DIFFERENT GSTIN:
    - is_bns_internal_customer = 0
    - status = "To Bill" (set on submit)
    - supplier_delivery_note = SI name
    """
    if source_parent is None:
        represents_company = _get_representing_company_from_customer(source_doc.customer)
        target_doc.company = represents_company
        
        supplier = _find_internal_supplier(represents_company)
        target_doc.supplier = supplier
        
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set bns_inter_company_reference for BNS internal transfers
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set supplier_delivery_note = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.supplier_delivery_note = source_doc.name
        
        # Set is_bns_internal_customer = 0 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_customer = 0
        
        _update_addresses(target_doc, source_doc)
        _update_taxes(target_doc)
    else:
        target_doc.company = source_parent.get("represents_company")
        supplier = _find_internal_supplier(source_parent.company)
        target_doc.supplier = supplier
        
        target_doc.buying_price_list = source_doc.selling_price_list
        # Do NOT set is_internal_supplier - only set bns_inter_company_reference for BNS internal transfers
        target_doc.bns_inter_company_reference = source_doc.name
        
        # Set supplier_delivery_note = SI name (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.supplier_delivery_note = source_doc.name
        
        # Set is_bns_internal_customer = 0 (TRANSFER UNDER DIFFERENT GSTIN)
        target_doc.is_bns_internal_customer = 0
        
        _update_sales_invoice_pr_reference(source_doc.name, target_doc.name)
        _update_addresses(target_doc, source_doc)
        _update_taxes(target_doc)


def _update_item_pr_from_si(source, target, source_parent) -> None:
    """Update item details for the purchase receipt item from sales invoice item."""
    target.received_qty = 0
    target.qty = source.qty
    target.stock_qty = source.stock_qty if hasattr(source, 'stock_qty') else source.qty
    
    _clear_item_level_fields(target)
    
    if source.get("use_serial_batch_fields"):
        target.set("use_serial_batch_fields", 1)


def _update_sales_invoice_pr_reference(si_name: str, pr_name: str) -> None:
    """Update sales invoice with purchase receipt reference."""
    # Note: Sales Invoice doesn't have a direct PR reference field like DN does
    # Do NOT update status here - it's handled by on_submit hook
    # Status will be updated automatically when SI is submitted
    pass


def update_sales_invoice_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Sales Invoice to "BNS Internally Transferred" 
    when submitted for a BNS internal customer with different GST.
    
    Args:
        doc: The Sales Invoice document
        method (Optional[str]): The method being called
    """
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return
    
    # Ensure is_bns_internal_customer is set from Customer if not already set
    if not doc.get("is_bns_internal_customer") and doc.customer:
        customer_internal = frappe.db.get_value("Customer", doc.customer, "is_bns_internal_customer")
        if customer_internal:
            doc.set("is_bns_internal_customer", customer_internal)
    
    if not _should_update_sales_invoice_status(doc):
        return

    try:
        # Update status immediately on the document object so it shows without refresh
        doc.status = "BNS Internally Transferred"
        # Also update in database using db_set
        doc.db_set("status", "BNS Internally Transferred", update_modified=False)
        frappe.clear_cache(doctype="Sales Invoice")
        logger.info(f"Updated Sales Invoice {doc.name} status to BNS Internally Transferred")
        
    except Exception as e:
        logger.error(f"Error updating Sales Invoice status: {str(e)}")
        raise


def update_purchase_invoice_status_for_bns_internal(doc, method: Optional[str] = None) -> None:
    """
    Update the status of a Purchase Invoice to "BNS Internally Transferred" 
    when submitted for a BNS internal supplier with inter company reference.
    
    This handles:
    1. PI created directly from SI (has inter_company_invoice_reference)
    2. PI created from PR that was created from SI (check PR's supplier_delivery_note or bns_inter_company_reference)
    
    Args:
        doc: The Purchase Invoice document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return
    
    # Guard: prevent infinite loops - if already updated, skip
    if doc.status == "BNS Internally Transferred":
        return
    
    # Check if it's a BNS internal transfer
    is_bns_internal = doc.get("is_bns_internal_supplier") or False
    is_from_si = False
    
    if is_bns_internal:
        is_from_si = True
    elif doc.bns_inter_company_reference:
        # Directly created from Sales Invoice (using bns_inter_company_reference)
        # Check if bns_inter_company_reference points to a Sales Invoice
        if frappe.db.exists("Sales Invoice", doc.bns_inter_company_reference):
            is_from_si = True
    elif doc.inter_company_invoice_reference:
        # Also check standard inter_company_invoice_reference for backward compatibility
        is_from_si = True
    elif doc.items:
        # Check if PI is created from PR that was created from SI
        # Get Purchase Receipt references from items
        pr_names = set()
        for item in doc.items:
            if item.get("purchase_receipt"):
                pr_names.add(item.purchase_receipt)
        
        # Check if any PR was created from SI
        if pr_names:
            for pr_name in pr_names:
                pr_supplier_dn = frappe.db.get_value("Purchase Receipt", pr_name, "supplier_delivery_note")
                pr_bns_ref = frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference")
                
                # Check if supplier_delivery_note or bns_inter_company_reference points to a Sales Invoice
                if pr_supplier_dn and frappe.db.exists("Sales Invoice", pr_supplier_dn):
                    is_from_si = True
                    break
                elif pr_bns_ref and frappe.db.exists("Sales Invoice", pr_bns_ref):
                    is_from_si = True
                    break
    
    if not is_from_si:
        return
    
    try:
        # Ensure is_bns_internal_supplier is set
        if not doc.get("is_bns_internal_supplier"):
            doc.is_bns_internal_supplier = 1
        
        # Ensure represents_company is set from supplier
        if not doc.represents_company and doc.supplier:
            represents_company = frappe.db.get_value("Supplier", doc.supplier, "bns_represents_company")
            if not represents_company:
                represents_company = frappe.db.get_value("Supplier", doc.supplier, "represents_company")
            if represents_company:
                doc.represents_company = represents_company
        
        # Update status immediately on document and in database using db_set
        doc.status = "BNS Internally Transferred"
        doc.db_set("status", "BNS Internally Transferred", update_modified=False)
        doc.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if doc.represents_company:
            doc.db_set("represents_company", doc.represents_company, update_modified=False)
        frappe.clear_cache(doctype="Purchase Invoice")
        logger.info(f"Updated Purchase Invoice {doc.name} status to BNS Internally Transferred")
        
    except Exception as e:
        logger.error(f"Error updating Purchase Invoice status: {str(e)}")
        raise


def _should_update_sales_invoice_status(doc) -> bool:
    """Check if the Sales Invoice status should be updated for internal transfers."""
    if doc.docstatus != 1:
        return False
    
    # Check if customer is BNS internal (only check is_bns_internal_customer)
    is_bns_internal = doc.get("is_bns_internal_customer") or False
    if not is_bns_internal:
        # Check customer's is_bns_internal_customer field
        customer_internal = frappe.db.get_value("Customer", doc.customer, "is_bns_internal_customer")
        if not customer_internal:
            return False
    
    # Check GST mismatch condition (different GST)
    billing_address_gstin = getattr(doc, 'billing_address_gstin', None)
    company_gstin = getattr(doc, 'company_gstin', None)
    
    if billing_address_gstin is None or company_gstin is None:
        return False
    
    # Only update if GST is different
    return billing_address_gstin != company_gstin


@frappe.whitelist()
def get_sales_invoice_by_bill_no(purchase_invoice: str) -> Dict:
    """
    Find Sales Invoice by bill_no (supplier_invoice_number) matching Purchase Invoice name.
    
    Args:
        purchase_invoice (str): Name of the Purchase Invoice
        
    Returns:
        Dict: Sales Invoice details if found, None otherwise
    """
    try:
        # Get Purchase Invoice to check bill_no
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Find SI where name matches PI's bill_no (supplier_invoice_number)
        si_name = None
        if pi.bill_no:
            si_name = frappe.db.get_value("Sales Invoice", {"name": pi.bill_no, "docstatus": 1}, "name")
        
        if not si_name:
            return {"found": False}
        
        si = frappe.get_doc("Sales Invoice", si_name)
        
        # Get basic details
        return {
            "found": True,
            "name": si.name,
            "customer": si.customer,
            "posting_date": str(si.posting_date) if si.posting_date else None,
            "grand_total": si.grand_total or 0,
            "status": si.status,
            "is_bns_internal_customer": si.get("is_bns_internal_customer") or 0,
            "bns_inter_company_reference": si.get("bns_inter_company_reference") or None
        }
    except Exception as e:
        logger.error(f"Error finding Sales Invoice: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def get_purchase_invoice_by_supplier_invoice(sales_invoice: str) -> Dict:
    """
    Find Purchase Invoice by supplier_invoice_number (bill_no) matching Sales Invoice name.
    
    Args:
        sales_invoice (str): Name of the Sales Invoice
        
    Returns:
        Dict: Purchase Invoice details if found, None otherwise
    """
    try:
        # Find PI where bill_no matches SI name
        pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": sales_invoice, "docstatus": 1}, "name")
        
        if not pi_name:
            return {"found": False}
        
        pi = frappe.get_doc("Purchase Invoice", pi_name)
        
        # Get basic details
        return {
            "found": True,
            "name": pi.name,
            "supplier": pi.supplier,
            "posting_date": str(pi.posting_date) if pi.posting_date else None,
            "grand_total": pi.grand_total or 0,
            "status": pi.status,
            "is_bns_internal_supplier": pi.get("is_bns_internal_supplier") or 0,
            "bns_inter_company_reference": pi.get("bns_inter_company_reference") or None
        }
    except Exception as e:
        logger.error(f"Error finding Purchase Invoice: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def validate_si_pi_items_match(sales_invoice: str, purchase_invoice: str) -> Dict:
    """
    Validate that all Sales Invoice items and quantities match Purchase Invoice items.
    
    Args:
        sales_invoice (str): Name of the Sales Invoice
        purchase_invoice (str): Name of the Purchase Invoice
        
    Returns:
        Dict: Validation result with match status and details
    """
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Get SI items
        si_items = {}
        for item in si.items:
            item_code = item.item_code
            qty = item.qty or 0
            stock_qty = item.stock_qty or qty
            
            if item_code not in si_items:
                si_items[item_code] = {"qty": 0, "stock_qty": 0}
            si_items[item_code]["qty"] += qty
            si_items[item_code]["stock_qty"] += stock_qty
        
        # Get PI items
        pi_items = {}
        for item in pi.items:
            item_code = item.item_code
            qty = item.qty or 0
            stock_qty = item.stock_qty or qty
            
            if item_code not in pi_items:
                pi_items[item_code] = {"qty": 0, "stock_qty": 0}
            pi_items[item_code]["qty"] += qty
            pi_items[item_code]["stock_qty"] += stock_qty
        
        # Check if all SI items exist in PI and quantities match
        missing_items = []
        qty_mismatches = []
        
        for item_code, si_data in si_items.items():
            if item_code not in pi_items:
                missing_items.append({
                    "item_code": item_code,
                    "si_qty": si_data["qty"],
                    "pi_qty": 0
                })
            else:
                pi_data = pi_items[item_code]
                # Check stock_qty first, then qty
                if si_data["stock_qty"] > 0:
                    if abs(si_data["stock_qty"] - pi_data["stock_qty"]) > 0.001:
                        qty_mismatches.append({
                            "item_code": item_code,
                            "si_qty": si_data["stock_qty"],
                            "pi_qty": pi_data["stock_qty"]
                        })
                elif abs(si_data["qty"] - pi_data["qty"]) > 0.001:
                    qty_mismatches.append({
                        "item_code": item_code,
                        "si_qty": si_data["qty"],
                        "pi_qty": pi_data["qty"]
                    })
        
        # Check if PI has extra items (not in SI)
        extra_items = []
        for item_code, pi_data in pi_items.items():
            if item_code not in si_items:
                extra_items.append({
                    "item_code": item_code,
                    "pi_qty": pi_data["qty"]
                })
        
        is_match = len(missing_items) == 0 and len(qty_mismatches) == 0
        
        return {
            "match": is_match,
            "missing_items": missing_items,
            "qty_mismatches": qty_mismatches,
            "extra_items": extra_items,
            "message": _("Items and quantities match") if is_match else _("Items or quantities do not match")
        }
        
    except Exception as e:
        logger.error(f"Error validating SI-PI items match: {str(e)}")
        frappe.throw(_("Error validating items: {0}").format(str(e)))


@frappe.whitelist()
def convert_sales_invoice_to_bns_internal(sales_invoice: str, purchase_invoice: Optional[str] = None) -> Dict:
    """
    Convert a Sales Invoice to BNS Internally Transferred status.
    
    This function:
    1. Marks Sales Invoice as BNS internal customer
    2. Updates status to "BNS Internally Transferred"
    3. If Purchase Invoice is provided, validates and links them properly
    
    Args:
        sales_invoice (str): Name of the Sales Invoice to convert
        purchase_invoice (Optional[str]): Optional Purchase Invoice name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    try:
        # Get Sales Invoice
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        
        # Validate Sales Invoice is submitted
        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before converting to BNS Internal"))
        
        # Check if customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(si.customer))
        
        # Check if already converted
        if si.get("is_bns_internal_customer") and si.status == "BNS Internally Transferred":
            frappe.msgprint(_("Sales Invoice is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Sales Invoice
        si.db_set("is_bns_internal_customer", 1, update_modified=False)
        si.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        result = {
            "success": True,
            "message": _("Sales Invoice converted to BNS Internally Transferred"),
            "sales_invoice": si.name
        }
        
        # If Purchase Invoice is provided, validate and link
        if purchase_invoice:
            pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
            
            # Validate PI is submitted
            if pi.docstatus != 1:
                raise BNSValidationError(_("Purchase Invoice {0} must be submitted before linking").format(purchase_invoice))
            
            # Validate items and quantities match
            validation_result = validate_si_pi_items_match(si.name, pi.name)
            if not validation_result.get("match"):
                missing = validation_result.get("missing_items", [])
                qty_mismatches = validation_result.get("qty_mismatches", [])
                errors = []
                if missing:
                    for item in missing[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                if qty_mismatches:
                    for item in qty_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                if len(missing) > 3 or len(qty_mismatches) > 3:
                    errors.append(_("... and more items"))
                raise BNSValidationError(_("Items and quantities do not match: {0}").format("; ".join(errors)))
            
            # Get representing companies for validation
            si_customer_company = frappe.db.get_value("Customer", si.customer, "bns_represents_company")
            pi_supplier_company = None
            if pi.supplier:
                pi_supplier_company = frappe.db.get_value("Supplier", pi.supplier, "bns_represents_company")
                if not pi_supplier_company:
                    pi_supplier_company = frappe.db.get_value("Supplier", pi.supplier, "represents_company")
            
            # Validate companies match (PI supplier should represent SI's company)
            if si_customer_company and pi_supplier_company:
                if pi_supplier_company != si_customer_company:
                    raise BNSValidationError(
                        _("Purchase Invoice supplier represents company {0}, but Sales Invoice customer represents {1}").format(
                            pi_supplier_company, si_customer_company
                        )
                    )
            
            # Check if PI already linked to another SI
            existing_ref = pi.get("bns_inter_company_reference")
            if existing_ref and existing_ref != si.name:
                raise BNSValidationError(
                    _("Purchase Invoice {0} is already linked to Sales Invoice {1}").format(
                        purchase_invoice, existing_ref
                    )
                )
            
            # Match SI items to PI items and update item-wise references
            # Create mapping: item_code -> list of (si_item, remaining_qty)
            si_item_map = {}
            for si_item in si.items:
                item_code = si_item.item_code
                if item_code not in si_item_map:
                    si_item_map[item_code] = []
                si_item_map[item_code].append({
                    "name": si_item.name,
                    "qty": si_item.qty or 0,
                    "stock_qty": si_item.stock_qty or (si_item.qty or 0),
                    "remaining_qty": si_item.qty or 0,
                    "remaining_stock_qty": si_item.stock_qty or (si_item.qty or 0)
                })
            
            # Match PI items to SI items and update sales_invoice_item field
            pi_items_to_update = []
            for pi_item in pi.items:
                item_code = pi_item.item_code
                pi_qty = pi_item.qty or 0
                pi_stock_qty = pi_item.stock_qty or pi_qty
                
                if item_code in si_item_map and si_item_map[item_code]:
                    # Find matching SI item(s) for this PI item
                    matched = False
                    for si_item_data in si_item_map[item_code]:
                        if si_item_data["remaining_qty"] <= 0:
                            continue
                        
                        # Check if quantities match (prefer stock_qty if available)
                        if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                            if abs(pi_stock_qty - si_item_data["remaining_stock_qty"]) < 0.001:
                                # Perfect match
                                pi_items_to_update.append({
                                    "name": pi_item.name,
                                    "sales_invoice_item": si_item_data["name"]
                                })
                                si_item_data["remaining_qty"] = 0
                                si_item_data["remaining_stock_qty"] = 0
                                matched = True
                                break
                        elif abs(pi_qty - si_item_data["remaining_qty"]) < 0.001:
                            # Match by qty
                            pi_items_to_update.append({
                                "name": pi_item.name,
                                "sales_invoice_item": si_item_data["name"]
                            })
                            si_item_data["remaining_qty"] = 0
                            si_item_data["remaining_stock_qty"] = 0
                            matched = True
                            break
                    
                    # If no exact match found, match with first available SI item (partial match)
                    if not matched:
                        for si_item_data in si_item_map[item_code]:
                            if si_item_data["remaining_qty"] > 0:
                                pi_items_to_update.append({
                                    "name": pi_item.name,
                                    "sales_invoice_item": si_item_data["name"]
                                })
                                # Reduce remaining quantity
                                if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                                    si_item_data["remaining_stock_qty"] -= pi_stock_qty
                                else:
                                    si_item_data["remaining_qty"] -= pi_qty
                                matched = True
                                break
            
            # Update Purchase Invoice document-level fields first
            frappe.db.set_value("Purchase Invoice", pi.name, {
                "is_bns_internal_supplier": 1,
                "bns_inter_company_reference": si.name,
                "status": "BNS Internally Transferred"
            }, update_modified=False)
            
            # Update item-wise sales_invoice_item references
            for item_update in pi_items_to_update:
                frappe.db.set_value("Purchase Invoice Item", item_update["name"], {
                    "sales_invoice_item": item_update["sales_invoice_item"]
                }, update_modified=False)
            
            # Reload PI to get updated values
            pi.reload()
            
            # Then update Sales Invoice
            si.db_set("bns_inter_company_reference", pi.name, update_modified=False)
            
            # Clear cache for both documents
            frappe.clear_cache(doctype="Purchase Invoice")
            frappe.clear_cache(doctype="Sales Invoice")
            
            result["purchase_invoice"] = pi.name
            result["message"] = _("Sales Invoice and Purchase Invoice linked successfully")
            
            logger.info(f"Linked Sales Invoice {si.name} with Purchase Invoice {pi.name}, updated {len(pi_items_to_update)} item references")
        
        frappe.clear_cache(doctype="Sales Invoice")
        
        logger.info(f"Converted Sales Invoice {si.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Sales Invoice to BNS Internal: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def convert_purchase_invoice_to_bns_internal(purchase_invoice: str, sales_invoice: Optional[str] = None) -> Dict:
    """
    Convert a Purchase Invoice to BNS Internally Transferred status.
    
    This function:
    1. Marks Purchase Invoice as BNS internal supplier
    2. Updates status to "BNS Internally Transferred"
    3. If Sales Invoice is provided, validates and links them properly
    
    Args:
        purchase_invoice (str): Name of the Purchase Invoice to convert
        sales_invoice (Optional[str]): Optional Sales Invoice name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    try:
        # Get Purchase Invoice
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Validate Purchase Invoice is submitted
        if pi.docstatus != 1:
            raise BNSValidationError(_("Purchase Invoice must be submitted before converting to BNS Internal"))
        
        # Check if supplier is BNS internal
        supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
        if not supplier_internal:
            raise BNSValidationError(_("Supplier {0} is not marked as BNS Internal Supplier").format(pi.supplier))
        
        # Check if already converted
        if pi.get("is_bns_internal_supplier") and pi.status == "BNS Internally Transferred":
            frappe.msgprint(_("Purchase Invoice is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Purchase Invoice
        pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
        pi.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        result = {
            "success": True,
            "message": _("Purchase Invoice converted to BNS Internally Transferred"),
            "purchase_invoice": pi.name
        }
        
        # If Sales Invoice is provided, validate and link
        if sales_invoice:
            si = frappe.get_doc("Sales Invoice", sales_invoice)
            
            # Validate SI is submitted
            if si.docstatus != 1:
                raise BNSValidationError(_("Sales Invoice {0} must be submitted before linking").format(sales_invoice))
            
            # Validate items and quantities match
            validation_result = validate_si_pi_items_match(si.name, pi.name)
            if not validation_result.get("match"):
                missing = validation_result.get("missing_items", [])
                qty_mismatches = validation_result.get("qty_mismatches", [])
                errors = []
                if missing:
                    for item in missing[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                if qty_mismatches:
                    for item in qty_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                if len(missing) > 3 or len(qty_mismatches) > 3:
                    errors.append(_("... and more items"))
                raise BNSValidationError(_("Items and quantities do not match: {0}").format("; ".join(errors)))
            
            # Get representing companies for validation
            si_customer_company = frappe.db.get_value("Customer", si.customer, "bns_represents_company")
            pi_supplier_company = None
            if pi.supplier:
                pi_supplier_company = frappe.db.get_value("Supplier", pi.supplier, "bns_represents_company")
                if not pi_supplier_company:
                    pi_supplier_company = frappe.db.get_value("Supplier", pi.supplier, "represents_company")
            
            # Validate companies match (PI supplier should represent SI's company)
            if si_customer_company and pi_supplier_company:
                if pi_supplier_company != si_customer_company:
                    raise BNSValidationError(
                        _("Purchase Invoice supplier represents company {0}, but Sales Invoice customer represents {1}").format(
                            pi_supplier_company, si_customer_company
                        )
                    )
            
            # Check if SI already linked to another PI
            existing_ref = si.get("bns_inter_company_reference")
            if existing_ref and existing_ref != pi.name:
                raise BNSValidationError(
                    _("Sales Invoice {0} is already linked to Purchase Invoice {1}").format(
                        sales_invoice, existing_ref
                    )
                )
            
            # Match SI items to PI items and update item-wise references
            # Create mapping: item_code -> list of (si_item, remaining_qty)
            si_item_map = {}
            for si_item in si.items:
                item_code = si_item.item_code
                if item_code not in si_item_map:
                    si_item_map[item_code] = []
                si_item_map[item_code].append({
                    "name": si_item.name,
                    "qty": si_item.qty or 0,
                    "stock_qty": si_item.stock_qty or (si_item.qty or 0),
                    "remaining_qty": si_item.qty or 0,
                    "remaining_stock_qty": si_item.stock_qty or (si_item.qty or 0)
                })
            
            # Match PI items to SI items and update sales_invoice_item field
            pi_items_to_update = []
            for pi_item in pi.items:
                item_code = pi_item.item_code
                pi_qty = pi_item.qty or 0
                pi_stock_qty = pi_item.stock_qty or pi_qty
                
                if item_code in si_item_map and si_item_map[item_code]:
                    # Find matching SI item(s) for this PI item
                    matched = False
                    for si_item_data in si_item_map[item_code]:
                        if si_item_data["remaining_qty"] <= 0:
                            continue
                        
                        # Check if quantities match (prefer stock_qty if available)
                        if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                            if abs(pi_stock_qty - si_item_data["remaining_stock_qty"]) < 0.001:
                                # Perfect match
                                pi_items_to_update.append({
                                    "name": pi_item.name,
                                    "sales_invoice_item": si_item_data["name"]
                                })
                                si_item_data["remaining_qty"] = 0
                                si_item_data["remaining_stock_qty"] = 0
                                matched = True
                                break
                        elif abs(pi_qty - si_item_data["remaining_qty"]) < 0.001:
                            # Match by qty
                            pi_items_to_update.append({
                                "name": pi_item.name,
                                "sales_invoice_item": si_item_data["name"]
                            })
                            si_item_data["remaining_qty"] = 0
                            si_item_data["remaining_stock_qty"] = 0
                            matched = True
                            break
                    
                    # If no exact match found, match with first available SI item (partial match)
                    if not matched:
                        for si_item_data in si_item_map[item_code]:
                            if si_item_data["remaining_qty"] > 0:
                                pi_items_to_update.append({
                                    "name": pi_item.name,
                                    "sales_invoice_item": si_item_data["name"]
                                })
                                # Reduce remaining quantity
                                if pi_stock_qty > 0 and si_item_data["remaining_stock_qty"] > 0:
                                    si_item_data["remaining_stock_qty"] -= pi_stock_qty
                                else:
                                    si_item_data["remaining_qty"] -= pi_qty
                                matched = True
                                break
            
            # Update Purchase Invoice document-level fields first
            frappe.db.set_value("Purchase Invoice", pi.name, {
                "is_bns_internal_supplier": 1,
                "bns_inter_company_reference": si.name,
                "status": "BNS Internally Transferred"
            }, update_modified=False)
            
            # Update item-wise sales_invoice_item references
            for item_update in pi_items_to_update:
                frappe.db.set_value("Purchase Invoice Item", item_update["name"], {
                    "sales_invoice_item": item_update["sales_invoice_item"]
                }, update_modified=False)
            
            # Reload PI to get updated values
            pi.reload()
            
            # Then update Sales Invoice
            si.db_set("bns_inter_company_reference", pi.name, update_modified=False)
            if si.status != "BNS Internally Transferred":
                si.db_set("status", "BNS Internally Transferred", update_modified=False)
            if not si.get("is_bns_internal_customer"):
                si.db_set("is_bns_internal_customer", 1, update_modified=False)
            
            # Clear cache for both documents
            frappe.clear_cache(doctype="Purchase Invoice")
            frappe.clear_cache(doctype="Sales Invoice")
            
            result["sales_invoice"] = si.name
            result["message"] = _("Purchase Invoice and Sales Invoice linked successfully")
            
            logger.info(f"Linked Purchase Invoice {pi.name} with Sales Invoice {si.name}, updated {len(pi_items_to_update)} item references")
        
        frappe.clear_cache(doctype="Purchase Invoice")
        
        logger.info(f"Converted Purchase Invoice {pi.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Purchase Invoice to BNS Internal: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def get_purchase_receipt_by_supplier_delivery_note(delivery_note: str) -> Dict:
    """
    Find Purchase Receipt by supplier_delivery_note matching Delivery Note name.
    
    Args:
        delivery_note (str): Name of the Delivery Note
        
    Returns:
        Dict: Purchase Receipt details if found, None otherwise
    """
    try:
        # Find PR where supplier_delivery_note matches DN name
        pr_name = frappe.db.get_value("Purchase Receipt", {"supplier_delivery_note": delivery_note, "docstatus": 1}, "name")
        
        if not pr_name:
            return {"found": False}
        
        pr = frappe.get_doc("Purchase Receipt", pr_name)
        
        # Get basic details
        return {
            "found": True,
            "name": pr.name,
            "supplier": pr.supplier,
            "posting_date": str(pr.posting_date) if pr.posting_date else None,
            "grand_total": pr.grand_total or 0,
            "status": pr.status,
            "is_bns_internal_customer": pr.get("is_bns_internal_customer") or 0,
            "bns_inter_company_reference": pr.get("bns_inter_company_reference") or None
        }
    except Exception as e:
        logger.error(f"Error finding Purchase Receipt: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def get_delivery_note_by_supplier_delivery_note(purchase_receipt: str) -> Dict:
    """
    Find Delivery Note by supplier_delivery_note from Purchase Receipt.
    
    Args:
        purchase_receipt (str): Name of the Purchase Receipt
        
    Returns:
        Dict: Delivery Note details if found, None otherwise
    """
    try:
        # Get Purchase Receipt to check supplier_delivery_note
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Find DN where name matches PR's supplier_delivery_note
        dn_name = None
        if pr.supplier_delivery_note:
            dn_name = frappe.db.get_value("Delivery Note", {"name": pr.supplier_delivery_note, "docstatus": 1}, "name")
        
        if not dn_name:
            return {"found": False}
        
        dn = frappe.get_doc("Delivery Note", dn_name)
        
        # Get basic details
        return {
            "found": True,
            "name": dn.name,
            "customer": dn.customer,
            "posting_date": str(dn.posting_date) if dn.posting_date else None,
            "grand_total": dn.grand_total or 0,
            "status": dn.status,
            "is_bns_internal_customer": dn.get("is_bns_internal_customer") or 0,
            "billing_address_gstin": dn.get("billing_address_gstin"),
            "company_gstin": dn.get("company_gstin")
        }
    except Exception as e:
        logger.error(f"Error finding Delivery Note: {str(e)}")
        return {"found": False}


@frappe.whitelist()
def convert_delivery_note_to_bns_internal(delivery_note: str, purchase_receipt: Optional[str] = None) -> Dict:
    """
    Convert a Delivery Note to BNS Internally Transferred status (same GSTIN only).
    
    This function:
    1. Validates GSTIN match (billing_address_gstin == company_gstin)
    2. Marks Delivery Note as BNS internal customer
    3. Updates status to "BNS Internally Transferred"
    4. Sets per_billed = 100%
    5. If Purchase Receipt is provided, validates and links them properly
    
    Args:
        delivery_note (str): Name of the Delivery Note to convert
        purchase_receipt (Optional[str]): Optional Purchase Receipt name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    try:
        # Get Delivery Note
        dn = frappe.get_doc("Delivery Note", delivery_note)
        
        # Validate Delivery Note is submitted
        if dn.docstatus != 1:
            raise BNSValidationError(_("Delivery Note must be submitted before converting to BNS Internal"))
        
        # Check if customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Validate GSTIN match (same GSTIN only)
        billing_address_gstin = getattr(dn, 'billing_address_gstin', None)
        company_gstin = getattr(dn, 'company_gstin', None)
        
        if billing_address_gstin is None or company_gstin is None:
            raise BNSValidationError(_("GSTIN information is missing. Cannot convert to BNS Internal transfer."))
        
        if billing_address_gstin != company_gstin:
            raise BNSValidationError(
                _("GSTIN mismatch: billing_address_gstin ({0}) != company_gstin ({1}). Only same GSTIN transfers can be converted.").format(
                    billing_address_gstin, company_gstin
                )
            )
        
        # Check if already converted
        if dn.get("is_bns_internal_customer") and dn.status == "BNS Internally Transferred":
            frappe.msgprint(_("Delivery Note is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Delivery Note
        dn.db_set("is_bns_internal_customer", 1, update_modified=False)
        dn.db_set("status", "BNS Internally Transferred", update_modified=False)
        dn.db_set("per_billed", 100, update_modified=False)
        
        result = {
            "success": True,
            "message": _("Delivery Note converted to BNS Internally Transferred"),
            "delivery_note": dn.name
        }
        
        # If Purchase Receipt is provided, validate and link
        if purchase_receipt:
            pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
            
            # Validate PR is submitted
            if pr.docstatus != 1:
                raise BNSValidationError(_("Purchase Receipt {0} must be submitted before linking").format(purchase_receipt))
            
            # Validate PR's supplier_delivery_note matches DN name
            if pr.supplier_delivery_note != dn.name:
                raise BNSValidationError(
                    _("Purchase Receipt {0} is not linked to Delivery Note {1}").format(
                        purchase_receipt, dn.name
                    )
                )
            
            # Validate PR GSTIN matches DN GSTIN
            pr_supplier_gstin = getattr(pr, 'supplier_gstin', None)
            pr_company_gstin = getattr(pr, 'company_gstin', None)
            
            if pr_company_gstin and pr_company_gstin != company_gstin:
                raise BNSValidationError(
                    _("Purchase Receipt company GSTIN ({0}) does not match Delivery Note company GSTIN ({1})").format(
                        pr_company_gstin, company_gstin
                    )
                )
            
            # Check if PR already linked to another DN
            existing_ref = pr.get("bns_inter_company_reference")
            if existing_ref and existing_ref != dn.name:
                raise BNSValidationError(
                    _("Purchase Receipt {0} is already linked to Delivery Note {1}").format(
                        purchase_receipt, existing_ref
                    )
                )
            
            # Update Purchase Receipt document-level fields
            pr.db_set("is_bns_internal_customer", 1, update_modified=False)
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
            pr.db_set("per_billed", 100, update_modified=False)
            if not pr.get("bns_inter_company_reference"):
                pr.db_set("bns_inter_company_reference", dn.name, update_modified=False)
            
            # Then update Delivery Note reference
            if not dn.get("bns_inter_company_reference"):
                dn.db_set("bns_inter_company_reference", pr.name, update_modified=False)
            
            # Clear cache for both documents
            frappe.clear_cache(doctype="Purchase Receipt")
            frappe.clear_cache(doctype="Delivery Note")
            
            result["purchase_receipt"] = pr.name
            result["message"] = _("Delivery Note and Purchase Receipt linked successfully")
            
            logger.info(f"Linked Delivery Note {dn.name} with Purchase Receipt {pr.name}")
        
        frappe.clear_cache(doctype="Delivery Note")
        
        logger.info(f"Converted Delivery Note {dn.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Delivery Note to BNS Internal: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def convert_purchase_receipt_to_bns_internal(purchase_receipt: str, delivery_note: Optional[str] = None) -> Dict:
    """
    Convert a Purchase Receipt to BNS Internally Transferred status (same GSTIN only).
    
    This function:
    1. Validates PR is from DN (via supplier_delivery_note)
    2. Validates GSTIN match (same GSTIN)
    3. Marks Purchase Receipt as BNS internal customer
    4. Updates status to "BNS Internally Transferred"
    5. Sets per_billed = 100%
    6. If Delivery Note is provided, validates and links them properly
    
    Args:
        purchase_receipt (str): Name of the Purchase Receipt to convert
        delivery_note (Optional[str]): Optional Delivery Note name to link
        
    Returns:
        Dict: Result with success message and updated references
        
    Raises:
        BNSValidationError: If validation fails
    """
    try:
        # Get Purchase Receipt
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Validate Purchase Receipt is submitted
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before converting to BNS Internal"))
        
        # Check if supplier_delivery_note exists and is a DN
        if not pr.supplier_delivery_note:
            raise BNSValidationError(_("Purchase Receipt must be created from a Delivery Note (supplier_delivery_note is missing)"))
        
        dn_exists = frappe.db.exists("Delivery Note", pr.supplier_delivery_note)
        if not dn_exists:
            raise BNSValidationError(_("Purchase Receipt supplier_delivery_note ({0}) is not a valid Delivery Note").format(pr.supplier_delivery_note))
        
        # Get the Delivery Note to validate GSTIN
        dn = frappe.get_doc("Delivery Note", pr.supplier_delivery_note)
        
        # Validate DN customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Delivery Note customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Validate GSTIN match (same GSTIN only)
        dn_billing_gstin = getattr(dn, 'billing_address_gstin', None)
        dn_company_gstin = getattr(dn, 'company_gstin', None)
        pr_company_gstin = getattr(pr, 'company_gstin', None)
        
        if dn_billing_gstin is None or dn_company_gstin is None:
            raise BNSValidationError(_("Delivery Note GSTIN information is missing. Cannot convert to BNS Internal transfer."))
        
        if dn_billing_gstin != dn_company_gstin:
            raise BNSValidationError(
                _("Delivery Note GSTIN mismatch: billing_address_gstin ({0}) != company_gstin ({1}). Only same GSTIN transfers can be converted.").format(
                    dn_billing_gstin, dn_company_gstin
                )
            )
        
        # Check if already converted
        if pr.get("is_bns_internal_customer") and pr.status == "BNS Internally Transferred":
            frappe.msgprint(_("Purchase Receipt is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Use delivery_note parameter if provided, otherwise use supplier_delivery_note
        linked_dn = delivery_note if delivery_note else pr.supplier_delivery_note
        
        # Validate linked DN matches supplier_delivery_note
        if linked_dn != pr.supplier_delivery_note:
            raise BNSValidationError(
                _("Delivery Note {0} does not match Purchase Receipt supplier_delivery_note ({1})").format(
                    linked_dn, pr.supplier_delivery_note
                )
            )
        
        # Update Purchase Receipt
        pr.db_set("is_bns_internal_customer", 1, update_modified=False)
        pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        pr.db_set("per_billed", 100, update_modified=False)
        if not pr.get("bns_inter_company_reference"):
            pr.db_set("bns_inter_company_reference", linked_dn, update_modified=False)
        
        result = {
            "success": True,
            "message": _("Purchase Receipt converted to BNS Internally Transferred"),
            "purchase_receipt": pr.name
        }
        
        # Update Delivery Note if not already updated
        if linked_dn:
            dn_reload = frappe.get_doc("Delivery Note", linked_dn)
            if not dn_reload.get("bns_inter_company_reference"):
                dn_reload.db_set("bns_inter_company_reference", pr.name, update_modified=False)
            if dn_reload.status != "BNS Internally Transferred":
                dn_reload.db_set("status", "BNS Internally Transferred", update_modified=False)
            if not dn_reload.get("is_bns_internal_customer"):
                dn_reload.db_set("is_bns_internal_customer", 1, update_modified=False)
            if dn_reload.per_billed != 100:
                dn_reload.db_set("per_billed", 100, update_modified=False)
            
            result["delivery_note"] = linked_dn
            result["message"] = _("Purchase Receipt and Delivery Note linked successfully")
            
            logger.info(f"Linked Purchase Receipt {pr.name} with Delivery Note {linked_dn}")
        
        frappe.clear_cache(doctype="Purchase Receipt")
        frappe.clear_cache(doctype="Delivery Note")
        
        logger.info(f"Converted Purchase Receipt {pr.name} to BNS Internally Transferred")
        return result
        
    except Exception as e:
        logger.error(f"Error converting Purchase Receipt to BNS Internal: {str(e)}")
        frappe.throw(str(e))


def validate_delivery_note_cancellation(doc, method: Optional[str] = None) -> None:
    """
    Validate that Delivery Note cannot be cancelled if Purchase Receipt exists.
    
    Args:
        doc: The Delivery Note document
        method (Optional[str]): The method being called
    """
    if doc.docstatus != 1:
        return
    
    try:
        # Check if any Purchase Receipt references this Delivery Note
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters={
                "supplier_delivery_note": doc.name,
                "docstatus": ["!=", 2]  # Not cancelled
            },
            fields=["name", "docstatus"],
            limit=1
        )
        
        if pr_list:
            pr_name = pr_list[0].name
            pr_status = "Submitted" if pr_list[0].docstatus == 1 else "Draft"
            frappe.throw(
                _("Cannot cancel Delivery Note {0} because Purchase Receipt {1} ({2}) references it. Please cancel the Purchase Receipt first.").format(
                    doc.name, pr_name, pr_status
                ),
                title=_("Cancellation Not Allowed")
            )
        
        # Also check via bns_inter_company_reference
        pr_list_bns = frappe.get_all(
            "Purchase Receipt",
            filters={
                "bns_inter_company_reference": doc.name,
                "docstatus": ["!=", 2]  # Not cancelled
            },
            fields=["name", "docstatus"],
            limit=1
        )
        
        if pr_list_bns:
            pr_name = pr_list_bns[0].name
            pr_status = "Submitted" if pr_list_bns[0].docstatus == 1 else "Draft"
            frappe.throw(
                _("Cannot cancel Delivery Note {0} because Purchase Receipt {1} ({2}) references it. Please cancel the Purchase Receipt first.").format(
                    doc.name, pr_name, pr_status
                ),
                title=_("Cancellation Not Allowed")
            )
        
    except frappe.ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error validating Delivery Note cancellation: {str(e)}")
        # Don't block cancellation if there's an error, but log it
        pass 