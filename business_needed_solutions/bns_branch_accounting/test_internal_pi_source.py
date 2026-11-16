# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
An internal-branch Purchase Invoice can be submitted only when it was made from the
sending branch's submitted Sales Invoice (utils.assert_internal_purchase_invoice_has_source).

In-memory documents; the database lookups are patched so each case shows one rule.

    bench --site <site> run-tests --module \
        business_needed_solutions.bns_branch_accounting.test_internal_pi_source
"""

import unittest
from unittest.mock import patch

import frappe

from business_needed_solutions.bns_branch_accounting import utils

AFTER, BEFORE = "2026-10-01", "2020-01-01"
CUTOFF = "2026-04-01"


def _pi(**header):
	doc = frappe.new_doc("Purchase Invoice")
	doc.update({"supplier": "Branch B", "company_gstin": "27AAAAA0000A1Z5", "supplier_gstin": "24AAAAA0000A1Z5",
				"posting_date": AFTER, "docstatus": 1, **header})
	doc.append("items", {"item_code": "P799", "qty": 1, "rate": 10})
	return doc


class TestInternalPurchaseInvoiceSource(unittest.TestCase):
	def setUp(self):
		self.si = None  # what the PI resolves to
		self.si_row = {"posting_date": AFTER, "docstatus": 1, "company_gstin": "24AAAAA0000A1Z5",
					   "billing_address_gstin": "27AAAAA0000A1Z5"}
		self.internal = True
		self._real_get_value = frappe.db.get_value
		self.patches = [
			patch.object(utils, "is_bns_internal_supplier", side_effect=lambda d: self.internal),
			patch.object(utils, "is_after_internal_transfer_cutoff", side_effect=lambda d: str(d) >= CUTOFF),
			patch.object(utils, "_structural_si_for_internal_pi", side_effect=lambda d: self.si),
			patch.object(utils.frappe.db, "get_value", side_effect=self._get_value),
		]
		for p in self.patches:
			p.start()

	def tearDown(self):
		for p in self.patches:
			p.stop()

	def _get_value(self, *args, **kwargs):
		if args and args[0] == "Sales Invoice" and self.si and args[1] == self.si:
			return frappe._dict(self.si_row)
		return self._real_get_value(*args, **kwargs)

	def _refused(self, doc, text):
		with self.assertRaises(frappe.ValidationError) as ctx:
			utils.assert_internal_purchase_invoice_has_source(doc)
		self.assertIn(text, str(ctx.exception))

	def test_pi_entered_directly_is_refused(self):
		self._refused(_pi(), "entered directly cannot be submitted")

	def test_bill_number_alone_is_not_a_source(self):
		# The resolver used here ignores bill_no; a typed SI name does not make it linked.
		self._refused(_pi(bill_no="SINV-0001"), "entered directly cannot be submitted")

	def test_pi_from_a_dn_made_receipt_is_refused(self):
		pi = _pi()
		pi.items[0].purchase_receipt = "PR-0001"
		self._refused(pi, "was not made from an internal Sales Invoice")

	def test_same_gstin_branch_has_no_purchase_invoice(self):
		self._refused(_pi(supplier_gstin="27AAAAA0000A1Z5"), "same GSTIN")

	def test_source_sales_invoice_must_be_submitted(self):
		self.si, self.si_row["docstatus"] = "SINV-0001", 0
		self._refused(_pi(), "a draft")

	def test_linked_pi_passes(self):
		self.si = "SINV-0001"
		self.assertEqual(utils.assert_internal_purchase_invoice_has_source(_pi()), "SINV-0001")

	def test_gstins_come_from_the_sales_invoice_when_missing(self):
		self.si = "SINV-0001"
		self.si_row.update(company_gstin="27AAAAA0000A1Z5", billing_address_gstin="27AAAAA0000A1Z5")
		self._refused(_pi(company_gstin="", supplier_gstin=""), "same GSTIN")

	def test_before_cutoff_is_left_alone(self):
		self.assertIsNone(utils.assert_internal_purchase_invoice_has_source(_pi(posting_date=BEFORE)))

	def test_source_date_decides_the_cutoff(self):
		self.si, self.si_row["posting_date"] = "SINV-0001", BEFORE
		self.assertIsNone(utils.assert_internal_purchase_invoice_has_source(_pi()))

	def test_regular_supplier_is_left_alone(self):
		self.internal = False
		self.assertIsNone(utils.assert_internal_purchase_invoice_has_source(_pi()))

	def test_returns_are_left_to_the_return_rules(self):
		self.assertIsNone(utils.assert_internal_purchase_invoice_has_source(_pi(is_return=1)))

	def test_submit_hook_refuses_a_direct_pi(self):
		with self.assertRaises(frappe.ValidationError):
			utils.validate_internal_purchase_invoice_si_parity(_pi())

	def test_draft_save_is_not_blocked(self):
		# The validate-time linkage check waits for submit.
		utils.validate_internal_purchase_invoice_linkage(_pi(docstatus=0))


class TestRowSourceSalesInvoice(unittest.TestCase):
	def _rows(self, **row):
		doc = frappe.new_doc("Purchase Invoice")
		doc.append("items", {"item_code": "P799", "qty": 1, **row})
		return doc

	def test_rows_name_their_sales_invoice(self):
		calls = {"Sales Invoice Item": ["SINV-0001"]}
		with patch.object(utils.frappe, "get_all", side_effect=lambda dt, **kw: calls[dt]):
			self.assertEqual(utils._pi_row_source_si(self._rows(sales_invoice_item="SIR-1")), "SINV-0001")

	def test_rows_made_from_a_receipt_follow_it_to_the_sales_invoice(self):
		calls = {"Purchase Receipt Item": ["SIR-1"], "Sales Invoice Item": ["SINV-0001"]}
		with patch.object(utils.frappe, "get_all", side_effect=lambda dt, **kw: calls[dt]):
			self.assertEqual(utils._pi_row_source_si(self._rows(pr_detail="PRR-1")), "SINV-0001")

	def test_unlinked_rows_have_no_source(self):
		self.assertIsNone(utils._pi_row_source_si(self._rows()))
