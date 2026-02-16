"""
Remove custom_destination custom field from Purchase Receipt and Purchase Invoice.
"""

import frappe


def execute():
    for name in ("Purchase Receipt-custom_destination", "Purchase Invoice-custom_destination"):
        if frappe.db.exists("Custom Field", name):
            frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)
    frappe.db.commit()
