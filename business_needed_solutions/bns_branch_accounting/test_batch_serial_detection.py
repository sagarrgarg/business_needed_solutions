# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Detection of wrong serial/batch data on BNS internal receipts.

A. serial_batch_parity_check: batch qty and serial -> batch pairs are read from the
   Serial and Batch Entry rows (ERPNext's get_batches_from_bundle collapses repeated batches).
B. Internal Transfer Accounting Audit: a forward row whose booked value is not
   qty x bns_transfer_rate is flagged (bundle rows always, plain rows unless the bin was negative).
C. The audit's repair workers queue a Transaction repost through queue_transfer_rate_repost.
D. Real ledger: a batched receipt booked at the invoice rate is flagged, a repost clears it.

Nothing is committed (rolled back in tearDown):

    bench --site test.localhost run-tests --module \
        business_needed_solutions.bns_branch_accounting.test_batch_serial_detection
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, nowdate

from business_needed_solutions.bns_branch_accounting import serial_batch_parity_check as parity
from business_needed_solutions.bns_branch_accounting.report.internal_transfer_accounting_audit import (
	internal_transfer_accounting_audit as audit,
)
from business_needed_solutions.bns_branch_accounting.test_transfer_value_conservation import (
	LedgerTestCase,
)

AUDIT = audit.__name__


def _entries(*triples):
	return [frappe._dict(serial_no=s, batch_no=b, qty=q) for s, b, q in triples]


# ======================================================================================
# A. Serial / batch parity
# ======================================================================================


class TestParityExtract(unittest.TestCase):
	def extract(self, entries, has_serial=True, has_batch=True):
		with patch.object(parity, "_bundle_entries", return_value=entries):
			return parity._extract(frappe._dict(serial_and_batch_bundle="SABB-1"), has_serial, has_batch)

	def test_serial_and_batch_bundle_sums_one_entry_per_serial(self):
		got = self.extract(_entries(("S1", "B1", -1), ("S2", "B1", -1), ("S3", "B2", -1)))
		self.assertEqual(got.batches, {"B1": 2, "B2": 1})
		self.assertEqual(got.serials, {"S1", "S2", "S3"})
		self.assertEqual(got.serial_batch, {"S1": "B1", "S2": "B1", "S3": "B2"})

	def test_batch_only_bundle_with_repeated_batch_is_summed(self):
		got = self.extract(_entries((None, "B1", 4), (None, "B1", 6)), has_serial=False)
		self.assertEqual(got.batches, {"B1": 10})
		self.assertEqual(got.serials, set())

	def test_legacy_row_fields(self):
		got = parity._extract(
			frappe._dict(serial_no="S1\nS2", batch_no="B9", stock_qty=2), True, True
		)
		self.assertEqual(got.batches, {"B9": 2})
		self.assertEqual(got.serial_batch, {"S1": "B9", "S2": "B9"})


class TestParityEnforcement(unittest.TestCase):
	"""Source S1,S2 in B1 and S3 in B2; per-entry qty is 1, so the old collapsed
	{batch: last qty} map was {B1: 1, B2: 1} on both sides whatever the receiver held."""

	SOURCE = _entries(("S1", "B1", -1), ("S2", "B1", -1), ("S3", "B2", -1))

	def enforce(self, target_entries):
		item = frappe._dict(idx=1, item_code="ITEM-SB", serial_and_batch_bundle="SABB-TGT")
		doc = frappe._dict(items=[item])
		source = frappe._dict(serial_and_batch_bundle="SABB-SRC")
		bundles = {"SABB-SRC": self.SOURCE, "SABB-TGT": target_entries}
		with (
			patch("business_needed_solutions.bns_branch_accounting.utils.is_bns_internal_supplier", return_value=True),
			patch(
				"business_needed_solutions.bns_branch_accounting.utils._resolve_source_item_for_batch_mapping",
				return_value=source,
			),
			patch.object(parity, "_tracking", return_value=(True, True)),
			patch.object(parity, "_bundle_entries", side_effect=lambda b: bundles[b]),
		):
			parity.enforce_internal_batch_serial_parity(doc)

	def test_exact_match_passes(self):
		self.enforce(_entries(("S1", "B1", 1), ("S2", "B1", 1), ("S3", "B2", 1)))

	def test_serials_swapped_between_batches_is_caught(self):
		# Same serials, same qty per batch - only the pairing differs.
		with self.assertRaisesRegex(frappe.ValidationError, "stay in the batch"):
			self.enforce(_entries(("S1", "B2", 1), ("S2", "B1", 1), ("S3", "B1", 1)))

	def test_batch_qty_difference_is_caught(self):
		with self.assertRaisesRegex(frappe.ValidationError, "quantity"):
			self.enforce(_entries(("S1", "B1", 1), ("S2", "B2", 1), ("S3", "B2", 1)))


# ======================================================================================
# B. Audit: booked value vs qty x transfer rate
# ======================================================================================


def _sle(name, qty, rate, svd, bundle=None, qty_after=None, detail="ROW-1", warehouse="WH-A"):
	return frappe._dict(
		name=name,
		voucher_detail_no=detail,
		warehouse=warehouse,
		actual_qty=qty,
		incoming_rate=rate,
		stock_value_difference=svd,
		qty_after_transaction=qty if qty_after is None else qty_after,
		serial_and_batch_bundle=bundle,
	)


class TestAuditTransferValue(unittest.TestCase):
	def check(self, sle_rows, rate=906.27, warehouses=None):
		with patch.object(audit.frappe.db, "sql", return_value=sle_rows):
			return audit._check_sle_transfer_value(
				"Purchase Invoice", "PI-1", {"ROW-1": rate}, warehouses or {"ROW-1": "WH-A"}
			)

	def test_batched_row_at_invoice_value_is_flagged(self):
		# PI070227-0471: SLE rate shows the transfer rate, bundle booked at 363.53.
		issues = self.check([_sle("SLE-1", 600, 906.27, 218118.0, bundle="SABB-1")])
		self.assertEqual(len(issues), 1)
		self.assertIn("bundle SABB-1", issues[0])
		self.assertIn("543762.0", issues[0])

	def test_multi_batch_per_batch_rates_summing_to_transfer_value_pass(self):
		# Entries at 900 and 912.54 (300 each) average 906.27: total is right.
		self.assertEqual(self.check([_sle("SLE-1", 600, 906.27, 543762.0, bundle="SABB-1")]), [])

	def test_rounding_within_one_paisa_per_unit_passes(self):
		self.assertEqual(self.check([_sle("SLE-1", 600, 906.27, 543762.0 - 5.0, bundle="SABB-1")]), [])
		self.assertEqual(len(self.check([_sle("SLE-1", 600, 906.27, 543762.0 - 6.5, bundle="SABB-1")])), 1)

	def test_plain_row_wrong_value_into_non_negative_bin_is_flagged(self):
		issues = self.check([_sle("SLE-1", 10, 906.27, 3635.3, qty_after=25)])
		self.assertEqual(len(issues), 1)
		self.assertIn("stock value booked 3635.3", issues[0])

	def test_plain_row_into_negative_bin_keeps_conservation_semantics(self):
		# Bin was -4 before: a residual may be legitimate (find_unconserved_transfer_receipts).
		self.assertEqual(self.check([_sle("SLE-1", 10, 906.27, 3635.3, qty_after=6)]), [])

	def test_rate_mismatch_reported_once(self):
		issues = self.check([_sle("SLE-1", 600, 363.53, 218118.0, bundle="SABB-1")])
		self.assertEqual(len(issues), 1)
		self.assertIn("incoming_rate=363.53", issues[0])

	def test_outward_unmapped_and_rejected_rows_are_ignored(self):
		rows = [
			_sle("SLE-OUT", -5, 0, -100),
			_sle("SLE-OTHER", 5, 906.27, 1, detail="ROW-X", bundle="SABB-X"),
			_sle("SLE-REJ", 5, 906.27, 1, warehouse="WH-REJ", bundle="SABB-R"),
		]
		self.assertEqual(self.check(rows), [])

	def test_pr_and_pi_wrappers_pass_their_voucher_and_rates(self):
		doc = frappe._dict(
			name="X-1",
			update_stock=1,
			items=[
				frappe._dict(name="ROW-1", bns_transfer_rate=906.27, warehouse="WH-A"),
				frappe._dict(name="ROW-2", bns_transfer_rate=0, warehouse="WH-A"),
			],
		)
		for fn, voucher_type, meta_doctype in (
			(audit._check_sle_for_pr, "Purchase Receipt", "Purchase Receipt Item"),
			(audit._check_sle_for_pi, "Purchase Invoice", "Purchase Invoice Item"),
		):
			if not frappe.get_meta(meta_doctype).has_field("bns_transfer_rate"):
				self.skipTest("bns_transfer_rate custom field not installed")
			with patch.object(audit, "_check_sle_transfer_value", return_value=["x"]) as check:
				self.assertEqual(fn(doc), ["x"])
			check.assert_called_once_with(voucher_type, "X-1", {"ROW-1": 906.27}, {"ROW-1": "WH-A", "ROW-2": "WH-A"})


# ======================================================================================
# C. Repair workers queue a Transaction repost
# ======================================================================================


class TestAuditRepairQueuesRepost(unittest.TestCase):
	def run_worker(self, worker):
		doc = frappe._dict(docstatus=1, company="C", posting_date=nowdate(), name="PI-1")
		with (
			patch.object(audit.frappe, "get_doc", return_value=doc),
			patch.object(audit, "_populate_transfer_rate_before_repost", return_value=[]),
			patch("business_needed_solutions.bns_branch_accounting.utils._voucher_owns_sle", return_value=True),
			patch(
				"business_needed_solutions.bns_branch_accounting.transfer_value_conservation.queue_transfer_rate_repost",
				return_value=True,
			) as queue,
			patch("business_needed_solutions.bns_branch_accounting.utils._apply_bns_internal_gl_rewrite_patch"),
			patch.object(audit.frappe, "new_doc"),
			patch.object(audit.frappe.db, "commit"),
			patch.object(audit.frappe, "publish_realtime"),
		):
			worker([{"voucher_type": "Purchase Invoice", "voucher_no": "PI-1"}])
		return queue

	def test_sle_repost_worker(self):
		queue = self.run_worker(audit._process_sle_repost_batch)
		queue.assert_called_once_with("Purchase Invoice", "PI-1", context="audit_sle_repost")

	def test_gl_repost_worker(self):
		queue = self.run_worker(audit._process_gl_repost_batch)
		queue.assert_called_once_with("Purchase Invoice", "PI-1", context="audit_gl_repost")


# ======================================================================================
# D. Real ledger
# ======================================================================================


class TestRealBundleDetection(LedgerTestCase):
	def batch_item(self, code, serial=False):
		name = f"BNS-BSD-{code}"
		if not frappe.db.exists("Item", name):
			values = {
				"doctype": "Item",
				"item_code": name,
				"item_name": name,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}) or "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"valuation_method": "Moving Average",
				"gst_hsn_code": "61149090",
				"has_batch_no": 1,
				"create_new_batch": 1,
				"batch_number_series": f"BBSD{code}-.#####",
			}
			if serial:
				values.update(has_serial_no=1, serial_no_series=f"SBSD{code}-.#####")
			frappe.get_doc(values).insert()
		return name

	def receipt_sle(self, se):
		return frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": se.name, "is_cancelled": 0, "actual_qty": (">", 0)},
			["name", "voucher_detail_no", "serial_and_batch_bundle"],
			as_dict=True,
		)

	def test_serial_batch_bundle_qty_is_summed_not_collapsed(self):
		from erpnext.stock.serial_batch_bundle import get_batches_from_bundle

		item = self.batch_item("SB", serial=True)
		se = self.receive(item, 3, 10, days_ago=2)
		bundle = self.receipt_sle(se).serial_and_batch_bundle
		(batch,) = set(frappe.get_all("Serial and Batch Entry", {"parent": bundle}, pluck="batch_no"))

		# ERPNext keeps one entry per serial: its batch map shows a single serial's qty.
		self.assertEqual(flt(get_batches_from_bundle(bundle)[batch]), 1)
		got = parity._extract(frappe._dict(serial_and_batch_bundle=bundle), True, True)
		self.assertEqual(got.batches, {batch: 3})
		self.assertEqual(len(got.serials), 3)
		self.assertEqual(set(got.serial_batch.values()), {batch})

	def test_batched_receipt_at_invoice_value_is_flagged_and_repost_clears_it(self):
		item = self.batch_item("B")
		se = self.receive(item, 600, 363.53, days_ago=5)  # priced by ERPNext alone (pre-fix booking)
		sle = self.receipt_sle(se)
		frappe.db.set_value("Stock Ledger Entry", sle.name, "incoming_rate", 906.27)  # the old SLE patch
		rates = {sle.voucher_detail_no: 906.27}

		issues = audit._check_sle_transfer_value("Stock Entry", se.name, rates)
		self.assertEqual(len(issues), 1, issues)
		self.assertIn(sle.serial_and_batch_bundle, issues[0])

		self.transfer_rates[se.name] = 906.27
		self.assertTrue(audit._queue_transaction_repost("Stock Entry", se.name, context="test"))  # runs now
		self.assertEqual(audit._check_sle_transfer_value("Stock Entry", se.name, rates), [])

	def test_batched_receipt_at_transfer_rate_passes(self):
		item = self.batch_item("C")
		se = self.receive(item, 600, 363.53, days_ago=5, transfer_rate=906.27)
		sle = self.receipt_sle(se)
		self.assertEqual(audit._check_sle_transfer_value("Stock Entry", se.name, {sle.voucher_detail_no: 906.27}), [])
