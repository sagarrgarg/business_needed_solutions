# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Tests for transfer value conservation inside the stock ledger engine
(transfer_value_conservation.py, the process_sle patch and the transfer-rate syncs in utils.py)
and for the ledger chain repair tool (ledger_chain_repair.py).

A. The pure planner, case by case and over a grid of scenarios (invariants).
B. The engine glue against fake engines: both ERPNext layouts, early returns, persistence order.
C. The real ERPNext ledger on a real DB: which row is a BNS internal receipt is decided by
   mocking utils._get_bns_transfer_rate_for_sle, everything else is ERPNext's own engine,
   Bin, GL and Repost Item Valuation (reposts run synchronously under tests).
D. Repost queueing (no loop, no duplicates, daily cap) and the sync functions' contract
   (they never write SLE values by hand).
E. The chain repair tool on a ledger broken the way the old BNS overwrite broke it.

Nothing is committed (rolled back in tearDown), as in test_stock_value_conservation.py:

    bench --site <site> run-tests --module \
        business_needed_solutions.bns_branch_accounting.test_transfer_value_conservation
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from business_needed_solutions.bns_branch_accounting import ledger_chain_repair
from business_needed_solutions.bns_branch_accounting import transfer_value_conservation as tvc
from business_needed_solutions.bns_branch_accounting import utils as bns_utils

P = 2  # currency precision used by the planner tests


def plan(qty_after, stock_value, svd, conserved, method="Moving Average", queue=None):
	return tvc.plan_transfer_value_conservation(
		qty_after=qty_after,
		stock_value=stock_value,
		stock_value_difference=svd,
		conserved_value=conserved,
		valuation_method=method,
		stock_queue=queue,
		precision=P,
	)


# ======================================================================================
# A. Planner
# ======================================================================================


