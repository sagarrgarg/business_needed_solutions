# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Integration tests for BNS Counter Repack.

Real DB, same approach as tests/test_stock_value_conservation.py: india_compliance's
"_Test Indian Registered Company" gets perpetual inventory, an address and a Location inside each
test's transaction, and everything is rolled back in tearDown. Nothing is committed, so this can
run on a dev site that holds real books.

    bench --site <site> run-tests --skip-before-tests --module \\
        business_needed_solutions.bns_counter_repack.test_counter_repack
"""

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from business_needed_solutions.business_needed_solutions.overrides import stock_value_conservation as svc

COMPANY = "_Test Indian Registered Company"
WAREHOUSE = "Stores - _TIRC"
ADJUSTMENT = "Stock Adjustment - _TIRC"

BLOCKED = "Counter Repack Not Possible"
LOT_EXHAUSTED = "margins are too low"
GRADE_IN_STOCK = "already has"
NO_RULE = "no Counter Repack Rule"
# BNS's own stock-update rule (overrides/stock_update_validation.py) runs earlier in validate and may
# refuse the invoice first; either message stops the bill with a reason.
NEEDS_UPDATE_STOCK = "needs Update Stock|must be referenced from a Delivery Note"
NEEDS_CONSERVATION = "needs Stock Value Conservation"


def _item(code: str, valuation_method: str = "") -> str:
	name = f"BNS-CRP-{code}"
	if frappe.db.exists("Item", name):
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": name,
				"item_name": name,
				"item_group": "Products",
				"stock_uom": "Kg",
				"is_stock_item": 1,
				"gst_hsn_code": "61149090",
				# Bulk lots must be Moving Average; grades hold no stock, so theirs does not matter.
				"valuation_method": valuation_method
				or ("Moving Average" if code.startswith("BULK") else "FIFO"),
			}
		)
		.insert()
		.name
	)


def _receive(item: str, qty: float, rate: float, days_ago: int):
	return make_stock_entry(
		item_code=item,
		target=WAREHOUSE,
		qty=qty,
		rate=rate,
		company=COMPANY,
		posting_date=add_days(nowdate(), -days_ago),
	)


def _rule(sold: str, bulk: str, margin: float, days_ago: int = 30, per_unit: float = 1):
	return frappe.get_doc(
		{
			"doctype": "BNS Counter Repack Rule",
			"company": COMPANY,
			"sold_item": sold,
			"bulk_item": bulk,
			"margin_percent": margin,
			"effective_from": add_days(nowdate(), -days_ago),
			"bulk_qty_per_unit": per_unit,
		}
	).insert()


def _repack_of(invoice, row_idx: int = 1):
	name = invoice.items[row_idx - 1].bns_counter_repack_entry
	return frappe.get_doc("Stock Entry", name) if name else None


def _sle_value(voucher_no: str, item_code: str) -> float:
	return flt(
		frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": voucher_no, "item_code": item_code, "is_cancelled": 0},
			"stock_value_difference",
		)
	)


class TestCounterRepack(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._started = frappe.utils.now_datetime()
		frappe.db.set_value(
			"Company",
			COMPANY,
			{
				"enable_perpetual_inventory": 1,
				"default_inventory_account": "Stock In Hand - _TIRC",
				"stock_adjustment_account": ADJUSTMENT,
				"expenses_included_in_valuation": "Expenses Included In Valuation - _TIRC",
				"stock_received_but_not_billed": "Stock Received But Not Billed - _TIRC",
				"default_expense_account": "Cost of Goods Sold - _TIRC",
			},
		)
		frappe.clear_document_cache("Company", COMPANY)
		frappe.local.enable_perpetual_inventory = {}
		self._conservation(on=True)
		if frappe.db.exists("DocType", "WMSuite Settings"):
			frappe.db.set_single_value("WMSuite Settings", "disallow_value_difference", 0)
		frappe.local.bns_svc_flagged = set()

		self.customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "BNS CRP Counter Customer",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"gst_category": "Unregistered",
			}
		).insert()
		self.address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": COMPANY,
				"address_type": "Billing",
				"address_line1": "1 Test Road",
				"city": "Ahmedabad",
				"state": "Gujarat",
				"pincode": "380001",
				"country": "India",
				"gstin": frappe.db.get_value("Company", COMPANY, "gstin"),
				"gst_category": "Registered Regular",
				"is_your_company_address": 1,
				"links": [{"link_doctype": "Company", "link_name": COMPANY}],
			}
		).insert()
		self.location = None
		if frappe.get_meta("Sales Invoice").has_field("location"):
			self.location = (
				frappe.get_doc(
					{
						"doctype": "Location",
						"location_name": "BNS CRP Counter",
						"lbs_location_code": "CRPC",
						"linked_address": self.address.name,
						"linked_warehouse": WAREHOUSE,
					}
				)
				.insert()
				.name
			)

	def tearDown(self):
		frappe.flags.through_repost_item_valuation = False
		frappe.db.rollback()
		frappe.db.delete(
			"Error Log",
			{"method": ("like", "BNS stock value conservation%"), "creation": (">=", self._started)},
		)

	def _conservation(self, on: bool):
		settings = frappe.get_single("BNS Settings")
		settings.enable_stock_value_conservation = 1 if on else 0
		settings.stock_value_conservation_effective_from = add_days(nowdate(), -60)
		settings.enforce_bom_for_manufacture = 0
		settings.enable_bns_variance_qty = 0
		settings.set("stock_value_conservation_rules", [])
		settings.append(
			"stock_value_conservation_rules",
			{"company": COMPANY, "apply_to_repack": 1, "apply_to_manufacture": 1, "is_active": 1},
		)
		settings.save()

	def _invoice(self, rows: list[dict], update_stock: int = 1, submit: bool = True, days_ago: int = 0):
		si = frappe.new_doc("Sales Invoice")
		si.company = COMPANY
		si.customer = self.customer.name
		si.update_stock = update_stock
		si.set_posting_time = 1
		si.posting_date = add_days(nowdate(), -days_ago)
		si.posting_time = "11:00:00"
		si.company_address = self.address.name
		if self.location:
			si.location = self.location
		for r in rows:
			si.append(
				"items",
				{
					"item_code": r["item"],
					"qty": r["qty"],
					"rate": r["rate"],
					"warehouse": WAREHOUSE,
					"cost_center": "Main - _TIRC",
					"item_tax_template": "GST 5% - _TIRC",
					"bns_counter_repack": r.get("repack", 1),
				},
			)
		si.insert()
		if submit:
			si.submit()
		return si

	def _lot(self, bulk: str):
		# 10 kg worth 1,20,000, bought in two lots at very different rates.
		_receive(bulk, 4, 20000, days_ago=5)
		_receive(bulk, 6, 6666.6667, days_ago=4)

	def test_sale_books_cost_at_margin_and_keeps_rest_in_lot(self):
		bulk, grade = _item("BULK-A"), _item("GRADE-A")
		_rule(grade, bulk, margin=10)
		self._lot(bulk)
		si = self._invoice([{"item": grade, "qty": 1, "rate": 27000}])

		repack = _repack_of(si)
		self.assertEqual(repack.docstatus, 1)
		out = next(d for d in repack.items if d.s_warehouse)
		sold = next(d for d in repack.items if d.item_code == grade)
		leftover = next(d for d in repack.items if d.item_code == bulk and d.t_warehouse)
		self.assertEqual((out.item_code, flt(out.qty)), (bulk, 10))
		self.assertAlmostEqual(sold.basic_rate, 24300, places=2)
		self.assertEqual(flt(leftover.qty), 9)
		self.assertAlmostEqual(leftover.basic_rate, (120000 - 24300) / 9, delta=0.02)
		self.assertAlmostEqual(_sle_value(si.name, grade), -24300, places=2)  # COGS = margin cost
		self.assertEqual(flt(svc._net_on_account("Stock Entry", repack.name, ADJUSTMENT), 2), 0)
		self.assertEqual(
			flt(frappe.db.get_value("Bin", {"item_code": grade, "warehouse": WAREHOUSE}, "actual_qty")), 0
		)

	def test_cancelling_the_invoice_undoes_the_repack(self):
		bulk, grade = _item("BULK-B"), _item("GRADE-B")
		_rule(grade, bulk, margin=10)
		self._lot(bulk)
		si = self._invoice([{"item": grade, "qty": 1, "rate": 27000}])
		repack = _repack_of(si)
		si.reload()
		si.cancel()
		repack.reload()
		self.assertEqual(repack.docstatus, 2)
		qty, value = frappe.db.get_value(
			"Bin", {"item_code": bulk, "warehouse": WAREHOUSE}, ["actual_qty", "stock_value"]
		)
		self.assertEqual(flt(qty), 10)
		self.assertAlmostEqual(flt(value), 120000, delta=0.05)

	def test_two_grades_from_one_lot_share_one_repack(self):
		bulk, premium, cheap = _item("BULK-C"), _item("PREMIUM-C"), _item("CHEAP-C")
		_rule(premium, bulk, margin=10)
		_rule(cheap, bulk, margin=20)
		self._lot(bulk)
		si = self._invoice(
			[{"item": premium, "qty": 1, "rate": 27000}, {"item": cheap, "qty": 2, "rate": 2000}]
		)
		self.assertEqual(si.items[0].bns_counter_repack_entry, si.items[1].bns_counter_repack_entry)
		repack = _repack_of(si)
		leftover = next(d for d in repack.items if d.item_code == bulk and d.t_warehouse)
		self.assertEqual(flt(leftover.qty), 7)
		self.assertAlmostEqual(leftover.basic_rate, (120000 - 24300 - 3200) / 7, delta=0.02)

	def test_backdated_purchase_moves_only_the_leftover(self):
		bulk, grade = _item("BULK-D"), _item("GRADE-D")
		_rule(grade, bulk, margin=10)
		self._lot(bulk)
		si = self._invoice([{"item": grade, "qty": 1, "rate": 27000}])
		repack = _repack_of(si)
		_receive(bulk, 10, 1000, days_ago=8)  # a cheap lot, backdated: the lot at the sale is now 20 kg

		repack.reload()
		self.assertAlmostEqual(_sle_value(si.name, grade), -24300, places=2)  # the sale's cost never moves
		self.assertAlmostEqual(
			next(d for d in repack.items if d.item_code == grade).basic_rate, 24300, places=2
		)
		self.assertEqual(flt(svc._net_on_account("Stock Entry", repack.name, ADJUSTMENT), 2), 0)

	def test_lot_value_exhausted_blocks_the_bill(self):
		bulk, grade = _item("BULK-E"), _item("GRADE-E")
		_rule(grade, bulk, margin=10)
		_receive(bulk, 10, 2000, days_ago=5)  # lot worth 20,000
		with self.assertRaisesRegex(frappe.ValidationError, LOT_EXHAUSTED):
			self._invoice([{"item": grade, "qty": 1, "rate": 27000}])  # needs 24,300

	def test_grade_with_its_own_stock_is_refused(self):
		bulk, grade = _item("BULK-F"), _item("GRADE-F")
		_rule(grade, bulk, margin=10)
		self._lot(bulk)
		_receive(grade, 1, 500, days_ago=3)
		with self.assertRaisesRegex(frappe.ValidationError, GRADE_IN_STOCK):
			self._invoice([{"item": grade, "qty": 1, "rate": 27000}])

	def test_no_rule_is_refused_on_save(self):
		bulk, grade = _item("BULK-G"), _item("GRADE-G")
		self._lot(bulk)
		with self.assertRaisesRegex(frappe.ValidationError, NO_RULE):
			self._invoice([{"item": grade, "qty": 1, "rate": 27000}], submit=False)

	def test_needs_update_stock(self):
		bulk, grade = _item("BULK-H"), _item("GRADE-H")
		_rule(grade, bulk, margin=10)
		with self.assertRaisesRegex(frappe.ValidationError, NEEDS_UPDATE_STOCK):
			self._invoice([{"item": grade, "qty": 1, "rate": 27000}], update_stock=0, submit=False)

	def test_needs_stock_value_conservation(self):
		bulk, grade = _item("BULK-I"), _item("GRADE-I")
		_rule(grade, bulk, margin=10)
		self._conservation(on=False)
		with self.assertRaisesRegex(frappe.ValidationError, NEEDS_CONSERVATION):
			self._invoice([{"item": grade, "qty": 1, "rate": 27000}], submit=False)

	def test_latest_effective_margin_applies(self):
		bulk, grade = _item("BULK-J"), _item("GRADE-J")
		_rule(grade, bulk, margin=10, days_ago=30)
		_rule(grade, bulk, margin=25, days_ago=2)
		self._lot(bulk)
		si = self._invoice([{"item": grade, "qty": 1, "rate": 20000}])
		sold = next(d for d in _repack_of(si).items if d.item_code == grade)
		self.assertAlmostEqual(sold.basic_rate, 15000, places=2)  # 25% since two days ago

	def test_fifo_bulk_item_is_refused(self):
		bulk, grade = _item("FIFOLOT-L", valuation_method="FIFO"), _item("GRADE-L")
		with self.assertRaisesRegex(frappe.ValidationError, "must use Moving Average"):
			_rule(grade, bulk, margin=10)

	def test_unticked_rows_sell_normally(self):
		bulk, grade, plain = _item("BULK-K"), _item("GRADE-K"), _item("PLAIN-K")
		_rule(grade, bulk, margin=10)
		self._lot(bulk)
		_receive(plain, 5, 100, days_ago=3)
		si = self._invoice(
			[{"item": grade, "qty": 1, "rate": 27000}, {"item": plain, "qty": 1, "rate": 150, "repack": 0}]
		)
		self.assertFalse(si.items[1].bns_counter_repack_entry)
		self.assertAlmostEqual(_sle_value(si.name, plain), -100, places=2)
