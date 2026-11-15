# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Batch / serial handling in BNS internal transfers (bns_branch_accounting/utils.py):

- per-batch transfer rates for a receipt bundle (_per_entry_transfer_rates)
- the fallback "what did the sender's voucher take out at" rate (_outgoing_rate_from_voucher_sle)
- the internal return credit note matched row by row and batch by batch to the debit note
  (_match_credit_items_to_debit_note)

    bench --site <site> run-tests --module \
        business_needed_solutions.bns_branch_accounting.test_batch_serial_transfers
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt

from business_needed_solutions.bns_branch_accounting import utils as bns_utils
from business_needed_solutions.bns_branch_accounting.test_transfer_value_conservation import LedgerTestCase


def _entries(*rows):
	return [frappe._dict(batch_no=b, serial_no=s, qty=q, stock_value_difference=v, incoming_rate=r)
			for b, s, q, v, r in rows]


class TestPerEntryTransferRates(unittest.TestCase):
	def test_rates_follow_the_sender_per_batch(self):
		source = _entries(("A", None, -6, -600, 0), ("B", None, -4, -560, 0))
		receiver = _entries(("A", None, 6, 0, 0), ("B", None, 4, 0, 0))
		rates = bns_utils._per_entry_transfer_rates(receiver, source, 116)
		self.assertEqual(rates, {(None, "A"): 100.0, (None, "B"): 140.0})

	def test_total_is_scaled_to_qty_times_transfer_rate(self):
		source = _entries(("A", None, -6, -600, 0), ("B", None, -4, -560, 0))
		receiver = _entries(("A", None, 6, 0, 0), ("B", None, 4, 0, 0))
		rates = bns_utils._per_entry_transfer_rates(receiver, source, 120)
		total = 6 * rates[(None, "A")] + 4 * rates[(None, "B")]
		self.assertAlmostEqual(total, 1200, places=6)
		self.assertGreater(rates[(None, "B")], rates[(None, "A")])

	def test_partial_receipt_of_one_batch(self):
		source = _entries(("A", None, -6, -600, 0), ("B", None, -4, -560, 0))
		receiver = _entries(("B", None, 4, 0, 0))
		# One entry: the flat transfer rate says the same, so no per-entry map.
		self.assertIsNone(bns_utils._per_entry_transfer_rates(receiver, source, 140))

	def test_unknown_batch_falls_back_to_flat_rate(self):
		source = _entries(("A", None, -6, -600, 0), ("B", None, -4, -560, 0))
		receiver = _entries(("A", None, 6, 0, 0), ("C", None, 4, 0, 0))
		self.assertIsNone(bns_utils._per_entry_transfer_rates(receiver, source, 116))

	def test_serials_each_keep_their_rate(self):
		source = _entries((None, "S1", -1, -100, 0), (None, "S2", -1, -300, 0))
		receiver = _entries((None, "S1", 1, 0, 0), (None, "S2", 1, 0, 0))
		rates = bns_utils._per_entry_transfer_rates(receiver, source, 200)
		self.assertEqual(rates, {("S1", None): 100.0, ("S2", None): 300.0})

	def test_zero_value_sender_uses_flat_rate(self):
		source = _entries(("A", None, -6, 0, 0), ("B", None, -4, 0, 0))
		receiver = _entries(("A", None, 6, 0, 0), ("B", None, 4, 0, 0))
		self.assertIsNone(bns_utils._per_entry_transfer_rates(receiver, source, 50))


class TestOutgoingRateFromVoucher(LedgerTestCase):
	def test_rate_is_row_value_not_warehouse_balance(self):
		item = self.item("OUTRATE")
		self.receive(item, 10, 100, days_ago=6)
		self.receive(item, 10, 200, days_ago=5)
		se = self.issue(item, 4, days_ago=4)  # moving average 150
		rate = bns_utils._outgoing_rate_from_voucher_sle("Stock Entry", se.name, item)
		self.assertAlmostEqual(rate, 150, places=2)  # the old reader gave 16 x 150 / 4 = 600
		by_row = bns_utils._outgoing_rate_from_voucher_sle(
			"Stock Entry", se.name, item, voucher_detail_no=se.items[0].name
		)
		self.assertAlmostEqual(by_row, 150, places=2)


