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


def _require_dashboard_access():
	"""Ensures the user has the required roles to access the POD Dashboard."""
	# Auto-create POD Dashboard User role if it doesn't exist
	if not frappe.db.exists("Role", "POD Dashboard User"):
		frappe.get_doc({"doctype": "Role", "role_name": "POD Dashboard User"}).insert(ignore_permissions=True)

	allowed_roles = ["POD Dashboard User", "Accounts User", "Accounts Manager", "System Manager", "Administrator"]
	if not any(r in frappe.get_roles() for r in allowed_roles):
		frappe.throw(
			_(
				"You do not have permission to access the POD Dashboard. "
				"Please ask an administrator to assign the 'POD Dashboard User' role."
			),
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
	page_length=500,
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
	_require_dashboard_access()

	company = company or _default_company()
	start = frappe.utils.cint(start)
	page_length = frappe.utils.cint(page_length) or 500
	
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

	# Build base SQL filters
	where_conds = [
		"si.docstatus = 1",
		"si.gst_category != 'Unregistered'"
	]
	params = {}

	if company:
		where_conds.append("si.company = %(company)s")
		params["company"] = company
	
	if internal_customers:
		where_conds.append("si.customer NOT IN %(internal_customers)s")
		params["internal_customers"] = tuple(internal_customers)

	if from_date:
		where_conds.append("si.posting_date >= %(from_date)s")
		params["from_date"] = from_date
	if to_date:
		where_conds.append("si.posting_date <= %(to_date)s")
		params["to_date"] = to_date

	if customer:
		where_conds.append("si.customer = %(customer)s")
		params["customer"] = customer

	if pod_status:
		if pod_status == "Missing":
			where_conds.append("(si.bns_pod_status IS NULL OR si.bns_pod_status = '')")
		else:
			where_conds.append("si.bns_pod_status = %(pod_status)s")
			params["pod_status"] = pod_status

	# Add quick column searches
	if search_name:
		where_conds.append("si.name LIKE %(search_name)s")
		params["search_name"] = f"%{search_name}%"
	if search_customer:
		where_conds.append("si.customer_name LIKE %(search_customer)s")
		params["search_customer"] = f"%{search_customer}%"
	if search_posting_date:
		where_conds.append("si.posting_date LIKE %(search_posting_date)s")
		params["search_posting_date"] = f"%{search_posting_date}%"
	if search_pod_status:
		where_conds.append("si.bns_pod_status LIKE %(search_pod_status)s")
		params["search_pod_status"] = f"%{search_pod_status}%"
	if search_pod_date:
		where_conds.append("si.bns_pod_date LIKE %(search_pod_date)s")
		params["search_pod_date"] = f"%{search_pod_date}%"
	if search_pod_attachment:
		where_conds.append("si.bns_pod_attachment LIKE %(search_pod_attachment)s")
		params["search_pod_attachment"] = f"%{search_pod_attachment}%"

	# Save KPI filters before applying the main dashboard pending condition
	kpi_where_conds = list(where_conds)

	# Base pending OR filters — at least one of the 3 fields must be missing
	where_conds.append("(si.bns_pod_status IS NULL OR si.bns_pod_status = '' OR si.bns_pod_date IS NULL OR si.bns_pod_attachment IS NULL OR si.bns_pod_attachment = '')")

	# Query matching records for current page using raw SQL with JOIN and subquery
	query = f"""
		SELECT 
			si.name,
			si.customer,
			si.customer_name,
			si.posting_date,
			si.grand_total,
			si.currency,
			si.bns_pod_status,
			si.bns_pod_date,
			si.bns_pod_attachment,
			si.po_no,
			si.po_date,
			addr.city,
			addr.state,
			(SELECT GROUP_CONCAT(DISTINCT sii.sales_order SEPARATOR ', ') 
			 FROM `tabSales Invoice Item` sii 
			 WHERE sii.parent = si.name AND sii.sales_order IS NOT NULL AND sii.sales_order != '') as sales_orders
		FROM `tabSales Invoice` si
		LEFT JOIN `tabAddress` addr ON si.customer_address = addr.name
		WHERE {" AND ".join(where_conds)}
		ORDER BY si.posting_date DESC
		LIMIT {start}, {page_length}
	"""
	invoices = frappe.db.sql(query, params, as_dict=True)

	# Calculate counts dynamically at database level
	# Total Pending (at least one missing)
	total_pending_res = frappe.db.sql(f"""
		SELECT COUNT(si.name) as total 
		FROM `tabSales Invoice` si
		LEFT JOIN `tabAddress` addr ON si.customer_address = addr.name
		WHERE {" AND ".join(where_conds)}
	""", params)
	total_pending = total_pending_res[0][0] if total_pending_res else 0

	# 1. Total Done POD: all three fields filled AND status = Delivered
	total_done_res = frappe.db.sql(f"""
		SELECT COUNT(si.name) as total 
		FROM `tabSales Invoice` si
		LEFT JOIN `tabAddress` addr ON si.customer_address = addr.name
		WHERE {" AND ".join(kpi_where_conds)}
		  AND si.bns_pod_status = 'Delivered'
		  AND si.bns_pod_date IS NOT NULL
		  AND si.bns_pod_attachment IS NOT NULL 
		  AND si.bns_pod_attachment != ''
	""", params)
	total_done = total_done_res[0][0] if total_done_res else 0

	# 2. Total Pending POD: all 3 fields missing/blank
	total_pending_all_missing_res = frappe.db.sql(f"""
		SELECT COUNT(si.name) as total 
		FROM `tabSales Invoice` si
		LEFT JOIN `tabAddress` addr ON si.customer_address = addr.name
		WHERE {" AND ".join(kpi_where_conds)}
		  AND (si.bns_pod_status IS NULL OR si.bns_pod_status = '')
		  AND si.bns_pod_date IS NULL
		  AND (si.bns_pod_attachment IS NULL OR si.bns_pod_attachment = '')
	""", params)
	total_pending_all_missing = total_pending_all_missing_res[0][0] if total_pending_all_missing_res else 0

	# 3. Total Partial POD: bns_pod_status = Partially Delivered
	total_partial_res = frappe.db.sql(f"""
		SELECT COUNT(si.name) as total 
		FROM `tabSales Invoice` si
		LEFT JOIN `tabAddress` addr ON si.customer_address = addr.name
		WHERE {" AND ".join(kpi_where_conds)}
		  AND si.bns_pod_status = 'Partially Delivered'
	""", params)
	total_partial = total_partial_res[0][0] if total_partial_res else 0

	return {
		"invoices": invoices,
		"total": total_pending,
		"total_done": total_done,
		"total_pending_all_missing": total_pending_all_missing,
		"total_partial": total_partial,
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
		pod_status (str): One of: Delivered, Partially Delivered, Not Delivered (or blank)
		pod_date (str): Date string YYYY-MM-DD (or blank)
		pod_attachment (str): URL/path of the attachment (or blank)

	Returns:
		dict: {success: True, all_filled: True/False}
	"""
	_require_dashboard_access()

	if not frappe.db.exists("Sales Invoice", sales_invoice):
		frappe.throw(_("Sales Invoice {0} not found.").format(sales_invoice))

	# Validate pod_status is one of allowed values if provided
	allowed_statuses = ["", "Delivered", "Partially Delivered", "Not Delivered"]
	if pod_status and pod_status not in allowed_statuses:
		frappe.throw(_("Invalid POD Status: {0}").format(pod_status))

	# Validate that the invoice is submitted (docstatus=1) — security guard
	doc_status = frappe.db.get_value("Sales Invoice", sales_invoice, "docstatus")
	if doc_status != 1:
		frappe.throw(_("POD details can only be updated for submitted Sales Invoices."))

	# Use frappe.db.set_value to surgically update ONLY the 3 POD fields.
	# DO NOT use doc.save() here — submitted Sales Invoices have many validate/
	# before_save hooks (internal customer checks, GST validations, etc.) that
	# modify unrelated fields, which then appear as dirty/"Not Saved" on next open.
	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		{
			"bns_pod_status": pod_status or "",
			"bns_pod_date": pod_date or None,
			"bns_pod_attachment": pod_attachment or "",
		},
		update_modified=False,
	)
	frappe.db.commit()

	# Programmatically link the file attachment if uploaded as unattached
	if pod_attachment:
		file_doc = frappe.db.get_value(
			"File",
			{"file_url": pod_attachment, "attached_to_name": ("in", ["", None])},
			"name"
		)
		if file_doc:
			frappe.db.set_value(
				"File",
				file_doc,
				{
					"attached_to_doctype": "Sales Invoice",
					"attached_to_name": sales_invoice
				},
				update_modified=False
			)

	# Check if all 3 fields are now filled
	all_filled = bool(pod_status and pod_date and pod_attachment)

	return {"success": True, "all_filled": all_filled}
