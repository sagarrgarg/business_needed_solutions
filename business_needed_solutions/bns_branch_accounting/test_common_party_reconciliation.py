# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Integration tests for the BNS auto Payment Reconciliation wrapper.

Same isolation pattern as test_common_party_squareoff.py: run on
_Test Indian Registered Company (dedicated _Test fixture company with full CoA),
tag fixture JVs, and monkey-patch scope helpers to prevent any contact with
real production companies on the shared dev site.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate, nowdate

from business_needed_solutions.bns_branch_accounting.common_party_reconciliation import (
	_iter_parties_for_scope,
	_resolve_window,
	get_reconciliation_candidates,
	reconcile_all_parties,
	reconcile_single_party,
)


RECONCILE_TEST_REMARK_TAG = "BNS_QA_RECONCILE_FIXTURE"


def _ensure_current_fiscal_year():
	today = getdate(nowdate())
	existing = frappe.db.sql(
		"""select name from `tabFiscal Year`
		where %(d)s between year_start_date and year_end_date and disabled = 0""",
		{"d": today},
	)
	if existing:
		return existing[0][0]
	start = today.replace(month=4, day=1)
	if today.month < 4:
		start = start.replace(year=today.year - 1)
	end = start.replace(year=start.year + 1, month=3, day=31)
	fy = frappe.get_doc(
		{
			"doctype": "Fiscal Year",
			"year": f"{start.year}-{end.year}",
			"year_start_date": start,
			"year_end_date": end,
		}
	)
	fy.flags.ignore_permissions = True
	fy.flags.ignore_mandatory = True
	fy.insert(ignore_if_duplicate=True)
	return fy.name


def _get_test_company():
	_ensure_current_fiscal_year()
	for name in [
		"_Test Indian Registered Company",
		"_Test Indian Unregistered Company",
		"_Test Company",
		"_Test Foreign Company",
	]:
		if not frappe.db.exists("Company", name):
			continue
		has_r = frappe.db.exists("Account", {"company": name, "account_type": "Receivable", "is_group": 0})
		has_p = frappe.db.exists("Account", {"company": name, "account_type": "Payable", "is_group": 0})
		if has_r and has_p:
			return frappe.get_doc("Company", name)
	raise RuntimeError("No test Company with Debtors+Creditors accounts on this site.")


def _ensure_customer(name):
	if frappe.db.exists("Customer", name):
		return frappe.get_doc("Customer", name)
	doc = frappe.get_doc(
		{"doctype": "Customer", "customer_name": name, "customer_type": "Company"}
	)
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_permissions = True
	return doc.insert()


def _ensure_supplier(name):
	if frappe.db.exists("Supplier", name):
		return frappe.get_doc("Supplier", name)
	supplier_group = (
		frappe.db.get_value("Supplier Group", {"supplier_group_name": "All Supplier Groups"}, "name")
		or frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		or "All Supplier Groups"
	)
	doc = frappe.get_doc(
		{"doctype": "Supplier", "supplier_name": name, "supplier_group": supplier_group}
	)
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_permissions = True
	return doc.insert()


def _balancing_account(company):
	acc = frappe.db.get_value(
		"Account", {"account_name": "Temporary Opening", "company": company, "is_group": 0}, "name"
	)
	if acc:
		return acc
	return frappe.db.get_value(
		"Account",
		{
			"company": company,
			"is_group": 0,
			"root_type": ("in", ["Expense", "Income"]),
		},
		"name",
	)


def _post_party_jv(company, party_account, party_type, party, debit, credit, posting_date=None):
	"""Post a balanced fixture JV: one party-linked row + one balancing temp-opening row.
	Tagged in user_remark so _reset_balances can find and cancel it.
	Returns the JE doc."""
	temp = _balancing_account(company)
	assert temp, f"No balancing account for {company}"
	jv = frappe.new_doc("Journal Entry")
	jv.posting_date = posting_date or nowdate()
	jv.company = company
	jv.voucher_type = "Journal Entry"
	jv.user_remark = f"{RECONCILE_TEST_REMARK_TAG} {party_type}:{party} {debit}/{credit}"
	jv.append(
		"accounts",
		{
			"account": party_account,
			"party_type": party_type,
			"party": party,
			"debit_in_account_currency": debit,
			"debit": debit,
			"credit_in_account_currency": credit,
			"credit": credit,
		},
	)
	jv.append(
		"accounts",
		{
			"account": temp,
			"debit_in_account_currency": credit,
			"debit": credit,
			"credit_in_account_currency": debit,
			"credit": debit,
		},
	)
	jv.flags.ignore_permissions = True
	jv.save()
	jv.submit()
	return jv


