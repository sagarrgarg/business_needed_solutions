"""
Business Needed Solutions - Stock Update Validation System

This module provides validation for Sales Invoice and Purchase Invoice documents,
ensuring that when stock updates are disabled, all stock items are properly referenced
from their respective source documents.

Note: Purchase Invoice against Purchase Receipt must have Update Stock unchecked
(ERPNext enforces this). This validation then only requires that all stock items
have purchase_receipt / pr_detail set (standard PI Item fields).
"""

import frappe
from frappe import _
from typing import Optional, List
import logging
from frappe.utils import cint
from business_needed_solutions.bns_branch_accounting.utils import (
    is_after_internal_validation_cutoff,
    validate_internal_purchase_invoice_linkage,
)

# Configure logging
logger = logging.getLogger(__name__)


class StockUpdateValidationError(Exception):
    """Custom exception for stock update validation errors."""
    pass


def validate_stock_update_or_reference(doc, method: Optional[str] = None) -> None:
    """
    Validate if either update_stock is enabled or all items are referenced 
    from Purchase Receipt or Delivery Note based on BNS Settings configuration.
    
    This function ensures that when stock updates are disabled in Sales Invoice or
    Purchase Invoice, all stock items must be referenced from their respective
    source documents (Delivery Note for Sales Invoice, Purchase Receipt for Purchase Invoice).
    
    Args:
        doc: The Sales Invoice or Purchase Invoice document being validated
        method (Optional[str]): The method being called
        
    Raises:
        StockUpdateValidationError: If validation fails
    """
    try:
        # Check if validation is enabled in BNS Settings
        if not _is_stock_update_validation_enabled():
            logger.debug("Stock update validation is disabled in BNS Settings")
            return
        
        # Only apply to Sales Invoice and Purchase Invoice
        if doc.doctype not in ["Sales Invoice", "Purchase Invoice"]:
            logger.debug(f"Validation skipped for non-invoice doctype: {doc.doctype}")
            return

        # ERPNext "Is Rate Adjustment Entry (Debit Note)" invoices are value-only
        # adjustments and must not carry Delivery Note links; no stock reference
        # check applies.
        if _is_sales_invoice_rate_adjustment_debit_note(doc):
            _validate_sales_invoice_rate_adjustment_without_dn_links(doc)
            logger.debug(
                "Sales Invoice %s is a rate-adjustment debit note, skipping reference validation",
                doc.name,
            )
            return

        # If update_stock is enabled, no need to check references
        if doc.update_stock:
            logger.debug(f"Stock update enabled for {doc.doctype} {doc.name}, skipping reference validation")
            return

        # Validate item references based on document type
        _validate_item_references(doc)
        
        logger.debug(f"Stock update validation passed for {doc.doctype} {doc.name}")
        
    except Exception as e:
        logger.error(f"Error in stock update validation: {str(e)}")
        raise


def _is_sales_invoice_rate_adjustment_debit_note(doc) -> bool:
    """
    Return True when the document is a Sales Invoice marked as Debit Note.

    In ERPNext, the `is_debit_note` checkbox is labeled
    "Is Rate Adjustment Entry (Debit Note)" and represents value-only
    adjustments that can be submitted without stock movement.
    """
    return doc.doctype == "Sales Invoice" and cint(doc.get("is_debit_note"))


def _validate_sales_invoice_rate_adjustment_without_dn_links(doc) -> None:
    """
    Enforce that rate-adjustment debit notes are not linked to Delivery Notes.

    Sales Invoice rate-adjustment entries (`is_debit_note=1`) are value-only
    adjustments and must not carry DN row links.
    """
    if not _has_sales_invoice_dn_links(doc):
        return

    frappe.throw(
        _(
            "Sales Invoice marked as 'Is Rate Adjustment Entry (Debit Note)' "
            "cannot have Delivery Note references. Remove Delivery Note linkage "
            "from item rows or disable Debit Note."
        ),
        title=_("Invalid Debit Note Linkage"),
    )


def _has_sales_invoice_dn_links(doc) -> bool:
    """Return True when any SI item references Delivery Note or DN Item."""
    for item in doc.items or []:
        if item.get("delivery_note") or item.get("dn_detail"):
            return True
    return False


def _is_stock_update_validation_enabled() -> bool:
    """
    Check if stock update validation is enabled in BNS Settings.
    
    Returns:
        bool: True if validation is enabled, False otherwise
    """
    try:
        return bool(cint(frappe.db.get_single_value("BNS Settings", "enforce_stock_update_or_reference")))
    except Exception as e:
        logger.error(f"Error checking stock update validation setting: {str(e)}")
        return False


def _validate_item_references(doc) -> None:
    """
    Validate that all stock items are properly referenced.
    
    Args:
        doc: The invoice document being validated
        
    Raises:
        StockUpdateValidationError: If validation fails
    """
    if doc.doctype == "Purchase Invoice":
        _validate_purchase_invoice_references(doc)
    elif doc.doctype == "Sales Invoice":
        _validate_sales_invoice_references(doc)


