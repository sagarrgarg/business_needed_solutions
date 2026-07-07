# Copyright (c) 2026, Business Needed Solutions
# License: Commercial

"""
BNS Dashboard API

Provides data and actions for the BNS Dashboard page.
"""

import frappe
from frappe import _
from frappe.utils import flt, cstr


# -------------------------------------------------------------------
# Permission gates for the BNS Dashboard whitelisted endpoints.
#
# Why: every entry point here either reads sensitive accounting data
# (expense accounts, PI/SI totals, party balances) or writes to Item /
# Purchase Invoice / GL. Several callers also use ignore_permissions=True
# internally, so the outer gate is the last line of defence.
#
# IMPORTANT: these helpers do NOT hardcode role names. They consult the
# Frappe Role Permission Manager via frappe.has_permission(doctype, action).
# Admins configure who can read/write the BNS Dashboard by editing BNS
# Settings role permissions in the Desk — no code change required. Each
# write endpoint additionally verifies write permission on the specific
# target doctype (Item, Purchase Invoice, Party Link, Address, ...).
# -------------------------------------------------------------------


def _require_dashboard_read():
	"""Any read endpoint: caller must have read permission on BNS Settings
	(the Single doctype that holds the app's config). Configure via the
	Role Permission Manager on the BNS Settings doctype."""
	if not frappe.has_permission("BNS Settings", "read"):
		frappe.throw(
			_("You need read permission on BNS Settings to use the BNS Dashboard. "
			  "Ask an administrator to grant your role read access via the Role Permission Manager."),
			frappe.PermissionError,
		)


def _require_dashboard_write(*doctypes):
	"""Write endpoint: caller must have write permission on BNS Settings
	AND write permission on every doctype this endpoint is about to
	save/submit. Both checks go through frappe.has_permission so the
	Role Permission Manager is the single source of truth."""
	if not frappe.has_permission("BNS Settings", "write"):
		frappe.throw(
			_("You need write permission on BNS Settings for this action. "
			  "Ask an administrator to grant your role write access via the Role Permission Manager."),
			frappe.PermissionError,
		)
	for dt in doctypes:
		if not frappe.has_permission(dt, "write"):
			frappe.throw(
				_("You do not have write permission on {0}.").format(dt),
				frappe.PermissionError,
			)


def _require_fixables_enabled(field, label):
	"""Hard gate on a BNS Settings toggle. The Expense Item Fixables and TDS
	Category Fixables tools are each disabled by default and must be switched
	on in BNS Settings before any of their endpoints will run."""
	if not frappe.db.get_single_value("BNS Settings", field):
		frappe.throw(
			_("{0} is disabled. Enable it in BNS Settings.").format(label),
			frappe.PermissionError,
		)


def _require_expense_fixables():
	"""Gate for every Expense Item Fixables endpoint: System Manager role AND
	the BNS Settings toggle. Invoice edits are additionally clamped to the
	current fiscal year at query/worker level."""
	_require_system_manager()
	_require_fixables_enabled("enable_expense_item_fixables", _("Expense Item Fixables"))


def _require_tds_fixables():
	"""Gate for every TDS Category Fixables endpoint: System Manager role AND
	the BNS Settings toggle. Invoice edits are additionally clamped to the
	current fiscal year at query/worker level."""
	_require_system_manager()
	_require_fixables_enabled("enable_tds_category_fixables", _("TDS Category Fixables"))


@frappe.whitelist()
def get_fixables_config():
	"""Frontend gate helper: which dashboard fixables the current user may see.
	Both tools require the BNS Settings toggle AND the System Manager role."""
	_require_dashboard_read()
	is_sys_mgr = "System Manager" in frappe.get_roles()
	return {
		"is_system_manager": is_sys_mgr,
		"expense_enabled": bool(frappe.db.get_single_value("BNS Settings", "enable_expense_item_fixables")) and is_sys_mgr,
		"tds_enabled": bool(frappe.db.get_single_value("BNS Settings", "enable_tds_category_fixables")) and is_sys_mgr,
	}


