# Why:
# Stock Received But Not Billed (SRBNB) is a liability account that grows
# when Purchase Receipts are submitted (Cr SRBNB + Dr Stock In Hand) and
# shrinks when matching Purchase Invoices clear it (Dr SRBNB + Cr Creditors).
# If PIs never arrive the balance stays inflated on the Balance Sheet.
# This module categorises every outstanding GL entry on the SRBNB account
# into 4 actionable buckets so accountants know exactly what's real
# liability vs noise (intra-state transfers, orphan PI debits, manual JEs).

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def get_srbnb_reconciliation(company: str) -> dict:
	"""Return the SRBNB reconciliation breakdown for the BNS Dashboard.

	Buckets:
	  1. stock_entries   — Stock Entries between own warehouses (same company)
	  2. orphan_pi_debits — Purchase Invoices that hit SRBNB Dr side without
	                        a purchase_receipt link on any item row
	  3. open_prs        — Purchase Receipts whose SRBNB Cr has NOT been
	                        cleared by a submitted PI (the real liability)
	  4. journal_entries — Manual JE adjustments; Cr-side flagged as needing review
	"""
	if not company:
		return {"error": "Company is required"}

	srbnb_account = frappe.db.get_value("Company", company, "stock_received_but_not_billed")
	if not srbnb_account:
		return {
			"error": f"No 'Stock Received But Not Billed' account configured for {company}. "
			"Set it in Company → Accounts → Stock Received But Not Billed.",
			"account": None,
		}

	# ------------------------------------------------------------------
	# 1. Fetch all non-cancelled GL entries on the SRBNB account
	# ------------------------------------------------------------------
	gl_rows = frappe.db.sql(
		"""
		SELECT voucher_type, voucher_no, debit, credit, posting_date, against, remarks
		FROM `tabGL Entry`
		WHERE account = %(account)s
		  AND company = %(company)s
		  AND is_cancelled = 0
		ORDER BY posting_date ASC
		""",
		{"account": srbnb_account, "company": company},
		as_dict=True,
	)

	if not gl_rows:
		return _empty_result(srbnb_account, company)

	net_balance = sum(flt(r.debit) - flt(r.credit) for r in gl_rows)

	# ------------------------------------------------------------------
	# 2. Group by voucher type and collect unique voucher_nos
	# ------------------------------------------------------------------
	pr_entries = {}   # voucher_no -> {credit, posting_date, against}
	pi_entries = {}   # voucher_no -> {debit, posting_date, against}
	se_entries = {}   # voucher_no -> {debit, credit, posting_date}
	je_entries = {}   # voucher_no -> {debit, credit, posting_date, remarks}

	for row in gl_rows:
		vt = row.voucher_type
		vn = row.voucher_no
		if vt == "Purchase Receipt":
			existing = pr_entries.get(vn, {"credit": 0, "debit": 0})
			existing["credit"] += flt(row.credit)
			existing["debit"] += flt(row.debit)
			existing["posting_date"] = row.posting_date
			existing["against"] = row.against
			pr_entries[vn] = existing
		elif vt == "Purchase Invoice":
			existing = pi_entries.get(vn, {"debit": 0, "credit": 0})
			existing["debit"] += flt(row.debit)
			existing["credit"] += flt(row.credit)
			existing["posting_date"] = row.posting_date
			existing["against"] = row.against
			pi_entries[vn] = existing
		elif vt == "Stock Entry":
			existing = se_entries.get(vn, {"debit": 0, "credit": 0})
			existing["debit"] += flt(row.debit)
			existing["credit"] += flt(row.credit)
			existing["posting_date"] = row.posting_date
			se_entries[vn] = existing
		elif vt == "Journal Entry":
			existing = je_entries.get(vn, {"debit": 0, "credit": 0, "remarks": ""})
			existing["debit"] += flt(row.debit)
			existing["credit"] += flt(row.credit)
			existing["posting_date"] = row.posting_date
			existing["remarks"] = row.remarks or existing.get("remarks", "")
			je_entries[vn] = existing

	# ------------------------------------------------------------------
	# 3. Determine which PRs are paired with a submitted PI
	# ------------------------------------------------------------------
	pr_names = list(pr_entries.keys())
	paired_prs = set()
	if pr_names:
		paired_prs = _get_paired_prs(pr_names)

	# ------------------------------------------------------------------
	# 4. Determine which PIs have a purchase_receipt link (not orphaned)
	# ------------------------------------------------------------------
	pi_names = list(pi_entries.keys())
	linked_pis = set()
	if pi_names:
		linked_pis = _get_pis_with_pr_link(pi_names)

	# ------------------------------------------------------------------
	# 5. Build buckets
	# ------------------------------------------------------------------
	today = getdate(nowdate())

	# ------------------------------------------------------------------
	# 5a. Identify which unmatched PRs are BNS internal transfers
	# ------------------------------------------------------------------
	unmatched_pr_names = [vn for vn in pr_entries if vn not in paired_prs]
	internal_pr_set = set()
	if unmatched_pr_names:
		internal_pr_set = _get_bns_internal_prs(unmatched_pr_names)

	# Bucket: Open PRs (external — Cr SRBNB not cleared by PI, not internal)
	open_prs_rows = []
	# Bucket: BNS Internal PRs (separate — clearable via JE to COGS)
	internal_prs_rows = []
	for vn, data in pr_entries.items():
		if vn in paired_prs:
			continue
		amount = flt(data["credit"]) - flt(data["debit"])
		if abs(amount) < 0.01:
			continue
		age_days = (today - getdate(data["posting_date"])).days if data["posting_date"] else 0
		supplier = _get_pr_supplier(vn)
		row = {
			"voucher_no": vn,
			"supplier": supplier,
			"posting_date": str(data["posting_date"]) if data["posting_date"] else "",
			"amount": amount,
			"age_days": age_days,
			"age_color": "red" if age_days > 60 else ("amber" if age_days > 30 else ""),
		}
		if vn in internal_pr_set:
			row["linked_dn"] = _get_pr_linked_dn(vn)
			internal_prs_rows.append(row)
		else:
			open_prs_rows.append(row)
	open_prs_rows.sort(key=lambda r: -r["age_days"])
	internal_prs_rows.sort(key=lambda r: -r["age_days"])

	# Bucket: Orphan PI Debits (Dr SRBNB without PR link)
	orphan_pi_rows = []
	for vn, data in pi_entries.items():
		if vn in linked_pis:
			continue
		amount = flt(data["debit"]) - flt(data["credit"])
		if abs(amount) < 0.01:
			continue
		supplier = _get_pi_supplier(vn)
		orphan_pi_rows.append({
			"voucher_no": vn,
			"supplier": supplier,
			"posting_date": str(data["posting_date"]) if data["posting_date"] else "",
			"amount": amount,
		})

	# Bucket: Stock Entries
	se_rows = []
	for vn, data in se_entries.items():
		amount = flt(data["debit"]) - flt(data["credit"])
		if abs(amount) < 0.01:
			continue
		se_info = _get_stock_entry_info(vn)
		se_rows.append({
			"voucher_no": vn,
			"posting_date": str(data["posting_date"]) if data["posting_date"] else "",
			"amount": amount,
			"stock_entry_type": se_info.get("stock_entry_type", ""),
			"from_warehouse": se_info.get("from_warehouse", ""),
			"to_warehouse": se_info.get("to_warehouse", ""),
			"is_same_gstin": se_info.get("is_same_gstin", False),
		})

	# Bucket: Journal Entries
	je_rows = []
	for vn, data in je_entries.items():
		dr = flt(data["debit"])
		cr = flt(data["credit"])
		if abs(dr) < 0.01 and abs(cr) < 0.01:
			continue
		je_rows.append({
			"voucher_no": vn,
			"posting_date": str(data["posting_date"]) if data["posting_date"] else "",
			"debit": dr,
			"credit": cr,
			"remark": (data.get("remarks") or "")[:200],
			"needs_review": cr > 0.01,  # Cr-side JE increases SRBNB liability without a PR — flag
		})

	return {
		"account": srbnb_account,
		"company": company,
		"net_balance": net_balance,
		"total_gl_entries": len(gl_rows),
		"paired_prs_excluded": len(paired_prs),
		"buckets": {
			"internal_prs": {
				"total": sum(r["amount"] for r in internal_prs_rows),
				"count": len(internal_prs_rows),
				"rows": internal_prs_rows,
			},
			"open_prs": {
				"total": sum(r["amount"] for r in open_prs_rows),
				"count": len(open_prs_rows),
				"rows": open_prs_rows,
			},
			"orphan_pi_debits": {
				"total": sum(r["amount"] for r in orphan_pi_rows),
				"count": len(orphan_pi_rows),
				"rows": orphan_pi_rows,
			},
			"stock_entries": {
				"total": sum(r["amount"] for r in se_rows),
				"count": len(se_rows),
				"rows": se_rows,
			},
			"journal_entries": {
				"total": sum(r.get("debit", 0) - r.get("credit", 0) for r in je_rows),
				"count": len(je_rows),
				"rows": je_rows,
			},
		},
	}


