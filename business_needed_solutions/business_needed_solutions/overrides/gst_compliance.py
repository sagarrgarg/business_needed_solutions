"""
Business Needed Solutions - GST Compliance System

This module provides GST compliance validations:
- Block Purchase Invoice when Supplier GSTIN = Company GSTIN

Internal-DN e-Waybill and vehicle validation are in bns_branch_accounting.gst_integration.
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

        # Get GSTINs from the document
        company_gstin = (doc.get("company_gstin") or "").strip()
        supplier_gstin = (doc.get("supplier_gstin") or "").strip()

        # Fetch from addresses if not on doc (India Compliance populates these from addresses)
        if not company_gstin and doc.get("company_address"):
            company_gstin = (
                frappe.db.get_value("Address", doc.company_address, "gstin") or ""
            ).strip()
        if not supplier_gstin and doc.get("supplier_address"):
            supplier_gstin = (
                frappe.db.get_value("Address", doc.supplier_address, "gstin") or ""
            ).strip()

        # Skip if either GSTIN is missing
        if not company_gstin or not supplier_gstin:
            logger.debug(
                f"Skipping GSTIN validation - company_gstin: {company_gstin!r}, "
                f"supplier_gstin: {supplier_gstin!r}"
            )
            return

        # Compare GSTINs (case-insensitive)
        if company_gstin.upper() == supplier_gstin.upper():
            logger.warning(f"Purchase Invoice {doc.name} blocked - same GSTIN: {company_gstin}")
            frappe.throw(
                _(
                    "Purchase Invoice cannot be submitted when Supplier GSTIN ({0}) is the same "
                    "as Company GSTIN ({1}). This is not allowed under GST regulations."
                ).format(supplier_gstin, company_gstin),
                title=_("Same GSTIN Validation Error"),
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
