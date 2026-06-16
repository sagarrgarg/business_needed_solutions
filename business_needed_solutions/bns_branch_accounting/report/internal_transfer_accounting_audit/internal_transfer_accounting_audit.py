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

def _apply_cutoff_filters(filters):
	"""Apply cutoff as default from_date when user has not provided one."""
	if filters.get("from_date"):
		return filters
	from business_needed_solutions.bns_branch_accounting.utils import _get_internal_transfer_cutoff_date
	cutoff = _get_internal_transfer_cutoff_date()
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

	sales_transfer = (
		frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_sales_transfer_account")
		or legacy
	).strip()
	purchase_transfer = (
		frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_purchase_transfer_account")
		or legacy
	).strip()

	settings = {
		"stock_in_transit": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "stock_in_transit_account") or ""
		).strip(),
		"internal_sales_transfer": sales_transfer,
		"internal_purchase_transfer": purchase_transfer,
		# Non-GST (DN/PR same-GSTIN) accounts fall back to the GST/Inter-State
		# account when the split field is blank.
		"internal_sales_non_gst": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_sales_non_gst_account")
			or sales_transfer
		).strip(),
		"internal_purchase_non_gst": (
			frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_purchase_non_gst_account")
			or purchase_transfer
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
	# Diff-GSTIN DN with the per-doc opt-in flag routes through the same-GSTIN
	# GL rewrite path (utils.py:_is_same_gstin_internal_delivery_note), so the
	# audit must expect the same-GSTIN GL pattern for these documents.
	if cint(doc.get("bns_allow_diff_gstin_dn_pr")):
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

	if source_ref and frappe.db.exists("Delivery Note", {"name": source_ref, "docstatus": 1}):
		dn_data = frappe.db.get_value(
			"Delivery Note", source_ref,
			["company_gstin", "billing_address_gstin", "bns_allow_diff_gstin_dn_pr"], as_dict=True
		)
		if dn_data:
			dn_co = (dn_data.get("company_gstin") or "").strip()
			dn_bill = (dn_data.get("billing_address_gstin") or "").strip()
			if dn_co and dn_bill and dn_co == dn_bill:
				return "dn_same_gstin"
			# Source DN carries the per-doc diff-GSTIN opt-in flag — PR routes
			# through the same-GSTIN GL rewrite path
			# (utils.py:_is_bns_internal_same_gstin_purchase_receipt).
			if cint(dn_data.get("bns_allow_diff_gstin_dn_pr")):
				return "dn_same_gstin"

	if source_ref and frappe.db.exists("Sales Invoice", {"name": source_ref, "docstatus": 1}):
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
	if si_ref and frappe.db.exists("Sales Invoice", {"name": si_ref, "docstatus": 1}):
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
				if pr_ref and frappe.db.exists("Sales Invoice", {"name": (pr_ref or "").strip(), "docstatus": 1}):
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
			(settings["internal_sales_non_gst"], "credit"),
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
			(settings["internal_purchase_non_gst"], "debit"),
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
# Zero-valuation reclassification
# ---------------------------------------------------------------------------

def _is_zero_stock_value(voucher_type, voucher_no):
	"""Return True when the voucher's stock movement carries zero value.

	When an item's valuation_rate is 0, the SLE stock_value_difference is 0 and
	ERPNext posts no stock-side GL. The absent stock legs are then correct, not a
	missing internal-transfer leg -- the real issue is the item valuation.
	"""
	row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(ABS(stock_value_difference)), 0)
		FROM `tabStock Ledger Entry`
		WHERE voucher_type = %s AND voucher_no = %s AND is_cancelled = 0
		""",
		(voucher_type, voucher_no),
	)
	return flt(row[0][0]) <= 0.005 if row else False


def _stock_side_accounts(settings, doc):
	"""Return the set of stock-side account names expected for a document."""
	accounts = set()
	sit = settings.get("stock_in_transit")
	if sit:
		accounts.add(sit)
	stock_account = _resolve_stock_account_for_doc(doc)
	if stock_account:
		accounts.add(stock_account)
	return accounts


def _missing_only_stock(missing, stock_accounts):
	"""True when every missing (account, side) entry is a stock-side account."""
	if not missing:
		return False
	return all(acc in stock_accounts for acc, _side in missing)


_ZERO_VALUATION_DETAILS = (
	"Stock-side GL is absent because the item valuation rate is 0 "
	"(stock_value_difference = 0). This is a genuine item-valuation gap, not a "
	"missing internal-transfer GL leg -- set the item's valuation / incoming cost "
	"and repost. Reposting alone will not create stock GL while the value is 0."
)


def _finalize_gl_deviation_row(doc_row, scope, settings, doc, expected, missing, unexpected, sle_issue=None):
	"""Build a GL Mismatch row, downgrading stock-only gaps at zero valuation."""
	stock_accounts = _stock_side_accounts(settings, doc)
	if (
		missing
		and not unexpected
		and _missing_only_stock(missing, stock_accounts)
		and _is_zero_stock_value(doc.doctype, doc.name)
	):
		return _build_row(
			doc_row, scope, "Zero Stock Valuation",
			details=_ZERO_VALUATION_DETAILS,
			sle_issue=sle_issue,
		)
	return _build_row(
		doc_row, scope, "GL Mismatch",
		expected_accounts=expected,
		missing_accounts=missing,
		unexpected_accounts=unexpected,
		sle_issue=sle_issue,
	)


def _finalize_gl_missing_row(doc_row, scope, settings, doc, expected, default_details):
	"""Build a GL Missing row, downgrading the stock-only zero-valuation case."""
	stock_accounts = _stock_side_accounts(settings, doc)
	expected_accounts = {acc for acc, _side in expected}
	if (
		expected_accounts
		and expected_accounts.issubset(stock_accounts)
		and _is_zero_stock_value(doc.doctype, doc.name)
	):
		return _build_row(
			doc_row, scope, "Zero Stock Valuation",
			details=_ZERO_VALUATION_DETAILS,
		)
	return _build_row(
		doc_row, scope, "GL Missing",
		expected_accounts=expected,
		details=default_details,
	)


def _build_combined_gl_sle_row(
	doc_row, scope, settings, doc, expected, gl_missing,
	missing_set, unexpected_set, sle_deviation, gl_missing_details,
):
	"""Build a combined GL/SLE deviation row for PR/PI, downgrading the
	zero-valuation stock-only gap to an informational 'Zero Stock Valuation' row.
	"""
	stock_accounts = _stock_side_accounts(settings, doc)
	expected_accounts = {acc for acc, _side in expected}
	zero_val_stock_gap = (
		not unexpected_set
		and _is_zero_stock_value(doc.doctype, doc.name)
		and (
			(gl_missing and expected_accounts and expected_accounts.issubset(stock_accounts))
			or (missing_set and _missing_only_stock(missing_set, stock_accounts))
		)
	)
	if zero_val_stock_gap:
		return _build_row(
			doc_row, scope, "Zero Stock Valuation",
			details=_ZERO_VALUATION_DETAILS,
			sle_issue=sle_deviation,
		)

	gl_dev = "GL Missing" if gl_missing else ("GL Mismatch" if (missing_set or unexpected_set) else None)
	deviation_type = "Both" if (gl_dev and sle_deviation) else (gl_dev or "SLE Mismatch")
	return _build_row(
		doc_row, scope, deviation_type,
		expected_accounts=expected if gl_dev else None,
		missing_accounts=missing_set,
		unexpected_accounts=unexpected_set,
		sle_issue=sle_deviation,
		details=(gl_missing_details if gl_missing else None),
	)


# ---------------------------------------------------------------------------
# Transfer-rate-missing detection (undervalued internal receive)
# ---------------------------------------------------------------------------

_TRANSFER_RATE_MISSING_DETAILS = (
	"Receiving document undervalues stock: bns_transfer_rate is 0 while the source "
	"(linked DN/SI) carries a positive incoming_rate. Stock-in-Transit / Internal COGS "
	"will not net to zero until the rate is populated and the document is reposted. "
	"Use the 'Repost GL' action -- it backfills the transfer rate from the source "
	"before reposting."
)


def _transfer_rate_missing_issues(doc, rate_by_code):
	"""Return per-row issue strings for stock items with a missing transfer rate."""
	issues = []
	for item in (doc.get("items") or []):
		if flt(item.get("qty") or 0) <= 0:
			continue
		if flt(item.get("bns_transfer_rate") or 0) > 0:
			continue
		code = item.get("item_code")
		if not code or not cint(frappe.db.get_value("Item", code, "is_stock_item")):
			continue
		expected = flt(rate_by_code.get(code) or 0)
		if expected > 0:
			issues.append(
				f"#{cint(item.get('idx') or 0) or '?'} {code}: "
				f"bns_transfer_rate=0, source incoming_rate={round(expected, 4)}"
			)
	return issues


def _check_transfer_rate_missing_for_pi(doc):
	"""Flag internal update-stock PI rows where bns_transfer_rate is 0 but the
	linked Sales Invoice carries a positive incoming_rate (undervalued receive).
	"""
	if not cint(doc.get("update_stock")):
		return []
	pi_meta = frappe.get_meta("Purchase Invoice Item")
	if not pi_meta.has_field("bns_transfer_rate"):
		return []
	from business_needed_solutions.bns_branch_accounting.utils import (
		_resolve_si_name_for_internal_pi,
		_build_si_rate_maps_for_pi,
	)
	si_name = _resolve_si_name_for_internal_pi(doc)
	if not si_name:
		return []
	si_rate_by_item, si_rows, _buckets = _build_si_rate_maps_for_pi(si_name)
	rate_by_code = {}
	for sr in si_rows:
		code = sr.get("item_code")
		rate = flt(si_rate_by_item.get(sr.get("name")) or 0)
		if code and rate > rate_by_code.get(code, 0):
			rate_by_code[code] = rate
	return _transfer_rate_missing_issues(doc, rate_by_code)


def _check_transfer_rate_missing_for_pr(doc):
	"""Flag internal PR rows where bns_transfer_rate is 0 but the source DN/SI
	carries a positive incoming_rate (undervalued receive).
	"""
	pr_meta = frappe.get_meta("Purchase Receipt Item")
	if not pr_meta.has_field("bns_transfer_rate"):
		return []
	ref = (doc.get("bns_inter_company_reference") or "").strip()
	if not ref:
		return []
	if frappe.db.exists("Delivery Note", ref):
		src_rows = frappe.get_all(
			"Delivery Note Item", filters={"parent": ref},
			fields=["item_code", "incoming_rate"],
		)
	elif frappe.db.exists("Sales Invoice", ref):
		src_rows = frappe.get_all(
			"Sales Invoice Item", filters={"parent": ref},
			fields=["item_code", "incoming_rate"],
		)
	else:
		return []
	rate_by_code = {}
	for sr in src_rows:
		code = sr.get("item_code")
		rate = flt(sr.get("incoming_rate") or 0)
		if code and rate > rate_by_code.get(code, 0):
			rate_by_code[code] = rate
	return _transfer_rate_missing_issues(doc, rate_by_code)


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
		SELECT name, voucher_detail_no, actual_qty, incoming_rate
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
		SELECT name, voucher_detail_no, actual_qty, incoming_rate
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
	"orphaned_receiving": "Orphaned (source cancelled/missing)",
	"flag_mismatch": "Flag Mismatch (one-sided internal)",
	"no_counter_doc": "Missing Counter-Document",
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

	data.extend(_audit_cross_document_consistency(filters, settings))

	data.sort(key=lambda r: r.get("posting_date") or "0000-00-00", reverse=True)
	return data


def _get_doc_types_to_audit(filters):
	"""Return list of doctypes to audit based on filter."""
	dt = (filters.get("document_type") or "").strip()
	if dt:
		return [dt]
	return ["Delivery Note", "Sales Invoice", "Purchase Receipt", "Purchase Invoice"]


def _is_zero_amount_document(doc):
	"""Return True when document has zero grand total and net total -- no GL expected."""
	return abs(flt(doc.get("base_grand_total"))) <= 0 and abs(flt(doc.get("base_net_total"))) <= 0


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
		if _is_zero_amount_document(doc):
			continue
		expected = _expected_gl_for_dn(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Delivery Note", row.name)

		if not gl_entries:
			results.append(_finalize_gl_missing_row(
				row, scope, settings, doc, expected,
				"No GL entries found for submitted internal DN.",
			))
			continue

		actual = _actual_gl_account_sides(gl_entries)
		missing, unexpected = _compare_gl(expected, actual, company=doc.company)

		if missing or unexpected:
			results.append(_finalize_gl_deviation_row(
				row, scope, settings, doc, expected, missing, unexpected,
			))

	return results


def _audit_sales_invoices(filters, settings):
	"""Audit GL entries for BNS internal Sales Invoices (including credit notes)."""
	from business_needed_solutions.bns_branch_accounting.utils import _internal_stock_movement_uncaptured
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
		if _is_zero_amount_document(doc):
			continue
		if scope == "different_gstin_return":
			expected = _expected_gl_for_si_return(scope, settings, doc)
		else:
			expected = _expected_gl_for_si(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Sales Invoice", row.name)

		if not gl_entries:
			results.append(_finalize_gl_missing_row(
				row, scope, settings, doc, expected,
				"No GL entries found for submitted internal SI.",
			))
			continue

		actual = _actual_gl_account_sides(gl_entries)
		missing, unexpected = _compare_gl(expected, actual, company=doc.company)

		if missing or unexpected:
			results.append(_finalize_gl_deviation_row(
				row, scope, settings, doc, expected, missing, unexpected,
			))

		# Stock-gap anomaly: stock items invoiced internally but no stock
		# movement recorded anywhere (Update Stock off + no Delivery Note).
		# Informational — neither repost button picks this up (no sle_issue);
		# the fix is a DN or Update Stock correction, not a repost.
		if _internal_stock_movement_uncaptured(doc):
			results.append(_build_row(
				row, scope, "Stock Not Captured",
				details=(
					"Internal SI has stock items but no stock movement is captured "
					"(Update Stock off and no Delivery Note linked). GL may be valid, "
					"but inventory was never moved — create from a Delivery Note (DN → SI) "
					"or enable Update Stock."
				),
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
		if _is_zero_amount_document(doc):
			continue
		expected = _expected_gl_for_pr(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Purchase Receipt", row.name)

		gl_missing = not gl_entries
		missing_set = set()
		unexpected_set = set()
		if not gl_missing:
			actual = _actual_gl_account_sides(gl_entries)
			missing_set, unexpected_set = _compare_gl(expected, actual, company=doc.company)
		gl_mismatch = bool(missing_set or unexpected_set)

		sle_issues = _check_sle_for_pr(doc)
		sle_deviation = "; ".join(sle_issues) if sle_issues else None

		if gl_missing or gl_mismatch or sle_deviation:
			results.append(_build_combined_gl_sle_row(
				row, scope, settings, doc, expected, gl_missing,
				missing_set, unexpected_set, sle_deviation,
				"No GL entries found for submitted internal PR.",
			))

		tr_missing = _check_transfer_rate_missing_for_pr(doc)
		if tr_missing:
			results.append(_build_row(
				row, scope, "Transfer Rate Missing",
				sle_issue="; ".join(tr_missing),
				details=_TRANSFER_RATE_MISSING_DETAILS,
			))

	return results


def _audit_purchase_invoices(filters, settings):
	"""Audit GL and SLE for BNS internal Purchase Invoices (including debit notes)."""
	from business_needed_solutions.bns_branch_accounting.utils import _internal_stock_movement_uncaptured
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
		if _is_zero_amount_document(doc):
			continue
		if scope == "si_linked_return":
			expected = _expected_gl_for_pi_return(scope, settings, doc)
		else:
			expected = _expected_gl_for_pi(scope, settings, doc)
		gl_entries = _fetch_gl_entries("Purchase Invoice", row.name)

		gl_missing = not gl_entries
		missing_set = set()
		unexpected_set = set()
		if not gl_missing:
			actual = _actual_gl_account_sides(gl_entries)
			missing_set, unexpected_set = _compare_gl(expected, actual, company=doc.company)
		gl_mismatch = bool(missing_set or unexpected_set)

		sle_issues = _check_sle_for_pi(doc)
		sle_deviation = "; ".join(sle_issues) if sle_issues else None

		if gl_missing or gl_mismatch or sle_deviation:
			results.append(_build_combined_gl_sle_row(
				row, scope, settings, doc, expected, gl_missing,
				missing_set, unexpected_set, sle_deviation,
				"No GL entries found for submitted internal PI.",
			))

		tr_missing = _check_transfer_rate_missing_for_pi(doc)
		if tr_missing:
			results.append(_build_row(
				row, scope, "Transfer Rate Missing",
				sle_issue="; ".join(tr_missing),
				details=_TRANSFER_RATE_MISSING_DETAILS,
			))

		# Stock-gap anomaly: stock items invoiced internally but no stock
		# movement recorded anywhere (Update Stock off + no Purchase Receipt).
		if _internal_stock_movement_uncaptured(doc):
			results.append(_build_row(
				row, scope, "Stock Not Captured",
				details=(
					"Internal PI has stock items but no stock movement is captured "
					"(Update Stock off and no Purchase Receipt linked). GL may be valid, "
					"but inventory was never moved — link a Purchase Receipt (PR → PI) "
					"or enable Update Stock."
				),
			))

	return results


# ---------------------------------------------------------------------------
# Cross-document consistency audit
# ---------------------------------------------------------------------------

def _audit_cross_document_consistency(filters, settings):
	"""
	Detect cross-document issues that per-document audits miss.

	Checks:
	1. Orphaned PR/PI: references a cancelled/missing source DN/SI but has BNS internal GL.
	2. Flag mismatch: PI has internal GL but referenced SI does not (or PR vs DN).
	3. Missing counter-document: DN/SI has BNS internal GL but no submitted PR/PI exists.
	"""
	results = []
	internal_accounts = {
		settings.get("internal_branch_debtor"),
		settings.get("internal_branch_creditor"),
		settings.get("internal_sales_transfer"),
		settings.get("internal_purchase_transfer"),
		settings.get("internal_sales_non_gst"),
		settings.get("internal_purchase_non_gst"),
		settings.get("stock_in_transit"),
	}
	internal_accounts.discard(None)
	internal_accounts.discard("")

	if not internal_accounts:
		return results

	def _has_internal_gl(voucher_type, voucher_no):
		"""Return True if document has any active GL entries on BNS internal accounts."""
		placeholders = ", ".join(["%s"] * len(internal_accounts))
		count = frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tabGL Entry`
			WHERE voucher_type = %s AND voucher_no = %s
			AND is_cancelled = 0 AND account IN ({placeholders})""",
			(voucher_type, voucher_no, *internal_accounts),
		)[0][0]
		return count > 0

	date_from = filters.get("from_date") or "2000-01-01"
	date_to = filters.get("to_date") or "2099-12-31"
	company = filters.get("company") or ""
	company_cond = "AND pr.company = %s" if company else ""
	company_vals = (company,) if company else ()

	# --- Check 1 & 2: PR with orphaned/mismatched DN ---
	pr_rows = frappe.db.sql(
		f"""SELECT pr.name, pr.posting_date, pr.bns_inter_company_reference,
		          pr.is_bns_internal_supplier, pr.supplier
		   FROM `tabPurchase Receipt` pr
		   WHERE pr.docstatus = 1
		     AND pr.posting_date >= %s AND pr.posting_date <= %s
		     {company_cond}
		     AND (pr.is_bns_internal_supplier = 1
		          OR pr.supplier IN (SELECT name FROM tabSupplier WHERE is_bns_internal_supplier = 1))
		""",
		(date_from, date_to, *company_vals),
		as_dict=True,
	) or []

	for pr in pr_rows:
		ref = (pr.bns_inter_company_reference or "").strip()
		if not ref:
			continue
		if not _has_internal_gl("Purchase Receipt", pr.name):
			continue

		if frappe.db.exists("Delivery Note", ref):
			dn_ds = frappe.db.get_value("Delivery Note", ref, "docstatus")
			if dn_ds == 2:
				results.append(_build_row(
					pr, "orphaned_receiving", "Orphaned GL",
					details=f"PR references cancelled DN {ref}. PR has BNS internal GL but source is dead.",
				))
			elif not _has_internal_gl("Delivery Note", ref):
				results.append(_build_row(
					pr, "flag_mismatch", "Flag Mismatch",
					details=f"PR has BNS internal GL but source DN {ref} does not.",
				))
		elif frappe.db.exists("Sales Invoice", ref):
			si_ds = frappe.db.get_value("Sales Invoice", ref, "docstatus")
			if si_ds == 2:
				results.append(_build_row(
					pr, "orphaned_receiving", "Orphaned GL",
					details=f"PR references cancelled SI {ref}. PR has BNS internal GL but source is dead.",
				))
			elif not _has_internal_gl("Sales Invoice", ref):
				results.append(_build_row(
					pr, "flag_mismatch", "Flag Mismatch",
					details=f"PR has BNS internal GL but source SI {ref} does not.",
				))

	company_cond_pi = "AND pi.company = %s" if company else ""

	# --- Check 1 & 2: PI with orphaned/mismatched SI ---
	pi_rows = frappe.db.sql(
		f"""SELECT pi.name, pi.posting_date, pi.bns_inter_company_reference,
		          pi.is_bns_internal_supplier, pi.supplier, pi.is_return
		   FROM `tabPurchase Invoice` pi
		   WHERE pi.docstatus = 1
		     AND pi.posting_date >= %s AND pi.posting_date <= %s
		     {company_cond_pi}
		     AND (pi.is_bns_internal_supplier = 1
		          OR pi.supplier IN (SELECT name FROM tabSupplier WHERE is_bns_internal_supplier = 1))
		""",
		(date_from, date_to, *company_vals),
		as_dict=True,
	) or []

	for pi in pi_rows:
		ref = (pi.bns_inter_company_reference or "").strip()
		if not ref:
			continue
		if not _has_internal_gl("Purchase Invoice", pi.name):
			continue

		if frappe.db.exists("Sales Invoice", ref):
			si_ds = frappe.db.get_value("Sales Invoice", ref, "docstatus")
			if si_ds == 2:
				results.append(_build_row(
					pi, "orphaned_receiving", "Orphaned GL",
					details=f"PI references cancelled SI {ref}. PI has BNS internal GL but source is dead.",
				))
			elif not _has_internal_gl("Sales Invoice", ref):
				results.append(_build_row(
					pi, "flag_mismatch", "Flag Mismatch",
					details=f"PI has BNS internal GL but source SI {ref} does not.",
				))

	company_cond_dn = "AND dn.company = %s" if company else ""

	# --- Check 3: DN with BNS internal GL but no submitted PR/SI->PI ---
	dn_rows = frappe.db.sql(
		f"""SELECT dn.name, dn.posting_date, dn.is_bns_internal_customer, dn.customer,
		          dn.company_gstin, dn.billing_address_gstin
		   FROM `tabDelivery Note` dn
		   WHERE dn.docstatus = 1
		     AND dn.posting_date >= %s AND dn.posting_date <= %s
		     {company_cond_dn}
		     AND dn.is_return = 0
		     AND (dn.is_bns_internal_customer = 1
		          OR dn.customer IN (SELECT name FROM tabCustomer WHERE is_bns_internal_customer = 1))
		""",
		(date_from, date_to, *company_vals),
		as_dict=True,
	) or []

	for dn in dn_rows:
		if not _has_internal_gl("Delivery Note", dn.name):
			continue

		co_gstin = (dn.get("company_gstin") or "").strip()
		bill_gstin = (dn.get("billing_address_gstin") or "").strip()
		is_same_gstin = co_gstin and bill_gstin and co_gstin == bill_gstin

		if is_same_gstin:
			has_pr = frappe.db.exists("Purchase Receipt", {
				"bns_inter_company_reference": dn.name,
				"docstatus": 1,
			})
			if not has_pr:
				results.append(_build_row(
					dn, "no_counter_doc", "No Counter-Document",
					details="Same-GSTIN DN has BNS internal GL but no submitted PR references it.",
				))
		else:
			linked_si = frappe.db.sql(
				"""SELECT DISTINCT si.name FROM `tabSales Invoice Item` sii
				   JOIN `tabSales Invoice` si ON si.name = sii.parent
				   WHERE sii.delivery_note = %s AND si.docstatus = 1
				   LIMIT 1""",
				(dn.name,),
			)
			if not linked_si:
				results.append(_build_row(
					dn, "no_counter_doc", "No Counter-Document",
					details="Different-GSTIN DN has BNS internal GL but no submitted SI is linked to it.",
				))
			else:
				si_name = linked_si[0][0]
				has_pi = frappe.db.exists("Purchase Invoice", {
					"bns_inter_company_reference": si_name,
					"docstatus": 1,
				})
				if not has_pi:
					has_pi = frappe.db.exists("Purchase Invoice", {
						"bill_no": si_name,
						"docstatus": 1,
					})
				if not has_pi:
					results.append(_build_row(
						dn, "no_counter_doc", "No Counter-Document",
						details=f"DN->SI chain exists (SI {si_name}) but no submitted PI references the SI.",
					))

	company_cond_si = "AND si.company = %s" if company else ""

	# --- Check 3: SI with BNS internal GL but no submitted PI ---
	si_rows = frappe.db.sql(
		f"""SELECT si.name, si.posting_date, si.is_bns_internal_customer, si.customer
		   FROM `tabSales Invoice` si
		   WHERE si.docstatus = 1
		     AND si.posting_date >= %s AND si.posting_date <= %s
		     {company_cond_si}
		     AND si.is_return = 0
		     AND (si.is_bns_internal_customer = 1
		          OR si.customer IN (SELECT name FROM tabCustomer WHERE is_bns_internal_customer = 1))
		     AND si.company_gstin IS NOT NULL
		     AND si.billing_address_gstin IS NOT NULL
		     AND si.company_gstin != si.billing_address_gstin
		""",
		(date_from, date_to, *company_vals),
		as_dict=True,
	) or []

	for si in si_rows:
		if not _has_internal_gl("Sales Invoice", si.name):
			continue
		has_pi = frappe.db.exists("Purchase Invoice", {
			"bns_inter_company_reference": si.name,
			"docstatus": 1,
		})
		if not has_pi:
			has_pi_bill = frappe.db.exists("Purchase Invoice", {
				"bill_no": si.name,
				"docstatus": 1,
			})
			if not has_pi_bill:
				results.append(_build_row(
					si, "no_counter_doc", "No Counter-Document",
					details=f"SI has BNS internal GL but no submitted PI references it.",
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
	ERPNext's standard repost pipeline. The user only needs write
	permission on BNS Branch Accounting Settings — the actual RIV
	creation runs with ignore_permissions because the admin gate has
	already been cleared.

	Args:
		documents: JSON string of [{voucher_type, voucher_no}, ...].

	Returns:
		dict with success count, error count, and per-document results.
	"""
	if not frappe.has_permission("BNS Branch Accounting Settings", "write"):
		frappe.throw(
			_("BNS Branch Accounting Settings write permission required."),
			frappe.PermissionError,
		)

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


def _populate_transfer_rate_before_repost(voucher_type, doc):
	"""Backfill a receiver's bns_transfer_rate from its source before repost so
	the repost values stock at source cost (closes Stock-in-Transit / Internal
	COGS). No-op for senders (DN/SI) and rows that already carry a rate.
	"""
	try:
		from business_needed_solutions.bns_branch_accounting.utils import (
			apply_internal_pi_transfer_rates_from_si,
			_sync_pr_item_transfer_rate_from_dn,
			_sync_pr_item_transfer_rate_from_si,
			_mirror_pr_item_valuation_from_transfer_rate,
			_mirror_pi_item_valuation_from_transfer_rate,
		)
	except Exception:
		return

	if voucher_type == "Purchase Invoice":
		apply_internal_pi_transfer_rates_from_si(doc)
		_mirror_pi_item_valuation_from_transfer_rate(doc.name)
	elif voucher_type == "Purchase Receipt":
		ref = (doc.get("bns_inter_company_reference") or "").strip()
		if ref and frappe.db.exists("Delivery Note", ref):
			_sync_pr_item_transfer_rate_from_dn(ref, pr_name=doc.name)
		elif ref and frappe.db.exists("Sales Invoice", ref):
			_sync_pr_item_transfer_rate_from_si(ref, pr_name=doc.name)
		_mirror_pr_item_valuation_from_transfer_rate(doc.name)


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

			_populate_transfer_rate_before_repost(voucher_type, doc)

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
	Enqueue GL repost for a batch of audit-flagged documents.

	Uses the proper RIV + RAL repost pipeline (matches BNS Verify &
	Repost), NOT direct GL writes. The user only needs write permission
	on BNS Branch Accounting Settings — RIV and RAL submission run with
	ignore_permissions because the admin gate has already been cleared.

	Args:
		documents: JSON string of [{voucher_type, voucher_no}, ...].

	Returns:
		dict with enqueue confirmation.
	"""
	if not frappe.has_permission("BNS Branch Accounting Settings", "write"):
		frappe.throw(
			_("BNS Branch Accounting Settings write permission required."),
			frappe.PermissionError,
		)

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


@frappe.whitelist()
def fix_transfer_rate_for_audit_documents(documents):
	"""
	Backfill bns_transfer_rate from the source, then repost (RIV + RAL) for the
	given receiver documents. Targets the audit's "Transfer Rate Missing" rows
	(internal PR/PI undervalued because the transfer rate was never populated).

	Reuses the GL repost worker, which already runs
	_populate_transfer_rate_before_repost -> RIV (valuation recompute from the
	transfer rate) -> RAL (GL regen). RIV is what corrects the valuation; RAL
	alone cannot. Both run with ignore_permissions because the caller has
	already cleared the BNS Branch Accounting Settings write gate.

	Args:
		documents: JSON string of [{voucher_type, voucher_no}, ...].

	Returns:
		dict with enqueue confirmation.
	"""
	if not frappe.has_permission("BNS Branch Accounting Settings", "write"):
		frappe.throw(
			_("BNS Branch Accounting Settings write permission required."),
			frappe.PermissionError,
		)

	if isinstance(documents, str):
		documents = json.loads(documents)

	if not documents:
		frappe.throw(_("No documents provided for transfer-rate fix."))

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
		"message": _(
			"Transfer-rate fix + repost (RIV + RAL) enqueued for {0} document(s). "
			"Check Background Jobs for progress."
		).format(len(documents)),
	}


def _process_gl_repost_batch(documents):
	"""
	Background worker: repost each document via RIV + RAL.

	RIV (Repost Item Valuation) recalculates SLE and triggers stock-side
	GL regen. RAL (Repost Accounting Ledger) unconditionally deletes the
	voucher's full GL and re-runs make_gl_entries() — which goes through
	the BNS-patched get_gl_entries and emits the correct internal-transfer
	accounts (incl. internal_sales_non_gst_account /
	internal_purchase_non_gst_account where applicable).

	Both submissions run with ignore_permissions=True because the caller
	already passed the admin gate (BNS Branch Accounting Settings write).

	Args:
		documents: list of dicts [{voucher_type, voucher_no}, ...].
	"""
	from erpnext.controllers.stock_controller import create_repost_item_valuation_entry

	from business_needed_solutions.bns_branch_accounting.utils import (
		_apply_bns_internal_gl_rewrite_patch,
		_voucher_owns_sle,
	)

	success = 0
	errors = 0
	failures = []

	for entry in documents:
		voucher_type = entry.get("voucher_type") or entry.get("document_type") or ""
		voucher_no = entry.get("voucher_no") or entry.get("document_name") or ""

		if voucher_type not in _VALID_REPOST_DOCTYPES or not voucher_no:
			errors += 1
			failures.append(f"{voucher_type or '?'} {voucher_no or '?'}: not a repostable doctype")
			continue

		try:
			doc = frappe.get_doc(voucher_type, voucher_no)
			if doc.docstatus != 1:
				errors += 1
				failures.append(f"{voucher_type} {voucher_no}: not submitted")
				continue

			# Backfill a missing transfer rate from the source before reposting,
			# so an undervalued receive (bns_transfer_rate=0) is corrected to
			# source cost instead of being re-posted at the wrong valuation.
			_populate_transfer_rate_before_repost(voucher_type, doc)

			# RIV (stock recalc + bns_transfer_rate sync) only for vouchers
			# that own SLE: DN/PR always, SI/PI only when update_stock=1. For
			# an update_stock=0 invoice the stock lives on the linked DN/PR
			# (which is reposted on its own), so RIV would throw on ERPNext's
			# validate_update_stock and has nothing to recompute — repost GL
			# only via RAL.
			if _voucher_owns_sle(voucher_type, doc):
				create_repost_item_valuation_entry({
					"based_on": "Transaction",
					"voucher_type": voucher_type,
					"voucher_no": voucher_no,
					"posting_date": doc.posting_date,
					"posting_time": getattr(doc, "posting_time", "00:00:00") or "00:00:00",
					"company": doc.company,
					"allow_zero_rate": 1,
				})

			# RAL — full GL regen. Must be preceded by patch application
			# so start_repost's make_gl_entries call hits the BNS-rewritten
			# get_gl_entries; otherwise the regen would wipe BNS GL back to
			# standard ERPNext pattern.
			_apply_bns_internal_gl_rewrite_patch()
			ral = frappe.new_doc("Repost Accounting Ledger")
			ral.company = doc.company
			ral.delete_cancelled_entries = 0
			ral.append("vouchers", {
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
			})
			ral.flags.ignore_permissions = True
			ral.save()
			ral.submit()

			success += 1
			frappe.db.commit()
		except Exception as e:
			errors += 1
			frappe.db.rollback()
			failures.append(f"{voucher_type} {voucher_no}: {str(e)[:200]}")
			frappe.log_error(
				title=f"Audit GL Repost Error: {voucher_type} {voucher_no}",
			)

	message = _("GL repost complete: {0} succeeded, {1} failed.").format(success, errors)
	if failures:
		message += "<br><br>" + _("Failures:") + "<br>" + "<br>".join(
			frappe.utils.escape_html(f) for f in failures[:20]
		)
		if len(failures) > 20:
			message += "<br>" + _("(showing first 20 of {0})").format(len(failures))

	frappe.publish_realtime(
		"msgprint",
		{
			"message": message,
			"title": _("Audit GL Repost"),
			"indicator": "green" if errors == 0 else "orange",
		},
	)
