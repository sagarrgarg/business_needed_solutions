# Copyright (c) 2026, Business Needed Solutions
# License: Commercial

"""
BNS Dashboard API

Provides data and actions for the BNS Dashboard page.
"""

import frappe
from frappe import _
from frappe.utils import flt, cstr


@frappe.whitelist()
def get_items_missing_expense_account(company=None):
	"""
	Get non-stock items that don't have a default expense account set.
	
	Args:
		company: Optional company filter for Item Default
		
	Returns:
		dict with count and items list
	"""
	# Get default company if not provided
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	# Query for non-stock items without default expense account
	# Excludes fixed asset items (they have their own accounting)
	items = frappe.db.sql("""
		SELECT 
			i.name as item_code,
			i.item_name,
			i.item_group,
			id.expense_account as default_expense_account,
			id.company
		FROM `tabItem` i
		LEFT JOIN `tabItem Default` id 
			ON id.parent = i.name 
			AND id.parenttype = 'Item'
			AND id.company = %(company)s
		WHERE 
			i.is_stock_item = 0
			AND i.is_fixed_asset = 0
			AND i.disabled = 0
			AND (id.expense_account IS NULL OR id.expense_account = '')
		ORDER BY i.item_name
		LIMIT 500
	""", {"company": company}, as_dict=True)
	
	return {
		"count": len(items),
		"items": items,
		"company": company
	}


@frappe.whitelist()
def set_item_expense_account(item_code, expense_account, company=None):
	"""
	Set the default expense account for an item.
	
	Args:
		item_code: The item code
		expense_account: The expense account to set
		company: The company for the item default
		
	Returns:
		dict with success status
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	if not expense_account:
		frappe.throw(_("Expense Account is required"))
	
	# Validate the expense account exists and is an expense type
	account_type = frappe.db.get_value("Account", expense_account, "root_type")
	if account_type != "Expense":
		frappe.throw(_("Account {0} is not an Expense account").format(expense_account))
	
	item_doc = frappe.get_doc("Item", item_code)
	
	# Check if Item Default for this company already exists
	existing_default = None
	for d in item_doc.item_defaults:
		if d.company == company:
			existing_default = d
			break
	
	if existing_default:
		existing_default.expense_account = expense_account
	else:
		item_doc.append("item_defaults", {
			"company": company,
			"expense_account": expense_account
		})
	
	item_doc.save(ignore_permissions=True)
	
	return {
		"success": True,
		"message": _("Expense account set for {0}").format(item_code)
	}


@frappe.whitelist()
def get_purchase_invoices_with_wrong_expense_account(company=None, from_date=None, to_date=None):
	"""
	Get Purchase Invoices where non-stock items have wrong or missing expense accounts.
	
	Returns items where:
	1. Item is non-stock (is_stock_item = 0)
	2. Either:
	   - Item doesn't have a default expense account set, OR
	   - Item has default expense account but PI item has different expense account
	
	Args:
		company: Optional company filter
		from_date: Optional start date filter
		to_date: Optional end date filter
		
	Returns:
		dict with:
		- items_without_default: List of PI items where item has no default expense account
		- items_with_wrong_account: List of PI items where expense account differs from default
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	# Build date filters
	date_conditions = ""
	if from_date:
		date_conditions += " AND pi.posting_date >= %(from_date)s"
	if to_date:
		date_conditions += " AND pi.posting_date <= %(to_date)s"
	
	# Query for PI items with non-stock items
	query = """
		SELECT 
			pi.name as purchase_invoice,
			pi.posting_date,
			pi.supplier,
			pi.supplier_name,
			pii.name as pi_item_name,
			pii.idx as row_idx,
			pii.item_code,
			pii.item_name,
			pii.expense_account as pi_expense_account,
			id.expense_account as item_default_expense_account,
			i.is_stock_item
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		INNER JOIN `tabItem` i ON i.name = pii.item_code
		LEFT JOIN `tabItem Default` id 
			ON id.parent = pii.item_code 
			AND id.parenttype = 'Item'
			AND id.company = %(company)s
		WHERE 
			pi.docstatus = 1
			AND pi.company = %(company)s
			AND i.is_stock_item = 0
			AND i.is_fixed_asset = 0
			{date_conditions}
			AND (
				-- Case 1: No default expense account set
				(id.expense_account IS NULL OR id.expense_account = '')
				OR
				-- Case 2: Default exists but PI has different account
				(id.expense_account IS NOT NULL 
				 AND id.expense_account != '' 
				 AND pii.expense_account != id.expense_account)
			)
		ORDER BY pi.posting_date DESC, pi.name, pii.idx
		LIMIT 1000
	""".format(date_conditions=date_conditions)
	
	items = frappe.db.sql(query, {
		"company": company,
		"from_date": from_date,
		"to_date": to_date
	}, as_dict=True)
	
	# Separate into two categories
	items_without_default = []
	items_with_wrong_account = []
	
	for item in items:
		if not item.item_default_expense_account:
			items_without_default.append(item)
		else:
			items_with_wrong_account.append(item)
	
	return {
		"items_without_default": items_without_default,
		"items_with_wrong_account": items_with_wrong_account,
		"count_without_default": len(items_without_default),
		"count_with_wrong_account": len(items_with_wrong_account),
		"company": company
	}


