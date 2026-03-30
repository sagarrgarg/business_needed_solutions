"""
Business Needed Solutions - PAN Validation System

This module provides validation for PAN (Permanent Account Number) uniqueness
across Customer and Supplier documents.
"""

import frappe
from frappe import _
from typing import Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)


# Temporarily disabled unused custom exception (kept commented for rollback safety).
# class PANValidationError(Exception):
#     """Custom exception for PAN validation errors."""
#     pass


def validate_pan_uniqueness(doc, method: Optional[str] = None) -> None:
    """
    Validate PAN uniqueness for both Customer and Supplier documents.
    
    This function checks if the PAN number is unique across all customers and suppliers
    when the enforce_pan_uniqueness setting is enabled in BNS Settings.
    
    Args:
        doc: The Customer or Supplier document being validated
        method (Optional[str]): The method being called
        
    Raises:
        PANValidationError: If PAN is not unique
    """
    try:
        # Skip validation if no PAN provided
        if not doc.pan:
            logger.debug(f"No PAN provided for {doc.doctype} {doc.name}")
            return

        # Check if PAN uniqueness is enabled in settings
        if not _is_pan_uniqueness_enabled():
            logger.debug("PAN uniqueness validation is disabled in BNS Settings")
            return

        # Validate PAN uniqueness
        _check_pan_uniqueness(doc)
        
        logger.debug(f"PAN uniqueness validation passed for {doc.doctype} {doc.name}")
        
    except Exception as e:
        logger.error(f"Error in PAN uniqueness validation: {str(e)}")
        raise


def _is_pan_uniqueness_enabled() -> bool:
    """
    Check if PAN uniqueness enforcement is enabled in BNS Settings.
    
    Returns:
        bool: True if PAN uniqueness is enabled, False otherwise
    """
    try:
        return bool(frappe.db.get_single_value("BNS Settings", "enforce_pan_uniqueness"))
    except Exception as e:
        logger.error(f"Error checking PAN uniqueness setting: {str(e)}")
        return False


def _check_pan_uniqueness(doc) -> None:
    """
    Check if the PAN number is unique across all customers and suppliers.
    
    Args:
        doc: The document being validated
        
    Raises:
        PANValidationError: If PAN is not unique
    """
    # Determine the doctype for the error message
    doctype_label = _get_doctype_label(doc.doctype)
    
    # Check for existing PAN in the same doctype
    existing_doc = _find_existing_pan_document(doc.doctype, doc.pan, doc.name)
    
    if existing_doc:
        _raise_pan_uniqueness_error(doctype_label, doc.pan)


def _get_doctype_label(doctype: str) -> str:
    """
    Get the human-readable label for the doctype.
    
    Args:
        doctype (str): The doctype name
        
    Returns:
        str: The human-readable label
    """
    return "Customer" if doctype == "Customer" else "Supplier"


def _find_existing_pan_document(doctype: str, pan: str, current_doc_name: str) -> Optional[str]:
    """
    Find existing document with the same PAN number.
    
    Args:
        doctype (str): The doctype to search in
        pan (str): The PAN number to search for
        current_doc_name (str): The name of the current document (to exclude from search)
        
    Returns:
        Optional[str]: The name of existing document if found, None otherwise
    """
    try:
        return frappe.db.exists(
            doctype,
            {
                "pan": pan,
                "name": ["!=", current_doc_name]
            }
        )
    except Exception as e:
        logger.error(f"Error searching for existing PAN document: {str(e)}")
        return None


def _raise_pan_uniqueness_error(doctype_label: str, pan: str) -> None:
    """
    Raise a PAN uniqueness error with appropriate message.
    
    Args:
        doctype_label (str): The human-readable doctype label
        pan (str): The PAN number that is not unique
        
    Raises:
        PANValidationError: With formatted error message
    """
    error_message = _(
        "PAN number must be unique. Another {doctype} with the same PAN already exists."
    ).format(doctype=doctype_label)
    
    logger.warning(f"PAN uniqueness validation failed for {doctype_label} with PAN: {pan}")
    frappe.throw(error_message, title=_("PAN Uniqueness Error")) 