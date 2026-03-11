# Copyright (c) 2026, Business Needed Solutions and Contributors
# License: Commercial

"""
Internal Transfer Accounting Audit Report

Validates GL Entry and Stock Ledger Entry correctness for BNS internal
Delivery Notes, Sales Invoices, Purchase Receipts, and Purchase Invoices.

For each submitted BNS internal document, the report compares the actual
GL/SLE rows against the expected BNS branch-accounting pattern defined
in bns_branch_accounting/utils.py and flags any deviations.
"""

import json
import frappe
from frappe import _
from frappe.utils import flt, getdate, cint


def execute(filters=None):
	"""
	Entry point for the Script Report.

	Args:
		filters: dict with optional keys company, from_date, to_date, document_type.

	Returns:
		tuple: (columns, data)
	"""
	filters = frappe._dict(filters or {})
	filters = _apply_cutoff_filters(filters)

	columns = _get_columns()
	data = _get_data(filters)

	return columns, data


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def _get_columns():
	"""Define report columns."""
	return [
		{"fieldname": "posting_date", "label": _("Posting Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "document_name",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "document_type",
			"width": 160,
		},
		{"fieldname": "internal_scope", "label": _("Internal Scope"), "fieldtype": "Data", "width": 140},
		{"fieldname": "deviation_type", "label": _("Deviation Type"), "fieldtype": "Data", "width": 120},
		{"fieldname": "expected_accounts", "label": _("Expected Accounts"), "fieldtype": "Small Text", "width": 250},
		{"fieldname": "unexpected_accounts", "label": _("Unexpected Accounts"), "fieldtype": "Small Text", "width": 250},
		{"fieldname": "missing_accounts", "label": _("Missing Accounts"), "fieldtype": "Small Text", "width": 250},
		{"fieldname": "sle_issue", "label": _("SLE Issue"), "fieldtype": "Small Text", "width": 250},
		{"fieldname": "details", "label": _("Details"), "fieldtype": "Small Text", "width": 300},
	]


# ---------------------------------------------------------------------------
# Cutoff helpers
# ---------------------------------------------------------------------------

def _get_internal_validation_cutoff_date():
	"""Read global posting-date cutoff from BNS Branch Accounting Settings."""
	cutoff = frappe.db.get_single_value(
		"BNS Branch Accounting Settings", "internal_validation_cutoff_date"
	)
	if not cutoff:
		return None
	try:
		return getdate(cutoff)
	except Exception:
		return None


def _apply_cutoff_filters(filters):
	"""Apply cutoff as default from_date when user has not provided one."""
	if filters.get("from_date"):
		return filters
	cutoff = _get_internal_validation_cutoff_date()
	if cutoff:
		filters["from_date"] = cutoff
	return filters


# ---------------------------------------------------------------------------
# BNS account settings
# ---------------------------------------------------------------------------

def _get_bns_accounts():
	"""
	Fetch BNS Branch Accounting account names.

	Returns:
		dict with account names, or empty dict if required settings are missing.
	"""
	legacy = (
		frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_transfer_account") or ""
	).strip()

	settings = {
		"stock_in_transit": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "stock_in_transit_account") or ""
		).strip(),
		"internal_sales_transfer": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_sales_transfer_account")
			or legacy
		).strip(),
		"internal_purchase_transfer": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_purchase_transfer_account")
			or legacy
		).strip(),
		"internal_branch_debtor": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_branch_debtor_account") or ""
		).strip(),
		"internal_branch_creditor": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_branch_creditor_account") or ""
		).strip(),
	}

	required = ("stock_in_transit", "internal_branch_debtor", "internal_branch_creditor")
	if any(not settings.get(f) for f in required):
		return {}

	return settings


# ---------------------------------------------------------------------------
# Scope detection (mirrors logic from bns_branch_accounting/utils.py)
# ---------------------------------------------------------------------------

def _classify_dn(doc):
	"""
	Classify a Delivery Note into its BNS internal scope.

	Returns:
		str or None: 'same_gstin' | 'different_gstin' | None
	"""
	if not cint(doc.get("is_bns_internal_customer")):
		customer = doc.get("customer")
		if not customer:
			return None
		if not frappe.db.get_value("Customer", customer, "is_bns_internal_customer"):
			return None

	company_gstin = (doc.get("company_gstin") or "").strip()
	billing_gstin = (doc.get("billing_address_gstin") or "").strip()
	if company_gstin and billing_gstin and company_gstin == billing_gstin:
		return "same_gstin"
	return "different_gstin"