PI_FIX_BATCH_SIZE = 10


@frappe.whitelist()
def bulk_fix_pi_expense_accounts(items):
	"""
	Enqueue a background job to fix expense accounts on Purchase Invoice items.

	Validates and groups the items by PI, then hands off to a long-running
	worker so the HTTP request returns immediately.

	Args:
		items: JSON list of dicts with pi_item_name and correct_expense_account

	Returns:
		dict with status and total_invoices (or validation_errors if any fail upfront)
	"""
	import json
	if isinstance(items, str):
		items = json.loads(items)

	validation_errors = []

	pi_updates = {}
	for item in items:
		pi_item_name = item.get("pi_item_name")
		correct_account = item.get("correct_expense_account")

		if not pi_item_name or not correct_account:
			validation_errors.append({
				"pi_item_name": pi_item_name,
				"error": _("Missing pi_item_name or correct_expense_account"),
			})
			continue

		pi_name = frappe.db.get_value("Purchase Invoice Item", pi_item_name, "parent")
		if not pi_name:
			validation_errors.append({
				"pi_item_name": pi_item_name,
				"error": _("Purchase Invoice Item not found"),
			})
			continue

		pi_updates.setdefault(pi_name, []).append({
			"pi_item_name": pi_item_name,
			"correct_account": correct_account,
		})

	if not pi_updates:
		return {
			"status": "error",
			"validation_errors": validation_errors,
			"total_invoices": 0,
		}

	frappe.enqueue(
		_process_pi_expense_fix,
		queue="long",
		timeout=1500,
		pi_updates=pi_updates,
		user=frappe.session.user,
	)

	return {
		"status": "queued",
		"total_invoices": len(pi_updates),
		"validation_errors": validation_errors,
	}


def _process_pi_expense_fix(pi_updates, user):
	"""
	Background worker: fix expense accounts on PI items and repost GL.

	Processes PIs in batches of PI_FIX_BATCH_SIZE, committing after each
	batch and publishing realtime progress to the requesting user.

	Args:
		pi_updates: dict mapping PI name -> list of {pi_item_name, correct_account}
		user: frappe user who triggered the job (for realtime scoping)
	"""
	total = len(pi_updates)
	done = 0
	success_count = 0
	errors = []

	pi_list = list(pi_updates.items())

	for idx, (pi_name, item_updates) in enumerate(pi_list, 1):
		try:
			pi_doc = frappe.get_doc("Purchase Invoice", pi_name)

			if pi_doc.docstatus != 1:
				for iu in item_updates:
					errors.append({
						"pi_item_name": iu["pi_item_name"],
						"error": _("Purchase Invoice {0} is not submitted").format(pi_name),
					})
				done += 1
				_publish_progress(done, total, pi_name, success_count, errors, user)
				continue

			items_updated = 0
			for iu in item_updates:
				for row in pi_doc.items:
					if row.name == iu["pi_item_name"]:
						row.expense_account = iu["correct_account"]
						row.db_set("expense_account", iu["correct_account"], update_modified=False)
						items_updated += 1
						break

			if items_updated > 0:
				pi_doc.repost_accounting_entries()
				success_count += items_updated

		except Exception as e:
			for iu in item_updates:
				errors.append({
					"pi_item_name": iu["pi_item_name"],
					"error": cstr(e),
				})

		done += 1

		if idx % PI_FIX_BATCH_SIZE == 0:
			frappe.db.commit()

		_publish_progress(done, total, pi_name, success_count, errors, user)

	frappe.db.commit()

	frappe.publish_realtime(
		"bns_pi_fix_complete",
		{
			"success_count": success_count,
			"error_count": len(errors),
			"errors": errors[:50],
		},
		user=user,
	)


