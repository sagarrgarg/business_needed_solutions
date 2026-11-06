"""BNS internal-transfer GL rewrite and the guards that keep ordinary accounting standard.

The invoice tests build real ERPNext invoices in memory (taxes and totals computed by
ERPNext) and run them through the BNS rewrite, so they check the rewrite against
ERPNext's own figures without needing a full branch-transfer setup. The cancel test
uses real documents inside a savepoint that is rolled back.

Needs the ERPNext test fixtures (_Test Company) and India Compliance's tax accounts.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from business_needed_solutions.bns_branch_accounting import utils as bns

COMPANY = "_Test Company"
CC = "_Test Cost Center - _TC"
DEBTOR = "_Test Receivable - _TC"
CREDITOR = "_Test Payable - _TC"
SETTINGS = {
	"stock_in_transit_account": "Cost of Goods Sold - _TC",
	"internal_sales_transfer_account": "Sales - _TC",
	"internal_purchase_transfer_account": "_Test Account Cost for Goods Sold - _TC",
	"internal_sales_non_gst_account": "Sales - _TC",
	"internal_purchase_non_gst_account": "_Test Account Cost for Goods Sold - _TC",
	"internal_transfer_account": "",
	"internal_branch_debtor_account": DEBTOR,
	"internal_branch_creditor_account": CREDITOR,
	"force_bns_internal_gl_rewrite": 0,
}


def _tax(account, add_deduct="Add", category="Total", rate=0, amount=0):
	row = {
		"account_head": account, "description": account, "category": category,
		"add_deduct_tax": add_deduct, "cost_center": CC,
	}
	if rate:
		row.update(charge_type="On Net Total", rate=rate)
	else:
		row.update(charge_type="Actual", tax_amount=amount)
	return row


def _purchase_invoice(rate=10000.40, qty=1, taxes=(), **fields):
	pi = frappe.get_doc({
		"doctype": "Purchase Invoice", "company": COMPANY, "supplier": "_Test Supplier",
		"posting_date": "2026-05-10", "credit_to": "Creditors - _TC", "currency": "INR",
		"conversion_rate": 1,
		"items": [{"item_code": "_Test Non Stock Item", "qty": qty, "rate": rate,
				   "expense_account": "_Test Account Cost for Goods Sold - _TC", "cost_center": CC}],
		"taxes": list(taxes),
		**fields,
	})
	pi.name = fields.get("name") or "BNS-TEST-PI"
	pi.set_missing_values()
	pi.calculate_taxes_and_totals()
	pi.docstatus = 1
	return pi


def _sales_invoice(rate=10000.40, qty=1, taxes=(), **fields):
	si = frappe.get_doc({
		"doctype": "Sales Invoice", "company": COMPANY, "customer": "_Test Customer",
		"posting_date": "2026-05-10", "debit_to": "Debtors - _TC", "currency": "INR",
		"conversion_rate": 1,
		"items": [{"item_code": "_Test Non Stock Item", "qty": qty, "rate": rate,
				   "income_account": "Sales - _TC", "cost_center": CC}],
		"taxes": list(taxes),
		**fields,
	})
	si.name = fields.get("name") or "BNS-TEST-SI"
	si.set_missing_values()
	si.calculate_taxes_and_totals()
	si.docstatus = 1
	return si


def _erpnext_gl(doc):
	"""ERPNext's own GL for the doc (bypassing the BNS patch if it is applied)."""
	method = type(doc).get_gl_entries
	return getattr(method, "_bns_original", method)(doc)


def _net(rows):
	"""account -> debit - credit, rounded to the paisa."""
	out = {}
	for r in rows:
		out[r["account"]] = out.get(r["account"], 0) + flt(r.get("debit")) - flt(r.get("credit"))
	return {k: round(v, 2) for k, v in out.items() if round(v, 2)}


