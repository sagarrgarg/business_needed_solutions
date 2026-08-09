import frappe

def create_doctypes():
    try:
        if not frappe.db.exists("DocType", "BNS Batch Naming Format"):
            doc = frappe.get_doc({
                "doctype": "DocType",
                "name": "BNS Batch Naming Format",
                "module": "Business Needed Solutions",
                "custom": 0,
                "istable": 1,
                "editable_grid": 1,
                "fields": [
                    {
                        "fieldname": "target_doctype",
                        "fieldtype": "Data",
                        "label": "Target Doctype",
                        "in_list_view": 1,
                        "reqd": 1,
                        "description": "Comma-separated list of DocTypes (e.g., Stock Entry, Purchase Receipt)"
                    },
                    {
                        "fieldname": "stock_entry_purposes",
                        "fieldtype": "Data",
                        "label": "Stock Entry Purposes",
                        "in_list_view": 1,
                        "description": "Comma-separated purposes (e.g., Manufacture, Repack). Leave blank for all."
                    },
                    {
                        "fieldname": "format_string",
                        "fieldtype": "Data",
                        "label": "Format String",
                        "in_list_view": 1,
                        "reqd": 1,
                        "description": "e.g., {item_code}/{day_of_year}{year_1digit}"
                    },
                    {
                        "fieldname": "append_suffix",
                        "fieldtype": "Check",
                        "label": "Append Suffix",
                        "default": "0",
                        "in_list_view": 1,
                        "description": "Check to append -01, -02 for uniqueness. Uncheck to reuse the same batch for the day."
                    },
                    {
                        "fieldname": "is_active",
                        "fieldtype": "Check",
                        "label": "Active",
                        "default": "1",
                        "in_list_view": 1
                    }
                ]
            })
            doc.insert()
            print("Created BNS Batch Naming Format")
        else:
            print("BNS Batch Naming Format already exists")

        # Now add it to BNS Settings
        bns_settings = frappe.get_doc("DocType", "BNS Settings")
        
        # Check if the field already exists
        exists = False
        for field in bns_settings.fields:
            if field.fieldname == "batch_naming_formats":
                exists = True
                break
        
        if not exists:
            bns_settings.append("fields", {
                "fieldname": "batch_naming_section",
                "fieldtype": "Section Break",
                "label": "Batch Naming"
            })
            bns_settings.append("fields", {
                "fieldname": "batch_naming_formats",
                "fieldtype": "Table",
                "options": "BNS Batch Naming Format",
                "label": "Batch Naming Formats"
            })
            bns_settings.save()
            print("Added batch_naming_formats to BNS Settings")
        else:
            print("batch_naming_formats already exists in BNS Settings")
            
        frappe.db.commit()
        
    except Exception as e:
        print(f"Error: {e}")
        frappe.db.rollback()