def _validate_purchase_invoice_references(doc) -> None:
    """
    Validate that all stock items in Purchase Invoice are referenced from Purchase Receipt.

    Uses purchase_receipt (doc link) and pr_detail (Purchase Receipt Item row) - standard
    ERPNext field names on Purchase Invoice Item.
    
    Args:
        doc: The Purchase Invoice document
        
    Raises:
        StockUpdateValidationError: If any stock item is not referenced
    """
    non_referenced_items = _get_non_referenced_stock_items(doc, "purchase_receipt", "pr_detail")
    
    if non_referenced_items:
        logger.warning(f"Purchase Invoice {doc.name} has non-referenced stock items: {non_referenced_items}")
        _raise_purchase_invoice_reference_error()

    _validate_batch_serial_reference_continuity(doc, "purchase_receipt", "pr_detail", "Purchase Receipt Item")

    # Additional BNS interstate guard after cutoff:
    # internal PI must be SI-linked or PR(SI-linked)-based; standalone PI is blocked.
    if is_after_internal_validation_cutoff(doc.get("posting_date")):
        validate_internal_purchase_invoice_linkage(doc)


def _validate_sales_invoice_references(doc) -> None:
    """
    Validate that all stock items in Sales Invoice are referenced from Delivery Note.
    
    Args:
        doc: The Sales Invoice document
        
    Raises:
        StockUpdateValidationError: If any stock item is not referenced
    """
    non_referenced_items = _get_non_referenced_stock_items(doc, "delivery_note", "dn_detail")
    
    if non_referenced_items:
        logger.warning(f"Sales Invoice {doc.name} has non-referenced stock items: {non_referenced_items}")
        _raise_sales_invoice_reference_error()

    _validate_batch_serial_reference_continuity(doc, "delivery_note", "dn_detail", "Delivery Note Item")


def _get_non_referenced_stock_items(doc, reference_field: str, reference_item_field: str) -> List[str]:
    """
    Get list of stock items that are not referenced from source documents.
    
    Args:
        doc: The invoice document
        reference_field (str): The field name for the reference document
        reference_item_field (str): The field name for the reference item
        
    Returns:
        List[str]: List of item codes that are not referenced
    """
    non_referenced_items = []
    
    for item in doc.items:
        # Skip non-stock items
        if not _is_stock_item(item.item_code):
            continue
            
        # Check if item is referenced
        if not item.get(reference_field) and not item.get(reference_item_field):
            non_referenced_items.append(item.item_code)
    
    return non_referenced_items


def _is_stock_item(item_code: str) -> bool:
    """
    Check if an item is a stock item.
    
    Args:
        item_code (str): The item code to check
        
    Returns:
        bool: True if the item is a stock item, False otherwise
    """
    try:
        return bool(cint(frappe.db.get_value("Item", item_code, "is_stock_item")))
    except Exception as e:
        logger.error(f"Error checking stock item status for {item_code}: {str(e)}")
        return False


def _validate_batch_serial_reference_continuity(
    doc, reference_field: str, reference_item_field: str, source_child_doctype: str
) -> None:
    """
    Verify batch/serial info on invoice items matches the referenced source document items.

    For batch-tracked items: ensures batch_no on the invoice item matches the
    source DN/PR item.  Skips items that use Serial and Batch Bundle (SBB)
    since bundles are independently validated by ERPNext.

    Args:
        doc: The invoice document
        reference_field: Field linking to the source document (e.g. "delivery_note")
        reference_item_field: Field linking to the source item row (e.g. "dn_detail")
        source_child_doctype: Child table doctype name (e.g. "Delivery Note Item")
    """
    for item in doc.items:
        source_detail_name = item.get(reference_item_field)
        if not source_detail_name:
            continue

        if not _is_stock_item(item.item_code):
            continue

        item_meta = frappe.get_cached_value(
            "Item", item.item_code, ["has_batch_no", "has_serial_no"], as_dict=True
        )
        if not item_meta:
            continue

        if not (item_meta.has_batch_no or item_meta.has_serial_no):
            continue

        if item.get("serial_and_batch_bundle"):
            continue

        invoice_batch = (item.get("batch_no") or "").strip()
        if not invoice_batch:
            continue

        source_batch = (
            frappe.db.get_value(source_child_doctype, source_detail_name, "batch_no") or ""
        ).strip()
        if source_batch and invoice_batch != source_batch:
            frappe.throw(
                _(
                    "Row {0}: Batch {1} on {2} does not match batch {3} on the source {4}."
                ).format(item.idx, frappe.bold(invoice_batch), doc.doctype, frappe.bold(source_batch), source_child_doctype),
                title=_("Batch Mismatch"),
            )


def _raise_purchase_invoice_reference_error() -> None:
    """
    Raise an error for Purchase Invoice reference validation failure.
    
    Raises:
        StockUpdateValidationError: With appropriate error message
    """
    error_message = _(
        "When 'Update Stock' is not checked, all stock items must be referenced from a Purchase Receipt."
    )
    
    logger.error("Purchase Invoice reference validation failed")
    frappe.throw(error_message, title=_("Validation Error"))


def _raise_sales_invoice_reference_error() -> None:
    """
    Raise an error for Sales Invoice reference validation failure.
    
    Raises:
        StockUpdateValidationError: With appropriate error message
    """
    error_message = _(
        "When 'Update Stock' is not checked, all stock items must be referenced from a Delivery Note."
    )
    
    logger.error("Sales Invoice reference validation failed")
    frappe.throw(error_message, title=_("Validation Error")) 