class TestConservationPlanner(unittest.TestCase):
	def test_already_conserved_is_noop(self):
		# Receipt into a positive bin: ERPNext's step is already qty x rate.
		self.assertIsNone(plan(15, 1500, 1000, 1000))

	def test_sub_precision_gap_is_noop(self):
		self.assertIsNone(plan(15, 1500, 1000, 1000.004))

	def test_moving_average_negative_to_positive(self):
		# -5 @ 100 (value -500), receive 20 @ 150: ERPNext -> 15 @ 150 = 2250, step 2750.
		p = plan(15, 2250, 2750, 3000)
		self.assertEqual(p.applied, 250)
		self.assertEqual(p.residual, 0)
		self.assertEqual(p.stock_value, 2500)
		self.assertEqual(p.stock_value_difference, 3000)
		self.assertAlmostEqual(p.valuation_rate, 2500 / 15)
		self.assertIsNone(p.stock_queue)

	def test_moving_average_stays_negative_rate_absorbs(self):
		# -5 @ 100, receive 3 @ 150: ERPNext -> -2 @ 100 = -200, step 300; conserved 450.
		p = plan(-2, -200, 300, 450)
		self.assertEqual((p.applied, p.residual), (150, 0))
		self.assertEqual(p.stock_value, -50)
		self.assertEqual(p.stock_value_difference, 450)
		self.assertAlmostEqual(p.valuation_rate, 25)  # value == qty x rate, rate >= 0

	def test_moving_average_stays_negative_low_rate(self):
		# Zero-cost transfer into a bin that stays negative: rate rises, sign stays sane.
		p = plan(-2, -200, 300, 0)
		self.assertEqual((p.applied, p.residual), (-300, 0))
		self.assertEqual(p.stock_value, -500)
		self.assertAlmostEqual(p.valuation_rate, 250)

	def test_moving_average_negative_clamped_at_zero_value(self):
		# Transfer rate far above the bin's rate: full conservation would need value > 0 at qty < 0.
		p = plan(-2, -200, 300, 1200)
		self.assertEqual((p.applied, p.residual), (200, 700))
		self.assertEqual(p.stock_value, 0)
		self.assertEqual(p.valuation_rate, 0)

	def test_zero_cost_into_negative_ending_positive_is_residual(self):
		# -5 @ 100, receive 10 @ 0: ERPNext -> 5 @ 0, step 500. Conserving 0 would need value -500
		# for +5 qty (a negative rate), so nothing is applied and the gap is reported.
		p = plan(5, 0, 500, 0)
		self.assertEqual((p.applied, p.residual), (0, -500))

	def test_partial_when_positive_bin_cannot_go_below_zero(self):
		p = plan(5, 100, 600, 0)
		self.assertEqual((p.applied, p.residual), (-100, -500))
		self.assertEqual(p.stock_value, 0)

	def test_zero_balance_carries_no_value(self):
		p = plan(0, 0, 500, 750)
		self.assertEqual((p.applied, p.residual), (0, 250))

	def test_existing_invalid_state_is_not_built_on(self):
		self.assertEqual(plan(5, -10, 100, 200).applied, 0)
		self.assertEqual(plan(-5, 10, 100, 50).applied, 0)

	def test_fifo_negative_to_positive_goes_into_receipt_lot(self):
		p = plan(15, 2250, 2750, 3000, "FIFO", [[15, 150]])
		self.assertEqual(p.applied, 250)
		self.assertAlmostEqual(p.stock_queue[0][1], 2500 / 15)
		self.assertAlmostEqual(_queue_value(p.stock_queue), 2500)

	def test_fifo_positive_delta_only_touches_newest_lot(self):
		p = plan(5, 40, 30, 35, "FIFO", [[2, 5], [3, 10]])
		self.assertEqual(p.stock_queue[0], [2, 5])
		self.assertAlmostEqual(p.stock_queue[1][1], 10 + 5 / 3)
		self.assertAlmostEqual(_queue_value(p.stock_queue), 45)

	def test_fifo_negative_delta_spreads_newest_first_never_below_zero(self):
		p = plan(5, 35, 15, -15, "FIFO", [[2, 10], [3, 5]])
		self.assertEqual(p.applied, -30)
		self.assertEqual(p.stock_queue[1], [3, 0.0])
		self.assertAlmostEqual(p.stock_queue[0][1], 2.5)
		self.assertAlmostEqual(_queue_value(p.stock_queue), 5)

	def test_lifo_uses_top_of_stack(self):
		p = plan(5, 40, 30, 35, "LIFO", [[2, 5], [3, 10]])
		self.assertAlmostEqual(p.stock_queue[1][1], 10 + 5 / 3)

	def test_fifo_negative_bin(self):
		p = plan(-2, -200, 300, 450, "FIFO", [[-2, 100]])
		self.assertEqual(p.applied, 150)
		self.assertAlmostEqual(p.stock_queue[0][1], 25)
		self.assertAlmostEqual(_queue_value(p.stock_queue), -50)

	def test_fifo_negative_bin_clamped(self):
		p = plan(-2, -200, 300, 1200, "FIFO", [[-2, 100]])
		self.assertEqual((p.applied, p.residual), (200, 700))
		self.assertAlmostEqual(p.stock_queue[0][1], 0)

	def test_fifo_inconsistent_queue_is_left_alone(self):
		p = plan(5, 100, 600, 700, "FIFO", [])
		self.assertEqual((p.applied, p.residual), (0, 100))

	def test_invariants_over_a_grid(self):
		"""For every scenario: applied has delta's sign and never exceeds it; the resulting rate is
		never negative; value and qty never have opposite signs; FIFO queue total == value."""
		checked = 0
		for prev_qty in (-7, -3, 0, 4):
			for prev_rate in (0, 40, 100):
				for qty in (1, 3, 10):
					for rate in (0, 25, 100, 400):
						for method in ("Moving Average", "FIFO"):
							self._check_scenario(prev_qty, prev_rate, qty, rate, method)
							checked += 1
		self.assertEqual(checked, 4 * 3 * 3 * 4 * 2)

	def _check_scenario(self, prev_qty, prev_rate, qty, rate, method):
		after_qty, after_value, queue = _erpnext_receipt(prev_qty, prev_rate, qty, rate, method)
		prev_value = prev_qty * prev_rate
		svd = after_value - prev_value
		conserved = qty * rate
		p = plan(after_qty, after_value, svd, conserved, method, queue)
		label = f"{method} prev {prev_qty}@{prev_rate} + {qty}@{rate}"
		delta = flt(conserved - svd, P)
		if p is None:
			self.assertEqual(delta, 0, label)
			return
		self.assertTrue(p.applied == 0 or (p.applied > 0) == (delta > 0), label)
		self.assertLessEqual(abs(p.applied), abs(delta) + 1e-9, label)
		self.assertAlmostEqual(p.applied + p.residual, delta, places=6, msg=label)
		if not p.applied:
			return
		self.assertGreaterEqual(p.valuation_rate, -1e-9, label)
		self.assertFalse(after_qty > 0 and p.stock_value < 0, label)
		self.assertFalse(after_qty < 0 and p.stock_value > 0, label)
		self.assertAlmostEqual(p.stock_value_difference - svd, p.applied, places=6, msg=label)
		if method == "FIFO":
			self.assertAlmostEqual(_queue_value(p.stock_queue), p.stock_value, places=4, msg=label)
			self.assertTrue(all(r >= -1e-9 for _, r in p.stock_queue), label)