def _publish_progress(done, total, current_pi, success_count, errors, user):
	"""Emit a realtime progress event scoped to the requesting user."""
	frappe.publish_realtime(
		"bns_pi_fix_progress",
		{
			"done": done,
			"total": total,
			"current_pi": current_pi,
			"success_count": success_count,
			"error_count": len(errors),
		},
		user=user,
	)


@frappe.whitelist()
def get_expense_accounts(company=None):
	"""
	Get list of expense accounts for the company.
	
	Args:
		company: The company to get accounts for
		
	Returns:
		list of expense accounts
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	accounts = frappe.get_all(
		"Account",
		filters={
			"company": company,
			"root_type": "Expense",
			"is_group": 0,
			"disabled": 0
		},
		fields=["name", "account_name"],
		order_by="name",
		limit=500
	)
	
	return accounts


@frappe.whitelist()
def get_all_expense_items(company=None):
	"""
	Get all non-stock, non-fixed-asset items with their current expense accounts.
	
	Args:
		company: Optional company filter for Item Default
		
	Returns:
		dict with count and items list
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	items = frappe.db.sql("""
		SELECT 
			i.name as item_code,
			i.item_name,
			i.item_group,
			id.expense_account,
			id.company
		FROM `tabItem` i
		LEFT JOIN `tabItem Default` id 
			ON id.parent = i.name 
			AND id.parenttype = 'Item'
			AND id.company = %(company)s
		WHERE 
			i.is_stock_item = 0
			AND i.is_fixed_asset = 0
			AND i.disabled = 0
		ORDER BY i.item_name
		LIMIT 1000
	""", {"company": company}, as_dict=True)
	
	return {
		"count": len(items),
		"items": items,
		"company": company
	}


