"""TDS on submitted Purchase Invoices, ERPNext v16 (overrides/tds_backfill_v16.py).

The yardstick is ERPNext itself: a supplier whose invoices were submitted with TDS from
the start is what a fixed supplier must end up as. Cases build the same invoices twice,
once natively and once without TDS, fix the second with the tool, and compare TDS rows,
Tax Withholding Entries and the ledger. Rolls everything back at the end.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate

from business_needed_solutions.business_needed_solutions.overrides import tds_backfill as tds
from business_needed_solutions.business_needed_solutions.overrides import tds_backfill_v16 as v16

COMPANY = "_Test BNS TDS16 Co"
ABBR = "_TB16"
CAT_C = "_Test BNS16 194C"
CAT_J = "_Test BNS16 194J"
CAT_Q = "_Test BNS16 194Q"
ITEM = "_Test BNS16 Item"
ITEM_J = "_Test BNS16 Prof Item"
ITEM_B = "_Test BNS16 Item B"
PANS = iter(f"AAAPB{n:04d}C" for n in range(1000, 9999))


def _acc(name):
	return f"{name} - {ABBR}"


class TestTDSBackfillV16(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not v16.supported():
			raise cls.skipTest(cls, "ERPNext without Tax Withholding Entries (v15)")
		frappe.set_user("Administrator")
		cls._setup_company()
		cls._setup_categories()
		settings = frappe.get_single("BNS Settings")
		settings.enable_tds_category_fixables = 1
		settings.tds_filed_upto = None
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.flags.pop("_bns_tds_backfill_roles", None)
		cls.fy_start, cls.fy_end = tds._fiscal_year(COMPANY)

	def setUp(self):
		frappe.db.savepoint("bns_tds16_test")

	def tearDown(self):
		frappe.db.rollback(save_point="bns_tds16_test")
		frappe.db.set_single_value("BNS Settings", "tds_filed_upto", None)

	# ------------------------------------------------------------------ fixtures

	@classmethod
	def _setup_company(cls):
		if not frappe.db.exists("Company", COMPANY):
			frappe.get_doc({
				"doctype": "Company", "company_name": COMPANY, "abbr": ABBR, "default_currency": "INR",
				"country": "India", "create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard", "pan": "AAACB1234Z",
			}).insert()
		from erpnext.accounts.utils import get_fiscal_year

		try:
			get_fiscal_year(frappe.utils.today(), company=COMPANY)
		except Exception:
			fy = frappe.get_doc("Fiscal Year", get_fiscal_year(frappe.utils.today())[0])
			fy.append("companies", {"company": COMPANY})
			fy.save()
			frappe.cache.delete_value("fiscal_years")
		for name in ("TDS 194C", "TDS 194J", "TDS 194Q"):
			if not frappe.db.exists("Account", _acc(name)):
				frappe.get_doc({"doctype": "Account", "account_name": name, "company": COMPANY,
								"parent_account": _acc("Duties and Taxes"), "account_type": "Tax"}).insert()
		for code in (ITEM, ITEM_J, ITEM_B):
			if not frappe.db.exists("Item", code):
				frappe.get_doc({"doctype": "Item", "item_code": code, "item_group": "Services", "is_stock_item": 0,
								"stock_uom": "Nos", "gst_hsn_code": "999900"}).insert()

	@classmethod
	def _setup_categories(cls):
		fy_start, fy_end = tds._fiscal_year(COMPANY)
		for name, account, rate, single, cumulative, excess in (
			(CAT_C, "TDS 194C", 1, 30000, 100000, 0),
			(CAT_J, "TDS 194J", 10, 30000, 0, 0),
			(CAT_Q, "TDS 194Q", 0.1, 0, 5000000, 1),
		):
			if frappe.db.exists("Tax Withholding Category", name):
				frappe.delete_doc("Tax Withholding Category", name, force=True)
			frappe.get_doc({
				"doctype": "Tax Withholding Category", "name": name, "category_name": name,
				"tax_on_excess_amount": excess, "round_off_tax_amount": 1,
				"rates": [{"from_date": fy_start, "to_date": fy_end, "tax_withholding_rate": rate,
						   "single_threshold": single, "cumulative_threshold": cumulative}],
				"accounts": [{"company": COMPANY, "account": _acc(account)}],
			}).insert()
		frappe.db.set_value("Item", ITEM_J, "purchase_tax_withholding_category", CAT_J)

	def _supplier(self, category=None):
		s = frappe.get_doc({"doctype": "Supplier", "supplier_name": f"_T16 {frappe.generate_hash(length=6)}",
							"supplier_group": "All Supplier Groups", "pan": next(PANS), "default_currency": "INR",
							"tax_withholding_category": category}).insert()
		return s.name

	def _date(self, month, day):
		year = self.fy_start.year if month >= 4 else self.fy_start.year + 1
		return getdate(f"{year}-{month:02d}-{day:02d}")

	def _pi(self, supplier, date, lines, tds=True):
		"""lines: [(item, amount)]. tds=False submits with TDS off and no row category."""
		pi = frappe.new_doc("Purchase Invoice")
		pi.update({
			"company": COMPANY, "supplier": supplier, "posting_date": date, "set_posting_time": 1,
			"due_date": date, "bill_date": date, "bill_no": frappe.generate_hash(length=8),
			"credit_to": _acc("Creditors"), "currency": "INR", "conversion_rate": 1, "update_stock": 0,
			"apply_tds": 1 if tds else 0,
		})
		for item, amount in lines:
			pi.append("items", {"item_code": item, "qty": 1, "rate": amount,
								"expense_account": _acc("Cost of Goods Sold"), "cost_center": _acc("Main")})
		pi.insert()
		if not tds:
			pi.apply_tds = 0
			for row in pi.items:
				row.tax_withholding_category = None
			pi.save()
		pi.submit()
		return pi.name

	def _year(self, supplier, schedule, tds=True):
		return [self._pi(supplier, self._date(m, d), lines, tds) for (m, d, lines) in schedule]

	def _state(self, name):
		"""What an invoice carries."""
		tds_rows = frappe.get_all("Purchase Taxes and Charges",
								  filters={"parent": name, "is_tax_withholding_account": 1},
								  fields=["account_head", "base_tax_amount_after_discount_amount as amount"],
								  order_by="account_head")
		gl = frappe.db.sql("""SELECT account, SUM(debit) - SUM(credit) FROM `tabGL Entry`
			WHERE voucher_no = %s AND is_cancelled = 0 GROUP BY account ORDER BY account""", name)
		doc = frappe.db.get_value("Purchase Invoice", name, ["grand_total", "outstanding_amount", "apply_tds"],
								  as_dict=True)
		return {"tds": [(r.account_head, flt(r.amount, 2)) for r in tds_rows],
				"gl": [(a, flt(v, 2)) for a, v in gl], "grand_total": flt(doc.grand_total, 2),
				"outstanding": flt(doc.outstanding_amount, 2), "apply_tds": doc.apply_tds}

	def _entries(self, names):
		"""The year's entries, invoice names replaced by their position."""
		pos = {n: i for i, n in enumerate(names)}
		out = []
		for n in names:
			for e in frappe.get_all("Tax Withholding Entry", filters={"parent": n, "docstatus": 1}, fields=["*"]):
				out.append((pos[n], e.tax_withholding_category, e.status, flt(e.taxable_amount, 2),
							flt(e.withholding_amount, 2), pos.get(e.taxable_name, e.taxable_name or ""),
							pos.get(e.withholding_name, e.withholding_name or ""), e.under_withheld_reason or ""))
		return sorted(out)

	def _apply(self, supplier, mode="keep", overrides=None, allow_filed=0):
		spec = {"supplier": supplier, "company": COMPANY, "date": str(self.fy_start), "mode": mode,
				"overrides": overrides or {}}
		plans = tds._plans_from_specs([spec], allow_filed)
		return plans[0], tds._apply_specs([spec], tds._plan_token(plans), allow_filed)

	def assertSameYear(self, native, fixed):
		for a, b in zip(native, fixed):
			sa, sb = self._state(a), self._state(b)
			self.assertEqual(sa["tds"], sb["tds"], f"TDS rows differ: {a} vs {b}")
			self.assertEqual(sa["grand_total"], sb["grand_total"], f"{a} vs {b}")
			self.assertEqual(sa["outstanding"], sb["outstanding"], f"{a} vs {b}")
			self.assertEqual(sa["gl"], sb["gl"], f"ledger differs: {a} vs {b}")
		self.assertEqual(self._entries(native), self._entries(fixed))

	# ------------------------------------------------------------------ cases

	SCHEDULE = [
		(4, 5, [(ITEM, 20000)]), (4, 20, [(ITEM, 25000)]), (5, 2, [(ITEM, 18000)]),
		(5, 20, [(ITEM, 45000)]), (6, 10, [(ITEM, 12000)]), (7, 1, [(ITEM, 8000)]),
	]

	def test_model_is_v16(self):
		self.assertEqual(tds._model(), "v16")
		self.assertTrue(tds.can_backfill_tds())

	def test_keep_on_a_native_year_changes_nothing(self):
		s = self._supplier(CAT_C)
		self._year(s, self.SCHEDULE)
		plan = tds.plan_supplier_year(s, COMPANY, date=self.fy_start)
		self.assertFalse(plan.problems, plan.problems)
		self.assertEqual([d.action for d in plan.docs], ["none"] * len(self.SCHEDULE))

	def test_backfill_matches_native(self):
		native = self._supplier(CAT_C)
		fixed = self._supplier(None)
		a = self._year(native, self.SCHEDULE)
		b = self._year(fixed, self.SCHEDULE, tds=False)
		frappe.db.set_value("Supplier", fixed, "tax_withholding_category", CAT_C)
		_plan, summary = self._apply(fixed, mode="supplier")
		self.assertFalse(summary["error_count"], summary)
		self.assertGreater(summary["changed"], 0)
		self.assertSameYear(a, b)
		again = tds.plan_supplier_year(fixed, COMPANY, date=self.fy_start)
		self.assertEqual({d.action for d in again.docs}, {"none"})

	def test_whole_year_defaults(self):
		native = self._supplier(CAT_C)
		fixed = self._supplier(None)
		a = self._year(native, self.SCHEDULE)
		b = self._year(fixed, self.SCHEDULE, tds=False)
		frappe.db.set_value("Supplier", fixed, "tax_withholding_category", CAT_C)
		specs = [s for s in tds._year_specs(COMPANY, None, "defaults") if s["supplier"] in (native, fixed)]
		self.assertEqual(len(specs), 2)
		plans = tds._plans_from_specs(specs, 0)
		summary = tds._apply_specs(specs, tds._plan_token(plans), 0)
		self.assertFalse(summary["error_count"], summary)
		self.assertSameYear(a, b)

	def test_remove_tds_matches_native_without(self):
		plain = self._supplier(None)
		fixed = self._supplier(CAT_C)
		a = self._year(plain, self.SCHEDULE, tds=False)
		b = self._year(fixed, self.SCHEDULE)
		frappe.db.set_value("Supplier", fixed, "tax_withholding_category", None)
		_plan, summary = self._apply(fixed, mode="supplier")
		self.assertFalse(summary["error_count"], summary)
		for x, y in zip(a, b):
			self.assertEqual(self._state(x)["tds"], self._state(y)["tds"])
			self.assertEqual(self._state(x)["gl"], self._state(y)["gl"])
		self.assertEqual([e for e in self._entries(b) if e[4]], [])  # nothing withheld

	def test_item_level_category_wins_over_supplier(self):
		schedule = [(4, 5, [(ITEM, 20000), (ITEM_J, 40000)]), (5, 5, [(ITEM, 90000), (ITEM_J, 5000)])]
		native = self._supplier(CAT_C)
		fixed = self._supplier(None)
		a = self._year(native, schedule)
		b = self._year(fixed, schedule, tds=False)
		self.assertIn(_acc("TDS 194J"), [x[0] for x in self._state(a[0])["tds"]])  # natively, on its own account
		frappe.db.set_value("Supplier", fixed, "tax_withholding_category", CAT_C)
		_plan, summary = self._apply(fixed, mode="supplier")
		self.assertFalse(summary["error_count"], summary)
		self.assertSameYear(a, b)
		cats = frappe.get_all("Purchase Invoice Item", filters={"parent": b[0]},
							  fields=["item_code", "tax_withholding_category"], order_by="idx")
		self.assertEqual([(c.item_code, c.tax_withholding_category) for c in cats], [(ITEM, CAT_C), (ITEM_J, CAT_J)])

	def test_one_invoice_row_override(self):
		s = self._supplier(CAT_C)
		names = self._year(s, [(4, 5, [(ITEM, 50000), (ITEM_B, 10000)])])
		rows = frappe.get_all("Purchase Invoice Item", filters={"parent": names[0]}, pluck="name", order_by="idx")
		preview = tds.preview_tds_category_change(names[0], rows={rows[1]: CAT_Q})
		spec = tds._invoice_spec(names[0], None, {rows[1]: CAT_Q})
		self.assertEqual(spec["overrides"][names[0]], {rows[1]: CAT_Q})
		summary = tds._apply_specs([spec], preview["token"])
		self.assertFalse(summary["error_count"], summary)
		self.assertEqual(frappe.db.get_value("Purchase Invoice Item", rows[1], "tax_withholding_category"), CAT_Q)
		# 50000 alone crosses 194C's single threshold (1% = 500); 194Q stays under its threshold
		self.assertEqual(self._state(names[0])["tds"], [(_acc("TDS 194C"), 500.0)])

	def test_filed_quarter_is_kept(self):
		fixed = self._supplier(None)
		b = self._year(fixed, self.SCHEDULE, tds=False)
		frappe.db.set_value("Supplier", fixed, "tax_withholding_category", CAT_C)
		frappe.db.set_single_value("BNS Settings", "tds_filed_upto", self._date(5, 31))
		plan, summary = self._apply(fixed, mode="supplier")
		self.assertFalse(summary["error_count"], summary)
		for d in plan.docs:
			if d.posting_date <= self._date(5, 31) and d.action == "ledger":
				self.assertTrue(d.blocked, (d.name, str(d.posting_date), d.current_tds, d.target_tds,
											str(tds._filed_upto()), d.get("keep_reason")))
		for name in b[:4]:
			self.assertEqual(self._state(name)["tds"], [])  # filed: left as they were
		total_tds = sum(v for n in b for _a, v in self._state(n)["tds"])
		self.assertLessEqual(total_tds, flt(sum(x[1] for m in self.SCHEDULE for x in m[2]) / 100, 2) + 1)

	def test_debit_note_category_follows_original(self):
		s = self._supplier(None)
		names = self._year(s, [(4, 5, [(ITEM, 50000)])], tds=False)
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		dn = make_debit_note(names[0])
		dn.posting_date = self._date(4, 10)
		dn.set_posting_time = 1
		dn.insert()
		dn.submit()
		spec = tds._invoice_spec(dn.name, CAT_C)
		self.assertEqual(list(spec["overrides"]), [names[0]])

	def test_outside_entries_refuse_the_year(self):
		s = self._supplier(CAT_C)
		names = self._year(s, [(4, 5, [(ITEM, 50000)])])
		row = frappe.get_all("Tax Withholding Entry", filters={"parent": names[0]}, fields=["*"])[0]
		e = frappe.get_doc(dict(row, doctype="Tax Withholding Entry", name=None, parenttype="Journal Entry",
								parent="JV-FAKE-1", status="Over Withheld", taxable_name="", taxable_doctype=""))
		e.db_insert()
		plan = tds.plan_supplier_year(s, COMPANY, date=self.fy_start)
		self.assertTrue(plan.problems)
		self.assertTrue(all(d.action == "none" for d in plan.docs))

	def test_preview_leaves_nothing_behind(self):
		s = self._supplier(None)
		names = self._year(s, self.SCHEDULE, tds=False)
		frappe.db.set_value("Supplier", s, "tax_withholding_category", CAT_C)
		before = self._entries(names)
		plan = tds.plan_supplier_year(s, COMPANY, date=self.fy_start, mode="supplier")
		self.assertTrue([d for d in plan.docs if d.action == "ledger"])
		self.assertEqual(self._entries(names), before)
		self.assertEqual([self._state(n)["tds"] for n in names], [[]] * len(names))

	def test_stale_token_refused(self):
		s = self._supplier(None)
		self._year(s, self.SCHEDULE, tds=False)
		frappe.db.set_value("Supplier", s, "tax_withholding_category", CAT_C)
		spec = {"supplier": s, "company": COMPANY, "date": str(self.fy_start), "mode": "supplier"}
		token = tds._plan_token(tds._plans_from_specs([spec], 0))
		self._pi(s, self._date(8, 1), [(ITEM, 70000)], tds=False)  # the year changes after the preview
		with self.assertRaises(frappe.ValidationError):
			tds._apply_specs([spec], token, 0)

	def test_migrated_shape_kept_without_double_deduction(self):
		"""A v15 invoice migrated with the whole cumulative deduction on its own row, in a
		filed quarter: the earlier invoices it covered count as settled by it."""
		s = self._supplier(CAT_C)
		names = self._year(s, self.SCHEDULE)
		before = [self._state(n)["tds"] for n in names]
		# Rewrite the year into the migration's shape: own rows only, the excess on the deductor.
		for n in names:
			for e in frappe.get_all("Tax Withholding Entry", filters={"parent": n, "docstatus": 1}, fields=["*"]):
				if e.status == "Duplicate":
					frappe.db.set_value("Tax Withholding Entry", e.name, {
						"status": "Under Withheld", "withholding_name": "", "withholding_doctype": "",
						"withholding_amount": 0, "withholding_date": None})
				elif e.status == "Settled" and e.taxable_name != n:
					own = frappe.get_all("Tax Withholding Entry", filters={
						"parent": n, "taxable_name": n, "status": "Settled",
						"tax_withholding_category": e.tax_withholding_category}, pluck="name")
					self.assertTrue(own)
					frappe.db.set_value("Tax Withholding Entry", own[0], "withholding_amount",
										flt(frappe.db.get_value("Tax Withholding Entry", own[0], "withholding_amount"))
										+ flt(e.withholding_amount))
					frappe.db.delete("Tax Withholding Entry", {"name": e.name})
		frappe.db.set_single_value("BNS Settings", "tds_filed_upto", self._date(6, 30))
		plan = tds.plan_supplier_year(s, COMPANY, date=self.fy_start)
		self.assertFalse(plan.problems, plan.problems)
		money = [(d.name, d.current_tds, d.target_tds) for d in plan.docs
				 if d.action == "ledger" and not d.blocked]
		self.assertEqual(money, [])
		self.assertEqual([self._state(n)["tds"] for n in names], before)

	def test_year_preview_is_compact(self):
		s = self._supplier(CAT_C)
		self._year(s, self.SCHEDULE)
		with patch.object(tds, "_year_specs", return_value=[
				{"supplier": s, "company": COMPANY, "date": str(self.fy_start), "mode": "keep"}]):
			view = tds.preview_year_tds(COMPANY, None, "keep")
		self.assertEqual(view["plans"], [])
		self.assertEqual(view["summary"]["changes"], 0)

	def _debit_note(self, against, date, amount, tds=True):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		dn = make_debit_note(against)
		dn.posting_date = date
		dn.set_posting_time = 1
		dn.bill_no = frappe.generate_hash(length=8)
		dn.items[0].qty = -1
		dn.items[0].rate = amount
		if not tds:
			dn.apply_tds = 0
			for row in dn.items:
				row.tax_withholding_category = None
		dn.insert()
		dn.submit()
		return dn.name

	def test_debit_note_in_the_year_matches_native(self):
		native = self._supplier(CAT_C)
		fixed = self._supplier(None)
		a = self._year(native, self.SCHEDULE[:4])
		b = self._year(fixed, self.SCHEDULE[:4], tds=False)
		a.append(self._debit_note(a[3], self._date(6, 1), 15000))
		b.append(self._debit_note(b[3], self._date(6, 1), 15000, tds=False))
		a += self._year(native, self.SCHEDULE[4:])
		b += self._year(fixed, self.SCHEDULE[4:], tds=False)
		frappe.db.set_value("Supplier", fixed, "tax_withholding_category", CAT_C)
		plan, summary = self._apply(fixed, mode="supplier")
		self.assertFalse(summary["error_count"], summary)
		dn = [d for d in plan.docs if d.is_return][0]
		self.assertFalse(dn.blocked, (dn.blocked, dn.action, dn.current_tds, dn.target_tds, summary.get("skipped")))
		self.assertSameYear(a, b)

	def test_paid_invoice_payment_is_cut_back(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		s = self._supplier(None)
		names = self._year(s, [(4, 5, [(ITEM, 50000)])], tds=False)
		pe = get_payment_entry("Purchase Invoice", names[0])
		pe.posting_date = self._date(4, 6)
		pe.reference_no, pe.reference_date = "UTR1", self._date(4, 6)
		pe.paid_from = _acc("Cash")
		pe.insert()
		pe.submit()
		frappe.db.set_value("Supplier", s, "tax_withholding_category", CAT_C)
		plan, summary = self._apply(s, mode="supplier")
		self.assertFalse(summary["error_count"], summary)
		self.assertEqual(self._state(names[0])["tds"], [(_acc("TDS 194C"), 500.0)])
		self.assertEqual(summary["payments_cut"][0]["new_allocated"], 49500.0)
		self.assertEqual(self._state(names[0])["outstanding"], 0.0)
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", pe.name, "unallocated_amount")), 500.0)
