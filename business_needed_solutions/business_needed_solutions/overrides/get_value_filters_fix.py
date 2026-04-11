"""
Fix malformed filters sent to frappe.client.get_value by old/cached client code.

When the client uses frappe.db.exists(doctype, filters_object), the client-side
exists() wraps the second arg as { name: filters }, so the server receives
filters = {"name": {"supplier_delivery_note": "...", "docstatus": 1}} which
produces invalid SQL. This override unwraps filters when they are {"name": <dict>}
and the value is a dict (real filter set) rather than a string (document name).

Registered via override_whitelisted_methods in hooks.py — no monkey-patching.
"""

import frappe
from frappe.utils import get_safe_filters


@frappe.whitelist()
@frappe.read_only()
def get_value(doctype, fieldname, filters=None, as_dict=True, debug=False, parent=None):
	"""
	Drop-in override for frappe.client.get_value.

	Unwraps {"name": <dict>} → <dict> before forwarding to the original.
	"""
	# The downstream frappe.client.get_value enforces per-doctype read
	# permission, but still reject unauthenticated callers at the edge.
	if frappe.session.user == "Guest":
		frappe.throw("Not permitted", frappe.PermissionError)
	filters = get_safe_filters(filters)
	if isinstance(filters, dict) and list(filters.keys()) == ["name"]:
		name_val = filters["name"]
		if isinstance(name_val, dict):
			filters = name_val
	return frappe.client.get_value(
		doctype, fieldname, filters=filters,
		as_dict=as_dict, debug=debug, parent=parent,
	)