@frappe.whitelist()
def get_dashboard_summary(company=None):
	"""
	Get overall dashboard summary statistics.
	
	Args:
		company: Optional company filter
		
	Returns:
		dict with various counts
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	# Count of non-stock items without expense account (excludes fixed assets)
	items_missing_count = frappe.db.sql("""
		SELECT COUNT(DISTINCT i.name)
		FROM `tabItem` i
		LEFT JOIN `tabItem Default` id 
			ON id.parent = i.name 
			AND id.parenttype = 'Item'
			AND id.company = %(company)s
		WHERE 
			i.is_stock_item = 0
			AND i.is_fixed_asset = 0
			AND i.disabled = 0
			AND (id.expense_account IS NULL OR id.expense_account = '')
	""", {"company": company})[0][0] or 0
	
	# Count of PI items with wrong expense account (fixable, excludes fixed assets)
	pi_fixable_count = frappe.db.sql("""
		SELECT COUNT(*)
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		INNER JOIN `tabItem` i ON i.name = pii.item_code
		INNER JOIN `tabItem Default` id 
			ON id.parent = pii.item_code 
			AND id.parenttype = 'Item'
			AND id.company = %(company)s
		WHERE 
			pi.docstatus = 1
			AND pi.company = %(company)s
			AND i.is_stock_item = 0
			AND i.is_fixed_asset = 0
			AND id.expense_account IS NOT NULL 
			AND id.expense_account != '' 
			AND pii.expense_account != id.expense_account
	""", {"company": company})[0][0] or 0
	
	# Count of unlinked customer/supplier by PAN
	unlinked_pan_count = get_unlinked_pan_count()
	
	# Get lightweight transfer mismatch info from last prepared report
	transfer_mismatch_info = get_transfer_mismatch_summary(company)
	
	return {
		"items_missing_expense_account": items_missing_count,
		"pi_items_fixable": pi_fixable_count,
		"unlinked_pan_count": unlinked_pan_count,
		"transfer_mismatch_count": transfer_mismatch_info.get("count", 0),
		"transfer_mismatch_prepared_at": transfer_mismatch_info.get("prepared_at"),
		"transfer_mismatch_status": transfer_mismatch_info.get("status"),
		"company": company
	}


def get_unlinked_pan_count():
	"""Get count of customer/supplier pairs with same PAN but no Party Link."""
	data = get_unlinked_customer_supplier_by_pan()
	return len(data.get("records", []))


@frappe.whitelist()
def get_unlinked_customer_supplier_by_pan():
	"""
	Get customers and suppliers with matching PAN but no Party Link.
	Uses batch Party Link lookup to avoid N+1 queries.
	
	Returns:
		dict with count and records list
	"""
	# Fetch Active Customers with PAN
	customers = frappe.db.get_list(
		"Customer",
		filters=[["pan", "!=", ""], ["disabled", "=", 0]],
		fields=["name", "pan", "customer_name"]
	)
	
	# Fetch Active Suppliers with PAN
	suppliers = frappe.db.get_list(
		"Supplier",
		filters=[["pan", "!=", ""], ["disabled", "=", 0]],
		fields=["name", "pan", "supplier_name"]
	)
	
	# Create a Supplier lookup dictionary by PAN
	supplier_dict = {}
	for s in suppliers:
		if s["pan"]:
			supplier_dict[s["pan"]] = {
				"name": s["name"],
				"supplier_name": s["supplier_name"]
			}
	
	# Batch-fetch ALL Party Links upfront (avoids N+1 db.exists per pair)
	all_party_links = set()
	for pl in frappe.get_all("Party Link", fields=["primary_party", "secondary_party"]):
		all_party_links.add((pl.primary_party, pl.secondary_party))
		all_party_links.add((pl.secondary_party, pl.primary_party))
	
	records = []
	
	for customer in customers:
		pan = customer.get("pan")
		if not pan or pan not in supplier_dict:
			continue
		
		supplier_info = supplier_dict[pan]
		supplier_name = supplier_info["name"]
		
		# Check both directions using the pre-fetched set (O(1) lookup)
		party_link_exists = (
			(customer["name"], supplier_name) in all_party_links
			or (supplier_name, customer["name"]) in all_party_links
		)
		
		if not party_link_exists:
			records.append({
				"customer": customer["name"],
				"customer_name": customer.get("customer_name") or customer["name"],
				"supplier": supplier_name,
				"supplier_name": supplier_info.get("supplier_name") or supplier_name,
				"pan": pan
			})
	
	return {
		"count": len(records),
		"records": records
	}


@frappe.whitelist()
def create_party_link(primary_party, secondary_party, primary_role, secondary_role):
	"""
	Create a Party Link between customer and supplier.
	
	Args:
		primary_party: Primary party name
		secondary_party: Secondary party name
		primary_role: Primary party type (Customer/Supplier)
		secondary_role: Secondary party type (Customer/Supplier)
		
	Returns:
		dict with success status and party link name
	"""
	# Validate inputs
	if not primary_party or not secondary_party:
		frappe.throw(_("Both parties are required"))
	
	if primary_role not in ("Customer", "Supplier") or secondary_role not in ("Customer", "Supplier"):
		frappe.throw(_("Invalid party role"))
	
	# Check if link already exists
	existing = frappe.db.exists(
		"Party Link",
		{
			"primary_party": primary_party,
			"secondary_party": secondary_party
		}
	) or frappe.db.exists(
		"Party Link",
		{
			"primary_party": secondary_party,
			"secondary_party": primary_party
		}
	)
	
	if existing:
		return {
			"success": False,
			"message": _("Party Link already exists")
		}
	
	# Create the Party Link
	party_link = frappe.get_doc({
		"doctype": "Party Link",
		"primary_role": primary_role,
		"primary_party": primary_party,
		"secondary_role": secondary_role,
		"secondary_party": secondary_party
	})
	party_link.insert(ignore_permissions=True)
	
	return {
		"success": True,
		"message": _("Party Link created"),
		"party_link": party_link.name
	}


def get_transfer_mismatch_summary(company=None):
	"""
	Get lightweight transfer mismatch info from the latest Prepared Report.
	Does NOT run the full report — only reads cached results.

	Args:
		company: Optional company filter

	Returns:
		dict with count, prepared_at, and status
	"""
	report_name = "Internal Transfer Receive Mismatch"

	# Find the latest completed Prepared Report for this report
	latest = frappe.db.get_value(
		"Prepared Report",
		filters={
			"report_name": report_name,
			"status": "Completed",
		},
		fieldname=["name", "creation"],
		order_by="creation desc",
		as_dict=True,
	)

	if not latest:
		# Check if one is queued/started
		pending = frappe.db.get_value(
			"Prepared Report",
			filters={
				"report_name": report_name,
				"status": ("in", ("Queued", "Started")),
			},
			fieldname=["name", "status", "creation"],
			order_by="creation desc",
			as_dict=True,
		)
		if pending:
			return {
				"count": 0,
				"prepared_at": None,
				"status": pending.status,
				"prepared_report_name": pending.name,
			}
		return {"count": 0, "prepared_at": None, "status": "Not Prepared"}

	# Read the row count from the prepared report's cached data
	count = 0
	try:
		pr_doc = frappe.get_doc("Prepared Report", latest.name)
		import json as _json

		raw_data = pr_doc.get_prepared_data()
		if raw_data:
			data = _json.loads(raw_data.decode("utf-8"))
			# data is either {"result": [...], "columns": [...]} or a plain list
			if isinstance(data, dict):
				result = data.get("result", [])
			else:
				result = data
			count = len(result) if isinstance(result, list) else 0
	except (FileNotFoundError, OSError):
		# Data file was deleted from disk — treat as stale/unavailable
		return {"count": 0, "prepared_at": None, "status": "Not Prepared"}
	except Exception:
		count = 0

	return {
		"count": count,
		"prepared_at": str(latest.creation),
		"status": "Completed",
		"prepared_report_name": latest.name,
	}


@frappe.whitelist()
def get_internal_transfer_mismatches(company=None):
	"""
	Get internal transfer mismatch data from the latest completed Prepared Report.
	Does NOT run the full report live — reads cached/prepared results only.

	Args:
		company: Optional company filter

	Returns:
		dict with count, records, prepared_at, and status
	"""
	import gzip
	import json as _json

	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")

	report_name = "Internal Transfer Receive Mismatch"

	# Find the latest completed Prepared Report
	latest = frappe.db.get_value(
		"Prepared Report",
		filters={
			"report_name": report_name,
			"status": "Completed",
		},
		fieldname=["name", "creation", "filters"],
		order_by="creation desc",
		as_dict=True,
	)

	if not latest:
		# Check for pending
		pending = frappe.db.get_value(
			"Prepared Report",
			filters={
				"report_name": report_name,
				"status": ("in", ("Queued", "Started")),
			},
			fieldname=["name", "status", "creation"],
			order_by="creation desc",
			as_dict=True,
		)
		return {
			"count": 0,
			"records": [],
			"company": company,
			"prepared_at": None,
			"status": pending.status if pending else "Not Prepared",
			"prepared_report_name": pending.name if pending else None,
		}

	# Read the full data from the prepared report
	records = []
	try:
		pr_doc = frappe.get_doc("Prepared Report", latest.name)
		raw_data = pr_doc.get_prepared_data()
		if raw_data:
			data = _json.loads(raw_data.decode("utf-8"))
			if isinstance(data, dict):
				result = data.get("result", [])
			else:
				result = data

			# Transform report rows to dashboard format
			for row in (result or []):
				mismatch_type = "Mismatch"
				mismatch_reason = row.get("mismatch_reason") or ""

				missing_doc = row.get("missing_document") or ""
				if "No PR" in mismatch_reason or missing_doc == "Purchase Receipt":
					mismatch_type = "Missing PR"
				elif "No PI" in mismatch_reason or missing_doc == "Purchase Invoice":
					mismatch_type = "Missing PI"
				elif "Mismatch" in missing_doc:
					mismatch_type = "Mismatch"

				linked_doc = row.get("purchase_receipt") or row.get("purchase_invoice")

				records.append({
					"posting_date": row.get("posting_date"),
					"document_type": row.get("document_type"),
					"document_name": row.get("document_name"),
					"grand_total": flt(row.get("grand_total")),
					"customer": "",
					"mismatch_type": mismatch_type,
					"mismatch_reason": mismatch_reason,
					"linked_document": linked_doc,
				})
	except (FileNotFoundError, OSError):
		# Data file was deleted from disk — stale prepared report
		return {
			"count": 0,
			"records": [],
			"company": company,
			"prepared_at": None,
			"status": "Not Prepared",
			"prepared_report_name": None,
		}
	except Exception as e:
		frappe.log_error(title="BNS Dashboard: Prepared report read error", message=str(e))

	return {
		"count": len(records),
		"records": records[:100],
		"company": company,
		"prepared_at": str(latest.creation),
		"status": "Completed",
		"prepared_report_name": latest.name,
	}


@frappe.whitelist()
def trigger_mismatch_report_preparation(company=None, from_date=None, to_date=None):
	"""
	Trigger a new Prepared Report for Internal Transfer Receive Mismatch.
	Enqueues the report generation in the background.

	Args:
		company: Optional company filter
		from_date: Optional start date
		to_date: Optional end date

	Returns:
		dict with prepared_report name and status
	"""
	import json as _json
	from frappe.core.doctype.prepared_report.prepared_report import get_reports_in_queued_state

	report_name = "Internal Transfer Receive Mismatch"

	filters = {}
	if company:
		filters["company"] = company
	if from_date:
		filters["from_date"] = from_date
	if to_date:
		filters["to_date"] = to_date

	# Check if a report is already queued/started
	queued = get_reports_in_queued_state(report_name, _json.dumps(filters))
	if queued:
		return {
			"status": "Already Queued",
			"prepared_report_name": queued[0].get("name"),
			"message": _("A report is already being prepared. Please wait."),
		}

	# Create a new Prepared Report (this auto-enqueues via after_insert)
	from frappe.core.doctype.prepared_report.prepared_report import make_prepared_report

	result = make_prepared_report(report_name, _json.dumps(filters))

	return {
		"status": "Queued",
		"prepared_report_name": result.get("name"),
		"message": _("Report preparation started. This may take a few minutes."),
	}


@frappe.whitelist()
def get_food_company_addresses(company=None):
	"""
	Get all company addresses with FSSAI license info when company is a food company.

	Args:
		company: Optional company filter; defaults to user default.

	Returns:
		dict with is_food_company, addresses list
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")

	if not company:
		return {"is_food_company": False, "addresses": []}

	is_food_company = frappe.db.get_value("Company", company, "bns_is_food_company")
	if not is_food_company:
		return {"is_food_company": False, "addresses": []}

	from frappe.contacts.doctype.address.address import get_address_display

	addresses = frappe.db.sql("""
		SELECT a.name, a.address_title, a.address_type,
			a.address_line1, a.address_line2, a.city, a.county, a.state, a.country, a.pincode,
			a.bns_fssai_license_no
		FROM `tabAddress` a
		INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
			AND dl.link_doctype = 'Company' AND dl.link_name = %(company)s
		WHERE a.disabled = 0
		ORDER BY a.address_title, a.address_type
	""", {"company": company}, as_dict=True)

	result = []
	for addr in addresses:
		full_address = get_address_display(addr)
		fssai = (addr.get("bns_fssai_license_no") or "").strip()
		result.append({
			"name": addr.name,
			"address_title": addr.address_title or addr.name,
			"address_type": addr.address_type,
			"full_address": full_address or "",
			"fssai_license_no": fssai,
			"has_fssai": bool(fssai),
		})

	return {
		"is_food_company": True,
		"addresses": result,
		"company": company,
	}


