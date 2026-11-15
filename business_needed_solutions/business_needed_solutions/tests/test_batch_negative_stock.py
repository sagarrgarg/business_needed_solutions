# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Batch-level negative stock checks for bundle-based stock (v15+).

ERPNext leaves Stock Ledger Entry.batch_no empty when the batch sits in a Serial
and Batch Bundle, so the old SLE.batch_no query never saw these batches. Both
BNS checks (per-warehouse disallow and the negative-stock cutoff) now read the
batch ledger through overrides/batch_stock_ledger.py.

ERPNext's own batch check is switched off here (allow_negative_stock_for_batch)
so only the BNS check can stop the entry. Real DB, rolled back in tearDown:

    bench --site test.localhost run-tests --skip-before-tests --module \
        business_needed_solutions.business_needed_solutions.tests.test_batch_negative_stock
"""

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.stock_ledger import NegativeStockError
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from business_needed_solutions.business_needed_solutions.overrides.batch_stock_ledger import (
	get_batch_qty_by_warehouse,
)

COMPANY = "_Test Indian Registered Company"
WAREHOUSE = "Stores - _TIRC"


def _batch_item():
	return make_item(
		f"BNS-BNS-{frappe.generate_hash(length=8)}",
		{
			"is_stock_item": 1,
			"has_batch_no": 1,
			"create_new_batch": 1,
			"stock_uom": "Nos",
			"gst_hsn_code": "61149090",
			"valuation_rate": 10,
		},
	).name


def _batch(item):
	return frappe.get_doc({"doctype": "Batch", "item": item}).insert().name


def _move(item, batch, qty, days_ago=0, out=False):
	kwargs = {"from_warehouse": WAREHOUSE} if out else {"to_warehouse": WAREHOUSE}
	# A backdated entry reposts inline in tests, and repost() leaves this flag set,
	# which would switch both BNS checks off for the next entry.
	frappe.flags.through_repost_item_valuation = False
	return make_stock_entry(
		item_code=item,
		qty=qty,
		rate=10,
		batch_no=batch,
		company=COMPANY,
		posting_date=add_days(nowdate(), -days_ago),
		posting_time="10:00:00",
		**kwargs,
	)


class BatchNegativeStockBase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock_for_batch", 1)
		frappe.db.set_single_value("BNS Settings", "enable_per_warehouse_negative_stock_disallow", 0)
		frappe.db.set_single_value("BNS Settings", "allow_negative_stock_override", 0)
		frappe.db.set_value("Warehouse", WAREHOUSE, "bns_disallow_negative_stock", 0)
		self.configure()
		# The checks read these with cache=True; drop values cached earlier in this process.
		frappe.db.value_cache.clear()
		frappe.flags.pop("_bns_negative_stock_override_roles", None)

		self.item = _batch_item()
		self.batch_a = _batch(self.item)
		self.batch_b = _batch(self.item)
		_move(self.item, self.batch_a, 10, days_ago=10)
		_move(self.item, self.batch_b, 10, days_ago=10)

	def configure(self):
		pass

	def tearDown(self):
		frappe.flags.through_repost_item_valuation = False
		frappe.db.rollback()
		frappe.db.value_cache.clear()

	def assert_batch_blocked(self, note, **move):
		with self.assertRaises(NegativeStockError) as ctx:
			_move(self.item, self.batch_a, out=True, **move)
		self.assertIn(self.batch_a, str(ctx.exception))
		self.assertIn(note, str(ctx.exception))


class TestWarehouseBatchNegativeStock(BatchNegativeStockBase):
	NOTE = "Disallow Negative Stock"

	def configure(self):
		frappe.db.set_single_value("BNS Settings", "enable_per_warehouse_negative_stock_disallow", 1)
		frappe.db.set_value("Warehouse", WAREHOUSE, "bns_disallow_negative_stock", 1)

	def test_ledger_reads_bundle_batches(self):
		self.assertEqual(get_batch_qty_by_warehouse(self.item, self.batch_a).get(WAREHOUSE), 10)

	def test_issue_within_batch_passes(self):
		_move(self.item, self.batch_a, 8, out=True)
		self.assertEqual(get_batch_qty_by_warehouse(self.item, self.batch_a).get(WAREHOUSE), 2)

	def test_issue_beyond_batch_is_blocked(self):
		# Item balance is 20, so only the batch check can stop this.
		self.assert_batch_blocked(self.NOTE, qty=15)

	def test_backdated_issue_that_breaks_a_later_issue_is_blocked(self):
		_move(self.item, self.batch_a, 10, days_ago=2, out=True)
		# Fine on day -5 (10 - 5), but leaves the day -2 issue 5 short.
		self.assert_batch_blocked(self.NOTE, qty=5, days_ago=5)


class TestCutoffBatchNegativeStock(BatchNegativeStockBase):
	NOTE = "negative-stock cutoff"

	def configure(self):
		frappe.db.set_single_value("BNS Settings", "allow_negative_stock_override", 1)
		frappe.db.set_single_value("BNS Settings", "negative_stock_cutoff_date", add_days(nowdate(), -30))

	def test_issue_within_batch_passes(self):
		_move(self.item, self.batch_a, 10, out=True)

	def test_issue_beyond_batch_is_blocked(self):
		self.assert_batch_blocked(self.NOTE, qty=15)

	def test_backdated_issue_that_breaks_a_later_issue_is_blocked(self):
		_move(self.item, self.batch_a, 10, days_ago=2, out=True)
		self.assert_batch_blocked(self.NOTE, qty=5, days_ago=5)
