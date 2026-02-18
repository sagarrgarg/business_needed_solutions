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
        
        # Add linked documents for BNS Internal Transfers
        add_bns_internal_transfer_links()

        # Ensure bns_purchase_receipt_reference exists on Sales Invoice (for SI↔PR connections)
        ensure_si_pr_reference_field()

        # Ensure sales_invoice_item exists on Purchase Receipt Item (for SI->PR partial receipt tracking)
        ensure_pr_item_sales_invoice_item_field()

        # Ensure bns_transfer_rate exists on PR/PI Item (valuation mirror from source DN/SI item)
        ensure_pr_item_bns_transfer_rate_field()
        ensure_pi_item_bns_transfer_rate_field()

        # Remove old is_bns_internal_customer field from Purchase Receipt
        remove_old_pr_internal_customer_field()

        # Disable custom script that forces "Update Stock" on PI (conflicts with PI-from-PR; BNS validates correctly)
        disable_pi_update_stock_mandatory_script()

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
    
    This function APPENDS the status option instead of overwriting to preserve
    system statuses that may be added in future ERPNext versions.
    """
    new_status = "BNS Internally Transferred"
    doctypes = ["Delivery Note", "Purchase Receipt", "Sales Invoice", "Purchase Invoice"]
    
    for doctype in doctypes:
        try:
            # Check if property setter already exists
            existing_ps_name = frappe.db.exists("Property Setter", {
                "doc_type": doctype,
                "field_name": "status",
                "property": "options"
            })
            
            if existing_ps_name:
                # Update existing property setter - APPEND only if missing
                ps = frappe.get_doc("Property Setter", existing_ps_name)
                # Check if BNS Internally Transferred is already in options
                existing_options = ps.value.split('\n') if ps.value else []
                if new_status not in existing_options:
                    # Append the new status option
                    ps.value = ps.value + "\n" + new_status
                    ps.save(ignore_permissions=True)
                    frappe.db.commit()
                    logger.info(f"Appended '{new_status}' to status options for {doctype}")
                else:
                    logger.info(f"Status option '{new_status}' already exists for {doctype}")
            else:
                # Get default options from DocField if available
                try:
                    meta = frappe.get_meta(doctype)
                    status_field = meta.get_field("status")
                    default_options = status_field.options or ""
                except Exception:
                    default_options = ""
                
                # Append new status to default options
                if default_options:
                    new_value = default_options + "\n" + new_status
                else:
                    # Fallback: use newline-separated format
                    new_value = "\n" + new_status
                
                # Create new property setter
                ps = frappe.new_doc("Property Setter")
                ps.update({
                    "doctype_or_field": "DocField",
                    "doc_type": doctype,
                    "field_name": "status",
                    "property": "options",
                    "value": new_value,
                    "property_type": "Text"
                })
                ps.save(ignore_permissions=True)
                frappe.db.commit()
                logger.info(f"Created status options property setter for {doctype} with '{new_status}'")
                
        except Exception as e:
            logger.error(f"Error adding BNS status option for {doctype}: {str(e)}")
            frappe.db.rollback()
            # Continue with other doctypes even if one fails


def add_bns_internal_transfer_links():
    """
    Add linked documents for BNS Internal Transfers:
    - Sales Invoice -> Purchase Invoice (via bns_inter_company_reference)
    - Purchase Invoice -> Sales Invoice (via bns_inter_company_reference)
    - Delivery Note -> Purchase Receipt (via bns_inter_company_reference)
    - Purchase Receipt -> Delivery Note (via bns_inter_company_reference)
    
    This creates DocType Link records so that linked documents appear
    in the "Linked Documents" section of each doctype form.
    """
    links_to_create = [
        {
            "parent": "Sales Invoice",
            "link_doctype": "Purchase Invoice",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1
        },
        {
            "parent": "Sales Invoice",
            "link_doctype": "Purchase Receipt",
            "link_fieldname": "supplier_delivery_note",
            "group": "BNS Internal Transfer",
            "custom": 1
        },
        {
            "parent": "Purchase Invoice",
            "link_doctype": "Sales Invoice",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1
        },
        {
            "parent": "Delivery Note",
            "link_doctype": "Purchase Receipt",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1
        },
        {
            "parent": "Purchase Receipt",
            "link_doctype": "Delivery Note",
            "link_fieldname": "bns_inter_company_reference",
            "group": "BNS Internal Transfer",
            "custom": 1
        },
        {
            "parent": "Purchase Receipt",
            "link_doctype": "Sales Invoice",
            "link_fieldname": "bns_purchase_receipt_reference",
            "group": "BNS Internal Transfer",
            "custom": 1
        }
    ]
    
    for link_config in links_to_create:
        try:
            parent = link_config["parent"]
            link_doctype = link_config["link_doctype"]
            link_fieldname = link_config["link_fieldname"]
            group = link_config.get("group", "")
            
            # Check if link already exists
            existing_link = frappe.db.exists("DocType Link", {
                "parent": parent,
                "link_doctype": link_doctype,
                "link_fieldname": link_fieldname,
                "custom": 1
            })
            
            if existing_link:
                logger.info(f"Link from {parent} to {link_doctype} via {link_fieldname} already exists")
                continue
            
            # Create new DocType Link
            link_doc = frappe.new_doc("DocType Link")
            link_doc.update({
                "parent": parent,
                "parenttype": "DocType",
                "parentfield": "links",
                "link_doctype": link_doctype,
                "link_fieldname": link_fieldname,
                "group": group,
                "custom": 1
            })
            link_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            logger.info(f"Created link from {parent} to {link_doctype} via {link_fieldname}")
            
        except Exception as e:
            logger.error(f"Error creating link from {link_config.get('parent')} to {link_config.get('link_doctype')}: {str(e)}")
            frappe.db.rollback()
            # Continue with other links even if one fails


def ensure_si_pr_reference_field():
    """
    Ensure Sales Invoice has bns_purchase_receipt_reference field for SI↔PR record connections.
    """
    field_name = "Sales Invoice-bns_purchase_receipt_reference"
    if frappe.db.exists("Custom Field", field_name):
        logger.info(f"Custom Field {field_name} already exists")
        return
    try:
        cf = frappe.new_doc("Custom Field")
        cf.update({
            "dt": "Sales Invoice",
            "fieldname": "bns_purchase_receipt_reference",
            "label": "BNS Purchase Receipt Reference",
            "fieldtype": "Link",
            "options": "Purchase Receipt",
            "insert_after": "bns_inter_company_reference",
            "read_only": 1,
            "hidden": 1,
            "print_hide": 1,
            "module": "BNS Branch Accounting",
            "description": "Stores linked Purchase Receipt when PR is created from SI (different GSTIN flow). Used for record connections.",
        })
        cf.insert(ignore_permissions=True)
        frappe.db.commit()
        logger.info(f"Created Custom Field {field_name}")
    except Exception as e:
        logger.error(f"Error creating {field_name}: {str(e)}")
        frappe.db.rollback()


def ensure_pr_item_sales_invoice_item_field():
    """
    Ensure Purchase Receipt Item has sales_invoice_item field for SI->PR partial receipt tracking.
    """
    field_name = "Purchase Receipt Item-sales_invoice_item"
    if frappe.db.exists("Custom Field", field_name):
        logger.info(f"Custom Field {field_name} already exists")
        return
    try:
        cf = frappe.new_doc("Custom Field")
        cf.update({
            "dt": "Purchase Receipt Item",
            "fieldname": "sales_invoice_item",
            "label": "Sales Invoice Item",
            "fieldtype": "Data",
            "insert_after": "delivery_note_item",
            "read_only": 1,
            "hidden": 1,
            "no_copy": 1,
            "module": "BNS Branch Accounting",
            "description": "Stores source Sales Invoice Item name when PR is created from SI. Used for partial receipt tracking.",
        })
        cf.insert(ignore_permissions=True)
        frappe.db.commit()
        logger.info(f"Created Custom Field {field_name}")
    except Exception as e:
        logger.error(f"Error creating {field_name}: {str(e)}")
        frappe.db.rollback()


def ensure_pr_item_bns_transfer_rate_field():
    """
    Ensure Purchase Receipt Item has bns_transfer_rate.

    This field stores source outgoing cost (incoming_rate) for BNS internal
    DN -> PR flow and is intentionally separate from billing rate.
    """
    field_name = "Purchase Receipt Item-bns_transfer_rate"
    if frappe.db.exists("Custom Field", field_name):
        logger.info(f"Custom Field {field_name} already exists")
        return

    try:
        cf = frappe.new_doc("Custom Field")
        cf.update({
            "dt": "Purchase Receipt Item",
            "fieldname": "bns_transfer_rate",
            "label": "BNS Transfer Rate",
            "fieldtype": "Float",
            "insert_after": "valuation_rate",
            "read_only": 1,
            "no_copy": 1,
            "module": "BNS Branch Accounting",
            "description": "Source outgoing valuation from linked Delivery Note/Sales Invoice item. Separate from billing rate.",
        })
        cf.insert(ignore_permissions=True)
        frappe.db.commit()
        logger.info(f"Created Custom Field {field_name}")
    except Exception as e:
        logger.error(f"Error creating {field_name}: {str(e)}")
        frappe.db.rollback()


def ensure_pi_item_bns_transfer_rate_field():
    """
    Ensure Purchase Invoice Item has bns_transfer_rate.

    This is used for stock-updating PI internal transfer valuation tracking.
    """
    field_name = "Purchase Invoice Item-bns_transfer_rate"
    if frappe.db.exists("Custom Field", field_name):
        logger.info(f"Custom Field {field_name} already exists")
        return

    try:
        cf = frappe.new_doc("Custom Field")
        cf.update({
            "dt": "Purchase Invoice Item",
            "fieldname": "bns_transfer_rate",
            "label": "BNS Transfer Rate",
            "fieldtype": "Float",
            "insert_after": "valuation_rate",
            "read_only": 1,
            "no_copy": 1,
            "module": "BNS Branch Accounting",
            "description": "Source outgoing valuation from linked Sales Invoice/Delivery Note item. Separate from billing rate.",
        })
        cf.insert(ignore_permissions=True)
        frappe.db.commit()
        logger.info(f"Created Custom Field {field_name}")
    except Exception as e:
        logger.error(f"Error creating {field_name}: {str(e)}")
        frappe.db.rollback()


def disable_pi_update_stock_mandatory_script():
    """
    Disable any custom script that forces 'Update Stock' on Purchase Invoice.
    PI against Purchase Receipt must have Update Stock unchecked (stock already updated by PR).
    BNS enforce_stock_update_or_reference validates correctly (update_stock OR all items from PR).
    """
    try:
        # Server Script: DocType Event on Purchase Invoice that throws Update Stock mandatory
        if frappe.db.table_exists("Server Script"):
            for name in frappe.get_all(
                "Server Script",
                filters={
                    "reference_doctype": "Purchase Invoice",
                    "disabled": 0,
                },
                pluck="name",
            ):
                script = frappe.db.get_value("Server Script", name, "script") or ""
                if "update_stock" in script.lower() and ("mandatory" in script.lower() or "must be checked" in script.lower()):
                    frappe.db.set_value("Server Script", name, "disabled", 1)
                    frappe.db.commit()
                    logger.info(f"Disabled Server Script '{name}' (conflicts with PI-from-PR Update Stock rule)")

        # Client Script: Purchase Invoice with same validation
        if frappe.db.table_exists("Client Script"):
            for name in frappe.get_all(
                "Client Script",
                filters={"dt": "Purchase Invoice", "enabled": 1},
                pluck="name",
            ):
                script = frappe.db.get_value("Client Script", name, "script") or ""
                if "update_stock" in script.lower() and ("mandatory" in script.lower() or "must be checked" in script.lower()):
                    frappe.db.set_value("Client Script", name, "enabled", 0)
                    frappe.db.commit()
                    logger.info(f"Disabled Client Script '{name}' (conflicts with PI-from-PR Update Stock rule)")
    except Exception as e:
        logger.warning(f"Could not disable PI Update Stock mandatory script: {e}")
        frappe.db.rollback()


def remove_old_pr_internal_customer_field():
    """
    Remove the old is_bns_internal_customer field from Purchase Receipt.
    
    This field was renamed to is_bns_internal_supplier, so we need to:
    1. Delete the old custom field record
    2. Drop the old column from the database table
    """
    try:
        # Delete the old custom field record
        old_field_name = "Purchase Receipt-is_bns_internal_customer"
        if frappe.db.exists("Custom Field", old_field_name):
            frappe.delete_doc("Custom Field", old_field_name, force=1, ignore_permissions=True)
            frappe.db.commit()
            logger.info(f"Deleted old custom field: {old_field_name}")
        
        # Drop the old column from the database table if it exists
        table_name = "tabPurchase Receipt"
        column_name = "is_bns_internal_customer"
        
        # Check if column exists
        columns = frappe.db.sql(f"SHOW COLUMNS FROM `{table_name}` LIKE '{column_name}'", as_dict=True)
        if columns:
            frappe.db.sql(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`")
            frappe.db.commit()
            logger.info(f"Dropped column {column_name} from {table_name}")
        else:
            logger.info(f"Column {column_name} does not exist in {table_name}, skipping drop")
            
    except Exception as e:
        logger.error(f"Error removing old PR internal customer field: {str(e)}")
        frappe.db.rollback()
        # Don't raise - this is not critical if the field doesn't exist