@frappe.whitelist()
def set_address_fssai(address_name, fssai_license_no):
	"""
	Set FSSAI License No. on an Address from the dashboard.

	Args:
		address_name: The Address document name
		fssai_license_no: The FSSAI license number to set (can be empty to clear)

	Returns:
		dict with success status
	"""
	if not address_name:
		frappe.throw(_("Address is required"))

	if not frappe.db.exists("Address", address_name):
		frappe.throw(_("Address {0} not found").format(address_name))

	frappe.db.set_value(
		"Address",
		address_name,
		"bns_fssai_license_no",
		(fssai_license_no or "").strip(),
		update_modified=True,
	)

	return {"success": True, "message": _("FSSAI license updated")}


@frappe.whitelist()
def get_prepared_report_status(prepared_report_name):
	"""
	Check the status of a specific Prepared Report.

	Args:
		prepared_report_name: The Prepared Report document name

	Returns:
		dict with status and error_message if any
	"""
	if not prepared_report_name:
		return {"status": "Not Found"}

	doc = frappe.db.get_value(
		"Prepared Report",
		prepared_report_name,
		["status", "error_message", "creation", "report_end_time"],
		as_dict=True,
	)

	if not doc:
		return {"status": "Not Found"}

	return {
		"status": doc.status,
		"error_message": doc.error_message,
		"created_at": str(doc.creation) if doc.creation else None,
		"completed_at": str(doc.report_end_time) if doc.report_end_time else None,
	}