def _classify_si(doc):
	"""
	Classify a Sales Invoice.

	Returns:
		str or None: 'different_gstin' | 'different_gstin_return' | None
	"""
	if not cint(doc.get("is_bns_internal_customer")):
		customer = doc.get("customer")
		if not customer:
			return None
		if not frappe.db.get_value("Customer", customer, "is_bns_internal_customer"):
			return None

	company_gstin = (doc.get("company_gstin") or "").strip()
	billing_gstin = (doc.get("billing_address_gstin") or "").strip()
	if company_gstin and billing_gstin and company_gstin != billing_gstin:
		if cint(doc.get("is_return")):
			return "different_gstin_return"
		return "different_gstin"
	return None


def _classify_pr(doc):
	"""
	Classify a Purchase Receipt.

	Returns:
		str or None: 'dn_same_gstin' | 'si_linked' | None
	"""
	is_internal = cint(doc.get("is_bns_internal_supplier"))
	if not is_internal:
		supplier = doc.get("supplier")
		if not supplier:
			return None
		if not frappe.db.get_value("Supplier", supplier, "is_bns_internal_supplier"):
			return None

	source_ref = (doc.get("bns_inter_company_reference") or "").strip()

	if source_ref and frappe.db.exists("Delivery Note", source_ref):
		dn_data = frappe.db.get_value(
			"Delivery Note", source_ref,
			["company_gstin", "billing_address_gstin"], as_dict=True
		)
		if dn_data:
			dn_co = (dn_data.get("company_gstin") or "").strip()
			dn_bill = (dn_data.get("billing_address_gstin") or "").strip()
			if dn_co and dn_bill and dn_co == dn_bill:
				return "dn_same_gstin"

	if source_ref and frappe.db.exists("Sales Invoice", source_ref):
		return "si_linked"

	return None


def _classify_pi(doc):
	"""
	Classify a Purchase Invoice.

	Returns:
		str or None: 'si_linked' | 'si_linked_return' | None
	"""
	is_internal = cint(doc.get("is_bns_internal_supplier"))
	if not is_internal:
		supplier = doc.get("supplier")
		if not supplier:
			return None
		if not frappe.db.get_value("Supplier", supplier, "is_bns_internal_supplier"):
			return None

	is_linked = False

	si_ref = (doc.get("bns_inter_company_reference") or "").strip()
	if si_ref and frappe.db.exists("Sales Invoice", si_ref):
		is_linked = True

	if not is_linked:
		bill_no = (doc.get("bill_no") or "").strip()
		if bill_no and frappe.db.exists("Sales Invoice", {"name": bill_no, "docstatus": 1}):
			is_linked = True

	if not is_linked:
		pr_names = list({
			(row.get("purchase_receipt") or "").strip()
			for row in (doc.get("items") or [])
			if (row.get("purchase_receipt") or "").strip()
		})
		if pr_names:
			for pr_name in pr_names:
				pr_ref = frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference")
				if pr_ref and frappe.db.exists("Sales Invoice", (pr_ref or "").strip()):
					is_linked = True
					break

	if is_linked:
		if cint(doc.get("is_return")):
			return "si_linked_return"
		return "si_linked"

	return None


# ---------------------------------------------------------------------------
# Expected GL pattern builders
# ---------------------------------------------------------------------------

def _expected_gl_for_dn(scope, settings, doc):
	"""
	Return set of (account, side) tuples for expected BNS GL pattern.

	Args:
		scope: 'same_gstin' or 'different_gstin'
		settings: BNS account dict
		doc: DN doc dict (for stock account resolution)

	Returns:
		set of (account, 'debit'|'credit') tuples
	"""
	stock_account = _resolve_stock_account_for_doc(doc)

	if scope == "same_gstin":
		return {
			(settings["internal_branch_debtor"], "debit"),
			(settings["stock_in_transit"], "debit"),
			(settings["internal_sales_transfer"], "credit"),
			(stock_account, "credit") if stock_account else ("Stock In Hand", "credit"),
		}
	else:
		return {
			(settings["stock_in_transit"], "debit"),
			(stock_account, "credit") if stock_account else ("Stock In Hand", "credit"),
		}


def _expected_gl_for_si(scope, settings, doc):
	"""Return set of (account, side) tuples for expected BNS GL pattern on SI."""
	expected = {
		(settings["internal_branch_debtor"], "debit"),
		(settings["internal_sales_transfer"], "credit"),
	}
	for tax in (doc.get("taxes") or []):
		account = (tax.get("account_head") or "").strip()
		base_amount = flt(
			tax.get("base_tax_amount_after_discount_amount")
			or tax.get("base_tax_amount") or 0
		)
		if account and abs(base_amount) > 0.000001:
			side = "credit" if base_amount > 0 else "debit"
			expected.add((account, side))

	if cint(doc.get("update_stock")):
		stock_account = _resolve_stock_account_for_doc(doc)
		if stock_account:
			expected.add((settings["stock_in_transit"], "debit"))
			expected.add((stock_account, "credit"))
	return expected


