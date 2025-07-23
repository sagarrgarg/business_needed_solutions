"""
Business Needed Solutions - BNS Settings Controller

This module provides the controller for the BNS Settings doctype, handling
discount type configurations and field property management.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Dict, List, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)


class BNSSettingsError(Exception):
    """Custom exception for BNS Settings errors."""
    pass


class BNSSettings(Document):
    """
    BNS Settings Document Controller
    
    This class handles the configuration and management of BNS app settings,
    including discount type management and field property configurations.
    """
    
    def on_update(self) -> None:
        """
        Handle document updates and apply settings when discount type changes.
        """
        if not self.has_value_changed('discount_type'):
            return
            
        try:
            self.apply_settings()
            logger.info(f"BNS Settings updated successfully for discount type: {self.discount_type}")
        except Exception as e:
            logger.error(f"Error updating BNS Settings: {str(e)}")
            raise BNSSettingsError(f"Failed to update BNS Settings: {str(e)}")

    @frappe.whitelist()
    def apply_settings(self) -> None:
        """
        Apply BNS settings to all relevant doctypes.
        
        This method updates field properties for sales and purchase doctypes
        based on the configured discount type (Single or Triple).
        """
        try:
            # Update sales doctypes
            self._update_sales_doctypes()
            
            # Update purchase doctypes
            self._update_purchase_doctypes()
            
            frappe.msgprint(_("Settings applied successfully!"))
            logger.info("BNS Settings applied successfully to all doctypes")
            
        except Exception as e:
            logger.error(f"Error applying BNS Settings: {str(e)}")
            frappe.msgprint(_("Error applying settings. Please check error logs."))
            raise
    
    def _update_sales_doctypes(self) -> None:
        """Update sales-related doctypes with new settings."""
        sales_doctypes = [
            "Sales Invoice Item", 
            "Sales Order Item", 
            "Delivery Note Item", 
            "Quotation Item"
        ]
        
        for doctype in sales_doctypes:
            self._update_sales_item_fields(doctype)
    
    def _update_purchase_doctypes(self) -> None:
        """Update purchase-related doctypes with new settings."""
        purchase_doctypes = [
            "Purchase Invoice Item", 
            "Purchase Receipt Item", 
            "Purchase Order Item",
            "Supplier Quotation Item"
        ]
        
        for doctype in purchase_doctypes:
            self._update_purchase_item_fields(doctype)
    
    def _update_sales_item_fields(self, doctype: str) -> None:
        """
        Update sales item fields based on discount type configuration.
        
        Args:
            doctype (str): The doctype to update
        """
        is_single = self.discount_type == "Single"
        
        # Set rate field to read-only
        self._set_property_setter(doctype, "rate", "read_only", "1")
        
        # Reset all fields to not show in list view
        self._reset_list_view_fields(doctype)
        
        # Configure standard visible fields
        self._configure_sales_visible_fields(doctype, is_single)
        
        # Handle discount fields based on type
        self._configure_sales_discount_fields(doctype, is_single)
        
        # Clear cache to apply changes immediately
        frappe.clear_cache(doctype=doctype)
    
    def _update_purchase_item_fields(self, doctype: str) -> None:
        """
        Update purchase item fields based on discount type configuration.
        
        Args:
            doctype (str): The doctype to update
        """
        is_single = self.discount_type == "Single"
        
        # Set rate field to read-only
        self._set_property_setter(doctype, "rate", "read_only", "1")
        
        # Reset all fields to not show in list view
        self._reset_list_view_fields(doctype)
        
        # Configure standard visible fields
        self._configure_purchase_visible_fields(doctype)
        
        # Handle discount fields based on type
        self._configure_purchase_discount_fields(doctype, is_single)
        
        # Clear cache to apply changes immediately
        frappe.clear_cache(doctype=doctype)
    
    def _reset_list_view_fields(self, doctype: str) -> None:
        """
        Reset all fields to not show in list view.
        
        Args:
            doctype (str): The doctype to update
        """
        docfields = frappe.get_all(
            "DocField",
            filters={"parent": doctype},
            fields=["name", "fieldname"]
        )
        
        for df in docfields:
            self._set_property_setter(doctype, df.fieldname, "in_list_view", "0")
            self._set_property_setter(doctype, df.fieldname, "columns", "0")
    
    def _configure_sales_visible_fields(self, doctype: str, is_single: bool) -> None:
        """
        Configure visible fields for sales doctypes.
        
        Args:
            doctype (str): The doctype to configure
            is_single (bool): Whether single discount mode is enabled
        """
        # Define the fields we want to show in list view with their column widths
        standard_visible_fields = {
            "item_code": 3 if is_single else 2,
            "gst_hsn_code": 1,
            "qty": 1,
            "uom": 1,
            "price_list_rate": 1,
            "amount": 2 if is_single else 1
        }

        # Set the standard visible fields
        for fieldname, columns in standard_visible_fields.items():
            self._set_property_setter(doctype, fieldname, "in_list_view", "1")
            self._set_property_setter(doctype, fieldname, "columns", str(columns))
    
    def _configure_purchase_visible_fields(self, doctype: str) -> None:
        """
        Configure visible fields for purchase doctypes.
        
        Args:
            doctype (str): The doctype to configure
        """
        # Define the fields we want to show in list view with their column widths
        standard_visible_fields = {
            "item_code": 3,
            "gst_hsn_code": 1,
            "qty": 1,
            "uom": 1,
            "price_list_rate": 1,
            "amount": 1,
            "item_tax_template": 1,
            "warehouse": 1
        }

        # Set the standard visible fields
        for fieldname, columns in standard_visible_fields.items():
            self._set_property_setter(doctype, fieldname, "in_list_view", "1")
            self._set_property_setter(doctype, fieldname, "columns", str(columns))
    
    def _configure_sales_discount_fields(self, doctype: str, is_single: bool) -> None:
        """
        Configure discount fields for sales doctypes.
        
        Args:
            doctype (str): The doctype to configure
            is_single (bool): Whether single discount mode is enabled
        """
        if is_single:
            # Single discount mode
            self._set_property_setter(doctype, "discount_percentage", "in_list_view", "1")
            self._set_property_setter(doctype, "discount_percentage", "columns", "1")
            self._set_property_setter(doctype, "discount_percentage", "read_only", "0")
            
            # Hide triple discount fields
            self._hide_triple_discount_fields(doctype)
        else:
            # Triple discount mode
            self._set_property_setter(doctype, "discount_percentage", "in_list_view", "0")
            self._set_property_setter(doctype, "discount_percentage", "columns", "0")
            self._set_property_setter(doctype, "discount_percentage", "read_only", "1")
            
            # Show triple discount fields
            self._show_triple_discount_fields(doctype)
    
    def _configure_purchase_discount_fields(self, doctype: str, is_single: bool) -> None:
        """
        Configure discount fields for purchase doctypes.
        
        Args:
            doctype (str): The doctype to configure
            is_single (bool): Whether single discount mode is enabled
        """
        if is_single:
            self._set_property_setter(doctype, "discount_percentage", "in_list_view", "1")
            self._set_property_setter(doctype, "discount_percentage", "columns", "1")
            self._set_property_setter(doctype, "discount_percentage", "read_only", "0")
        else:
            self._set_property_setter(doctype, "discount_percentage", "in_list_view", "0")
            self._set_property_setter(doctype, "discount_percentage", "columns", "0")
            self._set_property_setter(doctype, "discount_percentage", "read_only", "1")
    
    def _hide_triple_discount_fields(self, doctype: str) -> None:
        """
        Hide triple discount custom fields.
        
        Args:
            doctype (str): The doctype to update
        """
        custom_fields = [
            f"{doctype}-custom_d1_",
            f"{doctype}-custom_d2",
            f"{doctype}-custom_d3"
        ]
        
        for field_name in custom_fields:
            self._update_custom_field(field_name, {"hidden": 1, "in_list_view": 0, "columns": 0})
    
    def _show_triple_discount_fields(self, doctype: str) -> None:
        """
        Show triple discount custom fields.
        
        Args:
            doctype (str): The doctype to update
        """
        custom_fields = [
            f"{doctype}-custom_d1_",
            f"{doctype}-custom_d2",
            f"{doctype}-custom_d3"
        ]
        
        for field_name in custom_fields:
            self._update_custom_field(field_name, {"hidden": 0, "in_list_view": 1, "columns": 1})
    
    def _update_custom_field(self, field_name: str, properties: Dict[str, Any]) -> None:
        """
        Update custom field properties.
        
        Args:
            field_name (str): The custom field name
            properties (Dict[str, Any]): The properties to update
        """
        try:
            frappe.db.set_value("Custom Field", field_name, properties)
        except Exception as e:
            logger.warning(f"Could not update custom field {field_name}: {str(e)}")
    
    def _set_property_setter(self, doctype: str, fieldname: str, property_name: str, value: str) -> None:
        """
        Set or update a property setter for a field.
        
        Args:
            doctype (str): The doctype name
            fieldname (str): The field name
            property_name (str): The property name
            value (str): The property value
        """
        property_setter_name = f"{doctype}-{fieldname}-{property_name}"
        
        try:
            if frappe.db.exists("Property Setter", property_setter_name):
                frappe.db.set_value("Property Setter", property_setter_name, "value", value)
            else:
                self._create_property_setter(doctype, fieldname, property_name, value)
        except Exception as e:
            logger.error(f"Error setting property {property_name} for {doctype}.{fieldname}: {str(e)}")
    
    def _create_property_setter(self, doctype: str, fieldname: str, property_name: str, value: str) -> None:
        """
        Create a new property setter.
        
        Args:
            doctype (str): The doctype name
            fieldname (str): The field name
            property_name (str): The property name
            value (str): The property value
        """
        ps = frappe.new_doc("Property Setter")
        ps.update({
            "doctype_or_field": "DocField",
            "doc_type": doctype,
            "field_name": fieldname,
            "property": property_name,
            "value": value,
            "property_type": "Check" if property_name in ["in_list_view", "read_only"] else "Int"
        })
        ps.save()