# =====================================================================
# Health Check Overview APIs
# =====================================================================

def _default_company(company=None):
	"""Resolve company from argument, user default, or global default."""
	return (
		company
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)


@frappe.whitelist()
def get_health_check_overview(company=None):
	"""
	Single API returning all BNS health-check metrics.
	Minimises round-trips by bundling accounting, branch-accounting,
	stock, and compliance data in one call.

	Args:
		company: Optional company; falls back to user/global default.

	Returns:
		dict with keys: accounting, branch_accounting, stock, compliance, company
	"""
	company = _default_company(company)
	return {
		"branch_accounting": _get_branch_accounting_metrics(company),
		"stock": _get_stock_metrics(company),
		"compliance": _get_compliance_metrics(company),
		"company": company,
	}


def _get_branch_accounting_metrics(company):
	"""
	Internal-transfer completion rates and repost health.

	DN → PR completion applies to same-GSTIN transfers only
	(company_gstin = billing_address_gstin).
	SI → PI completion applies to different-GSTIN transfers only
	(company_gstin != billing_address_gstin).

	Only documents posted on or after the Internal Transfer Cutoff FY
	start date are counted, matching what the branch accounting reports show.
	"""
	from business_needed_solutions.bns_branch_accounting.utils import (
		_get_internal_transfer_cutoff_date,
	)

	cutoff = _get_internal_transfer_cutoff_date()

	SAME_GSTIN = (
		"AND company_gstin IS NOT NULL AND company_gstin != '' "
		"AND billing_address_gstin IS NOT NULL AND billing_address_gstin != '' "
		"AND company_gstin = billing_address_gstin"
	)
	DIFF_GSTIN = (
		"AND company_gstin IS NOT NULL AND company_gstin != '' "
		"AND billing_address_gstin IS NOT NULL AND billing_address_gstin != '' "
		"AND company_gstin != billing_address_gstin"
	)

	cutoff_clause = ""
	params = (company,)
	if cutoff:
		cutoff_clause = "AND posting_date >= %s"
		params = (company, cutoff)

	dns_without_pr = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabDelivery Note` "
		"WHERE docstatus=1 AND company=%s AND is_bns_internal_customer=1 "
		"AND (bns_inter_company_reference IS NULL OR bns_inter_company_reference='') "
		+ SAME_GSTIN + " " + cutoff_clause,
		params,
	)[0][0] or 0

	sis_without_pi = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabSales Invoice` "
		"WHERE docstatus=1 AND company=%s AND is_bns_internal_customer=1 "
		"AND (bns_inter_company_reference IS NULL OR bns_inter_company_reference='') "
		+ DIFF_GSTIN + " " + cutoff_clause,
		params,
	)[0][0] or 0

	total_internal_dns = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabDelivery Note` "
		"WHERE docstatus=1 AND company=%s AND is_bns_internal_customer=1 "
		+ SAME_GSTIN + " " + cutoff_clause,
		params,
	)[0][0] or 0

	total_internal_sis = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabSales Invoice` "
		"WHERE docstatus=1 AND company=%s AND is_bns_internal_customer=1 "
		+ DIFF_GSTIN + " " + cutoff_clause,
		params,
	)[0][0] or 0

	pending_repost = frappe.db.count("Repost Item Valuation", {
		"docstatus": 1,
		"status": ("in", ("Queued", "In Progress")),
		"company": company,
	})

	repost_tracking = 0
	if frappe.db.exists("DocType", "BNS Repost Tracking"):
		repost_tracking = frappe.db.count("BNS Repost Tracking")

	return {
		"dns_without_pr": dns_without_pr,
		"sis_without_pi": sis_without_pi,
		"total_internal_dns": total_internal_dns,
		"total_internal_sis": total_internal_sis,
		"pending_repost": pending_repost,
		"repost_tracking": repost_tracking,
		"cutoff_date": str(cutoff),
	}