@frappe.whitelist()
def get_items_missing_expense_account(company=None):
	"""
	Get non-stock items that don't have a default expense account set.

	Args:
		company: Optional company filter for Item Default

	Returns:
		dict with count and items list
	"""
	_require_dashboard_read()
	_require_expense_fixables()
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
	_require_dashboard_write("Item")
	_require_expense_fixables()
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
	_require_dashboard_read()
	_require_expense_fixables()
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")

	# Restrict to the CURRENT fiscal year -- older invoices are never listed
	# and are refused by the background worker too. System Manager only.
	fy_start, fy_end = _current_fiscal_year(company)
	date_conditions = " AND pi.posting_date >= %(fy_start)s AND pi.posting_date <= %(fy_end)s"
	
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
		"fy_start": fy_start,
		"fy_end": fy_end,
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
	# Gate on Purchase Invoice write — repost_accounting_entries is a standard
	# PI operation and handles the GL Entry writes internally with
	# ignore_permissions=True. Requiring direct GL Entry write here would lock
	# the action to System / Accounts Manager only, which is stricter than the
	# underlying ERPNext flow needs.
	_require_dashboard_write("Purchase Invoice")
	_require_expense_fixables()
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

			# Current-fiscal-year guard: never mutate older invoices, even if a
			# stale client pushed one through.
			fy_start, fy_end = _current_fiscal_year(pi_doc.company)
			if not (str(fy_start) <= str(pi_doc.posting_date) <= str(fy_end)):
				for iu in item_updates:
					errors.append({
						"pi_item_name": iu["pi_item_name"],
						"error": _("Purchase Invoice {0} is outside the current fiscal year").format(pi_name),
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
	_require_dashboard_read()
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
	_require_dashboard_read()
	_require_expense_fixables()
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


# ===================================================================
# TDS Category Fixables (System Manager only)
#
# Mirrors the Expense Item Fixables tools but for Tax Withholding
# ("TDS") Category on Suppliers and Purchase Invoices:
#   1. Suppliers missing a TDS Category  -> fill whichever empty
#   2. Purchase Invoices (current FY) whose tax_withholding_category
#      disagrees with the supplier's  -> bulk correct the field
#   3. Full supplier list with their current TDS Category
#
# Every endpoint here is gated to the System Manager role, per the
# requirement that this whole area is disabled for everyone else.
# ===================================================================


def _require_system_manager():
	"""Hard gate: only System Manager may read or act on the TDS Category
	Fixables tools. Enforced server-side so hiding the UI is not the only
	line of defence."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("The TDS Category Fixables tools are restricted to the System Manager role."),
			frappe.PermissionError,
		)


def _current_fiscal_year(company):
	"""Return (start_date, end_date) of the fiscal year containing today for
	the given company. Falls back to the global FY if company has none."""
	from erpnext.accounts.utils import get_fiscal_year
	from frappe.utils import nowdate

	fy = get_fiscal_year(nowdate(), company=company, as_dict=True)
	return fy.year_start_date, fy.year_end_date


@frappe.whitelist()
def get_tax_withholding_categories():
	"""List of Tax Withholding Category names for the fill/fix dropdowns."""
	_require_tds_fixables()
	return frappe.get_all(
		"Tax Withholding Category",
		fields=["name"],
		order_by="name",
		limit=500,
	)


@frappe.whitelist()
def get_suppliers_missing_tds_category():
	"""Enabled suppliers with no tax_withholding_category set."""
	_require_tds_fixables()
	suppliers = frappe.db.sql("""
		SELECT
			s.name AS supplier,
			s.supplier_name,
			s.supplier_group,
			s.pan
		FROM `tabSupplier` s
		WHERE
			s.disabled = 0
			AND (s.tax_withholding_category IS NULL OR s.tax_withholding_category = '')
		ORDER BY s.supplier_name
		LIMIT 1000
	""", as_dict=True)
	return {"count": len(suppliers), "suppliers": suppliers}


@frappe.whitelist()
def get_all_suppliers_with_tds_category():
	"""All enabled suppliers with their current TDS Category (blank if unset)."""
	_require_tds_fixables()
	suppliers = frappe.db.sql("""
		SELECT
			s.name AS supplier,
			s.supplier_name,
			s.supplier_group,
			s.tax_withholding_category,
			s.pan
		FROM `tabSupplier` s
		WHERE s.disabled = 0
		ORDER BY s.supplier_name
		LIMIT 2000
	""", as_dict=True)
	return {"count": len(suppliers), "suppliers": suppliers}


@frappe.whitelist()
def set_supplier_tds_category(supplier, tax_withholding_category):
	"""Set the tax_withholding_category on one supplier."""
	_require_tds_fixables()
	if not tax_withholding_category:
		frappe.throw(_("Tax Withholding Category is required"))
	if not frappe.db.exists("Tax Withholding Category", tax_withholding_category):
		frappe.throw(_("Tax Withholding Category {0} does not exist").format(tax_withholding_category))

	supplier_doc = frappe.get_doc("Supplier", supplier)
	supplier_doc.tax_withholding_category = tax_withholding_category
	supplier_doc.save(ignore_permissions=True)

	return {
		"success": True,
		"message": _("TDS Category set for {0}").format(supplier),
	}


@frappe.whitelist()
def get_pis_with_wrong_tds_category(company=None):
	"""Submitted Purchase Invoices in the CURRENT fiscal year whose
	tax_withholding_category disagrees with the supplier's configured
	category (covers both blank-on-PI and genuinely-different)."""
	_require_tds_fixables()
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")

	fy_start, fy_end = _current_fiscal_year(company)

	rows = frappe.db.sql("""
		SELECT
			pi.name AS purchase_invoice,
			pi.posting_date,
			pi.supplier,
			pi.supplier_name,
			pi.apply_tds,
			pi.tax_withholding_category AS pi_category,
			s.tax_withholding_category AS supplier_category
		FROM `tabPurchase Invoice` pi
		INNER JOIN `tabSupplier` s ON s.name = pi.supplier
		WHERE
			pi.docstatus = 1
			AND pi.company = %(company)s
			AND pi.posting_date >= %(fy_start)s
			AND pi.posting_date <= %(fy_end)s
			AND s.tax_withholding_category IS NOT NULL
			AND s.tax_withholding_category != ''
			AND COALESCE(pi.tax_withholding_category, '') != s.tax_withholding_category
		ORDER BY pi.posting_date DESC, pi.name
		LIMIT 2000
	""", {"company": company, "fy_start": fy_start, "fy_end": fy_end}, as_dict=True)

	return {
		"count": len(rows),
		"items": rows,
		"company": company,
		"fiscal_year_start": str(fy_start),
		"fiscal_year_end": str(fy_end),
	}


@frappe.whitelist()
def bulk_fix_pi_tds_category(items):
	"""Enqueue a background job that corrects the tax_withholding_category
	header field on submitted Purchase Invoices to match the supplier's
	configured category. This is a metadata correction only -- it does NOT
	recompute TDS amounts or touch GL (use the per-PI TDS backfill tool for
	that). Current-fiscal-year PIs only; System Manager only."""
	_require_tds_fixables()
	import json
	if isinstance(items, str):
		items = json.loads(items)

	validation_errors = []
	pi_updates = {}
	for item in items:
		pi_name = item.get("purchase_invoice")
		correct_category = item.get("correct_category")
		if not pi_name or not correct_category:
			validation_errors.append({
				"purchase_invoice": pi_name,
				"error": _("Missing purchase_invoice or correct_category"),
			})
			continue
		pi_updates[pi_name] = correct_category

	if not pi_updates:
		return {"status": "error", "validation_errors": validation_errors, "total_invoices": 0}

	frappe.enqueue(
		_process_pi_tds_category_fix,
		queue="long",
		timeout=1500,
		pi_updates=pi_updates,
		company=frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company"),
		user=frappe.session.user,
	)

	return {
		"status": "queued",
		"total_invoices": len(pi_updates),
		"validation_errors": validation_errors,
	}


def _process_pi_tds_category_fix(pi_updates, company, user):
	"""Background worker: db_set tax_withholding_category on each PI header
	(current-FY guarded), committing per batch and emitting realtime progress."""
	total = len(pi_updates)
	done = 0
	success_count = 0
	errors = []

	# Re-derive the FY window in the worker so a stale client can't push
	# out-of-year invoices through.
	pi_list = list(pi_updates.items())

	for idx, (pi_name, correct_category) in enumerate(pi_list, 1):
		try:
			pi = frappe.db.get_value(
				"Purchase Invoice", pi_name,
				["docstatus", "company", "posting_date"], as_dict=True,
			)
			if not pi:
				errors.append({"purchase_invoice": pi_name, "error": _("Not found")})
			elif pi.docstatus != 1:
				errors.append({"purchase_invoice": pi_name, "error": _("Not submitted")})
			else:
				fy_start, fy_end = _current_fiscal_year(pi.company or company)
				if not (str(fy_start) <= str(pi.posting_date) <= str(fy_end)):
					errors.append({"purchase_invoice": pi_name, "error": _("Outside current fiscal year")})
				elif not frappe.db.exists("Tax Withholding Category", correct_category):
					errors.append({"purchase_invoice": pi_name, "error": _("Category {0} missing").format(correct_category)})
				else:
					frappe.db.set_value(
						"Purchase Invoice", pi_name,
						"tax_withholding_category", correct_category,
						update_modified=True,
					)
					success_count += 1
		except Exception as e:
			errors.append({"purchase_invoice": pi_name, "error": cstr(e)})

		done += 1
		if idx % PI_FIX_BATCH_SIZE == 0:
			frappe.db.commit()

		frappe.publish_realtime(
			"bns_tds_fix_progress",
			{"done": done, "total": total, "current_pi": pi_name, "success_count": success_count, "error_count": len(errors)},
			user=user,
		)

	frappe.db.commit()
	frappe.publish_realtime(
		"bns_tds_fix_complete",
		{"success_count": success_count, "error_count": len(errors), "errors": errors[:50]},
		user=user,
	)


@frappe.whitelist()
def get_dashboard_summary(company=None):
	"""
	Get overall dashboard summary statistics.

	Args:
		company: Optional company filter

	Returns:
		dict with various counts
	"""
	_require_dashboard_read()
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
	
	# Count of PI items with wrong expense account (fixable, excludes fixed assets).
	# Scoped to the current fiscal year to match the actionable list.
	fy_start, fy_end = _current_fiscal_year(company)
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
			AND pi.posting_date >= %(fy_start)s
			AND pi.posting_date <= %(fy_end)s
			AND i.is_stock_item = 0
			AND i.is_fixed_asset = 0
			AND id.expense_account IS NOT NULL
			AND id.expense_account != ''
			AND pii.expense_account != id.expense_account
	""", {"company": company, "fy_start": fy_start, "fy_end": fy_end})[0][0] or 0
	
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
	_require_dashboard_read()
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
	_require_dashboard_write("Party Link")
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
	_require_dashboard_read()
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
	_require_dashboard_read()
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
	_require_dashboard_read()
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
	_require_dashboard_write("Address")
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
	_require_dashboard_read()
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
	_require_dashboard_read()
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


# -------------------------------------------------------------------
# Common Party Square-Off (Linked Customer/Supplier GL reconciliation)
# -------------------------------------------------------------------


def _require_accounts_manager():
	"""Common Party Square-Off + Payment Reconciliation gate.

	No hardcoded role lists — checks permission on the three doctypes the
	square-off / reconcile pipeline actually mutates:
	  - Journal Entry (create the contra JV)
	  - Payment Entry (Payment Reconciliation may rewrite PE references)
	  - BNS Settings  (outer dashboard gate, editable via Role Permission Manager)
	Admins grant these permissions via the Role Permission Manager; any role
	that has Journal Entry create + Payment Entry write + BNS Settings write
	can run the tool.
	"""
	if not frappe.has_permission("BNS Settings", "write"):
		frappe.throw(
			_("BNS Settings write permission is required to run Common Party square-off."),
			frappe.PermissionError,
		)
	if not frappe.has_permission("Journal Entry", "create"):
		frappe.throw(
			_("Journal Entry create permission is required."),
			frappe.PermissionError,
		)
	if not frappe.has_permission("Payment Entry", "write"):
		frappe.throw(
			_("Payment Entry write permission is required (Payment Reconciliation rewrites PE references)."),
			frappe.PermissionError,
		)


SQUAREOFF_SYNC_BATCH_CAP = 20  # larger batches run in the background job queue


def _filter_pairs_by_keys(pairs, pair_keys):
	if not pair_keys:
		return pairs
	if isinstance(pair_keys, str):
		pair_keys = frappe.parse_json(pair_keys) or []
	wanted = set(pair_keys)
	return [p for p in pairs if p.get("pair_key") in wanted]


def _run_squareoff_batch(company, pairs, posting_date, cost_center, remark=None):
	from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
		square_off_all_common_parties,
	)

	return square_off_all_common_parties(
		company,
		pairs=pairs,
		posting_date=posting_date,
		cost_center=cost_center,
		remark=remark,
	)


