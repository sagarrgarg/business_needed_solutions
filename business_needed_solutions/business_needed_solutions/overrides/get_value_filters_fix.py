"""
Fix malformed filters sent to frappe.client.get_value by old/cached client code.

When the client uses frappe.db.exists(doctype, filters_object), the client-side
exists() wraps the second arg as { name: filters }, so the server receives
filters = {"name": {"supplier_delivery_note": "...", "docstatus": 1}} which
produces invalid SQL. This patch unwraps filters when they are {"name": <dict>}
and the value is a dict (real filter set) rather than a string (document name).
"""

import frappe
from frappe.utils import get_safe_filters


def apply_patch():
	"""Patch frappe.client.get_value to unwrap mistaken filters. Idempotent."""
	import frappe.client as client_module

	if getattr(client_module, "_bns_get_value_filters_patched", False):
		return

	client_module._bns_get_value_filters_patched = True
	_original_get_value = frappe.client.get_value

	def patched_get_value(doctype, fieldname, filters=None, as_dict=True, debug=False, parent=None):
		filters = get_safe_filters(filters)
		if isinstance(filters, dict) and list(filters.keys()) == ["name"]:
			name_val = filters["name"]
			# Document name is a string; if it's a dict, client sent filter object as "name"
			if isinstance(name_val, dict):
				filters = name_val
		return _original_get_value(doctype, fieldname, filters=filters, as_dict=as_dict, debug=debug, parent=parent)

	frappe.client.get_value = patched_get_value