def _get_stock_metrics(company):
	"""Negative-stock guards, violations, and reconciliation queue."""
	guarded_warehouses = frappe.db.count("Warehouse", {
		"company": company,
		"bns_disallow_negative_stock": 1,
		"disabled": 0,
	})

	total_warehouses = frappe.db.count("Warehouse", {
		"company": company,
		"is_group": 0,
		"disabled": 0,
	})

	negative_stock_items = frappe.db.sql(
		"SELECT COUNT(DISTINCT b.item_code) FROM `tabBin` b "
		"INNER JOIN `tabWarehouse` w ON w.name=b.warehouse "
		"WHERE w.company=%s AND b.actual_qty<0", company
	)[0][0] or 0

	negative_stock_warehouses = frappe.db.sql(
		"SELECT COUNT(DISTINCT b.warehouse) FROM `tabBin` b "
		"INNER JOIN `tabWarehouse` w ON w.name=b.warehouse "
		"WHERE w.company=%s AND b.actual_qty<0", company
	)[0][0] or 0

	draft_reconciliations = frappe.db.count("Stock Reconciliation", {
		"company": company,
		"docstatus": 0,
	})

	return {
		"guarded_warehouses": guarded_warehouses,
		"total_warehouses": total_warehouses,
		"negative_stock_items": negative_stock_items,
		"negative_stock_warehouses": negative_stock_warehouses,
		"draft_reconciliations": draft_reconciliations,
	}


