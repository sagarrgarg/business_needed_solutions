"""Remove the interim 'BNS Health Check' workspace.

The workspace has been consolidated back into 'Business Needed Solutions'.
"""

import frappe


def execute():
	if frappe.db.exists("Workspace", "BNS Health Check"):
		frappe.delete_doc("Workspace", "BNS Health Check", ignore_permissions=True, force=True)