def _run_squareoff_or_enqueue(company, pairs, posting_date, cost_center, remark=None):
	"""Run synchronously for small batches; enqueue as a background job for large ones.
	Prevents a single request from locking GL for hundreds of JVs."""
	if len(pairs) <= SQUAREOFF_SYNC_BATCH_CAP:
		return _run_squareoff_batch(company, pairs, posting_date, cost_center, remark=remark)
	job = frappe.enqueue(
		"business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard._run_squareoff_batch",
		queue="long",
		timeout=3600,
		company=company,
		pairs=pairs,
		posting_date=posting_date,
		cost_center=cost_center,
		remark=remark,
		job_name=f"bns_squareoff_{frappe.generate_hash(length=8)}",
	)
	return {
		"enqueued": True,
		"job_id": getattr(job, "id", None),
		"pairs_count": len(pairs),
		"posted": [],
		"errors": [],
		"message": _(
			"{0} pairs queued in the background (batch exceeds {1}). Check Error Log / Background Jobs for progress."
		).format(len(pairs), SQUAREOFF_SYNC_BATCH_CAP),
	}


@frappe.whitelist()
def preview_common_party_squareoff(company, as_of_date=None):
	"""Return the list of linked pairs that currently have crossed balances."""
	_require_accounts_manager()
	from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
		compute_linked_party_net_positions,
	)

	pairs = compute_linked_party_net_positions(company, as_of_date=as_of_date)
	return {"pairs": pairs, "count": len(pairs), "as_of_date": as_of_date}


