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
def get_pending_pod_invoices(
	company=None,
	fiscal_year=None,
	from_date=None,
	to_date=None,
	customer=None,
	pod_status=None,
	start=0,
	page_length=20,
	search_name=None,
	search_customer=None,
	search_posting_date=None,
	search_grand_total=None,
	search_pod_status=None,
	search_pod_date=None,
	search_pod_attachment=None,
):
	"""
	Return submitted Sales Invoices where at least one POD field is empty.

	Fields checked:
	  - bns_pod_status
	  - bns_pod_date
	  - bns_pod_attachment
	"""
	_require_dashboard_read()

	company = company or _default_company()
	start = frappe.utils.cint(start)
	page_length = frappe.utils.cint(page_length) or 20
	
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
			or_filters=[
				["Customer", "is_internal_customer", "=", 1],
				["Customer", "is_bns_internal_customer", "=", 1]
			],
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

	# Add quick column searches
	if search_name:
		filters.append(["Sales Invoice", "name", "like", f"%{search_name}%"])
	if search_customer:
		filters.append(["Sales Invoice", "customer_name", "like", f"%{search_customer}%"])
	if search_posting_date:
		filters.append(["Sales Invoice", "posting_date", "like", f"%{search_posting_date}%"])
	if search_grand_total:
		filters.append(["Sales Invoice", "grand_total", "like", f"%{search_grand_total}%"])
	if search_pod_status:
		filters.append(["Sales Invoice", "bns_pod_status", "like", f"%{search_pod_status}%"])
	if search_pod_date:
		filters.append(["Sales Invoice", "bns_pod_date", "like", f"%{search_pod_date}%"])
	if search_pod_attachment:
		filters.append(["Sales Invoice", "bns_pod_attachment", "like", f"%{search_pod_attachment}%"])

	# Base pending OR filters — at least one of the 3 fields must be missing
	or_filters = [
		["Sales Invoice", "bns_pod_status", "in", ["", None]],
		["Sales Invoice", "bns_pod_date", "is", "not set"],
		["Sales Invoice", "bns_pod_attachment", "in", ["", None]]
	]

	# Query matching records for current page
	invoices = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		or_filters=or_filters,
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
		start=start,
		page_length=page_length
	)

	# Calculate counts dynamically at database level
	total_pending = frappe.get_all(
		"Sales Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=["count(name) as total"]
	)[0].total

	missing_status = frappe.get_all(
		"Sales Invoice",
		filters=filters + [["Sales Invoice", "bns_pod_status", "in", ["", None]]],
		fields=["count(name) as total"]
	)[0].total

	missing_date = frappe.get_all(
		"Sales Invoice",
		filters=filters + [["Sales Invoice", "bns_pod_date", "is", "not set"]],
		fields=["count(name) as total"]
	)[0].total

	missing_attach = frappe.get_all(
		"Sales Invoice",
		filters=filters + [["Sales Invoice", "bns_pod_attachment", "in", ["", None]]],
		fields=["count(name) as total"]
	)[0].total

	return {
		"invoices": invoices,
		"total": total_pending,
		"missing_status": missing_status,
		"missing_date": missing_date,
		"missing_attachment": missing_attach,
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