class _RewriteCase(FrappeTestCase):
	def rewrite(self, doc):
		gates = (
			patch.object(bns, "_is_bns_internal_purchase_invoice_from_si", return_value=True),
			patch.object(bns, "_is_bns_internal_different_gstin_sales_invoice", return_value=True),
			patch.object(bns, "is_after_accounting_rewrite_cutoff", return_value=True),
			patch.object(bns, "_get_bns_branch_accounting_accounts", return_value=dict(SETTINGS)),
		)
		for g in gates:
			g.start()
		try:
			fn = bns._rewrite_bns_internal_pi_gl_entries if doc.doctype == "Purchase Invoice" else bns._rewrite_bns_internal_si_gl_entries
			rows = fn(doc, _erpnext_gl(doc))
		finally:
			for g in gates:
				g.stop()
		self.assertAlmostEqual(sum(flt(r.get("debit")) - flt(r.get("credit")) for r in rows), 0, places=6)
		for r in rows:
			self.assertGreaterEqual(flt(r.get("debit")), 0)
			self.assertGreaterEqual(flt(r.get("credit")), 0)
		return rows


class TestInternalPurchaseInvoiceGL(_RewriteCase):
	def test_tds_deduct_row_is_a_credit(self):
		# GitHub issue #24: a TDS "Deduct" row is stored positive but is a credit.
		pi = _purchase_invoice(taxes=[
			_tax("Input Tax CGST - _TC", rate=9),
			_tax("TDS Payable - _TC", "Deduct", amount=100),
		])
		net = _net(self.rewrite(pi))
		self.assertEqual(net["TDS Payable - _TC"], -100)
		self.assertEqual(net["Input Tax CGST - _TC"], 900.04)
		# The payable is the unrounded grand total (net of TDS), with no round-off row.
		self.assertEqual(net[CREDITOR], -flt(pi.base_grand_total, 2))
		self.assertNotIn("Round Off - _TC", net)
		self.assertNotIn("Creditors - _TC", net)

	def test_reverse_charge_rows_post_both_sides(self):
		pi = _purchase_invoice(taxes=[
			_tax("Input Tax IGST - _TC", rate=18),
			_tax("Output Tax IGST RCM - _TC", "Deduct", rate=18),
		])
		net = _net(self.rewrite(pi))
		self.assertEqual(net["Input Tax IGST - _TC"], 1800.07)
		self.assertEqual(net["Output Tax IGST RCM - _TC"], -1800.07)

	def test_valuation_only_charge_is_not_posted_to_its_account(self):
		# A "Valuation" charge is not in the grand total; ERPNext puts it into stock
		# value, so the party/tax legs must not post it.
		pi = _purchase_invoice(rate=10000, taxes=[
			_tax("Input Tax CGST - _TC", rate=9),
			_tax("Freight and Forwarding Charges - _TC", category="Valuation", amount=50),
		])
		net = _net(self.rewrite(pi))
		self.assertNotIn("Freight and Forwarding Charges - _TC", net)
		self.assertEqual(net[CREDITOR], -10900)

	def test_debit_note_with_tds_reduces_the_original_invoice(self):
		pi = _purchase_invoice(qty=-1, is_return=1, return_against="BNS-ORIGINAL-PI", taxes=[
			_tax("Input Tax CGST - _TC", rate=9),
			_tax("TDS Payable - _TC", "Deduct", amount=-100),
		])
		rows = self.rewrite(pi)
		net = _net(rows)
		self.assertEqual(net["TDS Payable - _TC"], 100)  # TDS reversed: a debit
		self.assertEqual(net["Input Tax CGST - _TC"], -900.04)
		party = next(r for r in rows if r["account"] == CREDITOR)
		self.assertGreater(flt(party["debit"]), 0)
		self.assertEqual(party["against_voucher"], "BNS-ORIGINAL-PI")

	def test_ineligible_itc_is_expensed(self):
		gst_expense = frappe.get_cached_value("Company", COMPANY, "default_gst_expense_account")
		if not gst_expense:
			self.skipTest("_Test Company has no Default GST Expense Account")
		pi = _purchase_invoice(rate=10000, taxes=[_tax("Input Tax CGST - _TC", rate=9)])
		pi.company_gstin = "24AAACB1234C1Z5"  # a GST-registered branch
		pi.taxes[0].gst_tax_type = "cgst"
		pi.items[0].is_ineligible_for_itc = 1
		pi.items[0].cgst_amount = 900
		net = _net(self.rewrite(pi))
		# The input GST is reversed (nothing left to claim) and expensed.
		self.assertNotIn("Input Tax CGST - _TC", net)
		self.assertEqual(net[gst_expense], 900)
		self.assertEqual(net[CREDITOR], -10900)

	def test_rows_carry_transaction_currency(self):
		rows = self.rewrite(_purchase_invoice(taxes=[_tax("Input Tax CGST - _TC", rate=9)]))
		self.assertTrue(all(r.get("transaction_currency") == "INR" for r in rows))