@frappe.whitelist()
def execute_common_party_squareoff(
	company, as_of_date=None, pair_keys=None, posting_date=None, cost_center=None
):
	"""Post contra JVs for the requested linked pairs (or all crossed pairs)."""
	_require_accounts_manager()
	from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
		compute_linked_party_net_positions,
	)

	pairs = compute_linked_party_net_positions(company, as_of_date=as_of_date)
	pairs = _filter_pairs_by_keys(pairs, pair_keys)
	return _run_squareoff_or_enqueue(
		company, pairs, posting_date=posting_date, cost_center=cost_center
	)


@frappe.whitelist()
def preview_historical_backfill(company, cutoff_date):
	"""Preview pairs that would be squared off as of a historical cutoff date."""
	_require_accounts_manager()
	if not cutoff_date:
		frappe.throw(_("Cutoff date is required for historical backfill"))
	from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
		compute_linked_party_net_positions,
	)

	pairs = compute_linked_party_net_positions(company, as_of_date=cutoff_date)
	return {"pairs": pairs, "count": len(pairs), "cutoff_date": cutoff_date}


@frappe.whitelist()
def execute_historical_backfill(company, cutoff_date, pair_keys=None, cost_center=None):
	"""One-time backfill: post contra JVs dated cutoff_date for crossed pairs."""
	_require_accounts_manager()
	if not cutoff_date:
		frappe.throw(_("Cutoff date is required for historical backfill"))
	from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
		compute_linked_party_net_positions,
	)

	pairs = compute_linked_party_net_positions(company, as_of_date=cutoff_date)
	pairs = _filter_pairs_by_keys(pairs, pair_keys)
	return _run_squareoff_or_enqueue(
		company,
		pairs,
		posting_date=cutoff_date,
		cost_center=cost_center,
		remark=f"BNS Common Party historical backfill as of {cutoff_date}",
	)


