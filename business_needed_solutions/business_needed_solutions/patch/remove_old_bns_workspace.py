"""Remove stale workspace records that no longer have a JSON file on disk."""

import frappe


def execute():
	for name in ("Business Needed Solutions", "BNS Health Check"):
		if frappe.db.exists("Workspace", name):
			frappe.delete_doc("Workspace", name, ignore_permissions=True, force=True)