class TestInternalSalesInvoiceGL(_RewriteCase):
	def test_debtor_equals_creditor_whatever_the_rounding(self):
		# Users tick Disable Rounded Total on the receiving PI to match the bill;
		# the Internal Debtor and Internal Creditor must still be equal.
		si = _sales_invoice(taxes=[_tax("Output Tax CGST - _TC", rate=9)])
		pi = _purchase_invoice(disable_rounded_total=1, taxes=[_tax("Input Tax CGST - _TC", rate=9)])
		self.assertNotEqual(flt(si.base_rounded_total), flt(pi.base_grand_total))
		debtor = _net(self.rewrite(si))[DEBTOR]
		creditor = _net(self.rewrite(pi))[CREDITOR]
		self.assertEqual(debtor, -creditor)
		self.assertEqual(debtor, flt(si.base_grand_total, 2))

	def test_debtor_row_carries_erpnext_fields(self):
		si = _sales_invoice(taxes=[_tax("Output Tax CGST - _TC", rate=9)])
		rows = self.rewrite(si)
		net = _net(rows)
		self.assertNotIn("Round Off - _TC", net)
		self.assertEqual(net["Output Tax CGST - _TC"], -900.04)
		party = next(r for r in rows if r["account"] == DEBTOR)
		self.assertEqual(party["against_voucher"], si.name)
		self.assertEqual(party["due_date"], si.due_date)

	def test_credit_note_reduces_the_original_invoice(self):
		si = _sales_invoice(qty=-1, is_return=1, return_against="BNS-ORIGINAL-SI",
							taxes=[_tax("Output Tax CGST - _TC", rate=9)])
		party = next(r for r in self.rewrite(si) if r["account"] == DEBTOR)
		self.assertGreater(flt(party["credit"]), 0)
		self.assertEqual(party["against_voucher"], "BNS-ORIGINAL-SI")

	def test_tax_row_with_nothing_after_discount_is_skipped(self):
		si = _sales_invoice(taxes=[_tax("Output Tax CGST - _TC", rate=9)])
		tax = si.taxes[0]
		tax.base_tax_amount, tax.base_tax_amount_after_discount_amount = 500, 0
		self.assertEqual(bns._resolve_si_tax_account_amounts(si), {})


class TestStockLegs(FrappeTestCase):
	def _doc(self):
		return frappe._dict(doctype="Delivery Note", name="BNS-TEST-DN", company=None)

	def test_single_stock_account_unchanged(self):
		gl = [{"account": "Stock In Hand - A", "credit": 700}, {"account": "COGS - A", "debit": 700}]
		legs, reason = bns._resolve_stock_legs(self._doc(), gl, "credit", use_sle_value=False)
		self.assertEqual((legs, reason), ([("Stock In Hand - A", 700)], ""))

	def test_several_stock_accounts_each_get_a_leg(self):
		# Previously the stock legs were dropped ("multiple_stock_accounts").
		gl = [
			{"account": "Stock In Hand - A", "credit": 700},
			{"account": "Stock In Hand Branch - A", "credit": 300},
			{"account": "COGS - A", "debit": 1000},
		]
		legs, reason = bns._resolve_stock_legs(self._doc(), gl, "credit", use_sle_value=False)
		self.assertEqual(legs, [("Stock In Hand - A", 700), ("Stock In Hand Branch - A", 300)])
		self.assertEqual(reason, "")