# -------------------------------------------------------------------
# Payment Reconciliation (FIFO, all customers + all suppliers)
# -------------------------------------------------------------------


def _get_reconcile_settings():
	"""Read the BNS Settings knobs that govern Payment Reconciliation runs."""
	s = frappe.get_single("BNS Settings")
	return {
		"window": getattr(s, "common_party_reconcile_window", None) or "All time",
		"scope": getattr(s, "common_party_reconcile_scope", None) or "All Customers + All Suppliers",
		"include_advances": bool(getattr(s, "common_party_reconcile_include_advances", 1)),
		"last_run_on": getattr(s, "common_party_reconcile_last_run_on", None),
	}


@frappe.whitelist()
def preview_payment_reconciliation(company):
	"""Return the list of parties with unreconciled activity (non-zero signed
	balance on their party account). Cheap, read-only — used by the dashboard
	'Preview Unreconciled Parties' button."""
	_require_accounts_manager()
	from business_needed_solutions.bns_branch_accounting.common_party_reconciliation import (
		get_reconciliation_candidates,
	)

	cfg = _get_reconcile_settings()
	candidates = get_reconciliation_candidates(company, scope=cfg["scope"], limit=5000)
	totals = {
		"reconcilable_amount": sum(c.get("reconcilable_amount", 0) for c in candidates),
		"open_invoice_outstanding": sum(c.get("open_invoice_outstanding", 0) for c in candidates),
		"open_payment_unallocated": sum(c.get("open_payment_unallocated", 0) for c in candidates),
		"residual_invoice_side": sum(c.get("residual_invoice_side", 0) for c in candidates),
		"residual_payment_side": sum(c.get("residual_payment_side", 0) for c in candidates),
		"open_invoice_count": sum(c.get("open_invoice_count", 0) for c in candidates),
		"open_payment_count": sum(c.get("open_payment_count", 0) for c in candidates),
	}
	return {
		"candidates": candidates,
		"count": len(candidates),
		"totals": totals,
		"window": cfg["window"],
		"scope": cfg["scope"],
		"include_advances": cfg["include_advances"],
		"last_run_on": str(cfg["last_run_on"]) if cfg["last_run_on"] else None,
	}