class TestCreditNoteMatchesDebitNote(unittest.TestCase):
	"""The sender's return credit note follows the receiver's debit note row by row and
	batch by batch."""

	def setUp(self):
		# original PI row -> SI row it came from
		self.pi_to_si = {"P1": "S1", "P2": "S2"}
		self._real_get_value = frappe.db.get_value
		self._patch = patch.object(bns_utils.frappe.db, "get_value", side_effect=self._get_value)
		self._patch.start()

	def tearDown(self):
		self._patch.stop()

	def _get_value(self, *args, **kwargs):
		if len(args) >= 3 and args[0] == "Purchase Invoice Item" and args[2] == "sales_invoice_item":
			return self.pi_to_si.get(args[1])
		return self._real_get_value(*args, **kwargs)

	def _credit(self, *rows):
		credit = frappe.new_doc("Sales Invoice")
		for code, qty, si_row in rows:
			credit.append("items", {"item_code": code, "qty": qty, "conversion_factor": 1,
									"sales_invoice_item": si_row})
		return credit

	def _debit(self, *rows):
		items = [frappe._dict(item_code=code, qty=qty, purchase_invoice_item=link, batch_no=batch,
							  serial_no=None, serial_and_batch_bundle=None)
				 for code, qty, link, batch in rows]
		return frappe._dict(name="DBN-1", items=items)

	def _match(self, credit, debit):
		return bns_utils._match_credit_items_to_debit_note(credit, debit, "Purchase Invoice", "Sales Invoice")

	def test_split_sale_rows_are_not_doubled(self):
		# Sale: X x6 (row S1, batch A) + X x4 (row S2, batch B). Receiver returns B x4.
		credit = self._credit(("X", -6, "S1"), ("X", -4, "S2"))
		rows = self._match(credit, self._debit(("X", -4, "P2", "B")))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].sales_invoice_item, "S2")
		self.assertEqual(flt(rows[0].qty), -4)
		self.assertEqual(rows[0].batch_no, "B")
		self.assertEqual(rows[0].use_serial_batch_fields, 1)

	def test_untraced_rows_fill_sale_rows_in_order(self):
		credit = self._credit(("X", -6, "S1"), ("X", -4, "S2"))
		rows = self._match(credit, self._debit(("X", -7, None, None)))
		self.assertEqual([(r.sales_invoice_item, flt(r.qty)) for r in rows], [("S1", -6), ("S2", -1)])

	def test_items_not_returned_are_dropped(self):
		credit = self._credit(("X", -6, "S1"), ("Y", -2, None))
		rows = self._match(credit, self._debit(("X", -6, "P1", "A")))
		self.assertEqual([r.item_code for r in rows], ["X"])

	def test_return_that_does_not_fit_the_transfer_is_refused(self):
		credit = self._credit(("X", -6, "S1"))
		with self.assertRaises(frappe.ValidationError):
			self._match(credit, self._debit(("X", -9, None, None)))


class TestCreditNoteBatchesInRealLedger(LedgerTestCase):
	"""ERPNext accepts the matched credit note and restores the returned batch at its own cost."""

	def test_returned_batch_goes_back_at_its_cost(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		from india_compliance.gst_india.utils.tests import create_sales_invoice

		from business_needed_solutions.bns_branch_accounting.test_transfer_value_conservation import (
			TestBatchedReceipt,
		)

		item = TestBatchedReceipt.batch_item(self, "RET")
		se_a = self.receive(item, 6, 100, days_ago=6)
		se_b = self.receive(item, 4, 140, days_ago=5)

		def batch_of(se):
			bundle = frappe.db.get_value("Stock Entry Detail", se.items[0].name, "serial_and_batch_bundle")
			return frappe.db.get_value("Serial and Batch Entry", {"parent": bundle}, "batch_no")

		batch_a, batch_b = batch_of(se_a), batch_of(se_b)
		row = {"item_code": item, "rate": 200, "warehouse": "Stores - _TIRC", "use_serial_batch_fields": 1,
			   "cost_center": "Main - _TIRC", "gst_hsn_code": "61149090"}
		sale = create_sales_invoice(
			update_stock=1, set_posting_time=1, posting_date=frappe.utils.add_days(frappe.utils.nowdate(), -4),
			items=[{**row, "qty": 6, "batch_no": batch_a}, {**row, "qty": 4, "batch_no": batch_b}],
		)

		credit = make_return_doc("Sales Invoice", sale.name)
		debit = frappe._dict(name="DBN-T", items=[frappe._dict(
			item_code=item, qty=-4, purchase_invoice_item=None, batch_no=batch_b,
			serial_no=None, serial_and_batch_bundle=None,
		)])
		credit.set("items", bns_utils._match_credit_items_to_debit_note(credit, debit, "Purchase Invoice", "Sales Invoice"))
		credit.insert()
		credit.submit()

		sle = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": credit.name, "is_cancelled": 0},
			fields=["actual_qty", "stock_value_difference", "serial_and_batch_bundle"],
		)
		self.assertEqual(sum(flt(r.actual_qty) for r in sle), 4)
		self.assertAlmostEqual(sum(flt(r.stock_value_difference) for r in sle), 4 * 140, places=2)
		batches = frappe.get_all(
			"Serial and Batch Entry", filters={"parent": ("in", [r.serial_and_batch_bundle for r in sle])},
			pluck="batch_no",
		)
		self.assertEqual(set(batches), {batch_b})
