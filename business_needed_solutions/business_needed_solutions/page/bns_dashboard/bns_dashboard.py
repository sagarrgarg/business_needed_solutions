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


@frappe.whitelist()
def bulk_fix_pi_expense_accounts(items):
	"""
	Bulk fix expense accounts in Purchase Invoice items.
	
	Only fixes items where the Item has a default expense account set.
	Uses proper doc API to update expense_account and repost GL entries.
	
	Args:
		items: List of dicts with pi_item_name and correct_expense_account
		
	Returns:
		dict with success count and errors
	"""
	import json
	if isinstance(items, str):
		items = json.loads(items)
	
	success_count = 0
	errors = []
	
	# Group items by Purchase Invoice to minimize doc loads
	pi_updates = {}
	for item in items:
		pi_item_name = item.get("pi_item_name")
		correct_account = item.get("correct_expense_account")
		
		if not pi_item_name or not correct_account:
			errors.append({
				"pi_item_name": pi_item_name,
				"error": _("Missing pi_item_name or correct_expense_account")
			})
			continue
		
		# Get the PI item parent
		pi_name = frappe.db.get_value("Purchase Invoice Item", pi_item_name, "parent")
		if not pi_name:
			errors.append({
				"pi_item_name": pi_item_name,
				"error": _("Purchase Invoice Item not found")
			})
			continue
		
		if pi_name not in pi_updates:
			pi_updates[pi_name] = []
		pi_updates[pi_name].append({
			"pi_item_name": pi_item_name,
			"correct_account": correct_account
		})
	
	# Process each Purchase Invoice
	for pi_name, item_updates in pi_updates.items():
		try:
			# Load the Purchase Invoice
			pi_doc = frappe.get_doc("Purchase Invoice", pi_name)
			
			if pi_doc.docstatus != 1:
				for item_update in item_updates:
					errors.append({
						"pi_item_name": item_update["pi_item_name"],
						"error": _("Purchase Invoice {0} is not submitted").format(pi_name)
					})
				continue
			
			# Update expense accounts on matching items using db_set
			items_updated = 0
			for item_update in item_updates:
				for row in pi_doc.items:
					if row.name == item_update["pi_item_name"]:
						# Update in memory for repost
						row.expense_account = item_update["correct_account"]
						# Update in database
						row.db_set("expense_account", item_update["correct_account"], update_modified=False)
						items_updated += 1
						break
			
			if items_updated > 0:
				# Repost accounting entries to update GL
				pi_doc.repost_accounting_entries()
				success_count += items_updated
			
		except Exception as e:
			for item_update in item_updates:
				errors.append({
					"pi_item_name": item_update["pi_item_name"],
					"error": cstr(e)
				})
	
	return {
		"success_count": success_count,
		"error_count": len(errors),
		"errors": errors
	}


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
	
	# Count of internal transfer mismatches
	transfer_mismatch_count = get_internal_transfer_mismatch_count(company)
	
	return {
		"items_missing_expense_account": items_missing_count,
		"pi_items_fixable": pi_fixable_count,
		"unlinked_pan_count": unlinked_pan_count,
		"transfer_mismatch_count": transfer_mismatch_count,
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
	
	records = []
	
	for customer in customers:
		pan = customer.get("pan")
		if not pan or pan not in supplier_dict:
			continue
		
		supplier_info = supplier_dict[pan]
		supplier_name = supplier_info["name"]
		
		# Check if Party Link exists in either direction
		party_link_exists = frappe.db.exists(
			"Party Link",
			{
				"primary_party": customer["name"],
				"secondary_party": supplier_name
			}
		) or frappe.db.exists(
			"Party Link",
			{
				"primary_party": supplier_name,
				"secondary_party": customer["name"]
			}
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


@frappe.whitelist()
def get_internal_transfer_mismatches(company=None, from_date=None, to_date=None):
	"""
	Get internal transfer mismatches (DN to PR, SI to PI).
	
	Reuses logic from Internal Transfer Receive Mismatch report.
	
	Args:
		company: Optional company filter
		from_date: Optional start date filter
		to_date: Optional end date filter
		
	Returns:
		dict with count and records list
	"""
	# Import the report module to reuse its logic
	from business_needed_solutions.business_needed_solutions.report.internal_transfer_receive_mismatch import (
		internal_transfer_receive_mismatch as itrm_report
	)
	
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	# Build filters for the report
	filters = frappe._dict({
		"company": company,
		"from_date": from_date,
		"to_date": to_date
	})
	
	# Get data from the report
	try:
		report_data = itrm_report.get_data(filters) or []
	except Exception as e:
		frappe.log_error(f"Error getting internal transfer mismatches: {e}")
		report_data = []
	
	# Transform report data to dashboard format
	records = []
	for row in report_data:
		mismatch_type = "Mismatch"
		mismatch_reason = row.get("mismatch_reason") or ""
		
		# Determine type based on missing_document field
		missing_doc = row.get("missing_document") or ""
		if "No PR" in mismatch_reason or missing_doc == "Purchase Receipt":
			mismatch_type = "Missing PR"
		elif "No PI" in mismatch_reason or missing_doc == "Purchase Invoice":
			mismatch_type = "Missing PI"
		elif "Mismatch" in missing_doc:
			mismatch_type = "Mismatch"
		
		# Get linked document
		linked_doc = row.get("purchase_receipt") or row.get("purchase_invoice")
		
		records.append({
			"posting_date": row.get("posting_date"),
			"document_type": row.get("document_type"),
			"document_name": row.get("document_name"),
			"grand_total": flt(row.get("grand_total")),
			"customer": "",  # Report doesn't include customer directly
			"mismatch_type": mismatch_type,
			"mismatch_reason": mismatch_reason,
			"linked_document": linked_doc
		})
	
	# Limit to 100 for dashboard
	return {
		"count": len(records),
		"records": records[:100],
		"company": company
	}


def get_internal_transfer_mismatch_count(company=None):
	"""Get count of internal transfer mismatches for dashboard summary."""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	
	data = get_internal_transfer_mismatches(company)
	return data.get("count", 0)