def _empty_result(account, company):
	empty_bucket = {"total": 0, "count": 0, "rows": []}
	return {
		"account": account,
		"company": company,
		"net_balance": 0,
		"total_gl_entries": 0,
		"paired_prs_excluded": 0,
		"buckets": {
			"internal_prs": dict(empty_bucket),
			"open_prs": dict(empty_bucket),
			"orphan_pi_debits": dict(empty_bucket),
			"stock_entries": dict(empty_bucket),
			"journal_entries": dict(empty_bucket),
		},
	}


def _get_paired_prs(pr_names: list) -> set:
	"""Return set of PR names that have at least one submitted PI linked."""
	if not pr_names:
		return set()
	placeholders = ", ".join(["%s"] * len(pr_names))
	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT pii.purchase_receipt
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent AND pi.docstatus = 1
		WHERE pii.purchase_receipt IN ({placeholders})
		  AND IFNULL(pii.purchase_receipt, '') != ''
		""",
		tuple(pr_names),
		as_dict=False,
	)
	return {r[0] for r in rows if r[0]}


def _get_pis_with_pr_link(pi_names: list) -> set:
	"""Return set of PI names that have at least one item with a purchase_receipt link."""
	if not pi_names:
		return set()
	placeholders = ", ".join(["%s"] * len(pi_names))
	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT parent
		FROM `tabPurchase Invoice Item`
		WHERE parent IN ({placeholders})
		  AND IFNULL(purchase_receipt, '') != ''
		""",
		tuple(pi_names),
		as_dict=False,
	)
	return {r[0] for r in rows if r[0]}


