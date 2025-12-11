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
from frappe.utils import flt, get_link_to_form
from frappe import bold
from typing import Optional, Dict, Any
from collections import defaultdict
import logging

# Configure logging
logger = logging.getLogger(__name__)


class BNSInternalTransferError(Exception):
    """Custom exception for BNS internal transfer operations."""
    pass


class BNSValidationError(Exception):
    """Custom exception for BNS validation operations."""
    pass


def get_received_items(reference_name: str, doctype: str, reference_fieldname: str) -> Dict:
    """
    Get already received items for a reference document.
    
    Tracks partial receipts to prevent over-receipt.
    
    Args:
        reference_name (str): Name of the source document (DN/SI)
        doctype (str): Target doctype (Purchase Receipt/Purchase Invoice)
        reference_fieldname (str): Field name in child table that references source item
        
    Returns:
        Dict: Map of (source_item_name, item_code) -> received_qty
    """
    reference_field = "bns_inter_company_reference"
    
    filters = {
        reference_field: reference_name,
        "docstatus": 1,
    }
    
    target_doctypes = frappe.get_all(
        doctype,
        filters=filters,
        as_list=True,
    )
    
    if not target_doctypes:
        return {}
    
    target_doctypes = [d[0] for d in target_doctypes]
    
    # Get received items as list of tuples (as_list=1 returns tuples)
    received_items_list = frappe.get_all(
        doctype + " Item",
        filters={"parent": ("in", target_doctypes)},
        fields=[reference_fieldname, "item_code", "qty"],
        as_list=1,
    )
    
    # Convert to dict format: (source_item_name, item_code) -> qty
    result = defaultdict(float)
    for row in received_items_list:
        if len(row) >= 3:
            source_item_name = row[0]
            item_code = row[1] if len(row) > 1 else None
            qty = flt(row[2] if len(row) > 2 else row[1])
            if source_item_name and item_code:
                result[(source_item_name, item_code)] += qty
    
    return result


def validate_inter_company_party(doctype: str, party: str, company: str, inter_company_reference: Optional[str] = None) -> None:
    """
    Validate inter-company party relationships.
    
    Checks that represents_company matches between parties.
    Note: Skips "Allowed To Transact With" check as per BNS requirements.
    
    Args:
        doctype (str): Document type (Sales Invoice, Purchase Invoice, etc.)
        party (str): Party name (Customer/Supplier)
        company (str): Company name
        inter_company_reference (Optional[str]): Reference document name
        
    Raises:
        BNSValidationError: If validation fails
    """
    if not party:
        return
    
    if doctype in ["Sales Invoice", "Sales Order"]:
        partytype, ref_partytype = "Customer", "Supplier"
        
        if doctype == "Sales Invoice":
            ref_doc = "Purchase Invoice"
        else:
            ref_doc = "Purchase Order"
    else:
        partytype, ref_partytype = "Supplier", "Customer"
        
        if doctype == "Purchase Invoice":
            ref_doc = "Sales Invoice"
        else:
            ref_doc = "Sales Order"
    
    if inter_company_reference:
        # Validate against existing reference document
        if not frappe.db.exists(ref_doc, inter_company_reference):
            return
        
        doc = frappe.get_doc(ref_doc, inter_company_reference)
        ref_party = doc.supplier if doctype in ["Sales Invoice", "Sales Order"] else doc.customer
        
        # Check that party represents the reference document's company
        party_represents = frappe.db.get_value(partytype, {"name": party}, "bns_represents_company")
        if not party_represents:
            party_represents = frappe.db.get_value(partytype, {"name": party}, "represents_company")
        
        if not party_represents or party_represents != doc.company:
            raise BNSValidationError(_("Invalid {0} for Inter Company Transaction.").format(_(partytype)))
        
        # Check that reference party represents the target company
        ref_party_represents = frappe.get_cached_value(ref_partytype, ref_party, "bns_represents_company")
        if not ref_party_represents:
            ref_party_represents = frappe.get_cached_value(ref_partytype, ref_party, "represents_company")
        
        if not ref_party_represents or ref_party_represents != company:
            raise BNSValidationError(_("Invalid Company for Inter Company Transaction."))


def update_linked_doc(doctype: str, name: str, inter_company_reference: Optional[str]) -> None:
    """
    Update bidirectional linked document references.
    
    Args:
        doctype (str): Document type (Sales Invoice, Purchase Invoice, etc.)
        name (str): Document name
        inter_company_reference (Optional[str]): Reference document name
    """
    if not inter_company_reference:
        return
    
    ref_field = "bns_inter_company_reference"
    
    # Update the reference document with this document's name
    if doctype == "Sales Invoice":
        ref_doctype = "Purchase Invoice"
    elif doctype == "Purchase Invoice":
        ref_doctype = "Sales Invoice"
    elif doctype == "Delivery Note":
        ref_doctype = "Purchase Receipt"
    elif doctype == "Purchase Receipt":
        ref_doctype = "Delivery Note"
    else:
        return
    
    if frappe.db.exists(ref_doctype, inter_company_reference):
        frappe.db.set_value(ref_doctype, inter_company_reference, ref_field, name, update_modified=False)


def validate_internal_transfer_qty(doc) -> None:
    """
    Validate that PR/PI quantities don't exceed source document quantities.
    
    Args:
        doc: Purchase Receipt or Purchase Invoice document
        
    Raises:
        BNSValidationError: If quantities exceed source document
    """
    if doc.doctype not in ["Purchase Invoice", "Purchase Receipt"]:
        return
    
    # For Purchase Receipt, check if it's from SI (supplier_delivery_note) or DN (bns_inter_company_reference)
    inter_company_reference = doc.get("bns_inter_company_reference")
    supplier_delivery_note = doc.get("supplier_delivery_note")
    
    # Determine source document
    if doc.doctype == "Purchase Receipt" and supplier_delivery_note:
        # Check if supplier_delivery_note is a Sales Invoice
        if frappe.db.exists("Sales Invoice", supplier_delivery_note):
            inter_company_reference = supplier_delivery_note
            parent_doctype = "Sales Invoice"
            reference_fieldname = "sales_invoice_item"
        elif frappe.db.exists("Delivery Note", supplier_delivery_note):
            inter_company_reference = supplier_delivery_note
            parent_doctype = "Delivery Note"
            reference_fieldname = "delivery_note_item"
        else:
            return
    elif inter_company_reference:
        parent_doctype = {
            "Purchase Receipt": "Delivery Note",
            "Purchase Invoice": "Sales Invoice",
        }.get(doc.doctype)
        reference_fieldname = "delivery_note_item" if doc.doctype == "Purchase Receipt" else "sales_invoice_item"
    else:
        return
    
        if not parent_doctype or not inter_company_reference:
            return
    
    # Get item-wise transfer quantities from source document
    child_doctype = parent_doctype + " Item"
    
    # Check which fields exist based on doctype
    # Sales Invoice Item doesn't have returned_qty or received_qty
    has_returned_received_fields = parent_doctype not in ["Sales Invoice"]
    
    if has_returned_received_fields:
        fields = ["name", "item_code", "qty", "returned_qty", "received_qty"]
    else:
        fields = ["name", "item_code", "qty"]
    
    source_items = frappe.get_all(
        child_doctype,
        filters={"parent": inter_company_reference},
        fields=fields,
    )
    
    if not source_items:
        return
    
    # Calculate available quantities: qty + returned_qty - received_qty
    item_wise_transfer_qty = {}
    for item in source_items:
        key = (item.name, item.item_code)
        if has_returned_received_fields:
            available_qty = flt(item.qty or 0) + flt(item.get("returned_qty", 0) or 0) - flt(item.get("received_qty", 0) or 0)
        else:
            # For Sales Invoice Item, use qty directly
            available_qty = flt(item.qty or 0)
        item_wise_transfer_qty[key] = available_qty
    
    # Get already received quantities
    # For PR from SI, use supplier_delivery_note to find other PRs
    if doc.doctype == "Purchase Receipt" and supplier_delivery_note and frappe.db.exists("Sales Invoice", supplier_delivery_note):
        # Find other PRs created from this SI
        received_items = {}
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters={"supplier_delivery_note": supplier_delivery_note, "docstatus": 1, "name": ("!=", doc.name)},
            fields=["name"]
        )
        if pr_list:
            pr_names = [pr.name for pr in pr_list]
            pr_items = frappe.get_all(
                "Purchase Receipt Item",
                filters={"parent": ("in", pr_names)},
                fields=["sales_invoice_item", "item_code", "qty"]
            )
            for item in pr_items:
                key = (item.sales_invoice_item, item.item_code)
                received_items[key] = received_items.get(key, 0) + flt(item.qty)
    else:
        received_items = get_received_items(inter_company_reference, doc.doctype, reference_fieldname)
    
    # Calculate total received quantities including current document
    precision = frappe.get_precision(doc.doctype + " Item", "qty")
    over_receipt_allowance = frappe.db.get_single_value("Stock Settings", "over_delivery_receipt_allowance", cache=True) or 0
    
    # Check each item in current document
    for item in doc.items:
        source_item_name = item.get(reference_fieldname)
        item_code = item.get("item_code")
        
        if not source_item_name or not item_code:
            continue
        
        key = (source_item_name, item_code)
        transferred_qty = item_wise_transfer_qty.get(key, 0)
        
        if transferred_qty <= 0:
            continue
        
        # Calculate total received qty (already received + current)
        already_received = received_items.get(key, 0)
        current_qty = flt(item.qty or 0)
        total_received = already_received + current_qty
        
        # Apply over-receipt allowance if configured
        max_allowed = transferred_qty
        if over_receipt_allowance:
            max_allowed = transferred_qty + flt(transferred_qty * over_receipt_allowance / 100, precision)
        
        if total_received > flt(max_allowed, precision):
            frappe.throw(
                _("For Item {0} cannot be received more than {1} qty against the {2} {3}").format(
                    bold(item_code),
                    bold(flt(max_allowed, precision)),
                    bold(parent_doctype),
                    get_link_to_form(parent_doctype, inter_company_reference),
                )
            )


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
        
        # Validate inter-company party
        validate_inter_company_party("Purchase Receipt", dn.customer, represents_company)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Delivery Note",
            source_name,
            _get_delivery_note_mapping(),
            target_doc,
            _set_missing_values,
        )
        
        # Validate quantities
        validate_internal_transfer_qty(doclist)
        
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
            "condition": lambda item: flt(item.qty) + flt(item.returned_qty or 0) - flt(item.received_qty or 0) > 0,
            "postprocess": _update_item,
        },
    }