def _parse_party_keys(party_keys):
	"""Parse a list of 'PartyType|Party' strings into a set of tuples.
	Accepts either a JSON string or a list. Returns None if empty."""
	if not party_keys:
		return None
	if isinstance(party_keys, str):
		try:
			party_keys = frappe.parse_json(party_keys) or []
		except Exception:
			return None
	out = set()
	for raw in party_keys:
		if not raw:
			continue
		if "|" not in raw:
			continue
		pt, p = raw.split("|", 1)
		pt = pt.strip()
		p = p.strip()
		if pt and p:
			out.add((pt, p))
	return out or None


@frappe.whitelist()
def execute_payment_reconciliation(
	company, force_window=None, force_scope=None, party_keys=None
):
	"""Run ERPNext Payment Reconciliation (FIFO) for the selected parties, or
	for every party in scope if `party_keys` is not provided.
	Runs synchronously for small batches; enqueues for larger ones."""
	_require_accounts_manager()
	from business_needed_solutions.bns_branch_accounting.common_party_reconciliation import (
		get_reconciliation_candidates,
		reconcile_all_parties,
		stamp_reconcile_last_run,
	)

	cfg = _get_reconcile_settings()
	window = force_window or cfg["window"]
	scope = force_scope or cfg["scope"]
	party_filter = _parse_party_keys(party_keys)

	if party_filter is not None:
		batch_size = len(party_filter)
	else:
		candidates = get_reconciliation_candidates(company, scope=scope, limit=5000)
		batch_size = len(candidates)

	if batch_size <= SQUAREOFF_SYNC_BATCH_CAP:
		result = reconcile_all_parties(
			company=company,
			window=window,
			include_advances=cfg["include_advances"],
			scope=scope,
			party_filter=party_filter,
		)
		stamp_reconcile_last_run()
		return result

	job = frappe.enqueue(
		"business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard._run_reconcile_batch",
		queue="long",
		timeout=7200,
		company=company,
		window=window,
		include_advances=cfg["include_advances"],
		scope=scope,
		party_filter=list(party_filter) if party_filter else None,
		job_name=f"bns_reconcile_{frappe.generate_hash(length=8)}",
	)
	return {
		"enqueued": True,
		"job_id": getattr(job, "id", None),
		"candidates_count": batch_size,
		"reconciled_parties": [],
		"errors": [],
		"message": _(
			"{0} parties queued for background Payment Reconciliation. Check Error Log / Background Jobs for progress."
		).format(batch_size),
	}