def _expected_gl_for_pr(scope, settings, doc):
	"""Return set of (account, side) tuples for expected BNS GL pattern on PR."""
	stock_account = _resolve_stock_account_for_doc(doc)

	if scope == "dn_same_gstin":
		return {
			(settings["internal_purchase_transfer"], "debit"),
			(stock_account, "debit") if stock_account else ("Stock In Hand", "debit"),
			(settings["internal_branch_creditor"], "credit"),
			(settings["stock_in_transit"], "credit"),
		}
	else:
		return {
			(stock_account, "debit") if stock_account else ("Stock In Hand", "debit"),
			(settings["stock_in_transit"], "credit"),
		}


def _expected_gl_for_pi(scope, settings, doc):
	"""Return set of (account, side) tuples for expected BNS GL pattern on PI."""
	expected = {
		(settings["internal_branch_creditor"], "credit"),
		(settings["internal_purchase_transfer"], "debit"),
	}

	for tax in (doc.get("taxes") or []):
		account = (tax.get("account_head") or "").strip()
		base_amount = flt(
			tax.get("base_tax_amount_after_discount_amount")
			or tax.get("base_tax_amount") or 0
		)
		if account and abs(base_amount) > 0.000001:
			side = "debit" if base_amount > 0 else "credit"
			expected.add((account, side))

	has_pr_linked = any(
		(row.get("purchase_receipt") or "").strip()
		for row in (doc.get("items") or [])
	)
	if cint(doc.get("update_stock")) and not has_pr_linked:
		stock_account = _resolve_stock_account_for_doc(doc)
		if stock_account:
			expected.add((stock_account, "debit"))
			expected.add((settings["stock_in_transit"], "credit"))
	return expected


def _expected_gl_for_si_return(scope, settings, doc):
	"""Return set of (account, side) tuples for expected BNS GL on SI credit note (reversed)."""
	expected = {
		(settings["internal_branch_debtor"], "credit"),
		(settings["internal_sales_transfer"], "debit"),
	}
	for tax in (doc.get("taxes") or []):
		account = (tax.get("account_head") or "").strip()
		base_amount = flt(
			tax.get("base_tax_amount_after_discount_amount")
			or tax.get("base_tax_amount") or 0
		)
		if account and abs(base_amount) > 0.000001:
			side = "debit" if base_amount < 0 else "credit"
			expected.add((account, side))

	if cint(doc.get("update_stock")):
		stock_account = _resolve_stock_account_for_doc(doc)
		if stock_account:
			expected.add((settings["stock_in_transit"], "credit"))
			expected.add((stock_account, "debit"))
	return expected


def _expected_gl_for_pi_return(scope, settings, doc):
	"""Return set of (account, side) tuples for expected BNS GL on PI debit note (reversed)."""
	expected = {
		(settings["internal_branch_creditor"], "debit"),
		(settings["internal_purchase_transfer"], "credit"),
	}

	for tax in (doc.get("taxes") or []):
		account = (tax.get("account_head") or "").strip()
		base_amount = flt(
			tax.get("base_tax_amount_after_discount_amount")
			or tax.get("base_tax_amount") or 0
		)
		if account and abs(base_amount) > 0.000001:
			side = "credit" if base_amount < 0 else "debit"
			expected.add((account, side))

	has_pr_linked = any(
		(row.get("purchase_receipt") or "").strip()
		for row in (doc.get("items") or [])
	)
	if cint(doc.get("update_stock")) and not has_pr_linked:
		stock_account = _resolve_stock_account_for_doc(doc)
		if stock_account:
			expected.add((stock_account, "credit"))
			expected.add((settings["stock_in_transit"], "debit"))
	return expected


def _resolve_stock_account_for_doc(doc):
	"""
	Resolve the stock-in-hand account for a document via warehouse account map.

	Returns:
		str or None
	"""
	company = doc.get("company")
	if not company:
		return None
	try:
		from erpnext.stock import get_warehouse_account_map
		wh_map = get_warehouse_account_map(company)
	except Exception:
		return None

	items = doc.get("items") or []
	for item in items:
		wh = (item.get("warehouse") or item.get("target_warehouse") or "").strip()
		if wh and wh_map.get(wh):
			return wh_map[wh].get("account")
	return None


# ---------------------------------------------------------------------------
# GL comparison
# ---------------------------------------------------------------------------

