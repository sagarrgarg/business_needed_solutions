# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""Almonds Sorting Report reads only Stock Entries; a batch that also sits on a
receipt or invoice must not crash it.

    bench --site <site> run-tests --skip-before-tests --module \
        business_needed_solutions.business_needed_solutions.tests.test_almonds_sorting_report
"""

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import make_purchase_receipt
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.business_needed_solutions.report.almonds_sorting_report import (
	almonds_sorting_report as report,
)


class TestAlmondsSortingReport(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_batch_received_on_a_purchase_receipt(self):
		item = make_item(f"BNS-ALM-{frappe.generate_hash(length=6)}", {
			"is_stock_item": 1, "has_batch_no": 1, "create_new_batch": 1, "stock_uom": "Nos",
			"gst_hsn_code": "61149090",
		}).name
		pr = make_purchase_receipt(item_code=item, qty=5, rate=10, company="_Test Indian Registered Company",
								   warehouse="Stores - _TIRC", supplier="_Test Registered Supplier")
		bundle = pr.items[0].serial_and_batch_bundle
		batch = frappe.db.get_value("Serial and Batch Entry", {"parent": bundle}, "batch_no")
		columns, data = report.execute(frappe._dict(batch_no=batch, item_code=item))
		self.assertEqual(data, [])
		self.assertTrue(columns)
