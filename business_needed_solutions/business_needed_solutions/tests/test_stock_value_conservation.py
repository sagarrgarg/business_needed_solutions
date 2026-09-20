# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Integration tests for Stock Value Conservation (overrides/stock_value_conservation.py).

Real DB (FrappeTestCase), because the thing under test is how ERPNext's ledger, GL and Repost Item
Valuation behave around the plug — a mock would only test the mock.

Uses india_compliance's "_Test Indian Registered Company" and switches perpetual inventory on for it
inside each test's transaction (frappe.db.set_value, rolled back in tearDown). Nothing is committed,
so this can run on a dev site that also holds real books, and it does not need ERPNext's _Test
fixture tree.

    bench --site <site> run-tests --skip-before-tests --module \
        business_needed_solutions.business_needed_solutions.tests.test_stock_value_conservation

Reposts run synchronously inside the backdated submit, as in ERPNext's own tests
(RepostItemValuation.on_submit calls repost() when frappe.flags.in_test is set).
"""

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.doctype.stock_reconciliation.test_stock_reconciliation import (
	create_stock_reconciliation,
)
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from business_needed_solutions.business_needed_solutions.overrides import stock_value_conservation as svc

COMPANY = "_Test Indian Registered Company"
WAREHOUSE = "Stores - _TIRC"
ADJUSTMENT = "Stock Adjustment - _TIRC"
VALUATION_EXPENSE = "Expenses Included In Valuation - _TIRC"
PERPETUAL_INVENTORY = {
	"enable_perpetual_inventory": 1,
	"default_inventory_account": "Stock In Hand - _TIRC",
	"stock_adjustment_account": ADJUSTMENT,
	"expenses_included_in_valuation": VALUATION_EXPENSE,
	"stock_received_but_not_billed": "Stock Received But Not Billed - _TIRC",
	"default_expense_account": "Cost of Goods Sold - _TIRC",
}

# The messages each refusal must carry — asserting a bare ValidationError would let an unrelated
# validation (GST, a missing master) pass a test for the wrong reason.
NO_PLUG = "Every incoming line has a rate typed by hand"
TWO_PLUGS = "Only one incoming line can take the balancing value"
NEGATIVE_PLUG = "leave nothing for row"
ERPNEXT_MULTI_FG = "multiple finished goods"
ADJUSTMENT_BLOCKED = "on the Stock Adjustment account"


def _item(code: str) -> str:
	return make_item(
		f"BNS-SVC-{code}",
		{
			"is_stock_item": 1,
			"valuation_method": "Moving Average",
			"stock_uom": "Nos",
			"gst_hsn_code": "61149090",
		},
	).name


def _receive(item: str, qty: float, rate: float, days_ago: int):
	return make_stock_entry(
		item_code=item,
		target=WAREHOUSE,
		qty=qty,
		rate=rate,
		company=COMPANY,
		posting_date=add_days(nowdate(), -days_ago),
	)


def _entry(purpose: str, rows: list[dict], days_ago: int, additional: float = 0, submit: bool = True):
	se = frappe.new_doc("Stock Entry")
	se.purpose = purpose
	se.stock_entry_type = purpose
	se.company = COMPANY
	se.set_posting_time = 1
	se.posting_date = add_days(nowdate(), -days_ago)
	se.posting_time = "12:00:00"
	for r in rows:
		se.append(
			"items",
			{
				"item_code": r["item"],
				"qty": r["qty"],
				"transfer_qty": r["qty"],
				"uom": "Nos",
				"stock_uom": "Nos",
				"conversion_factor": 1,
				"s_warehouse": WAREHOUSE if r.get("out") else None,
				"t_warehouse": None if r.get("out") else WAREHOUSE,
				"basic_rate": r.get("rate", 0),
				"set_basic_rate_manually": r.get("manual", 0),
				"is_finished_item": r.get("fg", 0),
				"is_scrap_item": r.get("scrap", 0),
			},
		)
	if additional:
		se.append(
			"additional_costs",
			{"expense_account": VALUATION_EXPENSE, "description": "Freight", "amount": additional},
		)
	se.insert()
	if submit:
		se.submit()
	return se


def _adjustment_net(voucher_type: str, voucher_no: str) -> float:
	return flt(svc._net_on_account(voucher_type, voucher_no, ADJUSTMENT), 2)


def _row(se, item_code: str, incoming: bool = True):
	return next(d for d in se.items if d.item_code == item_code and bool(d.t_warehouse) == incoming)


def _incoming_rate(se, row) -> float:
	return flt(
		frappe.db.get_value(
			"Stock Ledger Entry",
			{"voucher_no": se.name, "voucher_detail_no": row.name, "is_cancelled": 0},
			"incoming_rate",
		)
	)


class TestStockValueConservation(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._started = frappe.utils.now_datetime()
		frappe.db.set_value("Company", COMPANY, PERPETUAL_INVENTORY)
		frappe.clear_document_cache("Company", COMPANY)
		frappe.local.enable_perpetual_inventory = {}  # erpnext caches this per company per request
		settings = frappe.get_single("BNS Settings")
		settings.enable_stock_value_conservation = 1
		settings.stock_value_conservation_effective_from = add_days(nowdate(), -60)
		settings.allow_balanced_entries_without_plug = 0
		settings.exclude_transactions_from_adjustment_guard = 0
		# Other BNS Stock Entry controls would get in the way of fixture-built entries.
		settings.enforce_bom_for_manufacture = 0
		settings.enable_bns_variance_qty = 0
		settings.set("stock_value_conservation_rules", [])
		settings.append(
			"stock_value_conservation_rules",
			{
				"company": COMPANY,
				"apply_to_repack": 1,
				"apply_to_manufacture": 1,
				"is_active": 1,
			},
		)
		settings.save()
		# WarehouseSuite blocks any non-zero value_difference, and a conserved entry with additional
		# costs has value_difference == total additional costs by design.
		if frappe.db.exists("DocType", "WMSuite Settings"):
			frappe.db.set_single_value("WMSuite Settings", "disallow_value_difference", 0)
		frappe.local.bns_svc_flagged = set()

	def tearDown(self):
		# repost() sets this and never clears it; later tests would run as if inside a repost.
		frappe.flags.through_repost_item_valuation = False
		frappe.db.rollback()
		# Error Log is MyISAM: rollback does not remove it, so remove what this test wrote.
		frappe.db.delete(
			"Error Log",
			{"method": ("like", "BNS stock value conservation%"), "creation": (">=", self._started)},
		)

	# (a) Repack with two incoming lines, one plug: value is conserved, nothing on Stock Adjustment.
	def test_repack_two_incoming_one_plug_conserves(self):
		rm, typed, plug = _item("RM-A"), _item("FG1-A"), _item("FG2-A")
		_receive(rm, 100, 50, days_ago=10)
		se = _entry(
			"Repack",
			[
				{"item": rm, "qty": 100, "out": 1},
				{"item": typed, "qty": 60, "rate": 60, "manual": 1, "fg": 1},
				{"item": plug, "qty": 30, "fg": 1},
			],
			days_ago=9,
		)
		self.assertEqual(se.bns_value_conserved, 1)
		self.assertAlmostEqual(_row(se, plug).basic_rate, (5000 - 3600) / 30, places=4)
		self.assertAlmostEqual(_row(se, typed).basic_rate, 60)
		self.assertAlmostEqual(flt(se.value_difference, 2), 0)
		self.assertEqual(_adjustment_net("Stock Entry", se.name), 0)
		self.assertAlmostEqual(flt(_row(se, typed).bns_fixed_rate), 60)

	# (b) Backdate an earlier receipt, repost: the plug's ledger entry moves, Stock Adjustment stays 0.
	def test_backdated_receipt_reprices_plug_without_adjustment(self):
		rm, typed, plug = _item("RM-B"), _item("FG1-B"), _item("FG2-B")
		_receive(rm, 100, 50, days_ago=10)
		se = _entry(
			"Repack",
			[
				{"item": rm, "qty": 100, "out": 1},
				{"item": typed, "qty": 60, "rate": 60, "manual": 1, "fg": 1},
				{"item": plug, "qty": 30, "fg": 1},
			],
			days_ago=9,
		)
		_receive(rm, 100, 80, days_ago=12)  # backdated: moving average at the repack becomes 65

		se.reload()
		self.assertAlmostEqual(_incoming_rate(se, _row(se, plug)), (6500 - 3600) / 30, places=2)
		self.assertAlmostEqual(_incoming_rate(se, _row(se, typed)), 60, places=4)
		self.assertEqual(_adjustment_net("Stock Entry", se.name), 0)

	# (c) Stock Reconciliation is still allowed to post to Stock Adjustment.
	def test_reconciliation_still_posts_adjustment(self):
		item = _item("RECO")
		_receive(item, 10, 100, days_ago=5)
		reco = create_stock_reconciliation(
			item_code=item,
			warehouse=WAREHOUSE,
			qty=10,
			rate=130,
			company=COMPANY,
			expense_account=ADJUSTMENT,
			posting_date=add_days(nowdate(), -4),
		)
		self.assertNotEqual(_adjustment_net("Stock Reconciliation", reco.name), 0)

	# (d) Every incoming line typed by hand: nothing can absorb the difference, so it is refused.
	def test_all_manual_incoming_throws(self):
		rm, a, b = _item("RM-D"), _item("FG1-D"), _item("FG2-D")
		_receive(rm, 100, 50, days_ago=10)
		with self.assertRaisesRegex(frappe.ValidationError, NO_PLUG):
			_entry(
				"Repack",
				[
					{"item": rm, "qty": 100, "out": 1},
					{"item": a, "qty": 60, "rate": 60, "manual": 1, "fg": 1},
					{"item": b, "qty": 30, "rate": 40, "manual": 1, "fg": 1},
				],
				days_ago=9,
			)

	def test_two_plug_lines_throw(self):
		rm, a, b = _item("RM-E"), _item("FG1-E"), _item("FG2-E")
		_receive(rm, 100, 50, days_ago=10)
		with self.assertRaisesRegex(frappe.ValidationError, TWO_PLUGS):
			_entry(
				"Repack",
				[
					{"item": rm, "qty": 100, "out": 1},
					{"item": a, "qty": 60, "fg": 1},
					{"item": b, "qty": 30, "fg": 1},
				],
				days_ago=9,
			)

	def test_negative_plug_blocked_at_submit(self):
		rm, typed, plug = _item("RM-F"), _item("FG1-F"), _item("FG2-F")
		_receive(rm, 100, 50, days_ago=10)
		with self.assertRaisesRegex(frappe.ValidationError, NEGATIVE_PLUG):
			_entry(
				"Repack",
				[
					{"item": rm, "qty": 100, "out": 1},
					{"item": typed, "qty": 60, "rate": 100, "manual": 1, "fg": 1},  # 6000 > 5000 going in
					{"item": plug, "qty": 30, "fg": 1},
				],
				days_ago=9,
			)

	def test_additional_costs_land_on_plug_only(self):
		rm, typed, plug = _item("RM-G"), _item("FG1-G"), _item("FG2-G")
		_receive(rm, 100, 50, days_ago=10)
		se = _entry(
			"Repack",
			[
				{"item": rm, "qty": 100, "out": 1},
				{"item": typed, "qty": 60, "rate": 60, "manual": 1, "fg": 1},
				{"item": plug, "qty": 30, "fg": 1},
			],
			days_ago=9,
			additional=300,
		)
		self.assertAlmostEqual(_row(se, typed).valuation_rate, 60, places=4)
		self.assertAlmostEqual(_row(se, plug).additional_cost, 300, places=2)
		self.assertEqual(_adjustment_net("Stock Entry", se.name), 0)

	def test_settings_off_keeps_erpnext_rule(self):
		settings = frappe.get_single("BNS Settings")
		settings.enable_stock_value_conservation = 0
		settings.save()
		rm, typed, plug = _item("RM-H"), _item("FG1-H"), _item("FG2-H")
		_receive(rm, 100, 50, days_ago=10)
		# ERPNext's own rule: several distinct finished goods must all be typed by hand.
		with self.assertRaisesRegex(frappe.ValidationError, ERPNEXT_MULTI_FG):
			_entry(
				"Repack",
				[
					{"item": rm, "qty": 100, "out": 1},
					{"item": typed, "qty": 60, "rate": 60, "manual": 1, "fg": 1},
					{"item": plug, "qty": 30, "fg": 1},
				],
				days_ago=9,
			)

	# The Guriya shape: Manufacture with a typed packing line; a backdated receipt moves the FG.
	def test_manufacture_fg_plug_follows_repost(self):
		rm, fg, packing = _item("RM-M"), _item("FG-M"), _item("PK-M")
		_receive(rm, 100, 50, days_ago=10)
		se = _entry(
			"Manufacture",
			[
				{"item": rm, "qty": 100, "out": 1},
				{"item": fg, "qty": 90, "fg": 1},
				{"item": packing, "qty": 5, "rate": 100, "manual": 1, "scrap": 1},
			],
			days_ago=9,
		)
		self.assertAlmostEqual(_row(se, fg).basic_rate, (5000 - 500) / 90, places=4)
		_receive(rm, 100, 80, days_ago=12)
		se.reload()
		self.assertAlmostEqual(_incoming_rate(se, _row(se, fg)), (6500 - 500) / 90, places=2)
		self.assertAlmostEqual(_incoming_rate(se, _row(se, packing)), 100, places=4)
		self.assertEqual(_adjustment_net("Stock Entry", se.name), 0)

	def test_repost_below_typed_value_floors_and_logs(self):
		rm, fg, packing = _item("RM-N"), _item("FG-N"), _item("PK-N")
		_receive(rm, 100, 50, days_ago=10)
		se = _entry(
			"Manufacture",
			[
				{"item": rm, "qty": 100, "out": 1},
				{"item": fg, "qty": 90, "fg": 1},
				{"item": packing, "qty": 10, "rate": 400, "manual": 1, "scrap": 1},  # 4000 of 5000
			],
			days_ago=9,
		)
		_receive(rm, 100, 10, days_ago=12)  # moving average falls to 30: 3000 out, 4000 typed in
		se.reload()
		self.assertEqual(flt(_row(se, fg).basic_rate), 0)
		self.assertTrue(
			frappe.db.exists("Error Log", {"reference_name": se.name, "method": ("like", "%floored%")})
		)
		# One repost, one detector entry — on_change reports Completed several times per repost.
		self.assertEqual(
			frappe.db.count(
				"Error Log",
				{"method": ("like", "%Stock Adjustment after repost%"), "creation": (">=", self._started)},
			),
			1,
		)

	def test_entry_before_effective_date_is_untouched(self):
		rm, typed, plug = _item("RM-P"), _item("FG1-P"), _item("FG2-P")
		_receive(rm, 100, 50, days_ago=80)
		# 80 days ago is before Effective From (60 days ago): ERPNext's rule applies.
		with self.assertRaisesRegex(frappe.ValidationError, ERPNEXT_MULTI_FG):
			_entry(
				"Repack",
				[
					{"item": rm, "qty": 100, "out": 1},
					{"item": typed, "qty": 60, "rate": 60, "manual": 1, "fg": 1},
					{"item": plug, "qty": 30, "fg": 1},
				],
				days_ago=79,
			)

	def test_delivery_note_to_stock_adjustment_is_blocked(self):
		from erpnext.stock.doctype.delivery_note.test_delivery_note import create_delivery_note
		from frappe.utils.nestedset import get_root_of

		item = _item("DN")
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "BNS SVC Test Customer",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")
				or get_root_of("Territory"),
				"gst_category": "Unregistered",
			}
		).insert()
		# india_compliance fetches the company GSTIN from the company address on every sales document.
		company_address = frappe.get_doc(
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
		_receive(item, 10, 100, days_ago=5)
		dn = create_delivery_note(
			item_code=item,
			customer=customer.name,
			qty=1,
			rate=150,
			company=COMPANY,
			warehouse=WAREHOUSE,
			expense_account=ADJUSTMENT,
			cost_center="Main - _TIRC",
			do_not_save=True,
		)
		# location_based_series (installed on this bench) requires a Location on sales documents.
		if frappe.get_meta("Delivery Note").has_field("location"):
			dn.location = (
				frappe.get_doc(
					{
						"doctype": "Location",
						"location_name": "BNS SVC Test Location",
						"lbs_location_code": "SVCT",
						"linked_address": company_address.name,
						"linked_warehouse": WAREHOUSE,
					}
				)
				.insert()
				.name
			)
		dn.company_address = company_address.name
		dn.insert()
		with self.assertRaisesRegex(frappe.ValidationError, ADJUSTMENT_BLOCKED):
			dn.submit()