def _fetch_gl_entries(voucher_type, voucher_no):
	"""
	Fetch actual GL Entry rows for a given voucher.

	Returns:
		list of dicts with account, debit, credit, is_cancelled
	"""
	return frappe.db.sql(
		"""
		SELECT account, debit, credit, is_cancelled
		FROM `tabGL Entry`
		WHERE voucher_type = %s AND voucher_no = %s AND is_cancelled = 0
		""",
		(voucher_type, voucher_no),
		as_dict=True,
	) or []


def _actual_gl_account_sides(gl_entries):
	"""
	Derive set of (account, side) tuples from actual GL entries.

	Returns:
		set of (account, 'debit'|'credit') tuples
	"""
	sides = set()
	for row in gl_entries:
		acc = (row.get("account") or "").strip()
		if not acc:
			continue
		if flt(row.get("debit") or 0) > 0:
			sides.add((acc, "debit"))
		if flt(row.get("credit") or 0) > 0:
			sides.add((acc, "credit"))
	return sides


def _get_round_off_account(company):
	"""Resolve the company round-off account (used by ERPNext for GL residuals)."""
	if not company:
		return None
	return frappe.get_cached_value("Company", company, "round_off_account")


def _compare_gl(expected_set, actual_set, company=None):
	"""
	Compare expected vs actual GL account-side sets.

	Ignores ERPNext round-off account entries (standard precision handling).

	Returns:
		tuple: (missing set, unexpected set)
	"""
	round_off_account = _get_round_off_account(company) if company else None
	expected_accounts = {acc for acc, _ in expected_set}

	missing = expected_set - actual_set
	unexpected = set()
	for acc, side in actual_set:
		if acc not in expected_accounts:
			if round_off_account and acc == round_off_account:
				continue
			unexpected.add((acc, side))
	return missing, unexpected


# ---------------------------------------------------------------------------
# SLE validation
# ---------------------------------------------------------------------------

def _check_sle_for_pr(doc):
	"""
	Validate SLE incoming_rate against bns_transfer_rate for PR items.

	Returns:
		list of issue description strings
	"""
	pr_meta = frappe.get_meta("Purchase Receipt Item")
	if not pr_meta.has_field("bns_transfer_rate"):
		return []

	items = doc.get("items") or []
	transfer_rates = {}
	for row in items:
		rate = flt(row.get("bns_transfer_rate") or 0)
		if rate > 0:
			transfer_rates[row.name] = rate

	if not transfer_rates:
		return []

	sle_rows = frappe.db.sql(
		"""
		SELECT name, voucher_detail_no, actual_qty, incoming_rate, stock_value_difference
		FROM `tabStock Ledger Entry`
		WHERE voucher_type = 'Purchase Receipt' AND voucher_no = %s AND is_cancelled = 0
		""",
		(doc.name,),
		as_dict=True,
	) or []

	issues = []
	for sle in sle_rows:
		if flt(sle.get("actual_qty") or 0) <= 0:
			continue
		expected_rate = transfer_rates.get(sle.get("voucher_detail_no"))
		if not expected_rate:
			continue
		actual_rate = flt(sle.get("incoming_rate") or 0)
		if abs(actual_rate - expected_rate) > 0.01:
			issues.append(
				f"SLE {sle.name}: incoming_rate={actual_rate}, expected={expected_rate}"
			)
		expected_svd = flt(sle.get("actual_qty") or 0) * expected_rate
		actual_svd = flt(sle.get("stock_value_difference") or 0)
		if abs(actual_svd - expected_svd) > 0.5:
			issues.append(
				f"SLE {sle.name}: stock_value_diff={actual_svd}, expected={expected_svd:.2f}"
			)

	return issues


def _check_sle_for_pi(doc):
	"""
	Validate SLE incoming_rate against bns_transfer_rate for PI items (update_stock flow).

	Returns:
		list of issue description strings
	"""
	if not cint(doc.get("update_stock")):
		return []

	pi_meta = frappe.get_meta("Purchase Invoice Item")
	if not pi_meta.has_field("bns_transfer_rate"):
		return []

	items = doc.get("items") or []
	transfer_rates = {}
	for row in items:
		rate = flt(row.get("bns_transfer_rate") or 0)
		if rate > 0:
			transfer_rates[row.name] = rate

	if not transfer_rates:
		return []

	sle_rows = frappe.db.sql(
		"""
		SELECT name, voucher_detail_no, actual_qty, incoming_rate, stock_value_difference
		FROM `tabStock Ledger Entry`
		WHERE voucher_type = 'Purchase Invoice' AND voucher_no = %s AND is_cancelled = 0
		""",
		(doc.name,),
		as_dict=True,
	) or []

	issues = []
	for sle in sle_rows:
		if flt(sle.get("actual_qty") or 0) <= 0:
			continue
		expected_rate = transfer_rates.get(sle.get("voucher_detail_no"))
		if not expected_rate:
			continue
		actual_rate = flt(sle.get("incoming_rate") or 0)
		if abs(actual_rate - expected_rate) > 0.01:
			issues.append(
				f"SLE {sle.name}: incoming_rate={actual_rate}, expected={expected_rate}"
			)
		expected_svd = flt(sle.get("actual_qty") or 0) * expected_rate
		actual_svd = flt(sle.get("stock_value_difference") or 0)
		if abs(actual_svd - expected_svd) > 0.5:
			issues.append(
				f"SLE {sle.name}: stock_value_diff={actual_svd}, expected={expected_svd:.2f}"
			)

	return issues


