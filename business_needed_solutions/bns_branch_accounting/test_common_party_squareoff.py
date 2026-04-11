# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Integration tests for Common Party GL Square-Off.

Uses the real DB (FrappeTestCase) so the feedback from past incidents around
mocked accounting tests diverging from production is respected.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate, nowdate

from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
	_schedule_is_due,
	check_linked_party_opposite_balance,
	compute_linked_party_net_positions,
	scheduled_squareoff_run,
	square_off_all_common_parties,
	square_off_linked_party,
)


SQUAREOFF_TEST_REMARK_TAG = "BNS_QA_SQUAREOFF_FIXTURE"


def _ensure_current_fiscal_year():
	"""FrappeTestCase pins test company to _Test Foreign Company which has no FY.
	Create a fiscal year covering today if none exists — idempotent."""
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
	"""Pick a dedicated _Test company first so we NEVER write fixture JVs to the
	production company on a shared dev site. Only falls back to the site default
	if no _Test* company has a full CoA — and even then it tags every JV with
	the fixture remark so cleanup can find them."""
	_ensure_current_fiscal_year()
	# Prefer erpnext fixture test companies (created by FrappeTestCase if missing).
	test_company_names = [
		"_Test Indian Registered Company",
		"_Test Indian Unregistered Company",
		"_Test Company",
		"_Test Foreign Company",
	]
	candidates = [c for c in test_company_names if frappe.db.exists("Company", c)]
	# Last resort: site default (will still work, but taint production CoA).
	preferred = frappe.db.get_single_value("Global Defaults", "default_company")
	if preferred and preferred not in candidates:
		candidates.append(preferred)
	for name in candidates:
		has_debtors = frappe.db.exists("Account", {"company": name, "account_type": "Receivable", "is_group": 0})
		has_creditors = frappe.db.exists("Account", {"company": name, "account_type": "Payable", "is_group": 0})
		if has_debtors and has_creditors:
			return frappe.get_doc("Company", name)
	raise RuntimeError("No Company with Debtors+Creditors accounts on this site.")


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


def _ensure_party_link(customer, supplier):
	existing = frappe.db.exists(
		"Party Link",
		{"primary_role": "Customer", "primary_party": customer, "secondary_role": "Supplier", "secondary_party": supplier},
	)
	if existing:
		return frappe.get_doc("Party Link", existing)
	return frappe.get_doc(
		{
			"doctype": "Party Link",
			"primary_role": "Customer",
			"primary_party": customer,
			"secondary_role": "Supplier",
			"secondary_party": supplier,
		}
	).insert(ignore_permissions=True)


def _pick_balancing_account(company):
	"""Pick a non-party, non-group expense/income account to balance fixture JVs."""
	acc = frappe.db.get_value(
		"Account", {"account_name": "Temporary Opening", "company": company, "is_group": 0}, "name"
	)
	if acc:
		return acc
	acc = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"is_group": 0,
			"root_type": ("in", ["Expense", "Income"]),
		},
		"name",
	)
	return acc