def _queue_value(queue):
	return sum(q * r for q, r in queue)


def _erpnext_receipt(prev_qty, prev_rate, qty, rate, method):
	"""ERPNext's own pricing of a receipt (Moving Average / FIFO), for the grid test."""
	after = prev_qty + qty
	if method == "Moving Average":
		if after >= 0:
			valuation = rate if prev_qty <= 0 else (prev_qty * prev_rate + qty * rate) / after
		else:
			valuation = prev_rate or rate
		return after, after * valuation if after else 0.0, None
	from erpnext.stock.valuation import FIFOValuation

	queue = FIFOValuation([[prev_qty, prev_rate]] if prev_qty else [])
	queue.add_stock(qty=qty, rate=rate)
	return after, (_queue_value(queue.state) if after else 0.0), [list(b) for b in queue.state]


# ======================================================================================
# B. Engine glue (fake engines)
# ======================================================================================


def _fake_row(**overrides):
	row = frappe._dict(
		name="SLE-1",
		item_code="ITEM",
		warehouse="WH",
		company="CO",
		voucher_type="Purchase Receipt",
		voucher_no="PR-1",
		actual_qty=20,
		qty_after_transaction=15,
		stock_value=2250,
		stock_value_difference=2750,
		valuation_rate=150,
		stock_queue=json.dumps([[15, 150]]),
		doctype="Stock Ledger Entry",
		is_cancelled=0,
	)
	row.update(overrides)
	return row


def _fake_engine(sle, layout="new", method="Moving Average"):
	wh_data = frappe._dict(
		stock_value=2250, prev_stock_value=2250, valuation_rate=150, stock_queue=[[15, 150]]
	)
	engine = SimpleNamespace(
		currency_precision=2,
		valuation_method=method,
		wh_data=wh_data,
		args=frappe._dict(item_code="OTHER", warehouse="WH"),
		repost_affected_transaction=set(),
	)
	if layout == "new":
		engine.prev_sle_dict = {("ITEM", "WH"): sle}
	return engine


