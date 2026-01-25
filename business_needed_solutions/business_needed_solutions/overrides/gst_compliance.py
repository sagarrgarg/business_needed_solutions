"""
Business Needed Solutions - GST Compliance System

This module provides GST compliance validations and e-Waybill generation
for BNS internal transfers:
1. Block Purchase Invoice when Supplier GSTIN = Company GSTIN
2. Auto-generate e-Waybill for internal customer Delivery Notes with same GSTIN
"""

import frappe
from frappe import _
from typing import Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)


class GSTComplianceError(Exception):
    """Custom exception for GST compliance errors."""
    pass


def validate_purchase_invoice_same_gstin(doc, method: Optional[str] = None) -> None:
    """
    Validate that Purchase Invoice is not submitted when Supplier GSTIN
    and Company GSTIN are the same.
    
    This validation prevents self-invoicing which is not allowed under GST.
    
    Args:
        doc: The Purchase Invoice document being validated
        method (Optional[str]): The method being called
        
    Raises:
        GSTComplianceError: If Supplier GSTIN equals Company GSTIN
    """
    try:
        # Check if validation is enabled in BNS Settings
        if not _is_same_gstin_validation_enabled():
            logger.debug("Same GSTIN validation is disabled in BNS Settings")
            return
        
        # Only validate on submit (docstatus changing to 1)
        if doc.docstatus != 1:
            return
        
        # Get GSTINs from the document
        company_gstin = doc.get("company_gstin")
        supplier_gstin = doc.get("supplier_gstin")
        
        # Skip if either GSTIN is missing
        if not company_gstin or not supplier_gstin:
            logger.debug(f"Skipping GSTIN validation - company_gstin: {company_gstin}, supplier_gstin: {supplier_gstin}")
            return
        
        # Compare GSTINs
        if company_gstin.strip().upper() == supplier_gstin.strip().upper():
            logger.warning(f"Purchase Invoice {doc.name} blocked - same GSTIN: {company_gstin}")
            frappe.throw(
                _("Purchase Invoice cannot be submitted when Supplier GSTIN ({0}) is the same as Company GSTIN ({1}). "
                  "This is not allowed under GST regulations.").format(supplier_gstin, company_gstin),
                title=_("Same GSTIN Validation Error")
            )
        
        logger.debug(f"GSTIN validation passed for Purchase Invoice {doc.name}")
        
    except Exception as e:
        if "Same GSTIN Validation Error" in str(e):
            raise
        logger.error(f"Error in GSTIN validation: {str(e)}")
        raise


def _is_same_gstin_validation_enabled() -> bool:
    """
    Check if same GSTIN validation is enabled in BNS Settings.
    
    Returns:
        bool: True if validation is enabled, False otherwise
    """
    try:
        return bool(frappe.db.get_single_value("BNS Settings", "block_purchase_invoice_same_gstin"))
    except Exception as e:
        logger.error(f"Error checking same GSTIN validation setting: {str(e)}")
        return False


