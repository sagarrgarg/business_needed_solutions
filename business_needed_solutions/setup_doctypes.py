import frappe

def setup():
    # 1. Create Child DocType for Mappings
    mapping_dt = "Item Replacement Mapping"
    if not frappe.db.exists("DocType", mapping_dt):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": mapping_dt,
            "module": "Business Needed Solutions",
            "custom": 1,
            "istable": 1,
            "fields": [
                {
                    "fieldname": "old_item",
                    "label": "Old Item",
                    "fieldtype": "Link",
                    "options": "Item",
                    "in_list_view": 1,
                    "reqd": 1
                },
                {
                    "fieldname": "new_item",
                    "label": "New Item",
                    "fieldtype": "Link",
                    "options": "Item",
                    "in_list_view": 1,
                    "reqd": 1
                },
                {
                    "fieldname": "enabled",
                    "label": "Enabled",
                    "fieldtype": "Check",
                    "default": "1",
                    "in_list_view": 1
                }
            ]
        })
        doc.insert(ignore_permissions=True)
        print(f"Created DocType: {mapping_dt}")

    # 2. Create Single DocType for Settings
    settings_dt = "Item Replacement Settings"
    if not frappe.db.exists("DocType", settings_dt):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": settings_dt,
            "module": "Business Needed Solutions",
            "custom": 1,
            "issingle": 1,
            "fields": [
                {
                    "fieldname": "enable_item_replacement",
                    "label": "Enable Item Replacement",
                    "fieldtype": "Check",
                    "default": "0"
                },
                {
                    "fieldname": "replacements",
                    "label": "Replacements",
                    "fieldtype": "Table",
                    "options": mapping_dt,
                    "depends_on": "eval:doc.enable_item_replacement==1"
                }
            ]
        })
        doc.insert(ignore_permissions=True)
        print(f"Created DocType: {settings_dt}")

    frappe.db.commit()