@patch("erpnext.is_perpetual_inventory_enabled", return_value=1)
@patch.object(tvc, "_persist_row")
class TestEngineGlue(unittest.TestCase):
	def test_new_layout_updates_row_wh_data_and_persists(self, persist, _pi):
		sle = _fake_row()
		engine = _fake_engine(sle, "new")
		tvc.conserve_transfer_value_in_engine(engine, sle, 150, svd_before=0, doctype_before=None)
		persist.assert_called_once()
		self.assertEqual(sle.stock_value, 2500)
		self.assertEqual(sle.stock_value_difference, 3000)
		self.assertAlmostEqual(sle.valuation_rate, 2500 / 15)
		self.assertEqual(sle.prev_stock_value, 2500)  # the next row reads its previous value from here
		self.assertEqual(engine.wh_data.stock_value, 2500)
		self.assertEqual(engine.wh_data.prev_stock_value, 2500)
		self.assertIn(("Purchase Receipt", "PR-1"), engine.repost_affected_transaction)

	def test_old_layout_detected_by_doctype_mark(self, persist, _pi):
		sle = _fake_row()
		engine = _fake_engine(sle, "old")
		tvc.conserve_transfer_value_in_engine(engine, sle, 150, svd_before=0, doctype_before=None)
		persist.assert_called_once()
		self.assertEqual(engine.wh_data.stock_value, 2500)  # old layout carries state on wh_data

	def test_early_return_is_detected(self, persist, _pi):
		# ERPNext returned before pricing: the row is not the previous entry and was never marked.
		sle = _fake_row(doctype=None)
		engine = _fake_engine(sle, "old")
		tvc.conserve_transfer_value_in_engine(engine, sle, 150, svd_before=0, doctype_before=None)
		persist.assert_not_called()
		self.assertEqual(sle.stock_value_difference, 2750)

	def test_fifo_queue_is_json_on_row_and_list_on_wh_data(self, persist, _pi):
		sle = _fake_row()
		engine = _fake_engine(sle, "new", method="FIFO")
		tvc.conserve_transfer_value_in_engine(engine, sle, 150, svd_before=0, doctype_before=None)
		self.assertIsInstance(sle.stock_queue, str)
		self.assertAlmostEqual(json.loads(sle.stock_queue)[0][1], 2500 / 15)
		self.assertIsInstance(engine.wh_data.stock_queue, list)

	def test_serial_batch_rows_are_left_alone(self, persist, _pi):
		for field in ("serial_and_batch_bundle", "serial_no", "batch_no"):
			sle = _fake_row(**{field: "X"})
			tvc.conserve_transfer_value_in_engine(_fake_engine(sle), sle, 150, 0, None)
		persist.assert_not_called()

	def test_cancelled_and_outward_rows_are_left_alone(self, persist, _pi):
		sle = _fake_row(is_cancelled=1)
		tvc.conserve_transfer_value_in_engine(_fake_engine(sle), sle, 150, 0, None)
		sle = _fake_row(actual_qty=-5)
		tvc.conserve_transfer_value_in_engine(_fake_engine(sle), sle, 150, 0, None)
		persist.assert_not_called()

	def test_own_item_warehouse_is_not_flagged(self, persist, _pi):
		sle = _fake_row()
		engine = _fake_engine(sle)
		engine.args = frappe._dict(item_code="ITEM", warehouse="WH")
		tvc.conserve_transfer_value_in_engine(engine, sle, 150, 0, None)
		self.assertEqual(engine.repost_affected_transaction, set())

	def test_persist_failure_leaves_memory_untouched(self, persist, _pi):
		persist.side_effect = RuntimeError("db down")
		sle = _fake_row()
		engine = _fake_engine(sle)
		with self.assertRaises(RuntimeError):
			tvc.conserve_transfer_value_in_engine(engine, sle, 150, 0, None)
		self.assertEqual(sle.stock_value, 2250)
		self.assertEqual(sle.stock_value_difference, 2750)
		self.assertEqual(engine.wh_data.stock_value, 2250)

	def test_planner_bug_is_logged_not_raised(self, persist, _pi):
		sle = _fake_row()
		with (
			patch.object(tvc, "plan_transfer_value_conservation", side_effect=ZeroDivisionError),
			patch("frappe.log_error") as log_error,
		):
			tvc.conserve_transfer_value_in_engine(_fake_engine(sle), sle, 150, 0, None)
		log_error.assert_called_once()
		persist.assert_not_called()


# ======================================================================================
# C/D/E. Real ERPNext ledger
# ======================================================================================

COMPANY = "_Test Indian Registered Company"
WAREHOUSE = "Stores - _TIRC"
PERPETUAL_INVENTORY = {
	"enable_perpetual_inventory": 1,
	"default_inventory_account": "Stock In Hand - _TIRC",
	"stock_adjustment_account": "Stock Adjustment - _TIRC",
	"expenses_included_in_valuation": "Expenses Included In Valuation - _TIRC",
	"stock_received_but_not_billed": "Stock Received But Not Billed - _TIRC",
	"default_expense_account": "Cost of Goods Sold - _TIRC",
}