class TestSubmitGuards(FrappeTestCase):
	def _prepare(self, doc):
		with patch.object(bns, "_will_rewrite_internal_invoice_gl", return_value=True), \
			 patch.object(bns, "_get_bns_branch_accounting_accounts", return_value=dict(SETTINGS)):
			bns.prepare_internal_invoice_for_gl_rewrite(doc)

	def test_unsupported_features_are_refused(self):
		cases = [
			_purchase_invoice(is_paid=1),
			_purchase_invoice(write_off_amount=10),
			_purchase_invoice(rate=10000, taxes=[_tax("Freight and Forwarding Charges - _TC", category="Valuation", amount=50)]),
			_sales_invoice(is_pos=1),
		]
		# Same company, same PAN: TDS does not apply between branches.
		pi = _purchase_invoice(taxes=[_tax("TDS Payable - _TC", "Deduct", amount=100)])
		pi.taxes[0].is_tax_withholding_account = 1
		cases.append(pi)
		cases.append(_purchase_invoice(is_reverse_charge=1))
		pi = _purchase_invoice()
		pi.total_advance = 500  # ERPNext recomputes it from the advances table
		cases.append(pi)
		for doc in cases:
			with self.subTest(doc=doc.doctype), self.assertRaises(frappe.ValidationError):
				self._prepare(doc)

	def test_tds_found_by_category_account_without_the_flag(self):
		# v15 Sales/Purchase tax rows may not carry is_tax_withholding_account.
		account = frappe.db.get_value("Tax Withholding Account", {"company": COMPANY}, "account")
		if not account:
			self.skipTest("no Tax Withholding Category account for _Test Company")
		pi = _purchase_invoice(taxes=[_tax(account, "Deduct", amount=100)])
		pi.taxes[0].is_tax_withholding_account = 0
		with self.assertRaises(frappe.ValidationError):
			self._prepare(pi)

	def test_ineligible_itc_on_goods_is_allowed(self):
		pi = _purchase_invoice()
		pi.items[0].is_ineligible_for_itc = 1
		self._prepare(pi)  # no error: the rewrite expenses it

	def test_party_account_follows_the_ledger(self):
		pi, si = _purchase_invoice(), _sales_invoice()
		self._prepare(pi)
		self._prepare(si)
		self.assertEqual(pi.credit_to, CREDITOR)
		self.assertEqual(si.debit_to, DEBTOR)

	def test_missing_settings_refused(self):
		with patch.object(bns, "_will_rewrite_internal_invoice_gl", return_value=True), \
			 patch.object(bns, "_get_bns_branch_accounting_accounts", return_value={}):
			with self.assertRaises(frappe.ValidationError):
				bns.prepare_internal_invoice_for_gl_rewrite(_sales_invoice())

	def test_regular_invoice_untouched(self):
		pi = _purchase_invoice(is_paid=1)
		with patch.object(bns, "_will_rewrite_internal_invoice_gl", return_value=False):
			bns.prepare_internal_invoice_for_gl_rewrite(pi)
		self.assertEqual(pi.credit_to, "Creditors - _TC")


class TestInternalGates(FrappeTestCase):
	def test_regular_supplier_challan_number_is_not_a_transfer(self):
		pr = frappe._dict(doctype="Purchase Receipt", docstatus=1, supplier="_Test Supplier",
						  bns_inter_company_reference="", supplier_delivery_note="SI-ANY")
		with patch.object(frappe.db, "exists", return_value=True):
			with patch.object(bns, "is_bns_internal_supplier", return_value=False):
				self.assertFalse(bns._is_bns_internal_si_linked_purchase_receipt(pr))
			with patch.object(bns, "is_bns_internal_supplier", return_value=True):
				self.assertTrue(bns._is_bns_internal_si_linked_purchase_receipt(pr))

	def test_regular_supplier_bill_number_is_not_a_transfer(self):
		pi = frappe._dict(doctype="Purchase Invoice", docstatus=1, supplier="_Test Supplier",
						  bns_inter_company_reference="", bill_no="SI-ANY", items=[])
		with patch.object(bns, "is_bns_internal_supplier", return_value=False), \
			 patch.object(bns, "_is_internal_transfer_sales_invoice", return_value=True):
			self.assertFalse(bns._is_bns_internal_purchase_invoice_from_si(pi))

	def test_draft_flag_cleared_when_supplier_is_regular(self):
		pi = frappe._dict(doctype="Purchase Invoice", docstatus=0, supplier="_Test Supplier", is_bns_internal_supplier=1)
		bns.sync_internal_supplier_flag_on_draft(pi)
		self.assertEqual(pi.is_bns_internal_supplier, 0)


