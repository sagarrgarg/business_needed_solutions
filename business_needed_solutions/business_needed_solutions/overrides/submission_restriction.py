"""
Business Needed Solutions - Submission Restriction System

This module provides a unified validation system for document submission restrictions
across different document categories (stock, transaction, order).
"""

import frappe
from frappe import _
from typing import Dict, List, Optional, Set
import logging

# Configure logging
logger = logging.getLogger(__name__)


class SubmissionRestrictionError(Exception):
    """Custom exception for submission restriction errors."""
    pass


# Define document categories and their associated doctypes
DOCUMENT_CATEGORIES = {
    "stock": {
        "doctypes": [
            "Stock Entry",
            "Stock Reconciliation",
            "Sales Invoice",  # Only when update_stock is enabled
            "Purchase Invoice",  # Only when update_stock is enabled
            "Delivery Note",
            "Purchase Receipt"
        ],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted. You may save as draft, but only authorized users can submit.")
    },
    "transaction": {
        "doctypes": [
            "Sales Invoice",
            "Delivery Note", 
            "Purchase Invoice",
            "Purchase Receipt",
            "Journal Entry",
            "Payment Entry"
        ],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted. You may save as draft, but only authorized users can submit.")
    },
    "order": {
        "doctypes": [
            "Sales Order",
            "Purchase Order",
            "Payment Request"
        ],
        "setting_field": "restrict_submission",
        "override_field": "submission_restriction_override_roles",
        "error_message": _("Submitting {doctype} has been restricted. You may save as draft, but only authorized users can submit.")
    }
}


def validate_submission_permission(doc, method: Optional[str] = None) -> None:
    """
    Unified validation function for submission restrictions across all document types.
    
    This function replaces the separate stock_restriction and transaction_restriction
    validation functions with a single, cleaner implementation.
    
    Args:
        doc: The document being validated
        method (Optional[str]): The method being called
        
    Raises:
        SubmissionRestrictionError: If submission is restricted and user lacks permission
    """
    try:
        # Check if submission restriction is enabled
        if not _is_submission_restricted():
            return
        
        # Find which category this document belongs to
        document_category = get_document_category(doc.doctype)
        
        if not document_category:
            logger.debug(f"No category found for doctype: {doc.doctype}")
            return
        
        # Special handling for Sales/Purchase Invoice with stock updates
        document_category = _adjust_category_for_stock_updates(doc, document_category)
        
        # Check if user has override permissions
        if has_override_permission(document_category):
            logger.debug(f"User has override permission for {doc.doctype} in category {document_category}")
            return
        
        # If we reach here, the restriction is enabled and user is not authorized
        _raise_restriction_error(doc.doctype, document_category)
        
    except Exception as e:
        logger.error(f"Error in submission permission validation: {str(e)}")
        raise


def _is_submission_restricted() -> bool:
    """Check if submission restriction is enabled in BNS Settings."""
    try:
        return bool(frappe.db.get_single_value("BNS Settings", "restrict_submission"))
    except Exception as e:
        logger.error(f"Error checking submission restriction setting: {str(e)}")
        return False


def get_document_category(doctype: str) -> Optional[str]:
    """
    Determine which category a document type belongs to.
    
    Args:
        doctype (str): The document type to categorize
        
    Returns:
        str: The category name ('stock', 'transaction', 'order') or None if not categorized
    """
    for category, config in DOCUMENT_CATEGORIES.items():
        if doctype in config["doctypes"]:
            return category
    return None


def _adjust_category_for_stock_updates(doc, current_category: str) -> str:
    """
    Adjust document category based on stock update settings.
    
    Args:
        doc: The document being validated
        current_category (str): The current category assigned to the document
        
    Returns:
        str: The adjusted category
    """
    if doc.doctype in ["Sales Invoice", "Purchase Invoice"] and not doc.update_stock:
        # If update_stock is not enabled, treat as transaction, not stock
        if current_category == "stock":
            return "transaction"
    return current_category


def has_override_permission(category: str) -> bool:
    """
    Check if the current user has override permissions for the given category.
    
    Args:
        category (str): The document category to check permissions for
        
    Returns:
        bool: True if user has override permission, False otherwise
    """
    try:
        # Get user roles
        user_roles = _get_user_roles()
        
        # Get override roles from BNS Settings
        override_roles = _get_override_roles(category)
        
        # Check if user has any of the override roles
        has_permission = bool(override_roles and user_roles.intersection(override_roles))
        
        logger.debug(f"User override permission check for category {category}: {has_permission}")
        return has_permission
        
    except Exception as e:
        logger.error(f"Error checking override permission for category {category}: {str(e)}")
        return False


def _get_user_roles() -> Set[str]:
    """Get the current user's roles."""
    return set(frappe.get_roles())


def _get_override_roles(category: str) -> Set[str]:
    """
    Get override roles for the specified category from BNS Settings.
    
    Args:
        category (str): The document category
        
    Returns:
        Set[str]: Set of role names that have override permission
    """
    try:
        if category not in DOCUMENT_CATEGORIES:
            return set()
            
        override_roles_data = frappe.db.get_all(
            "Has Role",
            filters={
                "parenttype": "BNS Settings",
                "parentfield": DOCUMENT_CATEGORIES[category]["override_field"]
            },
            fields=["role"],
            ignore_permissions=True
        )
        
        return {d.role for d in override_roles_data if d.role}
        
    except Exception as e:
        logger.error(f"Error getting override roles for category {category}: {str(e)}")
        return set()


def _raise_restriction_error(doctype: str, category: str) -> None:
    """
    Raise a submission restriction error with appropriate message.
    
    Args:
        doctype (str): The document type being restricted
        category (str): The category of the document
        
    Raises:
        SubmissionRestrictionError: With formatted error message
    """
    if category not in DOCUMENT_CATEGORIES:
        raise SubmissionRestrictionError(_("Unknown document category: {0}").format(category))
        
    category_config = DOCUMENT_CATEGORIES[category]
    error_message = category_config["error_message"].format(doctype=doctype)
    
    logger.warning(f"Submission restricted for {doctype} in category {category}")
    frappe.throw(error_message, title=_("Submission Permission Error"))


# Legacy function names for backward compatibility
def validate_stock_modification(doc, method: Optional[str] = None) -> None:
    """
    Legacy function for stock modification validation.
    Now redirects to the unified validation function.
    
    Args:
        doc: The document being validated
        method (Optional[str]): The method being called
    """
    validate_submission_permission(doc, method)


def validate_transaction_modification(doc, method: Optional[str] = None) -> None:
    """
    Legacy function for transaction modification validation.
    Now redirects to the unified validation function.
    
    Args:
        doc: The document being validated
        method (Optional[str]): The method being called
    """
    validate_submission_permission(doc, method)


def validate_order_modification(doc, method: Optional[str] = None) -> None:
    """
    Legacy function for order modification validation.
    Now redirects to the unified validation function.
    
    Args:
        doc: The document being validated
        method (Optional[str]): The method being called
    """
    validate_submission_permission(doc, method) 