def _run_reconcile_batch(company, window, include_advances, scope, party_filter=None):
	"""RQ job entry point for the enqueued reconciliation path."""
	from business_needed_solutions.bns_branch_accounting.common_party_reconciliation import (
		reconcile_all_parties,
		stamp_reconcile_last_run,
	)

	result = reconcile_all_parties(
		company=company,
		window=window,
		include_advances=include_advances,
		scope=scope,
		party_filter=party_filter,
	)
	stamp_reconcile_last_run()
	return result


@frappe.whitelist()
def execute_full_squareoff_pipeline(company, as_of_date=None, cost_center=None):
	"""One-button upgrade: pre-reconcile \u2192 post contra JVs \u2192 post-reconcile.
	All three steps run for the chosen company under the current BNS Settings."""
	_require_accounts_manager()
	from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
		compute_linked_party_net_positions,
	)
	from business_needed_solutions.bns_branch_accounting.common_party_reconciliation import (
		reconcile_all_parties,
		stamp_reconcile_last_run,
	)

	cfg = _get_reconcile_settings()
	summary = {
		"company": company,
		"window": cfg["window"],
		"scope": cfg["scope"],
	}

	# Pre-reconcile
	pre = reconcile_all_parties(
		company=company,
		window=cfg["window"],
		include_advances=cfg["include_advances"],
		scope=cfg["scope"],
	)
	summary["pre_reconcile"] = {
		"reconciled_parties": len(pre.get("reconciled_parties", [])),
		"total_allocations": pre.get("total_allocations", 0),
		"errors": len(pre.get("errors", [])),
	}

	# Square-off crossed pairs
	pairs = compute_linked_party_net_positions(company, as_of_date=as_of_date)
	if pairs:
		sq = _run_squareoff_or_enqueue(
			company,
			pairs,
			posting_date=as_of_date,
			cost_center=cost_center,
			remark="BNS full pipeline square-off",
		)
	else:
		sq = {"posted": [], "errors": [], "skipped": [], "message": "no crossed pairs"}
	summary["squareoff"] = {
		"posted": len(sq.get("posted", [])),
		"errors": len(sq.get("errors", [])),
		"skipped": len(sq.get("skipped", [])),
	}

	# Post-reconcile
	post = reconcile_all_parties(
		company=company,
		window=cfg["window"],
		include_advances=cfg["include_advances"],
		scope=cfg["scope"],
	)
	summary["post_reconcile"] = {
		"reconciled_parties": len(post.get("reconciled_parties", [])),
		"total_allocations": post.get("total_allocations", 0),
		"errors": len(post.get("errors", [])),
	}

	stamp_reconcile_last_run()
	return summary


# -------------------------------------------------------------------
# SRBNB Reconciliation (Stock Received But Not Billed)
# -------------------------------------------------------------------


@frappe.whitelist()
def get_srbnb_reconciliation(company=None):
	"""Return the 4-bucket SRBNB reconciliation breakdown for the dashboard."""
	_require_dashboard_read()
	from business_needed_solutions.bns_branch_accounting.srbnb_reconciliation import (
		get_srbnb_reconciliation as _get_srbnb,
	)

	company = company or _default_company()
	return _get_srbnb(company)


@frappe.whitelist()
def clear_internal_srbnb(company, pr_names, posting_date=None):
	"""Post a JE that clears SRBNB for selected BNS internal Purchase Receipts.
	Dr SRBNB / Cr Clearing Account (configurable in BNS Settings, default COGS)."""
	_require_dashboard_write("Journal Entry")
	from business_needed_solutions.bns_branch_accounting.srbnb_reconciliation import (
		build_internal_srbnb_clearing_je,
	)

	if isinstance(pr_names, str):
		pr_names = frappe.parse_json(pr_names) or []
	if not pr_names:
		frappe.throw(_("Select at least one internal Purchase Receipt"))
	company = company or _default_company()
	return build_internal_srbnb_clearing_je(
		company=company,
		pr_names=pr_names,
		posting_date=posting_date,
		submit=False,  # Never auto-submit — user reviews and posts manually
	)
