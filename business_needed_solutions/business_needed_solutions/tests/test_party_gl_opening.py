"""Party GL: Opening and Closing rows show one side only (Tally style).

Each report test runs Party GL twice on the same data: as it is now, and with the
netting switched off (the output before this change). Every running balance must
match, transaction and Total rows must not change, and each Opening/Closing row
must carry the same net on one side only.

Uses ERPNext's _Test Company records; everything is rolled back after each test.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from business_needed_solutions.business_needed_solutions.report.party_gl import party_gl

COMPANY = "_Test Company"
FROM, TO = "2026-04-01", "2026-06-30"
BEFORE = "2026-02-10"  # inside the books, before the period
TDS_CATEGORY = "Payments Under Specified Agreement - Company"  # 10%, no threshold
PAIRS = (
	("debit", "credit"),
	("debit_in_account_currency", "credit_in_account_currency"),
	("debit_in_transaction_currency", "credit_in_transaction_currency"),
)


def _net(row, dr="debit", cr="credit"):
	return flt(row.get(dr)) - flt(row.get(cr))


def _label(row):
	return str(row.get("account") or "") if not row.get("posting_date") else ""


class TestPartyGLOpening(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.db.exists("Company", COMPANY):
			raise cls.skipTest(cls, "needs ERPNext test records (_Test Company)")

	def setUp(self):
		frappe.db.savepoint("bns_party_gl_opening")

	def tearDown(self):
		frappe.db.rollback(save_point="bns_party_gl_opening")

	# ------------------------------------------------------------------ fixtures

	def _customer(self, currency="INR"):
		return frappe.get_doc({
			"doctype": "Customer", "customer_name": f"_Test PGL {frappe.generate_hash(length=8)}",
			"customer_group": "_Test Customer Group", "territory": "_Test Territory",
			"default_currency": currency,
		}).insert().name

	def _je(self, date, party, debit=0, credit=0, party_type="Customer", account="Debtors - _TC",
			exchange_rate=1):
		"""Post `debit`/`credit` (in the account's currency) to the party, against the bank."""
		base = flt((debit or credit) * exchange_rate, 2)
		je = frappe.get_doc({
			"doctype": "Journal Entry", "company": COMPANY, "posting_date": date,
			"multi_currency": 1 if exchange_rate != 1 else 0,
			"accounts": [
				{"account": account, "party_type": party_type, "party": party,
				 "cost_center": "_Test Cost Center - _TC", "exchange_rate": exchange_rate,
				 "debit_in_account_currency": debit, "credit_in_account_currency": credit},
				{"account": "_Test Bank - _TC", "cost_center": "_Test Cost Center - _TC",
				 "debit_in_account_currency": base if credit else 0,
				 "credit_in_account_currency": base if debit else 0},
			],
		})
		je.insert()
		je.submit()
		return je.name

	# ------------------------------------------------------------------ running the report

	def _run(self, **filters):
		args = {"company": COMPANY, "from_date": FROM, "to_date": TO,
				"group_by": "Group by Voucher (Consolidated)", "include_dimensions": 1,
				"show_tds_breakup": 1}
		args.update(filters)
		args["party"] = list(args.get("party") or [])  # execute() rewrites it
		return party_gl.execute(frappe._dict(args))[1]

	def _run_checked(self, **filters):
		"""Run with and without the netting; check the new rows against the old ones."""
		new = self._run(**filters)
		with patch.object(party_gl, "net_opening_and_closing", side_effect=lambda data: data):
			old = self._run(**filters)

		self.assertEqual(len(new), len(old))
		for n, o in zip(new, old):
			self.assertEqual(n.get("balance"), o.get("balance"), f"balance moved on {n}")
			if n.get("is_opening_or_closing"):
				for dr, cr in PAIRS:
					if o.get(dr) is None and o.get(cr) is None:
						self.assertIsNone(n.get(dr))
						self.assertIsNone(n.get(cr))
						continue
					self.assertAlmostEqual(_net(n, dr, cr), _net(o, dr, cr), places=2)
					self.assertGreaterEqual(n[dr], 0)
					self.assertGreaterEqual(n[cr], 0)
					self.assertFalse(n[dr] and n[cr], f"two-sided {dr}/{cr}: {n}")
			else:
				for dr, cr in PAIRS:
					self.assertEqual((n.get(dr), n.get(cr)), (o.get(dr), o.get(cr)), f"row changed: {n}")
		self._assert_closing_adds_up(new)
		return new

	def _assert_closing_adds_up(self, rows):
		"""Closing = net Opening + period (Dr - Cr), for the report and for each group."""
		opening, closing = rows[0], rows[-1]
		self.assertIn("Opening", _label(opening))
		self.assertIn("Closing", _label(closing))
		period = sum(_net(r) for r in rows if r.get("posting_date"))
		self.assertAlmostEqual(_net(closing), _net(opening) + period, places=2)

		group = None  # [opening net, period net]
		for r in rows[1:-1]:
			label = _label(r)
			if "Opening" in label:
				group = [_net(r), 0.0]
			elif r.get("posting_date") and group:
				group[1] += _net(r)
			elif "Total" in label and group:
				self.assertAlmostEqual(_net(r), group[1], places=2)
			elif "Closing" in label and group:
				self.assertAlmostEqual(_net(r), group[0] + group[1], places=2)
				group = None

	def _side(self, row):
		return (flt(row.debit, 2), flt(row.credit, 2))

	# ------------------------------------------------------------------ cases

	def test_opening_mostly_debit(self):
		c = self._customer()
		self._je(BEFORE, c, debit=1000)
		self._je(BEFORE, c, credit=400)
		self._je("2026-04-10", c, debit=300)
		self._je("2026-05-10", c, credit=100)

		rows = self._run_checked(party=[c])
		self.assertEqual(self._side(rows[0]), (600, 0))
		self.assertEqual(self._side(rows[-1]), (800, 0))

	def test_opening_mostly_credit(self):
		c = self._customer()
		self._je(BEFORE, c, debit=200)
		self._je(BEFORE, c, credit=900)
		self._je("2026-04-10", c, debit=500)

		rows = self._run_checked(party=[c])
		self.assertEqual(self._side(rows[0]), (0, 700))
		self.assertEqual(self._side(rows[-1]), (0, 200))

	def test_opening_exactly_settled_shows_zero_both_sides(self):
		c = self._customer()
		self._je(BEFORE, c, debit=500)
		self._je(BEFORE, c, credit=500)
		self._je("2026-04-10", c, debit=250)

		rows = self._run_checked(party=[c])
		self.assertEqual(self._side(rows[0]), (0, 0))
		self.assertEqual(self._side(rows[-1]), (250, 0))

	def test_no_rows_before_period(self):
		c = self._customer()
		self._je("2026-04-10", c, debit=100)
		self._je("2026-05-10", c, credit=40)

		rows = self._run_checked(party=[c])
		# 0.0, not None, so the screen and PDF print 0.00 rather than a blank.
		self.assertEqual((rows[0].debit, rows[0].credit), (0.0, 0.0))
		self.assertEqual(self._side(rows[-1]), (60, 0))

	def test_group_by_party_one_debit_one_credit(self):
		dr_party, cr_party = self._customer(), self._customer()
		self._je(BEFORE, dr_party, debit=1000)
		self._je(BEFORE, dr_party, credit=100)
		self._je(BEFORE, cr_party, debit=100)
		self._je(BEFORE, cr_party, credit=600)
		for party in (dr_party, cr_party):
			self._je("2026-04-10", party, debit=50)
			self._je("2026-05-10", party, credit=20)

		rows = self._run_checked(party=[dr_party, cr_party], group_by="Group by Party")
		self.assertEqual(self._side(rows[0]), (400, 0))  # 900 Dr + 500 Cr
		self.assertEqual(self._side(rows[-1]), (460, 0))

		blocks = [r for r in rows[1:-1] if _label(r)]
		labels = [_label(r).strip("'") for r in blocks]
		self.assertEqual(labels, ["Opening", "Total", "Closing"] * 2)
		first_party = [r.party for r in rows if r.get("posting_date")][0]
		expected = {dr_party: [(900, 0), (50, 20), (930, 0)], cr_party: [(0, 500), (50, 20), (0, 470)]}
		self.assertEqual([self._side(r) for r in blocks[:3]], expected[first_party])
		other = cr_party if first_party == dr_party else dr_party
		self.assertEqual([self._side(r) for r in blocks[3:]], expected[other])

	def test_account_currency_differs_from_company_currency(self):
		c = self._customer(currency="USD")
		acc = "_Test Receivable USD - _TC"
		self._je(BEFORE, c, debit=1000, account=acc, exchange_rate=80)  # 80,000 INR
		self._je(BEFORE, c, credit=300, account=acc, exchange_rate=82)  # 24,600 INR
		self._je("2026-04-10", c, debit=100, account=acc, exchange_rate=83)  # 8,300 INR

		rows = self._run_checked(party=[c])
		self.assertEqual(self._side(rows[0]), (55400, 0))
		self.assertEqual((rows[0].debit_in_account_currency, rows[0].credit_in_account_currency), (700, 0))
		self.assertEqual(self._side(rows[-1]), (63700, 0))

		rows = self._run_checked(party=[c], show_in_account_currency=1)
		self.assertEqual(rows[0].account_currency, "USD")
		self.assertEqual(self._side(rows[0]), (700, 0))
		self.assertEqual(self._side(rows[-1]), (800, 0))

	def test_tds_split_invoice_in_period(self):
		if not frappe.db.exists("Tax Withholding Category", TDS_CATEGORY):
			self.skipTest(f"needs the {TDS_CATEGORY} TDS category (India Compliance)")
		supplier = frappe.get_doc({
			"doctype": "Supplier", "supplier_name": f"_Test PGL TDS {frappe.generate_hash(length=8)}",
			"supplier_group": "All Supplier Groups", "tax_withholding_category": TDS_CATEGORY,
			"pan": "AAACP1234C",
		}).insert().name
		self._je(BEFORE, supplier, credit=50000, party_type="Supplier", account="Creditors - _TC")
		self._je(BEFORE, supplier, debit=20000, party_type="Supplier", account="Creditors - _TC")

		# Built by hand: ERPNext's make_purchase_invoice import commits its test bootstrap data.
		pi = frappe.get_doc({
			"doctype": "Purchase Invoice", "company": COMPANY, "supplier": supplier,
			"posting_date": "2026-05-10", "set_posting_time": 1, "credit_to": "Creditors - _TC",
			"currency": "INR", "conversion_rate": 1, "apply_tds": 1,
			"items": [{"item_code": "_Test Non Stock Item", "qty": 1, "rate": 10000,
					   "expense_account": "_Test Account Cost for Goods Sold - _TC",
					   "cost_center": "_Test Cost Center - _TC"}],
		})
		if pi.meta.has_field("tax_withholding_category"):
			pi.tax_withholding_category = TDS_CATEGORY
		pi.insert()
		pi.submit()
		self.assertEqual(sum(t.base_tax_amount for t in pi.taxes if t.get("is_tax_withholding_account")), 1000)

		# Net values on merges the TDS into the invoice line first, so the split
		# grosses it up and bumps the Closing columns: the case most likely to break.
		for net_values in (0, 1):
			rows = self._run_checked(party=[supplier], show_net_values_in_party_account=net_values)
			tds_rows = [r for r in rows if r.get("is_tds_row")]
			self.assertEqual(len(tds_rows), 1)
			self.assertEqual(self._side(tds_rows[0]), (1000, 0))
			self.assertEqual(self._side(rows[0]), (0, 30000))
			self.assertEqual(self._side(rows[-1]), (0, 39000))  # 30,000 + 10,000 - 1,000

	def test_net_values_filter_on_and_off(self):
		c = self._customer()
		self._je(BEFORE, c, debit=1000)
		self._je(BEFORE, c, credit=400)
		# One voucher with a debit and a credit line for the party: net values merges them.
		je = frappe.get_doc({
			"doctype": "Journal Entry", "company": COMPANY, "posting_date": "2026-04-10",
			"accounts": [
				{"account": "Debtors - _TC", "party_type": "Customer", "party": c,
				 "cost_center": "_Test Cost Center - _TC", "debit_in_account_currency": 300},
				{"account": "Debtors - _TC", "party_type": "Customer", "party": c,
				 "cost_center": "_Test Cost Center - _TC", "credit_in_account_currency": 50},
				{"account": "_Test Bank - _TC", "cost_center": "_Test Cost Center - _TC",
				 "credit_in_account_currency": 250},
			],
		}).insert()
		je.submit()

		results = {}
		for net_values in (0, 1):
			rows = self._run_checked(party=[c], show_net_values_in_party_account=net_values)
			line = next(r for r in rows if r.get("voucher_no") == je.name)
			results[net_values] = (self._side(rows[0]), self._side(rows[-1]), rows[-1].balance)
			# The filter still nets the voucher line itself; the new rule leaves that alone.
			self.assertEqual(self._side(line), (250, 0) if net_values else (300, 50))
		self.assertEqual(results[0], results[1])
		self.assertEqual(results[0][:2], ((600, 0), (850, 0)))

	def test_rule_on_bare_rows(self):
		rows = [
			frappe._dict(account="'Opening'", is_opening_or_closing=1, debit=100.004, credit=100,
						 debit_in_account_currency=5, credit_in_account_currency=8,
						 debit_in_transaction_currency=7, credit_in_transaction_currency=2),
			frappe._dict(account="'Total'", debit=40, credit=10),
			frappe._dict(account="'Closing'", is_opening_or_closing=1, debit=30, credit=0,
						 debit_in_account_currency=None, credit_in_account_currency=None),
		]
		party_gl.net_opening_and_closing(rows)
		opening, total, closing = rows
		self.assertEqual((opening.debit, opening.credit), (0.0, 0.0))  # within currency precision
		self.assertEqual((opening.debit_in_account_currency, opening.credit_in_account_currency), (0.0, 3))
		self.assertEqual(
			(opening.debit_in_transaction_currency, opening.credit_in_transaction_currency), (5, 0.0)
		)
		self.assertEqual((total.debit, total.credit), (40, 10))  # Total stays gross
		self.assertEqual((closing.debit, closing.credit), (30, 0.0))
		self.assertIsNone(closing.debit_in_account_currency)