class TestCommonPartyAccounting(FrappeTestCase):
	def test_skipped_for_rewritten_internal_invoice(self):
		from erpnext.controllers.accounts_controller import AccountsController

		bns._apply_bns_common_party_skip_patch()
		doc = SimpleNamespace(doctype="Purchase Invoice", name="X")
		with patch.object(bns, "_will_rewrite_internal_invoice_gl", return_value=True), \
			 patch("frappe.get_single_value", side_effect=AssertionError("ERPNext path must not run")):
			AccountsController.process_common_party_accounting(doc)


class TestCancelLinks(FrappeTestCase):
	def test_hook_keeps_erpnext_ignores(self):
		doc = frappe._dict(doctype="Purchase Invoice", supplier="_Test Supplier", flags=frappe._dict(),
						   ignore_linked_doctypes=("GL Entry", "Unreconcile Payment", "Tax Withholding Entry"))
		with patch.object(bns, "is_bns_internal_supplier", return_value=False):
			bns.ignore_parent_cancellation_links_for_bns_internal(doc)
		self.assertIn("Unreconcile Payment", doc.ignore_linked_doctypes)
		self.assertIn("Tax Withholding Entry", doc.ignore_linked_doctypes)
		self.assertIn("Repost Accounting Ledger", doc.ignore_linked_doctypes)
		self.assertNotIn("Sales Invoice", doc.ignore_linked_doctypes)

	def test_unreconciled_regular_invoice_can_be_cancelled(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		frappe.db.savepoint("bns_cancel_links")
		try:
			pi = frappe.get_doc({
				"doctype": "Purchase Invoice", "company": COMPANY, "supplier": "_Test Supplier",
				"posting_date": "2026-05-10", "set_posting_time": 1, "credit_to": "Creditors - _TC",
				"items": [{"item_code": "_Test Non Stock Item", "qty": 1, "rate": 1000,
						   "expense_account": "_Test Account Cost for Goods Sold - _TC", "cost_center": CC}],
			}).insert()
			pi.submit()
			pe = get_payment_entry("Purchase Invoice", pi.name, bank_account="_Test Bank - _TC")
			pe.reference_no, pe.reference_date, pe.posting_date = "BNS-T", "2026-05-11", "2026-05-11"
			pe.insert()
			pe.submit()
			ur = frappe.get_doc({"doctype": "Unreconcile Payment", "company": COMPANY,
								 "voucher_type": "Payment Entry", "voucher_no": pe.name})
			ur.add_references()
			ur.insert()
			ur.submit()
			pi.reload()
			pi.cancel()  # raised LinkExistsError before the fix
			self.assertEqual(pi.docstatus, 2)
		finally:
			frappe.db.rollback(save_point="bns_cancel_links")


class TestNegativeStockCheck(FrappeTestCase):
	def test_reserved_stock_is_counted(self):
		from erpnext.stock import stock_ledger

		from business_needed_solutions.business_needed_solutions.overrides import warehouse_negative_stock

		warehouse_negative_stock.apply_patches()
		fake = SimpleNamespace(
			wh_data=SimpleNamespace(qty_after_transaction=10), flt_precision=3,
			allow_negative_stock=0, exceptions={}, reserved_stock={},
			get_reserved_stock=lambda item, wh: 8,
		)
		sle = frappe._dict(actual_qty=-5, item_code="X", warehouse="W")
		# 10 - 5 - 8 reserved = -3: must be refused (reservations were ignored before).
		self.assertFalse(stock_ledger.update_entries_after.validate_negative_stock(fake, sle))
		fake.get_reserved_stock = lambda item, wh: 0
		self.assertTrue(stock_ledger.update_entries_after.validate_negative_stock(fake, sle))
