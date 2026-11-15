# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
BNS batch naming (overrides/batch_naming.py) must only name NEW batches.

ERPNext's own batch names are 7-character hashes, so the old "7 chars and no
rule prefix" test also caught existing batches with stock and moved their
stock into a brand-new empty batch.

Real DB, rolled back in tearDown:

    bench --site test.localhost run-tests --skip-before-tests --module \
        business_needed_solutions.business_needed_solutions.tests.test_batch_naming_guard
"""

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.doctype.stock_reconciliation.test_stock_reconciliation import (
	create_stock_reconciliation,
)
from erpnext.stock.serial_batch_bundle import SerialBatchCreation
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.business_needed_solutions.overrides.batch_naming import (
	set_custom_batch_nos,
)

COMPANY = "_Test Indian Registered Company"
WAREHOUSE = "Stores - _TIRC"
WAREHOUSE_2 = "Finished Goods - _TIRC"
PREFIX = "BNSGT"


def _batch_item():
	return make_item(
		f"BNS-BNG-{frappe.generate_hash(length=8)}",
		{
			"is_stock_item": 1,
			"has_batch_no": 1,
			"create_new_batch": 1,
			"stock_uom": "Nos",
			"gst_hsn_code": "61149090",
			"valuation_rate": 10,
		},
	).name


def _hash_batch(item, **extra):
	"""A batch named the ERPNext way (7-char hash), made while no BNS rule is active."""
	batch = frappe.get_doc({"doctype": "Batch", "item": item, **extra}).insert()
	assert len(batch.name) == 7, batch.name
	return batch.name


def _bundle_batches(bundle):
	return {
		row.batch_no
		for row in frappe.get_all("Serial and Batch Entry", filters={"parent": bundle}, fields=["batch_no"])
	}


def _set_rule(active):
	settings = frappe.get_single("BNS Settings")
	settings.set("batch_naming_formats", [])
	if active:
		settings.append(
			"batch_naming_formats",
			{
				"target_doctype": "Stock Entry, Stock Reconciliation, Purchase Receipt",
				"format_string": PREFIX + "-{day_of_year}",
				"append_suffix": 1,
				"is_active": 1,
			},
		)
	settings.save()


class TestBatchNamingGuard(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_set_rule(active=False)

	def tearDown(self):
		frappe.db.rollback()

	def _receive(self, item, batch, qty=10):
		return make_stock_entry(
			item_code=item, to_warehouse=WAREHOUSE, qty=qty, rate=10, batch_no=batch, company=COMPANY
		)

	def test_material_transfer_keeps_existing_hash_batch(self):
		item = _batch_item()
		batch = _hash_batch(item)
		self._receive(item, batch)
		_set_rule(active=True)

		se = make_stock_entry(
			item_code=item,
			from_warehouse=WAREHOUSE,
			to_warehouse=WAREHOUSE_2,
			qty=4,
			batch_no=batch,
			company=COMPANY,
		)

		self.assertEqual(_bundle_batches(se.items[0].serial_and_batch_bundle), {batch})
		target_bundle = frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": se.name, "warehouse": WAREHOUSE_2, "is_cancelled": 0},
			"serial_and_batch_bundle",
		)
		self.assertEqual(_bundle_batches(target_bundle), {batch})

	def test_receipt_into_existing_hash_batch_keeps_it(self):
		item = _batch_item()
		batch = _hash_batch(item)
		self._receive(item, batch)
		_set_rule(active=True)

		se = self._receive(item, batch, qty=5)

		self.assertEqual(_bundle_batches(se.items[0].serial_and_batch_bundle), {batch})

	def test_stock_reconciliation_keeps_existing_hash_batch(self):
		item = _batch_item()
		batch = _hash_batch(item)
		self._receive(item, batch)
		_set_rule(active=True)

		sr = create_stock_reconciliation(
			item_code=item, warehouse=WAREHOUSE, qty=7, rate=10, batch_no=batch, company=COMPANY
		)

		self.assertEqual(_bundle_batches(sr.items[0].serial_and_batch_bundle), {batch})

	def test_new_batch_made_by_this_voucher_gets_bns_name(self):
		item = _batch_item()
		se = make_stock_entry(
			item_code=item, to_warehouse=WAREHOUSE, qty=3, rate=10, company=COMPANY, do_not_submit=True
		)
		# A fresh hash batch this voucher made, and an older one made by another voucher.
		own = _hash_batch(item, reference_doctype="Stock Entry", reference_name=se.name)
		other_se = make_stock_entry(
			item_code=item, to_warehouse=WAREHOUSE, qty=1, rate=10, company=COMPANY, do_not_submit=True
		)
		other = _hash_batch(item, reference_doctype="Stock Entry", reference_name=other_se.name)
		bundles = {}
		for batch in (own, other):
			bundles[batch] = (
				SerialBatchCreation(
					{
						"item_code": item,
						"warehouse": WAREHOUSE,
						"voucher_type": "Stock Entry",
						"voucher_no": se.name,
						"total_qty": 3,
						"batches": frappe._dict({batch: 3}),
						"type_of_transaction": "Inward",
						"company": COMPANY,
						"do_not_submit": True,
					}
				)
				.make_serial_and_batch_bundle()
				.name
			)
		_set_rule(active=True)

		se.items[0].serial_and_batch_bundle = bundles[other]
		se.save()
		self.assertEqual(_bundle_batches(bundles[other]), {other})

		se.items[0].serial_and_batch_bundle = bundles[own]
		se.save()
		renamed = _bundle_batches(bundles[own])
		self.assertEqual(len(renamed), 1)
		self.assertTrue(next(iter(renamed)).startswith(PREFIX), renamed)

	def test_internal_receipt_is_left_alone(self):
		item = _batch_item()
		_set_rule(active=True)
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = COMPANY
		pr.is_bns_internal_supplier = 1
		pr.append("items", {"item_code": item, "qty": 1, "warehouse": WAREHOUSE})

		set_custom_batch_nos(pr)

		self.assertFalse(pr.items[0].batch_no)

	def test_batch_autoname_keeps_typed_seven_char_id(self):
		item = _batch_item()
		_set_rule(active=True)

		typed_id = "LT" + frappe.generate_hash(length=5).upper()
		typed = frappe.get_doc({"doctype": "Batch", "item": item, "batch_id": typed_id}).insert()
		generated = frappe.get_doc({"doctype": "Batch", "item": item}).insert()

		self.assertEqual(typed.name, typed_id)
		self.assertTrue(generated.name.startswith(PREFIX), generated.name)