def _get_compliance_metrics(company):
	"""Attachment and supplier-invoice compliance on PR / PI.
	Excludes internal suppliers and return documents (consistent with
	attachment_validation.py which skips returns)."""
	NOT_INTERNAL_OR_RETURN = "AND is_bns_internal_supplier=0 AND is_return=0"

	pr_without_attachment = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabPurchase Receipt` "
		"WHERE docstatus=1 AND company=%s "
		"AND (bns_supplier_invoice_attachment IS NULL OR bns_supplier_invoice_attachment='') "
		+ NOT_INTERNAL_OR_RETURN, company
	)[0][0] or 0

	total_prs = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabPurchase Receipt` "
		"WHERE docstatus=1 AND company=%s " + NOT_INTERNAL_OR_RETURN, company
	)[0][0] or 0

	pi_without_attachment = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabPurchase Invoice` "
		"WHERE docstatus=1 AND company=%s "
		"AND (bns_supplier_invoice_attachment IS NULL OR bns_supplier_invoice_attachment='') "
		+ NOT_INTERNAL_OR_RETURN, company
	)[0][0] or 0

	total_pis = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabPurchase Invoice` "
		"WHERE docstatus=1 AND company=%s " + NOT_INTERNAL_OR_RETURN, company
	)[0][0] or 0

	return {
		"pr_without_attachment": pr_without_attachment,
		"total_prs": total_prs,
		"pi_without_attachment": pi_without_attachment,
		"total_pis": total_pis,
	}