def _set_missing_values(source, target) -> None:
    """Set missing values for the target Purchase Receipt."""
    target.run_method("set_missing_values")
    
    # Get received items to track partial receipts
    received_items = get_received_items(source.name, "Purchase Receipt", "delivery_note_item")
    
    # Filter items that have already been fully received
    if received_items and target.get("items"):
        items_to_keep = []
        for item in target.items:
            source_item_name = item.get("delivery_note_item")
            item_code = item.get("item_code")
            if source_item_name and item_code:
                received_qty = received_items.get((source_item_name, item_code), 0)
                source_qty = flt(item.get("qty", 0))
                returned_qty = flt(item.get("returned_qty", 0))
                remaining_qty = source_qty + returned_qty - received_qty
                if remaining_qty > 0:
                    item.qty = remaining_qty
                    items_to_keep.append(item)
            else:
                items_to_keep.append(item)
        target.items = items_to_keep
    
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
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER SAME GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
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
        
        # Set is_bns_internal_supplier = 1 (TRANSFER UNDER SAME GSTIN)
        target_doc.is_bns_internal_supplier = 1
        
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
    }, update_modified=False)
    # Update bidirectional reference
    update_linked_doc("Purchase Receipt", pr_name, dn_name)


def _update_addresses(target_doc, source_doc) -> None:
    """Update addresses for internal transfer."""
    # For Purchase Receipt, swap shipping/dispatch addresses (inverse)
    if target_doc.doctype == "Purchase Receipt":
        # Company address becomes supplier address
        update_address(target_doc, "supplier_address", "address_display", source_doc.company_address)
        # Customer address becomes billing address
        update_address(target_doc, "billing_address", "billing_address_display", source_doc.customer_address)
        # Shipping address = Dispatch address from source (inverse)
        if source_doc.dispatch_address_name:
            update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.dispatch_address_name)
        else:
            # Clear shipping address if not in source document
            target_doc.shipping_address = None
            target_doc.shipping_address_name = None
            target_doc.shipping_address_display = None
        # Dispatch address = Shipping address from source (inverse)
        if source_doc.shipping_address_name:
            update_address(target_doc, "dispatch_address", "dispatch_address_display", source_doc.shipping_address_name)
        else:
            # Clear dispatch address if not in source document
            target_doc.dispatch_address = None
            target_doc.dispatch_address_name = None
            target_doc.dispatch_address_display = None
        # Clear templates for BNS internal transfers
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
    # Recalculate taxes based on supplier and addresses
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
    # Calculate quantity considering returned_qty and received_qty
    source_qty = flt(source.qty or 0)
    returned_qty = flt(source.returned_qty or 0)
    received_qty = flt(source.received_qty or 0)
    target.qty = source_qty + returned_qty - received_qty
    
    # Calculate stock_qty similarly
    source_stock_qty = flt(source.stock_qty or source_qty)
    target.stock_qty = source_stock_qty + returned_qty - received_qty
    
    # Map net_rate and base_net_rate from source (taxable rate)
    if source.get("net_rate"):
        target.net_rate = flt(source.net_rate)
    if source.get("base_net_rate"):
        target.base_net_rate = flt(source.base_net_rate)
    
    target.received_qty = 0
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
    Update the status of a Purchase Receipt based on is_bns_internal_supplier.
    
    TRANSFER UNDER SAME GSTIN (from DN):
    - is_bns_internal_supplier = 1
    - status = "BNS Internally Transferred"
    - per_billed = 100%
    
    TRANSFER UNDER DIFFERENT GSTIN (from SI):
    - is_bns_internal_supplier = 0
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
        is_bns_internal = doc.get("is_bns_internal_supplier") or False
        
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
        
        # Update is_bns_internal_supplier field
        if is_bns_internal != doc.get("is_bns_internal_supplier"):
            doc.is_bns_internal_supplier = is_bns_internal
        
        if is_bns_internal:
            # TRANSFER UNDER SAME GSTIN - from DN
            per_billed = 100
            doc.db_set("status", "BNS Internally Transferred", update_modified=False)
            doc.db_set("per_billed", per_billed, update_modified=False)
            doc.db_set("is_bns_internal_supplier", 1, update_modified=False)
            if doc.represents_company:
                doc.db_set("represents_company", doc.represents_company, update_modified=False)
            frappe.clear_cache(doctype="Purchase Receipt")
            logger.info(f"Updated Purchase Receipt {doc.name} status to BNS Internally Transferred (from DN)")
        else:
            # TRANSFER UNDER DIFFERENT GSTIN - from SI
            # Status should remain "To Bill" (default), but ensure it's set
            if doc.status != "To Bill":
                doc.db_set("status", "To Bill", update_modified=False)
            doc.db_set("is_bns_internal_supplier", 0, update_modified=False)
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
        
        # Validate inter-company party
        validate_inter_company_party("Purchase Invoice", si.customer, represents_company)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Sales Invoice",
            source_name,
            _get_sales_invoice_mapping(),
            target_doc,
            _set_missing_values_pi,
        )
        
        # Validate quantities
        validate_internal_transfer_qty(doclist)
        
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
            "condition": lambda item: flt(item.qty or 0) > 0,
            "postprocess": _update_item_pi,
        },
    }
    
    # Add warehouse, serial_no, batch_no mapping if update_stock is enabled
    # Note: We'll check this in postprocess, but prepare the mapping structure
    return mapping


def _set_missing_values_pi(source, target) -> None:
    """Set missing values for the target Purchase Invoice."""
    target.run_method("set_missing_values")
    
    # Get received items to track partial receipts
    received_items = get_received_items(source.name, "Purchase Invoice", "sales_invoice_item")
    
    # Filter items that have already been fully received
    if received_items and target.get("items"):
        items_to_keep = []
        for item in target.items:
            source_item_name = item.get("sales_invoice_item")
            item_code = item.get("item_code")
            if source_item_name and item_code:
                received_qty = received_items.get((source_item_name, item_code), 0)
                source_qty = flt(item.get("qty", 0))
                returned_qty = flt(item.get("returned_qty", 0))
                remaining_qty = source_qty + returned_qty - received_qty
                if remaining_qty > 0:
                    item.qty = remaining_qty
                    items_to_keep.append(item)
            else:
                items_to_keep.append(item)
        target.items = items_to_keep
            
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
    # Shipping address = Dispatch address from source (inverse)
    if source_doc.dispatch_address_name:
        update_address(target_doc, "shipping_address", "shipping_address_display", source_doc.dispatch_address_name)
    else:
        # Clear shipping address if not in source document
        target_doc.shipping_address = None
        target_doc.shipping_address_name = None
        target_doc.shipping_address_display = None
    # Dispatch address = Shipping address from source (inverse)
    if source_doc.shipping_address_name:
        update_address(target_doc, "dispatch_address", "dispatch_address_display", source_doc.shipping_address_name)
    else:
        # Clear dispatch address if not in source document
        target_doc.dispatch_address = None
        target_doc.dispatch_address_name = None
        target_doc.dispatch_address_display = None
    # Clear templates for BNS internal transfers
    target_doc.dispatch_address_template = None
    target_doc.shipping_address_template = None