# ---------------------------------------------------------------------------
# Scope label
# ---------------------------------------------------------------------------

_SCOPE_LABELS = {
	"same_gstin": "Same GSTIN",
	"different_gstin": "Different GSTIN",
	"different_gstin_return": "Different GSTIN (Credit Note)",
	"dn_same_gstin": "DN-linked (Same GSTIN)",
	"si_linked": "SI-linked (Different GSTIN)",
	"si_linked_return": "SI-linked (Debit Note)",
}


# ---------------------------------------------------------------------------
# Main data builder
# ---------------------------------------------------------------------------

def _get_data(filters):
	"""
	Build report rows by auditing GL and SLE for each BNS internal document.

	Args:
		filters: frappe._dict with company, from_date, to_date, document_type.

	Returns:
		list of dicts (one per document with at least one deviation).
	"""
	settings = _get_bns_accounts()
	if not settings:
		frappe.msgprint(
			_("BNS Branch Accounting Settings are incomplete. Cannot run audit."),
			title=_("Settings Missing"),
		)
		return []

	data = []

	doc_types = _get_doc_types_to_audit(filters)

	if "Delivery Note" in doc_types:
		data.extend(_audit_delivery_notes(filters, settings))
	if "Sales Invoice" in doc_types:
		data.extend(_audit_sales_invoices(filters, settings))
	if "Purchase Receipt" in doc_types:
		data.extend(_audit_purchase_receipts(filters, settings))
	if "Purchase Invoice" in doc_types:
		data.extend(_audit_purchase_invoices(filters, settings))

	data.sort(key=lambda r: r.get("posting_date") or "0000-00-00", reverse=True)
	return data


def _get_doc_types_to_audit(filters):
	"""Return list of doctypes to audit based on filter."""
	dt = (filters.get("document_type") or "").strip()
	if dt:
		return [dt]
	return ["Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"]


def _build_date_conditions(filters, alias="doc"):
	"""Build SQL WHERE fragments for date and company filters."""
	conditions = [f"{alias}.docstatus = 1"]
	values = []
	if filters.get("company"):
		conditions.append(f"{alias}.company = %s")
		values.append(filters.company)
	if filters.get("from_date"):
		conditions.append(f"{alias}.posting_date >= %s")
		values.append(filters.from_date)
	if filters.get("to_date"):
		conditions.append(f"{alias}.posting_date <= %s")
		values.append(filters.to_date)
	return conditions, values


# ---------------------------------------------------------------------------
# Per-doctype audit runners
# ---------------------------------------------------------------------------

