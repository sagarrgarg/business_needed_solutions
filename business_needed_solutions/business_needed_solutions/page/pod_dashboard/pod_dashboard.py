# Copyright (c) 2026, Business Needed Solutions
# License: Commercial

"""
POD Dashboard API

Provides data and actions for the POD (Proof of Delivery) Dashboard page.
Shows all submitted Sales Invoices where POD details are pending, and allows
inline updates of POD Status, POD Date, and POD Attachment.
"""

import frappe
from frappe import _
from frappe.utils import today, add_months


# -------------------------------------------------------------------
# Permission gates — reuse same pattern as bns_dashboard.py
# -------------------------------------------------------------------


def _require_dashboard_read():
	"""Any read endpoint: caller must have read permission on BNS Settings."""
	if not frappe.has_permission("BNS Settings", "read"):
		frappe.throw(
			_(
				"You need read permission on BNS Settings to use the POD Dashboard. "
				"Ask an administrator to grant your role read access via the Role Permission Manager."
			),
			frappe.PermissionError,
		)


def _require_dashboard_write(*doctypes):
	"""Write endpoint: caller must have write permission on BNS Settings and each target doctype."""
	if not frappe.has_permission("BNS Settings", "write"):
		frappe.throw(
			_(
				"You need write permission on BNS Settings for this action. "
				"Ask an administrator to grant your role write access via the Role Permission Manager."
			),
			frappe.PermissionError,
		)
	for dt in doctypes:
		if not frappe.has_permission(dt, "write"):
			frappe.throw(
				_("You do not have write permission on {0}.").format(dt),
				frappe.PermissionError,
			)


def _default_company():
	return frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")


# -------------------------------------------------------------------
# Read API
# -------------------------------------------------------------------


@frappe.whitelist()
def get_pending_pod_invoices(company=None, fiscal_year=None, from_date=None, to_date=None, customer=None, pod_status=None):
	"""
	Return submitted Sales Invoices where at least one POD field is empty.

	Fields checked:
	  - bns_pod_status
	  - bns_pod_date
	  - bns_pod_attachment

	Returns a list of dicts, ordered by posting_date descending.
	"""
	_require_dashboard_read()

	company = company or _default_company()
	
	if fiscal_year and not (from_date and to_date):
		year_start_date, year_end_date = frappe.db.get_value(
			"Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"]
		)
		if year_start_date and year_end_date:
			from_date = year_start_date
			to_date = year_end_date

	# Fetch internal customers to exclude
	internal_customers = [
		c.name for c in frappe.get_all(
			"Customer",
			filters=[
				["Customer", "is_internal_customer", "=", 1],
				["Customer", "is_bns_internal_customer", "=", 1]
			],
			or_filters=True,
			fields=["name"]
		)
	]

	# Build base filters — always submitted, always for selected company, and always exclude Unregistered GST category
	filters = [
		["Sales Invoice", "docstatus", "=", 1],
		["Sales Invoice", "gst_category", "!=", "Unregistered"]
	]
	if company:
		filters.append(["Sales Invoice", "company", "=", company])
	
	if internal_customers:
		filters.append(["Sales Invoice", "customer", "not in", internal_customers])

	if from_date:
		filters.append(["Sales Invoice", "posting_date", ">=", from_date])
	if to_date:
		filters.append(["Sales Invoice", "posting_date", "<=", to_date])

	if customer:
		filters.append(["Sales Invoice", "customer", "=", customer])

	if pod_status:
		if pod_status == "Missing":
			filters.append(["Sales Invoice", "bns_pod_status", "in", ["", None]])
		else:
			filters.append(["Sales Invoice", "bns_pod_status", "=", pod_status])

	invoices = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=[
			"name",
			"customer",
			"customer_name",
			"posting_date",
			"grand_total",
			"currency",
			"bns_pod_status",
			"bns_pod_date",
			"bns_pod_attachment",
			"po_no",
			"po_date"
		],
		order_by="posting_date desc",
		limit=500,
	)

	pending = [
		inv for inv in invoices
		if not (inv.get("bns_pod_status") and inv.get("bns_pod_date") and inv.get("bns_pod_attachment"))
	]

	return {
		"invoices": pending,
		"total": len(pending),
	}


# -------------------------------------------------------------------
# Write API
# -------------------------------------------------------------------


@frappe.whitelist()
def save_pod_details(sales_invoice, pod_status=None, pod_date=None, pod_attachment=None):
	"""
	Save POD fields on the given Sales Invoice using db.set_value.
	This works on submitted documents without triggering full document validation.

	Args:
		sales_invoice (str): Name of the Sales Invoice
		pod_status (str): One of: Delivered, In-Transit, Issue (or blank)
		pod_date (str): Date string YYYY-MM-DD (or blank)
		pod_attachment (str): URL/path of the attachment (or blank)

	Returns:
		dict: {success: True, all_filled: True/False}
	"""
	_require_dashboard_write("Sales Invoice")

	if not frappe.db.exists("Sales Invoice", sales_invoice):
		frappe.throw(_("Sales Invoice {0} not found.").format(sales_invoice))

	# Validate pod_status is one of allowed values if provided
	allowed_statuses = ["", "Delivered", "In-Transit", "Issue"]
	if pod_status and pod_status not in allowed_statuses:
		frappe.throw(_("Invalid POD Status: {0}").format(pod_status))

	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		{
			"bns_pod_status": pod_status or "",
			"bns_pod_date": pod_date or None,
			"bns_pod_attachment": pod_attachment or "",
		},
		update_modified=True,
	)
	frappe.db.commit()

	# Check if all 3 fields are now filled
	all_filled = bool(pod_status and pod_date and pod_attachment)

	return {"success": True, "all_filled": all_filled}