def _update_taxes_pi(target_doc) -> None:
    """Update taxes for the purchase invoice."""
    # Recalculate taxes based on supplier and addresses
    update_taxes(
        target_doc,
        party=target_doc.supplier,
        party_type="Supplier",
        company=target_doc.company,
        doctype=target_doc.doctype,
        party_address=target_doc.supplier_address,
        company_address=target_doc.shipping_address,
    )


def _update_item_pi(source, target, source_parent) -> None:
    """Update item details for the purchase invoice item."""
    # Sales Invoice Item doesn't have returned_qty or received_qty fields
    # Use qty directly
    source_qty = flt(source.qty or 0)
    target.qty = source_qty
    
    # Calculate stock_qty similarly
    source_stock_qty = flt(source.stock_qty if hasattr(source, 'stock_qty') else source_qty)
    target.stock_qty = source_stock_qty
    
    # Map net_rate and base_net_rate from source (taxable rate)
    if source.get("net_rate"):
        target.net_rate = flt(source.net_rate)
    if source.get("base_net_rate"):
        target.base_net_rate = flt(source.base_net_rate)
    
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
        
        # Check if Purchase Invoice already exists for this Sales Invoice
        # If PI exists, PR should not be created (PI is for non-stock items, PR is for stock items)
        pi_exists = frappe.db.exists("Purchase Invoice", {
            "bns_inter_company_reference": si.name,
            "docstatus": 1
        })
        if not pi_exists:
            # Also check inter_company_invoice_reference for backward compatibility
            pi_exists = frappe.db.exists("Purchase Invoice", {
                "inter_company_invoice_reference": si.name,
                "docstatus": 1
            })
        
        if pi_exists:
            pi_name = pi_exists if isinstance(pi_exists, str) else frappe.db.get_value(
                "Purchase Invoice",
                {"bns_inter_company_reference": si.name, "docstatus": 1},
                "name"
            ) or frappe.db.get_value(
                "Purchase Invoice",
                {"inter_company_invoice_reference": si.name, "docstatus": 1},
                "name"
            )
            raise BNSValidationError(
                _("Purchase Invoice {0} already exists for Sales Invoice {1}. Purchase Receipt cannot be created when Purchase Invoice exists.").format(
                    get_link_to_form("Purchase Invoice", pi_name) if pi_name else "",
                    get_link_to_form("Sales Invoice", si.name)
                )
            )
        
        # Get representing company
        represents_company = _get_representing_company_from_customer(si.customer)
        
        # Validate inter-company party
        validate_inter_company_party("Purchase Receipt", si.customer, represents_company)
        
        # Create mapped document
        doclist = get_mapped_doc(
            "Sales Invoice",
            source_name,
            _get_sales_invoice_to_pr_mapping(),
            target_doc,
            _set_missing_values_pr_from_si,
        )
        
        # Validate quantities (using supplier_delivery_note as reference)
        # Note: For SI->PR, we validate against SI items
        if doclist.supplier_delivery_note == si.name:
            validate_internal_transfer_qty(doclist)
        
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
            "condition": lambda item: flt(item.qty or 0) > 0,  # Sales Invoice Item doesn't have returned_qty or received_qty
            "postprocess": _update_item_pr_from_si,
        },
    }