class TestCommonPartyReconciliation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _get_test_company().name
		from erpnext.accounts.party import get_party_account

		cls.customer = _ensure_customer("BNS QA Reconcile Customer").name
		cls.supplier = _ensure_supplier("BNS QA Reconcile Supplier").name
		cls.customer_account = get_party_account("Customer", cls.customer, cls.company)
		cls.supplier_account = get_party_account("Supplier", cls.supplier, cls.company)

	def _reset_balances(self):
		# Cancel fixture-tagged JVs + any system-generated JV that references
		# our test parties on their child table.
		fixture = frappe.get_all(
			"Journal Entry",
			filters={
				"company": self.company,
				"docstatus": 1,
				"user_remark": ("like", f"%{RECONCILE_TEST_REMARK_TAG}%"),
			},
			pluck="name",
		)
		related = frappe.db.sql(
			"""
			SELECT DISTINCT je.name
			FROM `tabJournal Entry` je
			INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
			WHERE je.company = %(company)s
			  AND je.docstatus = 1
			  AND (
			    (jea.party_type = 'Customer' AND jea.party = %(customer)s)
			    OR (jea.party_type = 'Supplier' AND jea.party = %(supplier)s)
			  )
			""",
			{"company": self.company, "customer": self.customer, "supplier": self.supplier},
			as_dict=False,
		)
		system_jvs = [r[0] for r in related]
		for name in set(fixture) | set(system_jvs):
			try:
				doc = frappe.get_doc("Journal Entry", name)
				doc.flags.ignore_permissions = True
				doc.cancel()
			except Exception:
				pass

	def setUp(self):
		self._reset_balances()

	def test_resolve_window_all_time(self):
		self.assertEqual(_resolve_window("All time", self.company), (None, None))

	def test_resolve_window_last_2_fy(self):
		start, end = _resolve_window("Last 2 Fiscal Years", self.company)
		self.assertIsNotNone(start)
		self.assertIsNotNone(end)
		self.assertLess(start, end)

	def test_resolve_window_unknown_label_falls_back(self):
		self.assertEqual(_resolve_window("Quarterly Widget", self.company), (None, None))

	def test_reconciliation_candidates_picks_up_nonzero_balances(self):
		# Post a 100 Dr fixture JV against the test customer — creates unreconciled balance.
		_post_party_jv(self.company, self.customer_account, "Customer", self.customer, 100, 0)
		candidates = get_reconciliation_candidates(self.company, scope="All Customers + All Suppliers")
		# Should include our customer.
		hits = [c for c in candidates if c["party_type"] == "Customer" and c["party"] == self.customer]
		self.assertEqual(len(hits), 1)
		self.assertAlmostEqual(hits[0]["signed_balance"], 100.0, places=2)

	def test_reconcile_single_party_noop_when_only_one_side(self):
		# Customer only has an invoice-shaped Dr balance, no offsetting Cr payment → skip.
		_post_party_jv(self.company, self.customer_account, "Customer", self.customer, 100, 0)
		result = reconcile_single_party(
			self.company, "Customer", self.customer, window="All time", include_advances=True
		)
		self.assertIn(result.get("skipped_reason"), (
			"no invoices or no payments to match",
			"allocate_entries produced zero rows",
		))

	def test_reconcile_all_parties_patched_scope_stays_on_test_company(self):
		# Even with scope "All Customers + All Suppliers", the test must not
		# reach real production parties. Monkey-patch _iter_parties_for_scope to
		# return just our two fixtures. Run should be a safe no-op on balances.
		with patch(
			"business_needed_solutions.bns_branch_accounting.common_party_reconciliation._iter_parties_for_scope",
			return_value=iter([("Customer", self.customer), ("Supplier", self.supplier)]),
		):
			result = reconcile_all_parties(
				self.company,
				window="All time",
				include_advances=True,
				scope="All Customers + All Suppliers",
			)
		self.assertEqual(result["company"], self.company)
		self.assertIsInstance(result["reconciled_parties"], list)
		self.assertEqual(result["errors"], [])
