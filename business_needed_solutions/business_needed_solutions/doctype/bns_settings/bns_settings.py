# Copyright (c) 2025, Sagar Ratan Garg and contributors
# For license information, please see license.txt

# apps/business_needed_solutions/business_needed_solutions/business_needed_solutions/doctype/bns_settings/bns_settings.py

import frappe
from frappe.model.document import Document

class BNSSettings(Document):
    def on_update(self):
        if not self.has_value_changed('discount_type'):
            return
        self.apply_settings()

    @frappe.whitelist()
    def apply_settings(self):
        # Update sales doctypes
        for doctype in ["Sales Invoice Item", "Sales Order Item", "Delivery Note Item", "Quotation Item"]:
            self.update_sales_item_fields(doctype)
        
        # Update purchase doctypes
        for doctype in ["Purchase Invoice Item", "Purchase Receipt Item", "Purchase Order Item","Supplier Quotation Item"]:
            self.update_purchase_item_fields(doctype)
        
        frappe.msgprint("Settings applied successfully!")
    
    def update_sales_item_fields(self, doctype):
        is_single = self.discount_type == "Single"
        self.set_property_setter(doctype, "rate", "read_only", "1")
        
        # First, set all fields to not show in list view
        docfields = frappe.get_all(
            "DocField",
            filters={"parent": doctype},
            fields=["name", "fieldname"]
        )
        
        for df in docfields:
            self.set_property_setter(doctype, df.fieldname, "in_list_view", "0")
            self.set_property_setter(doctype, df.fieldname, "columns", "0")

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
            self.set_property_setter(doctype, fieldname, "in_list_view", "1")
            self.set_property_setter(doctype, fieldname, "columns", str(columns))

        # Handle discount fields based on discount type
        if is_single:
            # Single discount mode
            self.set_property_setter(doctype, "discount_percentage", "in_list_view", "1")
            self.set_property_setter(doctype, "discount_percentage", "columns", "1")
            self.set_property_setter(doctype, "discount_percentage", "read_only", "0")
            
            # Hide triple discount fields
            custom_fields = [
                f"{doctype}-custom_d1_",
                f"{doctype}-custom_d2",
                f"{doctype}-custom_d3"
            ]
            
            for field_name in custom_fields:
                frappe.db.set_value(
                    "Custom Field",
                    field_name,
                    {
                        "hidden": 1,
                        "in_list_view": 0,
                        "columns": 0
                    }
                )
        else:
            # Triple discount mode
            self.set_property_setter(doctype, "discount_percentage", "in_list_view", "0")
            self.set_property_setter(doctype, "discount_percentage", "columns", "0")
            self.set_property_setter(doctype, "discount_percentage", "read_only", "1")
            
            # Show triple discount fields
            custom_fields = [
                f"{doctype}-custom_d1_",
                f"{doctype}-custom_d2",
                f"{doctype}-custom_d3"
            ]
            
            for field_name in custom_fields:
                frappe.db.set_value(
                    "Custom Field",
                    field_name,
                    {
                        "hidden": 0,
                        "in_list_view": 1,
                        "columns": 1
                    }
                )

        # Clear cache to apply changes immediately
        frappe.clear_cache(doctype=doctype)

    def update_purchase_item_fields(self, doctype):
        is_single = self.discount_type == "Single"
        self.set_property_setter(doctype, "rate", "read_only", "1")
        # First, set all fields to not show in list view
        docfields = frappe.get_all(
            "DocField",
            filters={"parent": doctype},
            fields=["name", "fieldname"]
        )
        
        for df in docfields:
            self.set_property_setter(doctype, df.fieldname, "in_list_view", "0")
            self.set_property_setter(doctype, df.fieldname, "columns", "0")
        
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
            self.set_property_setter(doctype, fieldname, "in_list_view", "1")
            self.set_property_setter(doctype, fieldname, "columns", str(columns))

        # Handle discount fields based on discount type
        if is_single:
            self.set_property_setter(doctype, "discount_percentage", "in_list_view", "1")
            self.set_property_setter(doctype, "discount_percentage", "columns", "1")
            self.set_property_setter(doctype, "discount_percentage", "read_only", "0")
        else:
            self.set_property_setter(doctype, "discount_percentage", "in_list_view", "0")
            self.set_property_setter(doctype, "discount_percentage", "columns", "0")
            self.set_property_setter(doctype, "discount_percentage", "read_only", "1")

        # Clear cache to apply changes immediately
        frappe.clear_cache(doctype=doctype)
    
    def set_property_setter(self, doctype, fieldname, property_name, value):
        property_setter_name = f"{doctype}-{fieldname}-{property_name}"
        
        if frappe.db.exists("Property Setter", property_setter_name):
            frappe.db.set_value("Property Setter", property_setter_name, "value", value)
        else:
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