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
    """
    try:
        logger.info("Starting BNS post-migration setup...")
        
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