def _post_journal(company, account, party_type, party, debit, credit, posting_date=None):
	"""Post a balanced journal entry against a party account + a non-party balancing leg."""
	temp = _pick_balancing_account(company)
	if not temp:
		raise RuntimeError(f"No balancing account found for {company}")
	jv = frappe.new_doc("Journal Entry")
	jv.posting_date = posting_date or nowdate()
	jv.company = company
	jv.voucher_type = "Journal Entry"
	jv.user_remark = f"{SQUAREOFF_TEST_REMARK_TAG} {party_type}:{party} {debit}/{credit}"
	jv.append(
		"accounts",
		{
			"account": account,
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


class TestCommonPartySquareOff(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _get_test_company().name
		from erpnext.accounts.party import get_party_account

		cls.customer = _ensure_customer("BNS QA XYZ Customer").name
		cls.supplier = _ensure_supplier("BNS QA XYZ Supplier").name
		_ensure_party_link(cls.customer, cls.supplier)
		cls.customer_account = get_party_account("Customer", cls.customer, cls.company)
		cls.supplier_account = get_party_account("Supplier", cls.supplier, cls.company)
		if not cls.customer_account or not cls.supplier_account:
			raise RuntimeError(
				f"Could not resolve party accounts for test company {cls.company}; "
				"ensure default Debtors/Creditors accounts exist."
			)

	def _reset_balances(self):
		"""Cancel only fixture JVs this test class posted (tagged via user_remark)
		and any system-generated square-off JVs whose child accounts reference
		our two test parties. Filtering narrowly avoids clobbering unrelated data
		on the shared site."""
		fixture_jvs = frappe.get_all(
			"Journal Entry",
			filters={
				"company": self.company,
				"docstatus": 1,
				"user_remark": ("like", f"%{SQUAREOFF_TEST_REMARK_TAG}%"),
			},
			pluck="name",
		)
		# Find any system-generated JV on this test company whose child rows reference our parties.
		related = frappe.db.sql(
			"""
			SELECT DISTINCT je.name
			FROM `tabJournal Entry` je
			INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
			WHERE je.company = %(company)s
			  AND je.docstatus = 1
			  AND je.is_system_generated = 1
			  AND (
			    (jea.party_type = 'Customer' AND jea.party = %(customer)s)
			    OR (jea.party_type = 'Supplier' AND jea.party = %(supplier)s)
			  )
			""",
			{"company": self.company, "customer": self.customer, "supplier": self.supplier},
			as_dict=False,
		)
		system_jvs = [r[0] for r in related]
		for name in set(fixture_jvs) | set(system_jvs):
			try:
				doc = frappe.get_doc("Journal Entry", name)
				doc.flags.ignore_permissions = True
				doc.cancel()
			except Exception:
				pass

	def setUp(self):
		self._reset_balances()

	def _setup_matched_100(self):
		# Customer gets 100 Dr (open receivable), Supplier gets 100 Cr (open payable).
		_post_journal(self.company, self.customer_account, "Customer", self.customer, 100, 0)
		_post_journal(self.company, self.supplier_account, "Supplier", self.supplier, 0, 100)

	def _my_pair(self, pairs):
		"""Pick only the pair that involves our test customer + supplier."""
		for p in pairs:
			parties = {p.get("primary_party"), p.get("secondary_party")}
			if self.customer in parties and self.supplier in parties:
				return p
		return None

	def test_detects_crossed_pair(self):
		self._setup_matched_100()
		pairs = compute_linked_party_net_positions(self.company)
		p = self._my_pair(pairs)
		self.assertIsNotNone(p, "test pair not detected among crossed pairs")
		# Party Link primary/secondary order follows the Party Link doctype,
		# which our fixture creates as primary=Customer, secondary=Supplier.
		self.assertEqual(p["primary_party"], self.customer)
		self.assertEqual(p["secondary_party"], self.supplier)
		self.assertAlmostEqual(p["square_off_amount"], 100, places=2)
		self.assertGreater(p["primary_balance"], 0)
		self.assertLess(p["secondary_balance"], 0)

	def test_square_off_matched_amounts_to_zero(self):
		self._setup_matched_100()
		pairs = compute_linked_party_net_positions(self.company)
		p = self._my_pair(pairs)
		self.assertIsNotNone(p)
		jv = square_off_linked_party(p)
		self.assertEqual(jv.docstatus, 1)
		self.assertTrue(jv.is_system_generated)
		# After square off, our pair should no longer appear as crossed.
		self.assertIsNone(self._my_pair(compute_linked_party_net_positions(self.company)))

	def test_square_off_partial_leaves_residual(self):
		# Customer 60 Dr, Supplier 100 Cr → square off 60.
		_post_journal(self.company, self.customer_account, "Customer", self.customer, 60, 0)
		_post_journal(self.company, self.supplier_account, "Supplier", self.supplier, 0, 100)
		pairs = compute_linked_party_net_positions(self.company)
		p = self._my_pair(pairs)
		self.assertIsNotNone(p)
		self.assertEqual(p.get("kind"), "net")
		self.assertAlmostEqual(p["square_off_amount"], 60, places=2)
		square_off_linked_party(p)
		# Supplier should still have 40 Cr.
		from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
			_get_party_signed_balance,
		)

		residual = _get_party_signed_balance("Supplier", self.supplier, self.supplier_account, self.company)
		self.assertAlmostEqual(residual, -40, places=2)

	def test_consolidate_same_sign_cr_balances(self):
		# Both parties carry Cr balances (customer advance + supplier payable).
		# Classic detector skipped this. New detector classifies it as
		# "consolidate" and moves the secondary's 174 onto the primary side.
		# Party Link fixture: primary=Customer, secondary=Supplier.
		# Customer (primary) = Cr 569 via two JVs that net to Cr 569
		# Supplier (secondary) = Cr 174 via one JV
		_post_journal(self.company, self.customer_account, "Customer", self.customer, 0, 569)
		_post_journal(self.company, self.supplier_account, "Supplier", self.supplier, 0, 174)

		from business_needed_solutions.bns_branch_accounting.common_party_squareoff import (
			_get_party_signed_balance,
		)

		pair = self._my_pair(compute_linked_party_net_positions(self.company))
		self.assertIsNotNone(pair, "consolidate pair should be detected")
		self.assertEqual(pair.get("kind"), "consolidate")
		self.assertAlmostEqual(pair["square_off_amount"], 174, places=2)

		jv = square_off_linked_party(pair)
		self.assertEqual(jv.docstatus, 1)

		# Secondary (supplier) must be zero after the consolidation.
		sec_after = _get_party_signed_balance(
			"Supplier", self.supplier, self.supplier_account, self.company
		)
		self.assertAlmostEqual(sec_after, 0, places=2)
		# Primary (customer) must be Cr (569 + 174) = -743 after absorbing.
		pri_after = _get_party_signed_balance(
			"Customer", self.customer, self.customer_account, self.company
		)
		self.assertAlmostEqual(pri_after, -743, places=2)
		# The pair should no longer be a candidate (secondary = 0).
		self.assertIsNone(self._my_pair(compute_linked_party_net_positions(self.company)))

	def test_batch_runner_returns_summary(self):
		self._setup_matched_100()
		# Only square off our specific pair — avoid touching unrelated real data.
		pairs = compute_linked_party_net_positions(self.company)
		my = self._my_pair(pairs)
		self.assertIsNotNone(my)
		result = square_off_all_common_parties(self.company, pairs=[my])
		self.assertEqual(len(result["posted"]), 1)
		self.assertEqual(len(result["errors"]), 0)

	def test_no_crossed_pair_when_aligned(self):
		# Only Customer side has balance — our pair must not be crossed.
		_post_journal(self.company, self.customer_account, "Customer", self.customer, 100, 0)
		self.assertIsNone(self._my_pair(compute_linked_party_net_positions(self.company)))

	def test_warning_helper_gated_by_setting(self):
		self._setup_matched_100()
		frappe.db.set_single_value("BNS Settings", "common_party_warning_on_wrong_side", 1)
		res = check_linked_party_opposite_balance("Customer", self.customer, self.company)
		self.assertTrue(res["has_crossed"])
		self.assertAlmostEqual(res["square_off_amount"], 100, places=2)
		frappe.db.set_single_value("BNS Settings", "common_party_warning_on_wrong_side", 0)
		res2 = check_linked_party_opposite_balance("Customer", self.customer, self.company)
		self.assertFalse(res2["has_crossed"])

	def test_historical_backfill_posting_date(self):
		# Post balances, then backfill as of an earlier cutoff — JV must use cutoff date.
		past = add_days(getdate(nowdate()), -30)
		_post_journal(self.company, self.customer_account, "Customer", self.customer, 100, 0, posting_date=past)
		_post_journal(self.company, self.supplier_account, "Supplier", self.supplier, 0, 100, posting_date=past)
		pairs = compute_linked_party_net_positions(self.company, as_of_date=past)
		my = self._my_pair(pairs)
		self.assertIsNotNone(my)
		result = square_off_all_common_parties(
			self.company, pairs=[my], posting_date=past
		)
		self.assertEqual(len(result["posted"]), 1)
		jv_name = result["posted"][0]["journal_entry"]
		jv = frappe.get_doc("Journal Entry", jv_name)
		self.assertEqual(str(jv.posting_date), str(past))

	def test_schedule_is_due_logic(self):
		today = getdate(nowdate())
		# Disabled never runs.
		self.assertFalse(_schedule_is_due("Disabled", None, today))
		self.assertFalse(_schedule_is_due("", today, today))
		# Never-run schedules run immediately the first time.
		self.assertTrue(_schedule_is_due("Weekly", None, today))
		self.assertTrue(_schedule_is_due("Monthly", None, today))
		self.assertTrue(_schedule_is_due("Quarterly", None, today))
		self.assertTrue(_schedule_is_due("Yearly", None, today))
		# Interval elapsed → due.
		self.assertTrue(_schedule_is_due("Weekly", add_days(today, -7), today))
		self.assertFalse(_schedule_is_due("Weekly", add_days(today, -6), today))
		self.assertTrue(_schedule_is_due("Monthly", add_days(today, -28), today))
		self.assertFalse(_schedule_is_due("Monthly", add_days(today, -27), today))
		self.assertTrue(_schedule_is_due("Quarterly", add_days(today, -90), today))
		self.assertFalse(_schedule_is_due("Quarterly", add_days(today, -89), today))

	def _run_scheduler_scoped(self):
		# CRITICAL: this test site's default company is also the production one
		# with real Party Link data. Two layers of isolation:
		#  1. Restrict the scheduler's company list to our test company.
		#  2. Restrict the Party Link scan to ONLY the link between our
		#     fixture customer and supplier, so compute never sees the real
		#     linked pairs on the shared site.
		fake_link = frappe._dict(
			name="BNS_QA_FAKE_PARTY_LINK",
			primary_role="Customer",
			primary_party=self.customer,
			secondary_role="Supplier",
			secondary_party=self.supplier,
		)
		with patch(
			"business_needed_solutions.bns_branch_accounting.common_party_squareoff._list_companies_for_schedule",
			return_value=[self.company],
		), patch(
			"business_needed_solutions.bns_branch_accounting.common_party_squareoff._active_party_links",
			return_value=[fake_link],
		):
			scheduled_squareoff_run()

	def test_scheduled_run_disabled_is_noop(self):
		self._setup_matched_100()
		frappe.db.set_single_value("BNS Settings", "common_party_squareoff_schedule", "Disabled")
		frappe.db.set_single_value("BNS Settings", "common_party_squareoff_last_run_on", None)
		self._run_scheduler_scoped()
		# Pair still crossed — scheduler must not have posted anything.
		self.assertIsNotNone(self._my_pair(compute_linked_party_net_positions(self.company)))

	def test_scheduled_run_monthly_posts_when_due(self):
		self._setup_matched_100()
		frappe.db.set_single_value("BNS Settings", "common_party_squareoff_schedule", "Monthly")
		frappe.db.set_single_value("BNS Settings", "common_party_squareoff_last_run_on", None)
		self._run_scheduler_scoped()
		# Our pair should be squared off by the scheduler run.
		self.assertIsNone(self._my_pair(compute_linked_party_net_positions(self.company)))
		# last_run_on stamp should be set.
		stamp = frappe.db.get_single_value("BNS Settings", "common_party_squareoff_last_run_on")
		self.assertIsNotNone(stamp)

	def test_scheduled_run_respects_interval(self):
		self._setup_matched_100()
		frappe.db.set_single_value("BNS Settings", "common_party_squareoff_schedule", "Monthly")
		# Pretend it just ran yesterday — should NOT run again under Monthly.
		frappe.db.set_single_value(
			"BNS Settings", "common_party_squareoff_last_run_on", add_days(getdate(nowdate()), -1)
		)
		self._run_scheduler_scoped()
		# Pair still crossed.
		self.assertIsNotNone(self._my_pair(compute_linked_party_net_positions(self.company)))
