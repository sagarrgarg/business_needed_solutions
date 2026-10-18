import frappe
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.business_needed_solutions.bin_ledger_sync import (
	bin_differs,
	expected_bin_values,
)
from business_needed_solutions.business_needed_solutions.overrides import stock_balance_reco_fix


class TestBinLedgerCompare(FrappeTestCase):
	def test_expected_from_last_ledger_row(self):
		row = {"actual_qty": 2750.0, "stock_value": 27424.877, "valuation_rate": 9.972682545}
		self.assertEqual(
			expected_bin_values(row),
			{"actual_qty": 2750.0, "stock_value": 27424.877, "valuation_rate": 9.972682545},
		)

	def test_no_ledger_means_empty_bin(self):
		self.assertEqual(expected_bin_values(None), {"actual_qty": 0.0, "stock_value": 0.0})

	def test_matching_bin_has_no_diff(self):
		expected = {"actual_qty": 10.0, "stock_value": 100.0, "valuation_rate": 10.0}
		bin_row = {"actual_qty": 10.0, "stock_value": 100.004, "valuation_rate": 10.0}
		self.assertEqual(bin_differs(bin_row, expected), [])

	def test_stale_negative_bin_is_flagged(self):
		expected = {"actual_qty": 0.0, "stock_value": 0.0}
		bin_row = {"actual_qty": -1.0, "stock_value": 0.0, "valuation_rate": 12.0}
		self.assertEqual(bin_differs(bin_row, expected), ["actual_qty"])

	def test_missing_bin_only_needed_for_nonzero_position(self):
		self.assertEqual(bin_differs(None, {"actual_qty": 0.0, "stock_value": 0.0}), [])
		self.assertEqual(
			bin_differs(None, {"actual_qty": 5.0, "stock_value": 50.0}), ["actual_qty", "stock_value"]
		)


class TestStockBalanceRecoFix(FrappeTestCase):
	"""The patched method must take a reconciliation's qty_after_transaction as the balance
	on a plain (company, item, warehouse) key, and treat it as a delta on a dimension key."""

	def _report(self):
		report = frappe._dict(
			inventory_dimensions=[],
			stock_reco_voucher_wise_count={},
			from_date=frappe.utils.getdate("2026-04-01"),
			to_date=frappe.utils.getdate("2026-10-17"),
			opening_vouchers={"Stock Entry": [], "Stock Reconciliation": []},
			float_precision=3,
		)
		return report

	def _entry(self, **kw):
		base = dict(
			voucher_type="Stock Reconciliation",
			voucher_no="MAT-RECO-TEST",
			is_adjustment_entry=0,
			batch_no=None,
			serial_no=None,
			serial_and_batch_bundle=None,
			voucher_detail_no="x",
			actual_qty=0.0,
			qty_after_transaction=3520.0,
			stock_value=31623.68,
			stock_value_difference=832.74,
			valuation_rate=8.984,
			posting_date=frappe.utils.getdate("2026-05-01"),
		)
		base.update(kw)
		return frappe._dict(base)

	def _qty_dict(self):
		return frappe._dict(
			opening_qty=0.0,
			opening_val=0.0,
			in_qty=0.0,
			in_val=0.0,
			out_qty=0.0,
			out_val=0.0,
			bal_qty=3410.0,
			bal_val=30790.94,
			val_rate=0.0,
		)

	def test_three_part_key_uses_reconciliation_balance(self):
		key = ("Co", "FN259", "WH")
		item_map = {key: self._qty_dict()}
		stock_balance_reco_fix.prepare_item_warehouse_map(self._report(), item_map, self._entry(), key)
		self.assertAlmostEqual(item_map[key].bal_qty, 3520.0)
		self.assertAlmostEqual(item_map[key].in_qty, 110.0)

	def test_dimension_key_keeps_delta_treatment(self):
		key = ("Co", "FN259", "WH", "Project-A")
		item_map = {key: self._qty_dict()}
		stock_balance_reco_fix.prepare_item_warehouse_map(self._report(), item_map, self._entry(), key)
		self.assertAlmostEqual(item_map[key].bal_qty, 3410.0)
		self.assertAlmostEqual(item_map[key].in_qty, 0.0)

	def test_patch_is_self_retiring(self):
		class Fixed:
			def prepare_item_warehouse_map(self, item_warehouse_map, entry, group_by_key):
				if len(group_by_key) == 3:
					return None

		class Buggy:
			def prepare_item_warehouse_map(self, item_warehouse_map, entry, group_by_key):
				if len(group_by_key) == 2:
					return None

		# ERPNext v16: two-part key, so `== 2` is correct, and a different signature.
		class V16:
			def prepare_item_warehouse_map(self, entry, group_by_key):
				if len(group_by_key) == 2:
					return None

		self.assertFalse(stock_balance_reco_fix.installed_method_has_bug(Fixed))
		self.assertTrue(stock_balance_reco_fix.installed_method_has_bug(Buggy))
		self.assertFalse(stock_balance_reco_fix.installed_method_has_bug(V16))