def _get_pr_supplier(pr_name: str) -> str:
	return frappe.db.get_value("Purchase Receipt", pr_name, "supplier") or ""


def _get_pi_supplier(pi_name: str) -> str:
	return frappe.db.get_value("Purchase Invoice", pi_name, "supplier") or ""


def _get_bns_internal_prs(pr_names: list) -> set:
	"""Return set of PR names that are BNS internal transfers."""
	if not pr_names:
		return set()
	placeholders = ", ".join(["%s"] * len(pr_names))
	rows = frappe.db.sql(
		f"""
		SELECT name FROM `tabPurchase Receipt`
		WHERE name IN ({placeholders})
		  AND is_bns_internal_supplier = 1
		""",
		tuple(pr_names),
		as_dict=False,
	)
	return {r[0] for r in rows if r[0]}


def _get_pr_linked_dn(pr_name: str) -> str:
	"""Get the linked Delivery Note for a BNS internal PR."""
	dn = frappe.db.get_value("Purchase Receipt", pr_name, "bns_inter_company_reference")
	return dn or ""


def build_internal_srbnb_clearing_je(
	company: str,
	pr_names: list,
	posting_date: str | None = None,
	submit: bool = False,
) -> dict:
	"""Build (and optionally submit) a Journal Entry that clears the SRBNB
	liability for BNS internal Purchase Receipts.

	JE legs:
	  Dr SRBNB (reduces liability) = sum of internal PR credits on SRBNB
	  Cr Clearing Account (COGS or configured account)

	Returns: {"journal_entry": JE name, "amount": total, "pr_count": N}
	         or {"error": reason}
	"""
	import erpnext

	if not pr_names:
		return {"error": "No Purchase Receipt names provided"}

	srbnb_account = frappe.db.get_value("Company", company, "stock_received_but_not_billed")
	if not srbnb_account:
		return {"error": f"No SRBNB account configured for {company}"}

	# Clearing account: from BNS Settings, or fall back to default COGS
	clearing_account = frappe.db.get_single_value("BNS Settings", "srbnb_internal_clearing_account")
	if not clearing_account:
		clearing_account = frappe.db.get_value(
			"Company", company, "default_expense_account"
		)
	if not clearing_account:
		# Last resort: find any COGS-type account for the company
		clearing_account = frappe.db.get_value(
			"Account",
			{"company": company, "account_name": ("like", "%Cost of Goods Sold%"), "is_group": 0},
			"name",
		)
	if not clearing_account:
		return {"error": "No clearing account found. Set 'Internal Transfer SRBNB Clearing Account' in BNS Settings."}

	# Compute total SRBNB credit for these PRs
	placeholders = ", ".join(["%s"] * len(pr_names))
	rows = frappe.db.sql(
		f"""
		SELECT SUM(credit) - SUM(debit) AS net_credit
		FROM `tabGL Entry`
		WHERE account = %s
		  AND company = %s
		  AND is_cancelled = 0
		  AND voucher_type = 'Purchase Receipt'
		  AND voucher_no IN ({placeholders})
		""",
		[srbnb_account, company] + list(pr_names),
		as_dict=True,
	)
	total = flt(rows[0].net_credit) if rows and rows[0].net_credit else 0
	if total <= 0.01:
		return {"error": "No SRBNB credit balance found for the selected PRs"}

	posting_date = getdate(posting_date or nowdate())
	cost_center = erpnext.get_default_cost_center(company)

	jv = frappe.new_doc("Journal Entry")
	jv.voucher_type = "Journal Entry"
	jv.posting_date = posting_date
	jv.company = company
	jv.is_system_generated = 1
	jv.user_remark = (
		f"BNS Internal Transfer SRBNB clearing: "
		f"{len(pr_names)} PRs, {frappe.utils.fmt_money(total, currency=erpnext.get_company_currency(company))}"
	)

	# Leg 1: Dr SRBNB (reduce liability)
	jv.append("accounts", {
		"account": srbnb_account,
		"debit_in_account_currency": total,
		"debit": total,
		"credit_in_account_currency": 0,
		"credit": 0,
		"cost_center": cost_center,
	})
	# Leg 2: Cr Clearing Account (recognize cost)
	jv.append("accounts", {
		"account": clearing_account,
		"debit_in_account_currency": 0,
		"debit": 0,
		"credit_in_account_currency": total,
		"credit": total,
		"cost_center": cost_center,
	})

	jv.flags.ignore_permissions = True
	jv.save()
	if submit:
		jv.submit()

	return {
		"journal_entry": jv.name,
		"amount": total,
		"pr_count": len(pr_names),
		"clearing_account": clearing_account,
		"submitted": bool(submit),
	}


def _get_stock_entry_info(se_name: str) -> dict:
	"""Get Stock Entry type and warehouse info for SRBNB categorisation."""
	se = frappe.db.get_value(
		"Stock Entry",
		se_name,
		["stock_entry_type", "from_warehouse", "to_warehouse"],
		as_dict=True,
	)
	if not se:
		return {}
	is_same_gstin = False
	if se.from_warehouse and se.to_warehouse:
		from_gstin = frappe.db.get_value("Address", {"name": se.from_warehouse}, "gstin") or ""
		to_gstin = frappe.db.get_value("Address", {"name": se.to_warehouse}, "gstin") or ""
		if from_gstin and to_gstin and from_gstin == to_gstin:
			is_same_gstin = True
	return {
		"stock_entry_type": se.stock_entry_type or "",
		"from_warehouse": se.from_warehouse or "",
		"to_warehouse": se.to_warehouse or "",
		"is_same_gstin": is_same_gstin,
	}
