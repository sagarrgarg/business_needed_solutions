"""
Business Needed Solutions - Item Validation System

This module provides validation for Item documents, specifically ensuring that
non-stock items have appropriate expense accounts configured.
"""

import frappe
from frappe import _
from typing import Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)


class ItemValidationError(Exception):
    """Custom exception for item validation errors."""
    pass


def validate_expense_account_for_non_stock_items(doc, method: Optional[str] = None) -> None:
    """
    Validate that non-stock items have at least one expense account in Item Defaults
    based on BNS Settings configuration.
    
    This function ensures that when an item is not a stock item (is_stock_item = False),
    it has at least one expense account configured in its item defaults. This is important
    for proper accounting when the item is used in transactions.
    
    Args:
        doc: The Item document being validated
        method (Optional[str]): The method being called
        
    Raises:
        ItemValidationError: If validation fails
    """
    try:
        # Check if validation is enabled in BNS Settings
        if not _is_expense_account_validation_enabled():
            logger.debug("Expense account validation is disabled in BNS Settings")
            return
        
        # Only apply to Item doctype
        if doc.doctype != "Item":
            logger.debug(f"Validation skipped for non-Item doctype: {doc.doctype}")
            return
        
        # Check if item is a stock item
        if doc.is_stock_item:
            logger.debug(f"Validation skipped for stock item: {doc.name}")
            return
        
        # Validate expense account configuration
        _validate_expense_account_configuration(doc)
        
        logger.debug(f"Expense account validation passed for item: {doc.name}")
        
    except Exception as e:
        logger.error(f"Error in expense account validation: {str(e)}")
        raise


def _is_expense_account_validation_enabled() -> bool:
    """
    Check if expense account validation is enabled in BNS Settings.
    
    Returns:
        bool: True if validation is enabled, False otherwise
    """
    try:
        return bool(frappe.db.get_single_value("BNS Settings", "enforce_expense_account_for_non_stock_items"))
    except Exception as e:
        logger.error(f"Error checking expense account validation setting: {str(e)}")
        return False


def _validate_expense_account_configuration(doc) -> None:
    """
    Validate that the item has at least one expense account configured.
    
    Args:
        doc: The Item document being validated
        
    Raises:
        ItemValidationError: If no expense account is configured
    """
    if not _has_expense_account_configured(doc):
        _raise_expense_account_error()


def _has_expense_account_configured(doc) -> bool:
    """
    Check if the item has at least one expense account configured in item defaults.
    
    Args:
        doc: The Item document
        
    Returns:
        bool: True if expense account is configured, False otherwise
    """
    if not doc.item_defaults:
        logger.debug(f"No item defaults found for item: {doc.name}")
        return False
    
    for item_default in doc.item_defaults:
        if item_default.get("expense_account"):
            logger.debug(f"Expense account found for item {doc.name}: {item_default.expense_account}")
            return True
    
    logger.debug(f"No expense account configured for item: {doc.name}")
    return False


def _raise_expense_account_error() -> None:
    """
    Raise an error indicating that expense account is required.
    
    Raises:
        ItemValidationError: With appropriate error message
    """
    error_message = _(
        "Since 'Maintain Stock' is disabled, at least one Expense Account is required in Item Defaults."
    )
    
    logger.warning("Expense account validation failed - no expense account configured")
    frappe.throw(error_message, title=_("Missing Expense Account")) 