"""
Business Needed Solutions - Migration Handler

This module handles post-migration tasks to ensure BNS settings are properly applied
after any migration operation.
"""

import frappe
from frappe import _
import logging

# Configure logging
logger = logging.getLogger(__name__)


def after_migrate():
    """
    Post-migration hook to ensure BNS settings are properly applied.
    
    This function is called after every migration and ensures that:
    1. Property setters for discount fields are applied
    2. All doctypes reflect the correct discount type configuration
    3. Status field options include "BNS Internally Transferred"
    """
    try:
        logger.info("Starting BNS post-migration setup...")
        
        # Add "BNS Internally Transferred" to status field options
        add_bns_status_option()
        
        # Apply existing BNS Settings to ensure all property setters are up to date
        if frappe.db.exists("BNS Settings"):
            bns_settings = frappe.get_doc("BNS Settings")
            bns_settings.apply_settings()
            logger.info(f"BNS Settings applied successfully for discount type: {bns_settings.discount_type}")
        else:
            logger.warning("BNS Settings not found - skipping application")
        
        logger.info("BNS post-migration setup completed successfully")
        
    except Exception as e:
        logger.error(f"Error in BNS post-migration setup: {str(e)}")
        # Don't raise the exception to avoid blocking the migration process
        # The settings can be applied manually if needed


def add_bns_status_option():
    """
    Add "BNS Internally Transferred" to status field options for:
    - Delivery Note
    - Purchase Receipt
    - Sales Invoice
    - Purchase Invoice
    """
    doctypes_status_options = {
        "Delivery Note": "\nDraft\nTo Bill\nCompleted\nReturn Issued\nCancelled\nClosed\nBNS Internally Transferred",
        "Purchase Receipt": "\nDraft\nPartly Billed\nTo Bill\nCompleted\nReturn Issued\nCancelled\nClosed\nBNS Internally Transferred",
        "Sales Invoice": "\nDraft\nReturn\nCredit Note Issued\nSubmitted\nPaid\nPartly Paid\nUnpaid\nUnpaid and Discounted\nPartly Paid and Discounted\nOverdue and Discounted\nOverdue\nCancelled\nInternal Transfer\nBNS Internally Transferred",
        "Purchase Invoice": "\nDraft\nReturn\nDebit Note Issued\nSubmitted\nPaid\nPartly Paid\nUnpaid\nOverdue\nCancelled\nInternal Transfer\nBNS Internally Transferred"
    }
    
    for doctype, new_options in doctypes_status_options.items():
        try:
            # Check if property setter already exists
            existing_ps_name = frappe.db.exists("Property Setter", {
                "doc_type": doctype,
                "field_name": "status",
                "property": "options"
            })
            
            if existing_ps_name:
                # Update existing property setter
                ps = frappe.get_doc("Property Setter", existing_ps_name)
                # Check if BNS Internally Transferred is already in options
                if "BNS Internally Transferred" not in ps.value:
                    ps.value = new_options
                    ps.save(ignore_permissions=True)
                    frappe.db.commit()
                    logger.info(f"Updated status options for {doctype}")
                else:
                    logger.info(f"Status option already exists for {doctype}")
            else:
                # Create new property setter
                ps = frappe.new_doc("Property Setter")
                ps.update({
                    "doctype_or_field": "DocField",
                    "doc_type": doctype,
                    "field_name": "status",
                    "property": "options",
                    "value": new_options,
                    "property_type": "Text"
                })
                ps.save(ignore_permissions=True)
                frappe.db.commit()
                logger.info(f"Created status options property setter for {doctype}")
                
        except Exception as e:
            logger.error(f"Error adding BNS status option for {doctype}: {str(e)}")
            frappe.db.rollback()
            # Continue with other doctypes even if one fails