class LedgerTestCase(FrappeTestCase):
	"""Real ERPNext ledger. Vouchers registered in self.transfer_rates are treated as BNS internal
	receipts at that rate; every other row is priced by ERPNext alone."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._started = frappe.utils.now_datetime()
		company_meta = frappe.get_meta("Company")  # v16 dropped some of these fields
		frappe.db.set_value(
			"Company", COMPANY, {k: v for k, v in PERPETUAL_INVENTORY.items() if company_meta.has_field(k)}
		)
		frappe.clear_document_cache("Company", COMPANY)
		frappe.local.enable_perpetual_inventory = {}
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		if frappe.db.exists("DocType", "WMSuite Settings"):
			frappe.db.set_single_value("WMSuite Settings", "disallow_value_difference", 0)
		self.transfer_rates = {}
		self._rate_patch = patch.object(
			bns_utils, "_get_bns_transfer_rate_for_sle", side_effect=self._fake_transfer_rate
		)
		self._rate_patch.start()

	def tearDown(self):
		self._rate_patch.stop()
		frappe.flags.through_repost_item_valuation = False
		frappe.flags.dont_execute_stock_reposts = False
		frappe.db.rollback()
		frappe.db.delete(
			"Error Log", {"method": ("like", "BNS transfer%"), "creation": (">=", self._started)}
		)

	def _fake_transfer_rate(self, sle):
		if flt(sle.get("actual_qty")) <= 0:
			return None
		return self.transfer_rates.get(sle.get("voucher_no"))

	# -- fixtures -------------------------------------------------------------------------

	def item(self, code, method="Moving Average"):
		# Inserted directly: erpnext's test_item helper bootstraps ERPNext's whole test dataset on
		# import (v16), which india_compliance rejects.
		name = f"BNS-TVC-{code}"
		if not frappe.db.exists("Item", name):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": name,
					"item_name": name,
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}) or "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"valuation_method": method,
					"gst_hsn_code": "61149090",
				}
			).insert()
		return name

	def receive(self, item, qty, rate, days_ago, transfer_rate=None):
		se = make_stock_entry(
			item_code=item,
			target=WAREHOUSE,
			qty=qty,
			rate=rate,
			company=COMPANY,
			posting_date=add_days(nowdate(), -days_ago),
			do_not_save=True,
		)
		if not rate:
			for row in se.items:
				row.allow_zero_valuation_rate = 1  # a genuine zero-cost transfer
		se.insert()
		if transfer_rate is not None:
			self.transfer_rates[se.name] = transfer_rate
		se.submit()
		return se

	def issue(self, item, qty, days_ago):
		return make_stock_entry(
			item_code=item,
			source=WAREHOUSE,
			qty=qty,
			company=COMPANY,
			posting_date=add_days(nowdate(), -days_ago),
		)

	# -- assertions -----------------------------------------------------------------------

	def chain(self, item):
		return frappe.get_all(
			"Stock Ledger Entry",
			filters={"item_code": item, "warehouse": WAREHOUSE, "is_cancelled": 0},
			fields=[
				"name",
				"voucher_type",
				"voucher_no",
				"actual_qty",
				"qty_after_transaction",
				"incoming_rate",
				"valuation_rate",
				"stock_value",
				"stock_value_difference",
				"stock_queue",
			],
			order_by="posting_datetime, creation",
		)

	def assert_chain_consistent(self, item, method="Moving Average"):
		rows = self.chain(item)
		previous = 0.0
		for row in rows:
			self.assertAlmostEqual(
				row.stock_value_difference,
				row.stock_value - previous,
				places=2,
				msg=f"difference != step on {row.voucher_no}",
			)
			if row.qty_after_transaction:
				self.assertGreaterEqual(row.valuation_rate, -1e-9, f"negative rate on {row.voucher_no}")
				self.assertAlmostEqual(
					row.valuation_rate * row.qty_after_transaction,
					row.stock_value,
					places=1,
					msg=f"value != qty x rate on {row.voucher_no}",
				)
			if method in ("FIFO", "LIFO") and row.qty_after_transaction:
				self.assertAlmostEqual(
					_queue_value(json.loads(row.stock_queue or "[]")),
					row.stock_value,
					places=1,
					msg=f"queue != value on {row.voucher_no}",
				)
			previous = row.stock_value
		bin_value = frappe.db.get_value("Bin", {"item_code": item, "warehouse": WAREHOUSE}, "stock_value")
		self.assertAlmostEqual(flt(bin_value), previous, places=2, msg="Bin != last ledger row")
		self.assert_gl_equals_ledger(rows)
		return rows

	def assert_gl_equals_ledger(self, rows):
		account = PERPETUAL_INVENTORY["default_inventory_account"]
		for voucher_type, voucher_no in {(r.voucher_type, r.voucher_no) for r in rows}:
			sle_total = sum(r.stock_value_difference for r in rows if r.voucher_no == voucher_no)
			gl = frappe.db.sql(
				"""SELECT COALESCE(SUM(debit - credit), 0) FROM `tabGL Entry`
				WHERE voucher_type=%s AND voucher_no=%s AND account=%s AND is_cancelled=0""",
				(voucher_type, voucher_no, account),
			)[0][0]
			self.assertAlmostEqual(flt(gl), sle_total, places=2, msg=f"GL != ledger on {voucher_no}")

	def row_of(self, rows, voucher):
		return next(r for r in rows if r.voucher_no == voucher.name)


class TestConservationInRealLedger(LedgerTestCase):
	def test_receipt_into_negative_bin_conserves_and_keeps_chain(self):
		item = self.item("NEG-POS")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)  # -5 @ 100
		transfer = self.receive(item, 20, 150, days_ago=8, transfer_rate=150)

		rows = self.assert_chain_consistent(item)
		row = self.row_of(rows, transfer)
		self.assertAlmostEqual(row.stock_value_difference, 3000, places=2)  # 20 x 150, not ERPNext's 2750
		self.assertAlmostEqual(row.stock_value, 2500, places=2)
		self.assertAlmostEqual(row.incoming_rate, 150)

	def test_bin_that_stays_negative_then_crosses(self):
		item = self.item("NEG-NEG")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)  # -5 @ 100
		transfer = self.receive(item, 3, 150, days_ago=8, transfer_rate=150)
		later = self.receive(item, 10, 120, days_ago=7)  # ordinary receipt crosses to +8

		rows = self.assert_chain_consistent(item)
		self.assertAlmostEqual(self.row_of(rows, transfer).stock_value_difference, 450, places=2)
		self.assertAlmostEqual(self.row_of(rows, transfer).valuation_rate, 25, places=4)
		# The ordinary receipt settles the negative balance, as in plain ERPNext.
		self.assertAlmostEqual(self.row_of(rows, later).stock_value_difference, 8 * 120 + 50, places=2)

	def test_outward_rows_after_a_conserved_receipt_keep_their_sign(self):
		item = self.item("SIGN")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)
		self.receive(item, 3, 0, days_ago=8, transfer_rate=0)  # zero-cost transfer, stays negative
		issues = [self.issue(item, 1, days_ago=d) for d in (7, 6)]
		rows = self.assert_chain_consistent(item)
		for se in issues:
			self.assertLess(self.row_of(rows, se).stock_value_difference, 0)

	def test_zero_cost_into_negative_ending_positive_keeps_erpnext_value(self):
		item = self.item("ZERO")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)
		transfer = self.receive(item, 10, 0, days_ago=8, transfer_rate=0)
		rows = self.assert_chain_consistent(item)
		# Conserving 0 would need value -500 for +5 qty; the engine keeps ERPNext's 500 instead.
		self.assertAlmostEqual(self.row_of(rows, transfer).stock_value_difference, 500, places=2)

	def test_backdated_entry_reposts_and_still_conserves(self):
		item = self.item("BACKDATE")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=8)
		transfer = self.receive(item, 20, 150, days_ago=6, transfer_rate=150)
		self.issue(item, 4, days_ago=4)
		# Backdated receipt before the issue: Repost Item Valuation re-prices everything after it.
		# The bin before the transfer becomes -3 @ 133.33 (-400) instead of -5 @ 100, so ERPNext's
		# step changes (17 x 150 + 400 = 2950 instead of 2750) and the engine must conserve again
		# from the new state: value 2550 + (3000 - 2950) = 2600.
		self.receive(item, 2, 300, days_ago=9)

		rows = self.assert_chain_consistent(item)
		row = self.row_of(rows, transfer)
		self.assertAlmostEqual(row.stock_value_difference, 3000, places=2)
		self.assertAlmostEqual(row.stock_value, 2600, places=2)
		self.assertEqual(ledger_chain_repair.find_chain_breaks(item_code=item), [])

	def test_fifo_receipt_into_negative_bin(self):
		item = self.item("FIFO", method="FIFO")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)
		transfer = self.receive(item, 20, 150, days_ago=8, transfer_rate=150)
		self.issue(item, 6, days_ago=7)
		rows = self.assert_chain_consistent(item, method="FIFO")
		self.assertAlmostEqual(self.row_of(rows, transfer).stock_value_difference, 3000, places=2)

	def test_rows_that_are_not_transfers_are_priced_by_erpnext_alone(self):
		item = self.item("PLAIN")
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)
		plain = self.receive(item, 20, 150, days_ago=8)  # no transfer rate registered
		rows = self.assert_chain_consistent(item)
		self.assertAlmostEqual(self.row_of(rows, plain).stock_value_difference, 2750, places=2)


class TestRepostQueueing(LedgerTestCase):
	def _voucher(self):
		item = self.item("RIV")
		return self.receive(item, 5, 100, days_ago=3)

	def _reposts(self, se):
		return frappe.get_all(
			"Repost Item Valuation",
			filters={"voucher_type": "Stock Entry", "voucher_no": se.name, "docstatus": 1},
			fields=["name", "status"],
		)

	def test_pending_repost_is_not_duplicated(self):
		se = self._voucher()
		frappe.flags.dont_execute_stock_reposts = True  # keep it Queued
		self.assertTrue(tvc.queue_transfer_rate_repost("Stock Entry", se.name))
		self.assertFalse(tvc.queue_transfer_rate_repost("Stock Entry", se.name))
		self.assertEqual(len(self._reposts(se)), 1)

	def test_daily_cap_stops_a_loop_and_logs_it(self):
		se = self._voucher()
		before = len(self._reposts(se))
		queued = 0
		with patch("frappe.log_error") as log_error:
			for _ in range(tvc.AUTO_REPOST_DAILY_CAP + 3):
				queued += tvc.queue_transfer_rate_repost("Stock Entry", se.name)
		self.assertEqual(before + queued, tvc.AUTO_REPOST_DAILY_CAP)
		self.assertTrue(any("cap reached" in str(c) for c in log_error.call_args_list))

	def test_stale_row_count_compares_rates_only(self):
		se = self._voucher()
		detail = se.items[0].name
		self.assertEqual(
			bns_utils._count_sle_rows_at_stale_transfer_rate("Stock Entry", se.name, {detail: 100}), 0
		)
		self.assertEqual(
			bns_utils._count_sle_rows_at_stale_transfer_rate("Stock Entry", se.name, {detail: 101}), 1
		)


class _FakeDoc:
	"""Attribute + .get() access like a Document (frappe._dict would shadow .items)."""

	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


class TestSyncContract(unittest.TestCase):
	"""The syncs never write SLE values by hand; they queue a repost only for a stale rate."""

	def _run(self, sync, doctype, sle_incoming_rate):
		doc = _FakeDoc(
			name="X-1",
			doctype=doctype,
			docstatus=1,
			update_stock=1,
			is_bns_internal_supplier=1,
			bns_inter_company_reference="SRC-1",
			supplier_delivery_note=None,
			items=[frappe._dict(name="ROW-1", bns_transfer_rate=150)],
		)
		db = MagicMock()
		db.exists.return_value = True
		with (
			patch.object(bns_utils.frappe, "get_doc", return_value=doc),
			patch.object(bns_utils.frappe, "db", db),
			patch.object(bns_utils, "is_after_accounting_rewrite_cutoff", return_value=True),
			patch.object(bns_utils, "_resolve_source_posting_date", return_value="2026-01-01"),
			patch.object(
				bns_utils,
				"_count_sle_rows_at_stale_transfer_rate",
				return_value=0 if sle_incoming_rate == 150 else 1,
			),
			patch.object(bns_utils, "queue_transfer_rate_repost", return_value=True) as queue,
			patch.object(bns_utils, "_force_rebuild_bns_gl_for_voucher") as rebuild,
		):
			stale = sync("X-1")
		sle_writes = [c for c in db.set_value.call_args_list if c.args and c.args[0] == "Stock Ledger Entry"]
		return stale, queue, rebuild, sle_writes

	def test_pr_sync_queues_repost_for_stale_rate_and_never_writes_sle(self):
		stale, queue, rebuild, writes = self._run(
			bns_utils._sync_pr_sle_from_transfer_rate, "Purchase Receipt", 140
		)
		self.assertEqual(stale, 1)
		queue.assert_called_once_with("Purchase Receipt", "X-1", context="pr_transfer_rate_sle_sync")
		rebuild.assert_called_once()
		self.assertEqual(writes, [])

	def test_pr_sync_does_nothing_when_rate_is_current(self):
		stale, queue, _rebuild, writes = self._run(
			bns_utils._sync_pr_sle_from_transfer_rate, "Purchase Receipt", 150
		)
		self.assertEqual(stale, 0)
		queue.assert_not_called()
		self.assertEqual(writes, [])

	def test_pi_sync_same_contract(self):
		stale, queue, _rebuild, writes = self._run(
			bns_utils._sync_pi_sle_from_transfer_rate, "Purchase Invoice", 140
		)
		self.assertEqual(stale, 1)
		queue.assert_called_once_with("Purchase Invoice", "X-1", context="pi_transfer_rate_sle_sync")
		self.assertEqual(writes, [])


class TestChainRepair(LedgerTestCase):
	def _break_like_old_sync(self, item):
		"""Build the M057 shape and break it the way the old BNS overwrite did."""
		self.receive(item, 10, 100, days_ago=10)
		self.issue(item, 15, days_ago=9)
		with patch.object(bns_utils, "_get_bns_transfer_rate_for_sle", return_value=None):
			transfer = self.receive(item, 20, 150, days_ago=8)  # ERPNext: step 2750
		self.issue(item, 2, days_ago=7)
		sle = frappe.db.get_value(
			"Stock Ledger Entry", {"voucher_no": transfer.name, "is_cancelled": 0}, "name"
		)
		frappe.db.set_value(
			"Stock Ledger Entry", sle, "stock_value_difference", 20 * 150, update_modified=False
		)
		return transfer

	def test_finds_the_first_break_per_pair(self):
		item = self.item("REPAIR-FIND")
		transfer = self._break_like_old_sync(item)
		breaks = ledger_chain_repair.find_chain_breaks(item_code=item)
		self.assertEqual(len(breaks), 1)
		self.assertEqual(breaks[0].voucher_no, transfer.name)
		self.assertAlmostEqual(breaks[0].gap, 250, places=2)

	def test_dry_run_changes_nothing(self):
		item = self.item("REPAIR-DRY")
		self._break_like_old_sync(item)
		result = ledger_chain_repair.repair_chain_breaks(item_code=item, dry_run=1)
		self.assertEqual(len(result["would_queue"]), 1)
		self.assertEqual(len(ledger_chain_repair.find_chain_breaks(item_code=item)), 1)

	def test_repair_reposts_and_engine_conserves(self):
		item = self.item("REPAIR-RUN")
		transfer = self._break_like_old_sync(item)
		self.transfer_rates[transfer.name] = 150  # deployed: the engine now conserves this receipt
		result = ledger_chain_repair.repair_chain_breaks(item_code=item, dry_run=0)
		self.assertEqual(len(result["queued"]), 1)
		rows = self.assert_chain_consistent(item)
		self.assertEqual(ledger_chain_repair.find_chain_breaks(item_code=item), [])
		self.assertAlmostEqual(self.row_of(rows, transfer).stock_value_difference, 3000, places=2)
