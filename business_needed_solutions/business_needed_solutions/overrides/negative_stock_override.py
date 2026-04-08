"""
Business Needed Solutions - Negative Stock Cutoff

Prerequisite: ERPNext Stock Settings → Allow Negative Stock = ON.

Validates outgoing stock in before_submit doc_events:

    - posting_date > cutoff  → BLOCKED for everyone, no exceptions
    - posting_date ≤ cutoff  → BLOCKED unless user has an override role

No monkey-patching — just a straightforward doc_event validation like
submission_restriction.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate
from collections import defaultdict


def validate_negative_stock(doc, method=None):
	"""
	before_submit hook on stock documents.

	Checks every outgoing stock movement in the document against the
	current Bin balance. Throws if any item would go negative.
	"""
	posting_date = getattr(doc, "posting_date", None)
	if not should_restrict(posting_date):
		return

	outgoing = _collect_outgoing(doc)
	if not outgoing:
		return

	cutoff = frappe.db.get_single_value("BNS Settings", "negative_stock_cutoff_date", cache=True)
	after_cutoff = cutoff and posting_date and getdate(posting_date) > getdate(cutoff)

	for (item_code, warehouse), qty_out in outgoing.items():
		actual_qty = flt(
			frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
		)
		shortfall = flt(qty_out - actual_qty, 4)
		if shortfall > 0:
			if after_cutoff:
				msg = _("{0} units of {1} needed in {2} to complete this transaction."
						" Negative stock is blocked for posting dates after {3}.").format(
					shortfall,
					frappe.bold(item_code),
					frappe.bold(warehouse),
					frappe.format_value(cutoff, {"fieldtype": "Date"}),
				)
			else:
				msg = _("{0} units of {1} needed in {2} to complete this transaction."
						" Only authorized roles can submit negative stock on or before {3}.").format(
					shortfall,
					frappe.bold(item_code),
					frappe.bold(warehouse),
					frappe.format_value(cutoff, {"fieldtype": "Date"}),
				)
			frappe.throw(msg, title=_("Insufficient Stock"))


def should_restrict(posting_date):
	"""
	Returns True when BNS should block negative stock for this
	posting_date and current user.

	Logic:
		- Feature disabled or no cutoff → no restriction
		- posting_date > cutoff → ALWAYS restrict (no role bypass)
		- posting_date ≤ cutoff → restrict unless user has override role

	Args:
		posting_date: Document posting date.

	Returns:
		bool
	"""
	if frappe.flags.get("through_repost_item_valuation"):
		return False

	if not cint(
		frappe.db.get_single_value("BNS Settings", "allow_negative_stock_override", cache=True)
	):
		return False

	cutoff = frappe.db.get_single_value("BNS Settings", "negative_stock_cutoff_date", cache=True)
	if not cutoff or not posting_date:
		return False

	if getdate(posting_date) > getdate(cutoff):
		return True

	override_roles = _get_override_roles()
	if override_roles:
		user_roles = set(frappe.get_roles(frappe.session.user))
		if override_roles & user_roles:
			return False

	return True


def _get_override_roles():
	"""Roles allowed to submit negative stock on or before the cutoff date."""
	cache_key = "_bns_negative_stock_override_roles"
	if cache_key not in frappe.flags:
		roles = frappe.get_all(
			"Has Role",
			filters={
				"parenttype": "BNS Settings",
				"parentfield": "negative_stock_override_roles",
			},
			pluck="role",
		)
		frappe.flags[cache_key] = set(roles)
	return frappe.flags[cache_key]


def _collect_outgoing(doc):
	"""
	Collect outgoing stock movements from the document, grouped by
	(item_code, warehouse) → total outgoing qty.

	Non-stock items are excluded — they don't maintain bin balances and
	must never be checked for negative stock.

	Args:
		doc: Stock document (Stock Entry, Delivery Note, etc.)

	Returns:
		dict: {(item_code, warehouse): qty_out}
	"""
	out = defaultdict(float)
	doctype = doc.doctype

	stock_items = _get_stock_item_set(doc)

	if doctype == "Stock Entry":
		for row in doc.items:
			if row.s_warehouse and row.item_code in stock_items:
				out[(row.item_code, row.s_warehouse)] += flt(row.qty)

	elif doctype in ("Delivery Note", "Sales Invoice"):
		if doctype == "Sales Invoice" and not cint(doc.update_stock):
			return out
		for row in doc.items:
			if row.warehouse and flt(row.qty) > 0 and row.item_code in stock_items:
				out[(row.item_code, row.warehouse)] += flt(row.qty)

	elif doctype in ("Purchase Receipt", "Purchase Invoice"):
		if doctype == "Purchase Invoice" and not cint(doc.update_stock):
			return out
		for row in doc.items:
			if row.rejected_warehouse and flt(row.rejected_qty) > 0 and row.item_code in stock_items:
				out[(row.item_code, row.rejected_warehouse)] += flt(row.rejected_qty)

	elif doctype == "Stock Reconciliation":
		for row in doc.items:
			if row.warehouse and row.qty is not None and row.item_code in stock_items:
				actual = flt(
					frappe.db.get_value("Bin",
						{"item_code": row.item_code, "warehouse": row.warehouse},
						"actual_qty")
				)
				diff = actual - flt(row.qty)
				if diff > 0:
					out[(row.item_code, row.warehouse)] += diff

	return out


def _get_stock_item_set(doc):
	"""
	Return a set of item_code values from the document that are stock items.
	Single batch query to avoid N+1.
	"""
	item_codes = {row.item_code for row in doc.items if row.item_code}
	if not item_codes:
		return set()

	return set(frappe.get_all(
		"Item",
		filters={"name": ("in", list(item_codes)), "is_stock_item": 1},
		pluck="name",
	))