def _set_missing_values_pr_from_si(source, target) -> None:
    """Set missing values for the target Purchase Receipt from Sales Invoice."""
    target.run_method("set_missing_values")
    
    # Get received items to track partial receipts (using supplier_delivery_note as reference)
    # For SI->PR, we track via supplier_delivery_note field
    received_items = {}
    if source.name:
        # Find PRs created from this SI
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters={"supplier_delivery_note": source.name, "docstatus": 1},
            fields=["name"]
        )
        if pr_list:
            pr_names = [pr.name for pr in pr_list]
            pr_items = frappe.get_all(
                "Purchase Receipt Item",
                filters={"parent": ("in", pr_names)},
                fields=["sales_invoice_item", "item_code", "qty"]
            )
            for item in pr_items:
                key = (item.sales_invoice_item, item.item_code)
                received_items[key] = received_items.get(key, 0) + flt(item.qty)
    
    # Filter items that have already been fully received
    if received_items and target.get("items"):
        items_to_keep = []
        for item in target.items:
            source_item_name = item.get("sales_invoice_item")
            item_code = item.get("item_code")
            if source_item_name and item_code:
                received_qty = received_items.get((source_item_name, item_code), 0)
                source_qty = flt(item.get("qty", 0))
                returned_qty = flt(item.get("returned_qty", 0))
                remaining_qty = source_qty + returned_qty - received_qty
                if remaining_qty > 0:
                    item.qty = remaining_qty
                    items_to_keep.append(item)
            else:
                items_to_keep.append(item)
        target.items = items_to_keep
            
    if not target.get("items"):
        # Check if Purchase Invoice exists - if yes, show that in error
        pi_name = frappe.db.get_value(
            "Purchase Invoice",
            {"bns_inter_company_reference": source.name, "docstatus": 1},
            "name"
        ) or frappe.db.get_value(
            "Purchase Invoice",
            {"inter_company_invoice_reference": source.name, "docstatus": 1},
            "name"
        )
        
        if pi_name:
            raise BNSValidationError(
                _("Purchase Invoice {0} already exists for Sales Invoice {1}. Purchase Receipt cannot be created when Purchase Invoice exists.").format(
                    get_link_to_form("Purchase Invoice", pi_name),
                    get_link_to_form("Sales Invoice", source.name)
                )
            )
        else:
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
    # Sales Invoice Item doesn't have returned_qty or received_qty fields
    # Use qty directly
    source_qty = flt(source.qty or 0)
    target.qty = source_qty
    
    # Calculate stock_qty similarly
    source_stock_qty = flt(source.stock_qty if hasattr(source, 'stock_qty') else source_qty)
    target.stock_qty = source_stock_qty
    
    # Map net_rate and base_net_rate from source (taxable rate)
    if source.get("net_rate"):
        target.net_rate = flt(source.net_rate)
    if source.get("base_net_rate"):
        target.base_net_rate = flt(source.base_net_rate)
    
    target.received_qty = 0
    
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
        
        # Set bidirectional bns_inter_company_reference
        pi_name = None
        
        # Check if SI already has bns_inter_company_reference pointing to a PI
        if doc.bns_inter_company_reference and frappe.db.exists("Purchase Invoice", doc.bns_inter_company_reference):
            pi_name = doc.bns_inter_company_reference
        # Check if a PI exists with bill_no matching this SI name
        elif frappe.db.exists("Purchase Invoice", {"bill_no": doc.name, "docstatus": 1}):
            pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": doc.name, "docstatus": 1}, "name")
            # Set SI's bns_inter_company_reference if not already set
            if not doc.bns_inter_company_reference:
                doc.db_set("bns_inter_company_reference", pi_name, update_modified=False)
        
        # Update PI's bns_inter_company_reference to point back to SI
        if pi_name:
            pi = frappe.get_doc("Purchase Invoice", pi_name)
            if not pi.get("bns_inter_company_reference") or pi.bns_inter_company_reference != doc.name:
                pi.db_set("bns_inter_company_reference", doc.name, update_modified=False)
                # Also ensure PI status is updated if not already
                if pi.status != "BNS Internally Transferred":
                    pi.db_set("status", "BNS Internally Transferred", update_modified=False)
                # Ensure PI's is_bns_internal_supplier flag is set
                if not pi.get("is_bns_internal_supplier"):
                    pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
                frappe.clear_cache(doctype="Purchase Invoice")
                logger.info(f"Updated Purchase Invoice {pi_name} bns_inter_company_reference to {doc.name}")
        
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
        
        # Set bidirectional bns_inter_company_reference
        si_name = None
        
        # Check bns_inter_company_reference first
        if doc.bns_inter_company_reference and frappe.db.exists("Sales Invoice", doc.bns_inter_company_reference):
            si_name = doc.bns_inter_company_reference
        # Check bill_no (supplier_invoice_no) - if it matches an SI name, use it
        elif doc.bill_no and frappe.db.exists("Sales Invoice", {"name": doc.bill_no, "docstatus": 1}):
            si_name = doc.bill_no
            # Set PI's bns_inter_company_reference if not already set
            if not doc.bns_inter_company_reference:
                doc.db_set("bns_inter_company_reference", si_name, update_modified=False)
        # Check inter_company_invoice_reference for backward compatibility
        elif doc.inter_company_invoice_reference and frappe.db.exists("Sales Invoice", doc.inter_company_invoice_reference):
            si_name = doc.inter_company_invoice_reference
            # Set PI's bns_inter_company_reference if not already set
            if not doc.bns_inter_company_reference:
                doc.db_set("bns_inter_company_reference", si_name, update_modified=False)
        
        # Update SI's bns_inter_company_reference to point back to PI
        if si_name:
            si = frappe.get_doc("Sales Invoice", si_name)
            if not si.get("bns_inter_company_reference") or si.bns_inter_company_reference != doc.name:
                si.db_set("bns_inter_company_reference", doc.name, update_modified=False)
                # Also ensure SI status is updated if not already
                if si.status != "BNS Internally Transferred":
                    si.db_set("status", "BNS Internally Transferred", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")
                logger.info(f"Updated Sales Invoice {si_name} bns_inter_company_reference to {doc.name}")
        
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
def validate_si_pi_items_match(sales_invoice: str, purchase_invoice: str, check_all: bool = False) -> Dict:
    """
    Validate that all Sales Invoice items and quantities match Purchase Invoice items.
    Optionally also validates taxable values, grand totals, and taxes.
    
    Args:
        sales_invoice (str): Name of the Sales Invoice
        purchase_invoice (str): Name of the Purchase Invoice
        check_all (bool): If True, also validates taxable values, totals, and taxes
        
    Returns:
        Dict: Validation result with match status and details
    """
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Get SI items with taxable values
        si_items = {}
        for item in si.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            net_amount = flt(item.net_amount or 0)
            base_net_amount = flt(item.base_net_amount or 0)
            
            if item_code not in si_items:
                si_items[item_code] = {
                    "qty": 0, 
                    "stock_qty": 0,
                    "net_amount": 0,
                    "base_net_amount": 0
                }
            si_items[item_code]["qty"] += qty
            si_items[item_code]["stock_qty"] += stock_qty
            si_items[item_code]["net_amount"] += net_amount
            si_items[item_code]["base_net_amount"] += base_net_amount
        
        # Get PI items with taxable values
        pi_items = {}
        for item in pi.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            net_amount = flt(item.net_amount or 0)
            base_net_amount = flt(item.base_net_amount or 0)
            
            if item_code not in pi_items:
                pi_items[item_code] = {
                    "qty": 0, 
                    "stock_qty": 0,
                    "net_amount": 0,
                    "base_net_amount": 0
                }
            pi_items[item_code]["qty"] += qty
            pi_items[item_code]["stock_qty"] += stock_qty
            pi_items[item_code]["net_amount"] += net_amount
            pi_items[item_code]["base_net_amount"] += base_net_amount
        
        # Check if all SI items exist in PI and quantities match
        missing_items = []
        qty_mismatches = []
        taxable_value_mismatches = []
        
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
                
                # Check taxable value mismatch if check_all is True
                if check_all:
                    si_taxable_value = si_data["base_net_amount"] if si_data["base_net_amount"] > 0 else si_data["net_amount"]
                    pi_taxable_value = pi_data["base_net_amount"] if pi_data["base_net_amount"] > 0 else pi_data["net_amount"]
                    if abs(si_taxable_value - pi_taxable_value) > 0.01:
                        taxable_value_mismatches.append({
                            "item_code": item_code,
                            "si_taxable_value": si_taxable_value,
                            "pi_taxable_value": pi_taxable_value
                        })
        
        # Check if PI has extra items (not in SI)
        extra_items = []
        for item_code, pi_data in pi_items.items():
            if item_code not in si_items:
                extra_items.append({
                    "item_code": item_code,
                    "pi_qty": pi_data["qty"]
                })
        
        # Check grand total and tax mismatches if check_all is True
        grand_total_mismatch = None
        tax_mismatch = None
        
        if check_all:
            si_grand_total = flt(si.grand_total or 0)
            pi_grand_total = flt(pi.grand_total or 0)
            if abs(si_grand_total - pi_grand_total) > 0.01:
                grand_total_mismatch = {
                    "si_total": si_grand_total,
                    "pi_total": pi_grand_total,
                    "diff": si_grand_total - pi_grand_total
                }
            
            # Compare total taxes and charges in company currency
            si_base_taxes = flt(si.base_total_taxes_and_charges or 0)
            if si_base_taxes == 0:
                # Fallback to total_taxes_and_charges if base not available
                si_base_taxes = flt(si.total_taxes_and_charges or 0)
            pi_base_taxes = flt(pi.base_total_taxes_and_charges or 0)
            if pi_base_taxes == 0:
                # Fallback to total_taxes_and_charges if base not available
                pi_base_taxes = flt(pi.total_taxes_and_charges or 0)
            
            if abs(si_base_taxes - pi_base_taxes) > 0.01:
                tax_mismatch = {
                    "si_tax": si_base_taxes,
                    "pi_tax": pi_base_taxes,
                    "diff": si_base_taxes - pi_base_taxes
                }
        
        is_match = (
            len(missing_items) == 0 and 
            len(qty_mismatches) == 0 and 
            (not check_all or (
                len(taxable_value_mismatches) == 0 and 
                grand_total_mismatch is None and 
                tax_mismatch is None
            ))
        )
        
        result = {
            "match": is_match,
            "missing_items": missing_items,
            "qty_mismatches": qty_mismatches,
            "extra_items": extra_items,
            "message": _("Items and quantities match") if is_match else _("Items or quantities do not match")
        }
        
        if check_all:
            result.update({
                "taxable_value_mismatches": taxable_value_mismatches,
                "grand_total_mismatch": grand_total_mismatch,
                "tax_mismatch": tax_mismatch
            })
        
        return result
        
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
        
        # Check if already fully converted (both flag and status are set)
        if si.get("is_bns_internal_customer") and si.status == "BNS Internally Transferred":
            frappe.msgprint(_("Sales Invoice is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Sales Invoice (even if flag is already set, ensure status is updated)
        si.db_set("is_bns_internal_customer", 1, update_modified=False)
        si.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        result = {
            "success": True,
            "message": _("Sales Invoice converted to BNS Internally Transferred"),
            "sales_invoice": si.name
        }
        
        # Auto-find Purchase Invoice by bill_no if not provided
        if not purchase_invoice:
            pi_name = frappe.db.get_value("Purchase Invoice", {"bill_no": si.name, "docstatus": 1}, "name")
            if pi_name:
                purchase_invoice = pi_name
                logger.info(f"Auto-found Purchase Invoice {pi_name} for Sales Invoice {si.name} via bill_no")
        
        # If Purchase Invoice is found/provided, validate and link
        if purchase_invoice:
            pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
            
            # Validate PI is submitted
            if pi.docstatus != 1:
                raise BNSValidationError(_("Purchase Invoice {0} must be submitted before linking").format(purchase_invoice))
            
            # Validate items, quantities, rates, totals, and taxes (comprehensive check for auto-linking)
            validation_result = validate_si_pi_items_match(si.name, pi.name, check_all=True)
            if not validation_result.get("match"):
                missing = validation_result.get("missing_items", [])
                qty_mismatches = validation_result.get("qty_mismatches", [])
                taxable_value_mismatches = validation_result.get("taxable_value_mismatches", [])
                grand_total_mismatch = validation_result.get("grand_total_mismatch")
                tax_mismatch = validation_result.get("tax_mismatch")
                errors = []
                if missing:
                    for item in missing[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                if qty_mismatches:
                    for item in qty_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                if taxable_value_mismatches:
                    for item in taxable_value_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI Taxable Value ₹{1:.2f}, PI Taxable Value ₹{2:.2f}").format(
                            item["item_code"], item["si_taxable_value"], item["pi_taxable_value"]
                        ))
                if grand_total_mismatch:
                    errors.append(_("Grand Total: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        grand_total_mismatch["si_total"], grand_total_mismatch["pi_total"], abs(grand_total_mismatch["diff"])
                    ))
                if tax_mismatch:
                    errors.append(_("Total Taxes and Charges: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        tax_mismatch["si_tax"], tax_mismatch["pi_tax"], abs(tax_mismatch["diff"])
                    ))
                
                if len(missing) > 3 or len(qty_mismatches) > 3 or len(taxable_value_mismatches) > 3:
                    errors.append(_("... and more mismatches"))
                raise BNSValidationError(_("Items, quantities, taxable values, totals, or taxes do not match: {0}").format("; ".join(errors)))
            
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
        
        # Check if already fully converted (both flag and status are set)
        if pi.get("is_bns_internal_supplier") and pi.status == "BNS Internally Transferred":
            frappe.msgprint(_("Purchase Invoice is already marked as BNS Internally Transferred"))
            return {"success": True, "message": _("Already converted")}
        
        # Update Purchase Invoice (even if flag is already set, ensure status is updated)
        pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
        pi.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        result = {
            "success": True,
            "message": _("Purchase Invoice converted to BNS Internally Transferred"),
            "purchase_invoice": pi.name
        }
        
        # Auto-find Sales Invoice by bill_no if not provided
        if not sales_invoice and pi.bill_no:
            si_exists = frappe.db.exists("Sales Invoice", {"name": pi.bill_no, "docstatus": 1})
            if si_exists:
                sales_invoice = pi.bill_no
                logger.info(f"Auto-found Sales Invoice {sales_invoice} for Purchase Invoice {pi.name} via bill_no")
        
        # If Sales Invoice is found/provided, validate and link
        if sales_invoice:
            si = frappe.get_doc("Sales Invoice", sales_invoice)
            
            # Validate SI is submitted
            if si.docstatus != 1:
                raise BNSValidationError(_("Sales Invoice {0} must be submitted before linking").format(sales_invoice))
            
            # Validate items, quantities, rates, totals, and taxes (comprehensive check for auto-linking)
            validation_result = validate_si_pi_items_match(si.name, pi.name, check_all=True)
            if not validation_result.get("match"):
                missing = validation_result.get("missing_items", [])
                qty_mismatches = validation_result.get("qty_mismatches", [])
                taxable_value_mismatches = validation_result.get("taxable_value_mismatches", [])
                grand_total_mismatch = validation_result.get("grand_total_mismatch")
                tax_mismatch = validation_result.get("tax_mismatch")
                errors = []
                if missing:
                    for item in missing[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
                if qty_mismatches:
                    for item in qty_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
                if taxable_value_mismatches:
                    for item in taxable_value_mismatches[:3]:  # Show first 3
                        errors.append(_("Item {0}: SI Taxable Value ₹{1:.2f}, PI Taxable Value ₹{2:.2f}").format(
                            item["item_code"], item["si_taxable_value"], item["pi_taxable_value"]
                        ))
                if grand_total_mismatch:
                    errors.append(_("Grand Total: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        grand_total_mismatch["si_total"], grand_total_mismatch["pi_total"], abs(grand_total_mismatch["diff"])
                    ))
                if tax_mismatch:
                    errors.append(_("Total Taxes and Charges: SI ₹{0:.2f} vs PI ₹{1:.2f} (Diff: ₹{2:.2f})").format(
                        tax_mismatch["si_tax"], tax_mismatch["pi_tax"], abs(tax_mismatch["diff"])
                    ))
                
                if len(missing) > 3 or len(qty_mismatches) > 3 or len(taxable_value_mismatches) > 3:
                    errors.append(_("... and more mismatches"))
                raise BNSValidationError(_("Items, quantities, taxable values, totals, or taxes do not match: {0}").format("; ".join(errors)))
            
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
            "is_bns_internal_supplier": pr.get("is_bns_internal_supplier") or 0,
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
        
        # Check if already fully converted (both flag and status are set)
        if dn.get("is_bns_internal_customer") and dn.status == "BNS Internally Transferred":
            # Already converted, but still return success for bulk operations
            return {"success": True, "message": _("Already converted")}
        
        # Update Delivery Note (even if flag is already set, ensure status is updated)
        dn.db_set("is_bns_internal_customer", 1, update_modified=False)
        dn.db_set("status", "BNS Internally Transferred", update_modified=False)
        dn.db_set("per_billed", 100, update_modified=False)
        
        # Clear cache to ensure changes are reflected
        frappe.clear_cache(doctype="Delivery Note")
        
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
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
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
        
        # Check if already fully converted (both flag and status are set)
        if pr.get("is_bns_internal_supplier") and pr.status == "BNS Internally Transferred":
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
        
        # Update Purchase Receipt (even if flag is already set, ensure status is updated)
        pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
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


def validate_bns_internal_customer_return(doc, method: Optional[str] = None) -> None:
    """
    Block return entries (Credit Notes) for BNS internal customers.
    
    Args:
        doc: The Sales Invoice document
        method (Optional[str]): The method being called
    """
    if not doc.is_return or not doc.return_against:
        return
    
    try:
        # Get the original Sales Invoice
        original_si = frappe.get_doc("Sales Invoice", doc.return_against)
        
        # Check if original SI is for BNS internal customer
        is_bns_internal = original_si.get("is_bns_internal_customer") or False
        if not is_bns_internal:
            # Check customer's is_bns_internal_customer field
            customer_internal = frappe.db.get_value("Customer", original_si.customer, "is_bns_internal_customer")
            if customer_internal:
                is_bns_internal = True
        
        if is_bns_internal:
            frappe.throw(
                _("Returns (Credit Notes) are not allowed for BNS Internal Customers. Original Sales Invoice {0} is for a BNS Internal Customer.").format(
                    get_link_to_form("Sales Invoice", doc.return_against)
                ),
                title=_("Return Not Allowed")
            )
    except frappe.DoesNotExistError:
        # Original document doesn't exist, let ERPNext handle this validation
        pass
    except Exception as e:
        logger.error(f"Error validating BNS internal customer return for Sales Invoice: {str(e)}")
        # Don't block if there's an error, but log it
        pass


def validate_bns_internal_delivery_note_return(doc, method: Optional[str] = None) -> None:
    """
    Block return entries for Delivery Notes with BNS internal customers.
    
    Args:
        doc: The Delivery Note document
        method (Optional[str]): The method being called
    """
    if not doc.is_return or not doc.return_against:
        return
    
    try:
        # Get the original Delivery Note
        original_dn = frappe.get_doc("Delivery Note", doc.return_against)
        
        # Check if original DN is for BNS internal customer
        is_bns_internal = original_dn.get("is_bns_internal_customer") or False
        if not is_bns_internal:
            # Check customer's is_bns_internal_customer field
            customer_internal = frappe.db.get_value("Customer", original_dn.customer, "is_bns_internal_customer")
            if customer_internal:
                is_bns_internal = True
        
        if is_bns_internal:
            frappe.throw(
                _("Returns are not allowed for BNS Internal Customers. Original Delivery Note {0} is for a BNS Internal Customer.").format(
                    get_link_to_form("Delivery Note", doc.return_against)
                ),
                title=_("Return Not Allowed")
            )
    except frappe.DoesNotExistError:
        # Original document doesn't exist, let ERPNext handle this validation
        pass
    except Exception as e:
        logger.error(f"Error validating BNS internal customer return for Delivery Note: {str(e)}")
        # Don't block if there's an error, but log it
        pass


@frappe.whitelist()
def validate_dn_pr_items_match(delivery_note: str, purchase_receipt: str) -> Dict:
    """
    Validate that Delivery Note and Purchase Receipt items match.
    
    Args:
        delivery_note (str): Delivery Note name
        purchase_receipt (str): Purchase Receipt name
        
    Returns:
        Dict: Validation result with match status and details
    """
    try:
        dn = frappe.get_doc("Delivery Note", delivery_note)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Get DN items aggregated by item_code
        dn_items = {}
        for item in dn.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            
            if item_code not in dn_items:
                dn_items[item_code] = {"qty": 0, "stock_qty": 0}
            dn_items[item_code]["qty"] += qty
            dn_items[item_code]["stock_qty"] += stock_qty
        
        # Get PR items aggregated by item_code
        pr_items = {}
        for item in pr.items:
            item_code = item.item_code
            qty = flt(item.qty or 0)
            stock_qty = flt(item.stock_qty or qty)
            
            if item_code not in pr_items:
                pr_items[item_code] = {"qty": 0, "stock_qty": 0}
            pr_items[item_code]["qty"] += qty
            pr_items[item_code]["stock_qty"] += stock_qty
        
        # Check if all DN items exist in PR and quantities match
        missing_items = []
        qty_mismatches = []
        
        for item_code, dn_data in dn_items.items():
            if item_code not in pr_items:
                missing_items.append({
                    "item_code": item_code,
                    "dn_qty": dn_data["qty"],
                    "pr_qty": 0
                })
            elif flt(dn_data["qty"]) != flt(pr_items[item_code]["qty"]):
                qty_mismatches.append({
                    "item_code": item_code,
                    "dn_qty": dn_data["qty"],
                    "pr_qty": pr_items[item_code]["qty"]
                })
        
        # Check if PR has extra items not in DN
        extra_items = []
        for item_code in pr_items:
            if item_code not in dn_items:
                extra_items.append({
                    "item_code": item_code,
                    "dn_qty": 0,
                    "pr_qty": pr_items[item_code]["qty"]
                })
        
        if missing_items or qty_mismatches or extra_items:
            error_msg = _("Item mismatches found:\n")
            
            if missing_items:
                error_msg += _("\nMissing items in Purchase Receipt:\n")
                for item in missing_items:
                    error_msg += _("  - {0}: DN qty = {1}, PR qty = {2}\n").format(
                        item["item_code"], item["dn_qty"], item["pr_qty"]
                    )
            
            if qty_mismatches:
                error_msg += _("\nQuantity mismatches:\n")
                for item in qty_mismatches:
                    error_msg += _("  - {0}: DN qty = {1}, PR qty = {2}\n").format(
                        item["item_code"], item["dn_qty"], item["pr_qty"]
                    )
            
            if extra_items:
                error_msg += _("\nExtra items in Purchase Receipt:\n")
                for item in extra_items:
                    error_msg += _("  - {0}: DN qty = {1}, PR qty = {2}\n").format(
                        item["item_code"], item["dn_qty"], item["pr_qty"]
                    )
            
            return {
                "match": False,
                "error": error_msg,
                "missing_items": missing_items,
                "qty_mismatches": qty_mismatches,
                "extra_items": extra_items
            }
        
        return {
            "match": True,
            "message": _("All items match successfully")
        }
        
    except Exception as e:
        logger.error(f"Error validating DN-PR items match: {str(e)}")
        frappe.throw(_("Error validating items: {0}").format(str(e)))


@frappe.whitelist()
def link_dn_pr(delivery_note: str, purchase_receipt: str) -> Dict:
    """
    Link a Delivery Note with a Purchase Receipt for BNS Internal transfer.
    
    Args:
        delivery_note (str): Delivery Note name
        purchase_receipt (str): Purchase Receipt name
        
    Returns:
        Dict: Result with success message
    """
    try:
        dn = frappe.get_doc("Delivery Note", delivery_note)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Validate both documents are submitted
        if dn.docstatus != 1:
            raise BNSValidationError(_("Delivery Note must be submitted before linking"))
        
        if pr.docstatus != 1:
            raise BNSValidationError(_("Purchase Receipt must be submitted before linking"))
        
        # Validate PR's supplier_delivery_note matches DN name (only if supplier_delivery_note is set)
        # Allow linking even if supplier_delivery_note is empty or doesn't match
        if pr.supplier_delivery_note and pr.supplier_delivery_note != dn.name:
            # If supplier_delivery_note is set but doesn't match, warn but allow
            logger.warning(f"Purchase Receipt {purchase_receipt} has supplier_delivery_note {pr.supplier_delivery_note} but linking to {delivery_note}")
            # Don't raise error - allow manual linking
        
        # Validate GSTIN match (same GSTIN only)
        dn_billing_gstin = getattr(dn, 'billing_address_gstin', None)
        dn_company_gstin = getattr(dn, 'company_gstin', None)
        
        if not dn_billing_gstin or not dn_company_gstin:
            raise BNSValidationError(_("Delivery Note GSTIN information is missing"))
        
        if dn_billing_gstin != dn_company_gstin:
            raise BNSValidationError(
                _("GSTIN mismatch: Only same GSTIN transfers can be linked. billing_address_gstin ({0}) != company_gstin ({1})").format(
                    dn_billing_gstin, dn_company_gstin
                )
            )
        
        # Validate customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(dn.customer))
        
        # Check if already linked
        if dn.get("bns_inter_company_reference") == pr.name and pr.get("bns_inter_company_reference") == dn.name:
            frappe.msgprint(_("Delivery Note and Purchase Receipt are already linked"))
            return {"success": True, "message": _("Already linked")}
        
        # Check if DN is already linked to another PR
        if dn.get("bns_inter_company_reference") and dn.get("bns_inter_company_reference") != pr.name:
            raise BNSValidationError(
                _("Delivery Note {0} is already linked to Purchase Receipt {1}").format(
                    delivery_note, dn.get("bns_inter_company_reference")
                )
            )
        
        # Check if PR is already linked to another DN
        if pr.get("bns_inter_company_reference") and pr.get("bns_inter_company_reference") != dn.name:
            raise BNSValidationError(
                _("Purchase Receipt {0} is already linked to Delivery Note {1}").format(
                    purchase_receipt, pr.get("bns_inter_company_reference")
                )
            )
        
        # Validate items match
        items_validation = validate_dn_pr_items_match(delivery_note, purchase_receipt)
        if not items_validation.get("match"):
            raise BNSValidationError(_("Items do not match: {0}").format(items_validation.get("error")))
        
        # Set bidirectional references
        dn.db_set("bns_inter_company_reference", pr.name, update_modified=False)
        pr.db_set("bns_inter_company_reference", dn.name, update_modified=False)
        
        # Update status and flags if not already set
        if not dn.get("is_bns_internal_customer"):
            dn.db_set("is_bns_internal_customer", 1, update_modified=False)
        if dn.status != "BNS Internally Transferred":
            dn.db_set("status", "BNS Internally Transferred", update_modified=False)
        if dn.per_billed != 100:
            dn.db_set("per_billed", 100, update_modified=False)
        
        if not pr.get("is_bns_internal_supplier"):
            pr.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if pr.status != "BNS Internally Transferred":
            pr.db_set("status", "BNS Internally Transferred", update_modified=False)
        if pr.per_billed != 100:
            pr.db_set("per_billed", 100, update_modified=False)
        
        # Clear cache
        frappe.clear_cache(doctype="Delivery Note")
        frappe.clear_cache(doctype="Purchase Receipt")
        
        logger.info(f"Linked Delivery Note {delivery_note} with Purchase Receipt {purchase_receipt}")
        
        return {
            "success": True,
            "message": _("Delivery Note and Purchase Receipt linked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error linking DN-PR: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def unlink_dn_pr(delivery_note: str = None, purchase_receipt: str = None) -> Dict:
    """
    Unlink a Delivery Note and Purchase Receipt.
    
    This function allows unlinking from either side, even if the other side
    doesn't have the reference set. It will clear references on both sides
    if they exist, but won't fail if one side is missing.
    
    Args:
        delivery_note (str): Delivery Note name (optional if purchase_receipt provided)
        purchase_receipt (str): Purchase Receipt name (optional if delivery_note provided)
        
    Returns:
        Dict: Result with success message
    """
    try:
        if not delivery_note and not purchase_receipt:
            raise BNSValidationError(_("Either delivery_note or purchase_receipt must be provided"))
        
        # If only one is provided, get the other from the reference
        if delivery_note and not purchase_receipt:
            dn = frappe.get_doc("Delivery Note", delivery_note)
            purchase_receipt = dn.get("bns_inter_company_reference")
            if not purchase_receipt:
                # DN doesn't have reference, but still allow clearing if needed
                # Just clear DN's reference and return
                dn.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Delivery Note")
                logger.info(f"Cleared reference from Delivery Note {delivery_note} (no PR reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Delivery Note")
                }
        
        if purchase_receipt and not delivery_note:
            pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
            delivery_note = pr.get("bns_inter_company_reference")
            if not delivery_note:
                # PR doesn't have reference, but still allow clearing if needed
                # Just clear PR's reference and return
                pr.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Purchase Receipt")
                logger.info(f"Cleared reference from Purchase Receipt {purchase_receipt} (no DN reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Purchase Receipt")
                }
        
        # Validate both documents exist
        dn = frappe.get_doc("Delivery Note", delivery_note)
        pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
        
        # Remove bidirectional references - clear both sides regardless of current state
        # This allows unlinking even if one side doesn't have the reference
        if dn.get("bns_inter_company_reference"):
            dn.db_set("bns_inter_company_reference", "", update_modified=False)
        
        if pr.get("bns_inter_company_reference"):
            pr.db_set("bns_inter_company_reference", "", update_modified=False)
        
        # Note: We don't change status or flags as they might be set for other reasons
        # Only remove the inter-company reference
        
        # Clear cache
        frappe.clear_cache(doctype="Delivery Note")
        frappe.clear_cache(doctype="Purchase Receipt")
        
        logger.info(f"Unlinked Delivery Note {delivery_note} from Purchase Receipt {purchase_receipt}")
        
        return {
            "success": True,
            "message": _("Delivery Note and Purchase Receipt unlinked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error unlinking DN-PR: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def link_si_pi(sales_invoice: str, purchase_invoice: str) -> Dict:
    """
    Link a Sales Invoice with a Purchase Invoice for BNS Internal transfer.
    
    Args:
        sales_invoice (str): Sales Invoice name
        purchase_invoice (str): Purchase Invoice name
        
    Returns:
        Dict: Result with success message
    """
    try:
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Validate both documents are submitted
        if si.docstatus != 1:
            raise BNSValidationError(_("Sales Invoice must be submitted before linking"))
        
        if pi.docstatus != 1:
            raise BNSValidationError(_("Purchase Invoice must be submitted before linking"))
        
        # Validate PI's bill_no matches SI name (only if bill_no is set)
        # Allow linking even if bill_no is empty or doesn't match
        if pi.bill_no and pi.bill_no != si.name:
            logger.warning(f"Purchase Invoice {purchase_invoice} has bill_no {pi.bill_no} but linking to {sales_invoice}")
            # Don't raise error - allow manual linking
        
        # Validate customer is BNS internal
        customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
        if not customer_internal:
            raise BNSValidationError(_("Customer {0} is not marked as BNS Internal Customer").format(si.customer))
        
        # Validate supplier is BNS internal
        supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
        if not supplier_internal:
            raise BNSValidationError(_("Supplier {0} is not marked as BNS Internal Supplier").format(pi.supplier))
        
        # Validate inter-company party relationships using centralized function
        # This validates both directions: SI customer represents PI company, and PI supplier represents SI company
        validate_inter_company_party("Sales Invoice", si.customer, si.company, inter_company_reference=pi.name)
        
        # Check if already linked
        if si.get("bns_inter_company_reference") == pi.name and pi.get("bns_inter_company_reference") == si.name:
            frappe.msgprint(_("Sales Invoice and Purchase Invoice are already linked"))
            return {"success": True, "message": _("Already linked")}
        
        # Check if SI is already linked to another PI
        if si.get("bns_inter_company_reference") and si.get("bns_inter_company_reference") != pi.name:
            raise BNSValidationError(
                _("Sales Invoice {0} is already linked to Purchase Invoice {1}").format(
                    sales_invoice, si.get("bns_inter_company_reference")
                )
            )
        
        # Check if PI is already linked to another SI
        if pi.get("bns_inter_company_reference") and pi.get("bns_inter_company_reference") != si.name:
            raise BNSValidationError(
                _("Purchase Invoice {0} is already linked to Sales Invoice {1}").format(
                    purchase_invoice, pi.get("bns_inter_company_reference")
                )
            )
        
        # Validate items match
        items_validation = validate_si_pi_items_match(sales_invoice, purchase_invoice)
        if not items_validation.get("match"):
            missing = items_validation.get("missing_items", [])
            qty_mismatches = items_validation.get("qty_mismatches", [])
            errors = []
            if missing:
                for item in missing[:3]:
                    errors.append(_("Item {0}: SI has {1}, PI missing").format(item["item_code"], item["si_qty"]))
            if qty_mismatches:
                for item in qty_mismatches[:3]:
                    errors.append(_("Item {0}: SI has {1}, PI has {2}").format(item["item_code"], item["si_qty"], item["pi_qty"]))
            if len(missing) > 3 or len(qty_mismatches) > 3:
                errors.append(_("... and more items"))
            raise BNSValidationError(_("Items do not match: {0}").format("; ".join(errors)))
        
        # Set bidirectional references
        si.db_set("bns_inter_company_reference", pi.name, update_modified=False)
        pi.db_set("bns_inter_company_reference", si.name, update_modified=False)
        
        # Set item-wise references for PI items
        si_items = si.items
        pi_items = pi.items
        
        if len(si_items) == len(pi_items):
            for si_item, pi_item in zip(si_items, pi_items):
                if si_item.item_code == pi_item.item_code:
                    pi_item.db_set("sales_invoice_item", si_item.name, update_modified=False)
        
        # Update status and flags if not already set
        if not si.get("is_bns_internal_customer"):
            si.db_set("is_bns_internal_customer", 1, update_modified=False)
        if si.status != "BNS Internally Transferred":
            si.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        if not pi.get("is_bns_internal_supplier"):
            pi.db_set("is_bns_internal_supplier", 1, update_modified=False)
        if pi.status != "BNS Internally Transferred":
            pi.db_set("status", "BNS Internally Transferred", update_modified=False)
        
        # Clear cache
        frappe.clear_cache(doctype="Sales Invoice")
        frappe.clear_cache(doctype="Purchase Invoice")
        
        logger.info(f"Linked Sales Invoice {sales_invoice} with Purchase Invoice {purchase_invoice}")
        
        return {
            "success": True,
            "message": _("Sales Invoice and Purchase Invoice linked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error linking SI-PI: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def unlink_si_pi(sales_invoice: str = None, purchase_invoice: str = None) -> Dict:
    """
    Unlink a Sales Invoice and Purchase Invoice.
    
    This function allows unlinking from either side, even if the other side
    doesn't have the reference set. It will clear references on both sides
    if they exist, but won't fail if one side is missing.
    
    Args:
        sales_invoice (str): Sales Invoice name (optional if purchase_invoice provided)
        purchase_invoice (str): Purchase Invoice name (optional if sales_invoice provided)
        
    Returns:
        Dict: Result with success message
    """
    try:
        if not sales_invoice and not purchase_invoice:
            raise BNSValidationError(_("Either sales_invoice or purchase_invoice must be provided"))
        
        # If only one is provided, get the other from the reference
        if sales_invoice and not purchase_invoice:
            si = frappe.get_doc("Sales Invoice", sales_invoice)
            purchase_invoice = si.get("bns_inter_company_reference")
            if not purchase_invoice:
                # SI doesn't have reference, but still allow clearing if needed
                si.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Sales Invoice")
                logger.info(f"Cleared reference from Sales Invoice {sales_invoice} (no PI reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Sales Invoice")
                }
        
        if purchase_invoice and not sales_invoice:
            pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
            sales_invoice = pi.get("bns_inter_company_reference")
            if not sales_invoice:
                # PI doesn't have reference, but still allow clearing if needed
                pi.db_set("bns_inter_company_reference", "", update_modified=False)
                frappe.clear_cache(doctype="Purchase Invoice")
                logger.info(f"Cleared reference from Purchase Invoice {purchase_invoice} (no SI reference found)")
                return {
                    "success": True,
                    "message": _("Cleared reference from Purchase Invoice")
                }
        
        # Validate both documents exist
        si = frappe.get_doc("Sales Invoice", sales_invoice)
        pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
        
        # Remove bidirectional references - clear both sides regardless of current state
        if si.get("bns_inter_company_reference"):
            si.db_set("bns_inter_company_reference", "", update_modified=False)
        
        if pi.get("bns_inter_company_reference"):
            pi.db_set("bns_inter_company_reference", "", update_modified=False)
        
        # Clear item-wise references
        pi_items = pi.items
        for pi_item in pi_items:
            if pi_item.get("sales_invoice_item"):
                pi_item.db_set("sales_invoice_item", "", update_modified=False)
        
        # Note: We don't change status or flags as they might be set for other reasons
        # Only remove the inter-company reference
        
        # Clear cache
        frappe.clear_cache(doctype="Sales Invoice")
        frappe.clear_cache(doctype="Purchase Invoice")
        
        logger.info(f"Unlinked Sales Invoice {sales_invoice} from Purchase Invoice {purchase_invoice}")
        
        return {
            "success": True,
            "message": _("Sales Invoice and Purchase Invoice unlinked successfully")
        }
        
    except Exception as e:
        logger.error(f"Error unlinking SI-PI: {str(e)}")
        frappe.throw(str(e))


@frappe.whitelist()
def get_bulk_conversion_preview(from_date: str, force: int = 0) -> Dict:
    """
    Get preview of documents that can be bulk converted to BNS Internal.
    
    Args:
        from_date (str): Date filter (YYYY-MM-DD)
        force (int): If 1, include documents even if flag is already set
        
    Returns:
        Dict: Counts of documents that can be converted
    """
    try:
        from_date_obj = frappe.utils.getdate(from_date)
        
        # Build filters
        si_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["customer", "!=", ""]
        ]
        
        pi_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["supplier", "!=", ""]
        ]
        
        dn_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["customer", "!=", ""]
        ]
        
        pr_filters = [
            ["docstatus", "=", 1],
            ["posting_date", ">=", from_date_obj],
            ["supplier_delivery_note", "!=", ""]
        ]
        
        # Get counts for Sales Invoice
        si_count = 0
        si_list = frappe.get_all(
            "Sales Invoice",
            filters=si_filters,
            fields=["name", "customer", "is_bns_internal_customer", "status"],
            limit=10000
        )
        for si in si_list:
            customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
            if customer_internal:
                if force or not si.get("is_bns_internal_customer") or si.status != "BNS Internally Transferred":
                    si_count += 1
        
        # Get counts for Purchase Invoice
        pi_count = 0
        pi_list = frappe.get_all(
            "Purchase Invoice",
            filters=pi_filters,
            fields=["name", "supplier", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pi in pi_list:
            supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
            if supplier_internal:
                if force or not pi.get("is_bns_internal_supplier") or pi.status != "BNS Internally Transferred":
                    pi_count += 1
        
        # Get counts for Delivery Note (same GSTIN only)
        dn_count = 0
        dn_list = frappe.get_all(
            "Delivery Note",
            filters=dn_filters,
            fields=["name", "customer", "is_bns_internal_customer", "status", "billing_address_gstin", "company_gstin"],
            limit=10000
        )
        for dn in dn_list:
            customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
            if customer_internal:
                # Check GSTIN match (same GSTIN only)
                billing_gstin = dn.get("billing_address_gstin")
                company_gstin = dn.get("company_gstin")
                if billing_gstin and company_gstin and billing_gstin == company_gstin:
                    if force or not dn.get("is_bns_internal_customer") or dn.status != "BNS Internally Transferred":
                        dn_count += 1
        
        # Get counts for Purchase Receipt (from DN with same GSTIN)
        pr_count = 0
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters=pr_filters,
            fields=["name", "supplier_delivery_note", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pr in pr_list:
            if pr.supplier_delivery_note:
                # Check if supplier_delivery_note is a Delivery Note
                if frappe.db.exists("Delivery Note", pr.supplier_delivery_note):
                    dn_name = pr.supplier_delivery_note
                    dn_customer = frappe.db.get_value("Delivery Note", dn_name, "customer")
                    if dn_customer:
                        customer_internal = frappe.db.get_value("Customer", dn_customer, "is_bns_internal_customer")
                        if customer_internal:
                            # Check GSTIN match
                            dn_billing_gstin = frappe.db.get_value("Delivery Note", dn_name, "billing_address_gstin")
                            dn_company_gstin = frappe.db.get_value("Delivery Note", dn_name, "company_gstin")
                            if dn_billing_gstin and dn_company_gstin and dn_billing_gstin == dn_company_gstin:
                                if force or not pr.get("is_bns_internal_supplier") or pr.status != "BNS Internally Transferred":
                                    pr_count += 1
        
        total_count = si_count + pi_count + dn_count + pr_count
        
        return {
            "sales_invoice_count": si_count,
            "purchase_invoice_count": pi_count,
            "delivery_note_count": dn_count,
            "purchase_receipt_count": pr_count,
            "total_count": total_count
        }
        
    except Exception as e:
        logger.error(f"Error getting bulk conversion preview: {str(e)}")
        frappe.throw(_("Error getting preview: {0}").format(str(e)))


@frappe.whitelist()
def bulk_convert_to_bns_internal(from_date: str, force: int = 0) -> Dict:
    """
    Bulk convert documents to BNS Internally Transferred status.
    
    Args:
        from_date (str): Date filter (YYYY-MM-DD)
        force (int): If 1, update even if flag is already set
        
    Returns:
        Dict: Results with counts of converted documents
    """
    try:
        from_date_obj = frappe.utils.getdate(from_date)
        converted = {
            "sales_invoice": 0,
            "purchase_invoice": 0,
            "delivery_note": 0,
            "purchase_receipt": 0
        }
        
        # Convert Sales Invoices
        si_list = frappe.get_all(
            "Sales Invoice",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["customer", "!=", ""]
            ],
            fields=["name", "customer", "is_bns_internal_customer", "status"],
            limit=10000
        )
        for si in si_list:
            customer_internal = frappe.db.get_value("Customer", si.customer, "is_bns_internal_customer")
            if customer_internal:
                if force or not si.get("is_bns_internal_customer") or si.status != "BNS Internally Transferred":
                    try:
                        convert_sales_invoice_to_bns_internal(si.name, None)
                        converted["sales_invoice"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Sales Invoice {si.name}: {str(e)}")
                        continue
        
        # Convert Purchase Invoices
        pi_list = frappe.get_all(
            "Purchase Invoice",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["supplier", "!=", ""]
            ],
            fields=["name", "supplier", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pi in pi_list:
            supplier_internal = frappe.db.get_value("Supplier", pi.supplier, "is_bns_internal_supplier")
            if supplier_internal:
                if force or not pi.get("is_bns_internal_supplier") or pi.status != "BNS Internally Transferred":
                    try:
                        convert_purchase_invoice_to_bns_internal(pi.name, None)
                        converted["purchase_invoice"] += 1
                    except Exception as e:
                        logger.error(f"Error converting Purchase Invoice {pi.name}: {str(e)}")
                        continue
        
        # Convert Delivery Notes (same GSTIN only)
        dn_list = frappe.get_all(
            "Delivery Note",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["customer", "!=", ""]
            ],
            fields=["name", "customer", "is_bns_internal_customer", "status", "billing_address_gstin", "company_gstin"],
            limit=10000
        )
        for dn in dn_list:
            customer_internal = frappe.db.get_value("Customer", dn.customer, "is_bns_internal_customer")
            if customer_internal:
                billing_gstin = dn.get("billing_address_gstin")
                company_gstin = dn.get("company_gstin")
                if billing_gstin and company_gstin and billing_gstin == company_gstin:
                    if force or not dn.get("is_bns_internal_customer") or dn.status != "BNS Internally Transferred":
                        try:
                            result = convert_delivery_note_to_bns_internal(dn.name, None)
                            if result.get("success"):
                                converted["delivery_note"] += 1
                        except Exception as e:
                            logger.error(f"Error converting Delivery Note {dn.name}: {str(e)}")
                            frappe.log_error(f"Error converting Delivery Note {dn.name}: {str(e)}", "BNS Bulk Conversion")
                            continue
        
        # Convert Purchase Receipts (from DN with same GSTIN)
        pr_list = frappe.get_all(
            "Purchase Receipt",
            filters=[
                ["docstatus", "=", 1],
                ["posting_date", ">=", from_date_obj],
                ["supplier_delivery_note", "!=", ""]
            ],
            fields=["name", "supplier_delivery_note", "is_bns_internal_supplier", "status"],
            limit=10000
        )
        for pr in pr_list:
            if pr.supplier_delivery_note and frappe.db.exists("Delivery Note", pr.supplier_delivery_note):
                dn_name = pr.supplier_delivery_note
                dn_customer = frappe.db.get_value("Delivery Note", dn_name, "customer")
                if dn_customer:
                    customer_internal = frappe.db.get_value("Customer", dn_customer, "is_bns_internal_customer")
                    if customer_internal:
                        dn_billing_gstin = frappe.db.get_value("Delivery Note", dn_name, "billing_address_gstin")
                        dn_company_gstin = frappe.db.get_value("Delivery Note", dn_name, "company_gstin")
                        if dn_billing_gstin and dn_company_gstin and dn_billing_gstin == dn_company_gstin:
                            if force or not pr.get("is_bns_internal_supplier") or pr.status != "BNS Internally Transferred":
                                try:
                                    convert_purchase_receipt_to_bns_internal(pr.name, None)
                                    converted["purchase_receipt"] += 1
                                except Exception as e:
                                    logger.error(f"Error converting Purchase Receipt {pr.name}: {str(e)}")
                                    continue
        
        total_converted = converted["sales_invoice"] + converted["purchase_invoice"] + converted["delivery_note"] + converted["purchase_receipt"]
        
        return {
            "success": True,
            "total_converted": total_converted,
            "details": converted,
            "message": _("Converted {0} Sales Invoice(s), {1} Purchase Invoice(s), {2} Delivery Note(s), {3} Purchase Receipt(s)").format(
                converted["sales_invoice"],
                converted["purchase_invoice"],
                converted["delivery_note"],
                converted["purchase_receipt"]
            )
        }
        
    except Exception as e:
        logger.error(f"Error in bulk conversion: {str(e)}")
        frappe.throw(_("Error in bulk conversion: {0}").format(str(e)))