def _audit_delivery_notes(filters, settings):
	"""Audit GL entries for BNS internal Delivery Notes."""
	conditions, values = _build_date_conditions(filters, alias="dn")
	conditions.append(
		"(dn.is_bns_internal_customer = 1"
		" OR c.is_bns_internal_customer = 1)"
	)

	sql = f"""
		SELECT dn.name, dn.posting_date, dn.company, dn.customer,
			   dn.is_bns_internal_customer, dn.company_gstin, dn.billing_address_gstin
		FROM `tabDelivery Note` dn
		LEFT JOIN `tabCustomer` c ON dn.customer = c.name
		WHERE {" AND ".join(conditions)}
	"""
	docs = frappe.db.sql(sql, tuple(values), as_dict=True) or []
	results = []

	for row in docs:
		scope = _classify_dn(row)
		if not scope:
			continue

		doc = frappe.get_doc("Delivery Note", row.name)
		expected = _expected_gl_for_dn(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Delivery Note", row.name)

		if not gl_entries:
			results.append(_build_row(
				row, scope, "GL Missing",
				expected_accounts=expected,
				details="No GL entries found for submitted internal DN.",
			))
			continue

		actual = _actual_gl_account_sides(gl_entries)
		missing, unexpected = _compare_gl(expected, actual, company=doc.company)

		if missing or unexpected:
			results.append(_build_row(
				row, scope, "GL Mismatch",
				expected_accounts=expected,
				missing_accounts=missing,
				unexpected_accounts=unexpected,
			))

	return results


def _audit_sales_invoices(filters, settings):
	"""Audit GL entries for BNS internal Sales Invoices (including credit notes)."""
	conditions, values = _build_date_conditions(filters, alias="si")
	conditions.append(
		"(si.is_bns_internal_customer = 1"
		" OR c.is_bns_internal_customer = 1)"
	)

	sql = f"""
		SELECT si.name, si.posting_date, si.company, si.customer,
			   si.is_bns_internal_customer, si.company_gstin, si.billing_address_gstin,
			   si.update_stock, si.is_return
		FROM `tabSales Invoice` si
		LEFT JOIN `tabCustomer` c ON si.customer = c.name
		WHERE {" AND ".join(conditions)}
	"""
	docs = frappe.db.sql(sql, tuple(values), as_dict=True) or []
	results = []

	for row in docs:
		scope = _classify_si(row)
		if not scope:
			continue

		doc = frappe.get_doc("Sales Invoice", row.name)
		if scope == "different_gstin_return":
			expected = _expected_gl_for_si_return(scope, settings, doc)
		else:
			expected = _expected_gl_for_si(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Sales Invoice", row.name)

		if not gl_entries:
			results.append(_build_row(
				row, scope, "GL Missing",
				expected_accounts=expected,
				details="No GL entries found for submitted internal SI.",
			))
			continue

		actual = _actual_gl_account_sides(gl_entries)
		missing, unexpected = _compare_gl(expected, actual, company=doc.company)

		if missing or unexpected:
			results.append(_build_row(
				row, scope, "GL Mismatch",
				expected_accounts=expected,
				missing_accounts=missing,
				unexpected_accounts=unexpected,
			))

	return results


def _audit_purchase_receipts(filters, settings):
	"""Audit GL and SLE for BNS internal Purchase Receipts."""
	conditions, values = _build_date_conditions(filters, alias="pr")
	conditions.append(
		"(pr.is_bns_internal_supplier = 1"
		" OR s.is_bns_internal_supplier = 1)"
	)

	sql = f"""
		SELECT pr.name, pr.posting_date, pr.company, pr.supplier,
			   pr.is_bns_internal_supplier, pr.bns_inter_company_reference
		FROM `tabPurchase Receipt` pr
		LEFT JOIN `tabSupplier` s ON pr.supplier = s.name
		WHERE {" AND ".join(conditions)}
	"""
	docs = frappe.db.sql(sql, tuple(values), as_dict=True) or []
	results = []

	for row in docs:
		scope = _classify_pr(row)
		if not scope:
			continue

		doc = frappe.get_doc("Purchase Receipt", row.name)
		expected = _expected_gl_for_pr(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Purchase Receipt", row.name)

		gl_deviation = None
		sle_deviation = None

		if not gl_entries:
			gl_deviation = "GL Missing"
		else:
			actual = _actual_gl_account_sides(gl_entries)
			missing, unexpected = _compare_gl(expected, actual, company=doc.company)
			if missing or unexpected:
				gl_deviation = "GL Mismatch"

		sle_issues = _check_sle_for_pr(doc)
		if sle_issues:
			sle_deviation = "; ".join(sle_issues)

		if gl_deviation or sle_deviation:
			deviation_type = "Both" if (gl_deviation and sle_deviation) else (gl_deviation or "SLE Mismatch")
			missing_set = set()
			unexpected_set = set()
			details = None
			if gl_deviation == "GL Missing":
				details = "No GL entries found for submitted internal PR."
			elif gl_deviation == "GL Mismatch":
				actual = _actual_gl_account_sides(gl_entries)
				missing_set, unexpected_set = _compare_gl(expected, actual, company=doc.company)

			results.append(_build_row(
				row, scope, deviation_type,
				expected_accounts=expected,
				missing_accounts=missing_set,
				unexpected_accounts=unexpected_set,
				sle_issue=sle_deviation,
				details=details,
			))

	return results


def _audit_purchase_invoices(filters, settings):
	"""Audit GL and SLE for BNS internal Purchase Invoices (including debit notes)."""
	conditions, values = _build_date_conditions(filters, alias="pi")
	conditions.append(
		"(pi.is_bns_internal_supplier = 1"
		" OR s.is_bns_internal_supplier = 1)"
	)

	sql = f"""
		SELECT pi.name, pi.posting_date, pi.company, pi.supplier,
			   pi.is_bns_internal_supplier, pi.bns_inter_company_reference,
			   pi.bill_no, pi.update_stock, pi.is_return
		FROM `tabPurchase Invoice` pi
		LEFT JOIN `tabSupplier` s ON pi.supplier = s.name
		WHERE {" AND ".join(conditions)}
	"""
	docs = frappe.db.sql(sql, tuple(values), as_dict=True) or []
	results = []

	for row in docs:
		scope = _classify_pi(row)
		if not scope:
			continue

		doc = frappe.get_doc("Purchase Invoice", row.name)
		if scope == "si_linked_return":
			expected = _expected_gl_for_pi_return(scope, settings, doc)
		else:
			expected = _expected_gl_for_pi(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Purchase Invoice", row.name)

		gl_deviation = None
		sle_deviation = None

		if not gl_entries:
			gl_deviation = "GL Missing"
		else:
			actual = _actual_gl_account_sides(gl_entries)
			missing, unexpected = _compare_gl(expected, actual, company=doc.company)
			if missing or unexpected:
				gl_deviation = "GL Mismatch"

		sle_issues = _check_sle_for_pi(doc)
		if sle_issues:
			sle_deviation = "; ".join(sle_issues)

		if gl_deviation or sle_deviation:
			deviation_type = "Both" if (gl_deviation and sle_deviation) else (gl_deviation or "SLE Mismatch")
			missing_set = set()
			unexpected_set = set()
			details = None
			if gl_deviation == "GL Missing":
				details = "No GL entries found for submitted internal PI."
			elif gl_deviation == "GL Mismatch":
				actual = _actual_gl_account_sides(gl_entries)
				missing_set, unexpected_set = _compare_gl(expected, actual, company=doc.company)

			results.append(_build_row(
				row, scope, deviation_type,
				expected_accounts=expected,
				missing_accounts=missing_set,
				unexpected_accounts=unexpected_set,
				sle_issue=sle_deviation,
				details=details,
			))

	return results


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

def _format_account_set(account_set):
	"""Format a set of (account, side) tuples into a readable string."""
	if not account_set:
		return ""
	parts = sorted(f"{acc} ({side})" for acc, side in account_set)
	return ", ".join(parts)


def _build_row(
	doc_row,
	scope,
	deviation_type,
	expected_accounts=None,
	missing_accounts=None,
	unexpected_accounts=None,
	sle_issue=None,
	details=None,
):
	"""
	Build a single report output row.

	Args:
		doc_row: dict from SQL with name, posting_date, etc.
		scope: internal scope string
		deviation_type: GL Mismatch / GL Missing / SLE Mismatch / Both
		expected_accounts: set of (account, side) tuples
		missing_accounts: set of (account, side) tuples
		unexpected_accounts: set of (account, side) tuples
		sle_issue: string describing SLE problem
		details: optional additional context string

	Returns:
		dict suitable for report data row
	"""
	doctype_map = {
		"tabDelivery Note": "Delivery Note",
		"tabSales Invoice": "Sales Invoice",
		"tabPurchase Receipt": "Purchase Receipt",
		"tabPurchase Invoice": "Purchase Invoice",
	}
	doc_name = doc_row.get("name") or ""
	document_type = ""
	for dt in ("Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"):
		if frappe.db.exists(dt, doc_name):
			document_type = dt
			break

	if not details:
		parts = []
		if missing_accounts:
			parts.append(f"Missing: {_format_account_set(missing_accounts)}")
		if unexpected_accounts:
			parts.append(f"Unexpected: {_format_account_set(unexpected_accounts)}")
		if sle_issue:
			parts.append(sle_issue)
		details = " | ".join(parts) if parts else ""

	return {
		"posting_date": doc_row.get("posting_date"),
		"document_type": document_type,
		"document_name": doc_name,
		"internal_scope": _SCOPE_LABELS.get(scope, scope),
		"deviation_type": deviation_type,
		"expected_accounts": _format_account_set(expected_accounts) if expected_accounts else "",
		"unexpected_accounts": _format_account_set(unexpected_accounts) if unexpected_accounts else "",
		"missing_accounts": _format_account_set(missing_accounts) if missing_accounts else "",
		"sle_issue": sle_issue or "",
		"details": details or "",
	}


# ---------------------------------------------------------------------------
# Bulk repost APIs
# ---------------------------------------------------------------------------

_VALID_REPOST_DOCTYPES = frozenset({
	"Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice",
})


@frappe.whitelist()
def repost_sle_for_audit_documents(documents):
	"""
	Enqueue SLE repost for a batch of audit-flagged documents.

	Creates one Repost Item Valuation entry per document, queued through
	ERPNext's standard repost pipeline.

	Args:
		documents: JSON string of [{voucher_type, voucher_no}, ...].

	Returns:
		dict with success count, error count, and per-document results.
	"""
	frappe.only_for(["Accounts Manager", "System Manager"])

	if isinstance(documents, str):
		documents = json.loads(documents)

	if not documents:
		frappe.throw(_("No documents provided for SLE repost."))

	frappe.enqueue(
		"business_needed_solutions.bns_branch_accounting.report"
		".internal_transfer_accounting_audit.internal_transfer_accounting_audit"
		"._process_sle_repost_batch",
		queue="long",
		timeout=1800,
		documents=documents,
	)

	return {
		"success": True,
		"message": _("SLE repost job enqueued for {0} document(s). Check Background Jobs for progress.").format(
			len(documents)
		),
	}


def _process_sle_repost_batch(documents):
	"""
	Background worker: create Repost Item Valuation entries for each document.

	Args:
		documents: list of dicts [{voucher_type, voucher_no}, ...].
	"""
	from erpnext.controllers.stock_controller import create_repost_item_valuation_entry

	success = 0
	errors = 0

	for entry in documents:
		voucher_type = entry.get("voucher_type") or entry.get("document_type") or ""
		voucher_no = entry.get("voucher_no") or entry.get("document_name") or ""

		if voucher_type not in _VALID_REPOST_DOCTYPES or not voucher_no:
			errors += 1
			continue

		try:
			doc = frappe.get_doc(voucher_type, voucher_no)
			if doc.docstatus != 1:
				errors += 1
				continue

			create_repost_item_valuation_entry({
				"based_on": "Transaction",
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
				"posting_date": doc.posting_date,
				"posting_time": getattr(doc, "posting_time", "00:00:00") or "00:00:00",
				"company": doc.company,
				"allow_zero_rate": 1,
			})
			success += 1
			frappe.db.commit()
		except Exception:
			errors += 1
			frappe.db.rollback()
			frappe.log_error(
				title=f"Audit SLE Repost Error: {voucher_type} {voucher_no}",
			)

	frappe.publish_realtime(
		"msgprint",
		{
			"message": _("SLE repost complete: {0} succeeded, {1} failed.").format(success, errors),
			"title": _("Audit SLE Repost"),
			"indicator": "green" if errors == 0 else "orange",
		},
	)


@frappe.whitelist()
def repost_gl_for_audit_documents(documents):
	"""
	Enqueue GL rebuild for a batch of audit-flagged documents.

	Uses the existing bns_force_rebuild_gl_for_voucher from utils.py.

	Args:
		documents: JSON string of [{voucher_type, voucher_no}, ...].

	Returns:
		dict with enqueue confirmation.
	"""
	frappe.only_for(["Accounts Manager", "System Manager"])

	if isinstance(documents, str):
		documents = json.loads(documents)

	if not documents:
		frappe.throw(_("No documents provided for GL repost."))

	frappe.enqueue(
		"business_needed_solutions.bns_branch_accounting.report"
		".internal_transfer_accounting_audit.internal_transfer_accounting_audit"
		"._process_gl_repost_batch",
		queue="long",
		timeout=1800,
		documents=documents,
	)

	return {
		"success": True,
		"message": _("GL repost job enqueued for {0} document(s). Check Background Jobs for progress.").format(
			len(documents)
		),
	}


def _process_gl_repost_batch(documents):
	"""
	Background worker: force-rebuild GL entries for each document.

	Args:
		documents: list of dicts [{voucher_type, voucher_no}, ...].
	"""
	from business_needed_solutions.bns_branch_accounting.utils import (
		bns_force_rebuild_gl_for_voucher,
	)

	success = 0
	errors = 0

	for entry in documents:
		voucher_type = entry.get("voucher_type") or entry.get("document_type") or ""
		voucher_no = entry.get("voucher_no") or entry.get("document_name") or ""

		if voucher_type not in _VALID_REPOST_DOCTYPES or not voucher_no:
			errors += 1
			continue

		try:
			result = bns_force_rebuild_gl_for_voucher(voucher_type, voucher_no)
			if result.get("ok"):
				success += 1
			else:
				errors += 1
			frappe.db.commit()
		except Exception:
			errors += 1
			frappe.db.rollback()
			frappe.log_error(
				title=f"Audit GL Repost Error: {voucher_type} {voucher_no}",
			)

	frappe.publish_realtime(
		"msgprint",
		{
			"message": _("GL repost complete: {0} succeeded, {1} failed.").format(success, errors),
			"title": _("Audit GL Repost"),
			"indicator": "green" if errors == 0 else "orange",
		},
	)