def maybe_generate_internal_dn_ewaybill(doc, method: Optional[str] = None) -> None:
    """
    Auto-generate e-Waybill for internal customer Delivery Notes when:
    1. BNS Settings toggle is enabled
    2. Customer is BNS internal customer
    3. Billing GSTIN equals Company GSTIN (same GSTIN internal transfer)
    4. Invoice value exceeds GST Settings e-Waybill threshold
    5. Goods are supplied (not services)
    6. Transporter/vehicle requirements are met
    
    Args:
        doc: The Delivery Note document being submitted
        method (Optional[str]): The method being called
    """
    try:
        # Guard: Check if feature is enabled in BNS Settings
        if not _is_internal_dn_ewaybill_enabled():
            logger.debug("Internal DN e-Waybill feature is disabled in BNS Settings")
            return
        
        # Guard: Only process on submit (docstatus == 1)
        if doc.docstatus != 1:
            return
        
        # Guard: Check if already has e-Waybill
        if doc.get("ewaybill"):
            logger.debug(f"Delivery Note {doc.name} already has e-Waybill: {doc.ewaybill}")
            return
        
        # Guard: Check if customer is BNS internal
        is_bns_internal = _is_bns_internal_customer(doc)
        if not is_bns_internal:
            logger.debug(f"Customer {doc.customer} is not a BNS internal customer")
            return
        
        # Guard: Check if GSTIN is same (internal transfer under same GSTIN)
        company_gstin = doc.get("company_gstin")
        billing_address_gstin = doc.get("billing_address_gstin")
        
        if not company_gstin or not billing_address_gstin:
            logger.debug(f"Missing GSTIN - company: {company_gstin}, billing: {billing_address_gstin}")
            return
        
        if company_gstin.strip().upper() != billing_address_gstin.strip().upper():
            logger.debug(f"GSTINs are different - not a same-GSTIN internal transfer")
            return
        
        # Guard: Check GST Settings requirements
        gst_settings = frappe.get_cached_doc("GST Settings")
        
        if not gst_settings.enable_e_waybill:
            logger.debug("e-Waybill is disabled in GST Settings")
            return
        
        if not gst_settings.enable_e_waybill_from_dn:
            logger.debug("e-Waybill from Delivery Note is disabled in GST Settings")
            return
        
        # Guard: Check threshold
        e_waybill_threshold = gst_settings.e_waybill_threshold or 0
        if abs(doc.base_grand_total) < e_waybill_threshold:
            logger.debug(f"Invoice value {doc.base_grand_total} is below threshold {e_waybill_threshold}")
            return
        
        # Guard: Check if goods are supplied (not just services)
        if not _are_goods_supplied(doc):
            logger.debug("No goods supplied - only services")
            return
        
        # Guard: Validate transporter/vehicle requirements
        transport_error = _validate_transport_details(doc)
        if transport_error:
            logger.info(f"Transport validation failed for {doc.name}: {transport_error}")
            frappe.msgprint(
                _("e-Waybill not auto-generated: {0}").format(transport_error),
                title=_("e-Waybill Requirements Not Met"),
                indicator="orange"
            )
            return
        
        # All checks passed - enqueue e-Waybill generation
        logger.info(f"Enqueuing e-Waybill generation for internal DN {doc.name}")
        frappe.enqueue(
            "india_compliance.gst_india.utils.e_waybill.generate_e_waybill",
            enqueue_after_commit=True,
            queue="short",
            doctype="Delivery Note",
            docname=doc.name,
        )
        
        frappe.msgprint(
            _("e-Waybill generation has been queued for this internal transfer."),
            title=_("e-Waybill Queued"),
            indicator="blue"
        )
        
    except Exception as e:
        logger.error(f"Error in internal DN e-Waybill generation: {str(e)}")
        # Don't raise - this is a non-critical enhancement
        frappe.log_error(
            title=_("e-Waybill Auto-Generation Error"),
            message=f"Failed to auto-generate e-Waybill for Delivery Note {doc.name}: {str(e)}"
        )


def _is_internal_dn_ewaybill_enabled() -> bool:
    """
    Check if internal DN e-Waybill feature is enabled in BNS Settings.
    
    Returns:
        bool: True if feature is enabled, False otherwise
    """
    try:
        return bool(frappe.db.get_single_value("BNS Settings", "enable_internal_dn_ewaybill"))
    except Exception as e:
        logger.error(f"Error checking internal DN e-Waybill setting: {str(e)}")
        return False


def _is_bns_internal_customer(doc) -> bool:
    """
    Check if the document's customer is a BNS internal customer.
    
    Args:
        doc: The Delivery Note document
        
    Returns:
        bool: True if customer is BNS internal, False otherwise
    """
    # First check the document field
    if doc.get("is_bns_internal_customer"):
        return True
    
    # Then check the customer master
    if doc.customer:
        return bool(frappe.db.get_value("Customer", doc.customer, "is_bns_internal_customer"))
    
    return False


def _are_goods_supplied(doc) -> bool:
    """
    Check if goods (not just services) are supplied in the document.
    
    Goods are identified by HSN codes NOT starting with "99" (which are services).
    
    Args:
        doc: The document to check
        
    Returns:
        bool: True if goods are supplied, False otherwise
    """
    for item in doc.items:
        hsn_code = item.get("gst_hsn_code") or ""
        # Services have HSN codes starting with 99
        if hsn_code and not hsn_code.startswith("99") and item.qty != 0:
            return True
    return False


def _validate_transport_details(doc) -> Optional[str]:
    """
    Validate transporter/vehicle details required for e-Waybill generation.
    
    This mirrors the validation in India Compliance's GSTTransactionData.validate_mode_of_transport().
    
    Args:
        doc: The document to validate
        
    Returns:
        Optional[str]: Error message if validation fails, None if valid
    """
    mode_of_transport = doc.get("mode_of_transport")
    gst_transporter_id = doc.get("gst_transporter_id")
    
    # Either mode_of_transport or gst_transporter_id is required
    if not mode_of_transport and not gst_transporter_id:
        return _("Either GST Transporter ID or Mode of Transport is required to generate e-Waybill")
    
    # If only gst_transporter_id is provided (Part A only), that's acceptable
    if gst_transporter_id and not mode_of_transport:
        return None
    
    # Validate based on mode of transport
    if mode_of_transport == "Road" and not doc.get("vehicle_no"):
        return _("Vehicle Number is required to generate e-Waybill for supply via Road")
    
    if mode_of_transport == "Ship" and not (doc.get("vehicle_no") and doc.get("lr_no")):
        return _("Vehicle Number and L/R No is required to generate e-Waybill for supply via Ship")
    
    if mode_of_transport in ("Rail", "Air") and not doc.get("lr_no"):
        return _("L/R No. is required to generate e-Waybill for supply via Rail or Air")
    
    return None
