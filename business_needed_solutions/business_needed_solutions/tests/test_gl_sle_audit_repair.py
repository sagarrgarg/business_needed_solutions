# Copyright (c) 2026, Sagar Ratan Garg and Contributors
# License: Commercial

"""
Integration tests for the GL/SLE Audit "Missing SLE" repair (gl_sle_audit.py).

The repair queues a Transaction Repost Item Valuation with recreate_stock_ledgers
instead of calling update_stock_ledger() inline, so the voucher gets its SLE, later
SLEs are revalued and its GL gets the COGS / Stock In Hand pair.

Real DB (FrappeTestCase) on india_compliance's "_Test Indian Registered Company",
with perpetual inventory switched on inside each test's transaction. The repair loop
commits per document, so commit/rollback are patched out and tearDown rolls back.

    bench --site <site> run-tests --skip-before-tests --module \
        business_needed_solutions.business_needed_solutions.tests.test_gl_sle_audit_repair

Reposts run synchronously on RIV submit, as in ERPNext's own tests, unless
frappe.flags.dont_execute_stock_reposts is set.
"""

from unittest.mock import patch

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate
from india_compliance.gst_india.utils.tests import create_sales_invoice

from business_needed_solutions.business_needed_solutions import gl_sle_audit as audit

COMPANY = "_Test Indian Registered Company"
WAREHOUSE = "Stores - _TIRC"
STOCK_IN_HAND = "Stock In Hand - _TIRC"
COGS = "Cost of Goods Sold - _TIRC"
PERPETUAL_INVENTORY = {
	"enable_perpetual_inventory": 1,
	"default_inventory_account": STOCK_IN_HAND,
	"stock_adjustment_account": "Stock Adjustment - _TIRC",
	"stock_received_but_not_billed": "Stock Received But Not Billed - _TIRC",
	"default_expense_account": COGS,
}


def _item(code: str) -> str:
	return make_item(
		f"BNS-GLSLE-{code}",
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


def _issue(item: str, qty: float, days_ago: int):
	return make_stock_entry(
		item_code=item,
		source=WAREHOUSE,
		qty=qty,
		company=COMPANY,
		posting_date=add_days(nowdate(), -days_ago),
	)


def _sell(item: str, qty: float, days_ago: int, posting_time: str = "10:00:00"):
	return create_sales_invoice(
		item_code=item,
		qty=qty,
		rate=200,
		update_stock=1,
		set_posting_time=1,
		posting_date=add_days(nowdate(), -days_ago),
		posting_time=posting_time,
	)


def _drop_stock_gl(si) -> None:
	"""Remove the voucher's COGS / Stock In Hand GL rows (Debtors, Sales stay)."""
	frappe.db.delete(
		"GL Entry",
		{"voucher_type": si.doctype, "voucher_no": si.name, "account": ("in", (STOCK_IN_HAND, COGS))},
	)


def _drop_sle(si) -> None:
	"""The October import footprint: invoice submitted, no SLE, GL without stock lines."""
	frappe.db.delete("Stock Ledger Entry", {"voucher_type": si.doctype, "voucher_no": si.name})
	_drop_stock_gl(si)


def _sle_rows(doctype: str, name: str):
	return frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": doctype, "voucher_no": name, "is_cancelled": 0},
		fields=["actual_qty", "qty_after_transaction", "stock_value", "stock_value_difference"],
	)


def _gl_by_account(si) -> dict:
	rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": si.doctype, "voucher_no": si.name, "is_cancelled": 0},
		fields=["account", "debit", "credit"],
	)
	out: dict = {}
	for r in rows:
		out[r.account] = flt(out.get(r.account)) + flt(r.debit) - flt(r.credit)
	return out


def _audit_row(si):
	rows = audit.audit_gl_sle(
		cutoff_date=add_days(nowdate(), -30), doctypes=["Sales Invoice"], company=COMPANY
	)
	return next((r for r in rows if r["name"] == si.name), None)


def _repair(si, status: str):
	return audit.repair_gl_sle(
		docs=[{"doctype": si.doctype, "name": si.name, "status": status}],
		cutoff_date=add_days(nowdate(), -30),
		dry_run=0,
		force_sync=1,
	)


class TestMissingSleRepair(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		company_meta = frappe.get_meta("Company")
		frappe.db.set_value(
			"Company", COMPANY, {k: v for k, v in PERPETUAL_INVENTORY.items() if company_meta.has_field(k)}
		)
		frappe.clear_document_cache("Company", COMPANY)
		frappe.local.enable_perpetual_inventory = {}
		frappe.local.flags.pop("_bns_perpetual_cache", None)
		# The repair loop commits per document; keep everything inside this test's transaction.
		self._patches = [patch.object(frappe.db, "commit"), patch.object(frappe.db, "rollback")]
		for p in self._patches:
			p.start()

	def tearDown(self):
		for p in self._patches:
			p.stop()
		frappe.flags.through_repost_item_valuation = False
		frappe.flags.dont_execute_stock_reposts = False
		frappe.db.rollback()
		frappe.local.flags.pop("_bns_perpetual_cache", None)

	# A Missing-SLE invoice ends with its SLE plus a COGS / Stock In Hand GL pair.
	def test_missing_sle_gets_sle_and_stock_gl(self):
		item = _item("A")
		_receive(item, 10, 100, days_ago=10)
		si = _sell(item, 3, days_ago=5)
		_drop_sle(si)

		row = _audit_row(si)
		self.assertEqual(row["status"], audit.STATUS_MISSING_SLE)

		result = _repair(si, row["status"])
		self.assertFalse(result["errors"], result["errors"])
		actions = result["repaired"][0]["details"]["actions_run"]
		self.assertTrue(any(a.startswith("queued Repost Item Valuation") for a in actions), actions)

		riv = frappe.get_all(
			"Repost Item Valuation",
			filters={"voucher_type": "Sales Invoice", "voucher_no": si.name},
			fields=["based_on", "recreate_stock_ledgers", "allow_negative_stock", "status"],
		)
		self.assertEqual(len(riv), 1)
		self.assertEqual(riv[0].based_on, "Transaction")
		self.assertEqual(riv[0].recreate_stock_ledgers, 1)
		self.assertEqual(riv[0].allow_negative_stock, 1)
		self.assertEqual(riv[0].status, "Completed")

		sle = _sle_rows("Sales Invoice", si.name)
		self.assertEqual(len(sle), 1)
		self.assertEqual(flt(sle[0].actual_qty), -3)
		self.assertAlmostEqual(flt(sle[0].stock_value_difference), -300)

		gl = _gl_by_account(si)
		self.assertAlmostEqual(gl.get(COGS), 300)
		self.assertAlmostEqual(gl.get(STOCK_IN_HAND), -300)
		self.assertIsNone(_audit_row(si))

	# A later SLE on the same item-warehouse is revalued after the repair.
	def test_later_sle_is_revalued(self):
		item = _item("B")
		_receive(item, 10, 100, days_ago=10)
		si = _sell(item, 3, days_ago=5)
		_drop_sle(si)
		later = _issue(item, 2, days_ago=2)  # booked as if the invoice never moved stock

		stale = _sle_rows("Stock Entry", later.name)[0]
		self.assertEqual(flt(stale.qty_after_transaction), 8)

		result = _repair(si, audit.STATUS_MISSING_SLE)
		self.assertFalse(result["errors"], result["errors"])

		fresh = _sle_rows("Stock Entry", later.name)[0]
		self.assertEqual(flt(fresh.qty_after_transaction), 5)
		self.assertAlmostEqual(flt(fresh.stock_value), 500)

	# A 60-row repair runs on the default queue, creates 60 RIVs, and never a
	# second one while the first is still open.
	def test_big_batch_on_default_queue_without_duplicates(self):
		item = _item("C")
		_receive(item, 100, 100, days_ago=10)
		invoices = []
		for i in range(60):
			si = _sell(item, 1, days_ago=5, posting_time=f"10:{i // 60:02d}:{i % 60:02d}")
			_drop_sle(si)
			invoices.append(si)
		docs = [{"doctype": "Sales Invoice", "name": si.name, "status": audit.STATUS_MISSING_SLE} for si in invoices]

		with patch.object(frappe, "enqueue") as enqueue:
			queued = audit.repair_gl_sle(docs=docs, cutoff_date=add_days(nowdate(), -30), dry_run=0)
		self.assertTrue(queued["queued"])
		self.assertEqual(queued["queue"], "default")
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["queue"], "default")
		self.assertEqual(kwargs["job_id"], queued["job_name"])

		# Run the job body as the worker would. RIVs stay Queued, as on a live site.
		frappe.flags.dont_execute_stock_reposts = True
		job_args = {
			k: v
			for k, v in kwargs.items()
			if k not in ("method", "queue", "timeout", "job_id", "now")
		}
		result = audit._run_repair_in_background(**job_args)
		self.assertFalse(result["errors"], result["errors"])

		def open_rivs():
			return frappe.get_all(
				"Repost Item Valuation",
				filters={
					"voucher_type": "Sales Invoice",
					"voucher_no": ("in", [si.name for si in invoices]),
					"docstatus": 1,
				},
				fields=["voucher_no", "status"],
			)

		rivs = open_rivs()
		self.assertEqual(len(rivs), 60)
		self.assertEqual({r.voucher_no for r in rivs}, {si.name for si in invoices})
		self.assertEqual({r.status for r in rivs}, {"Queued"})

		again = audit._run_repair_in_background(**job_args)
		self.assertEqual(len(open_rivs()), 60)
		reasons = {s["reason"] for row in again["repaired"] for s in row["details"]["skipped"]}
		self.assertTrue(all("already open" in r or r.startswith("Repost Item Valuation rebuilds GL") for r in reasons), reasons)

	# Cancelled-heal repairs keep using the long queue (they repost inline).
	def test_queue_choice(self):
		self.assertEqual(audit._repair_queue(0), "default")
		self.assertEqual(audit._repair_queue(1), "long")

	# SLE present but no stock GL → "GL missing stock lines", and the repair restores the pair.
	def test_gl_missing_stock_lines_status(self):
		item = _item("D")
		_receive(item, 10, 100, days_ago=10)
		si = _sell(item, 4, days_ago=5)
		ok = _sell(item, 1, days_ago=4)
		_drop_stock_gl(si)

		row = _audit_row(si)
		self.assertEqual(row["status"], audit.STATUS_GL_MISSING_STOCK)
		self.assertEqual(row["stock_gl_count"], 0)
		self.assertIsNone(_audit_row(ok))

		result = _repair(si, row["status"])
		self.assertFalse(result["errors"], result["errors"])
		gl = _gl_by_account(si)
		self.assertAlmostEqual(gl.get(COGS), 400)
		self.assertAlmostEqual(gl.get(STOCK_IN_HAND), -400)
		self.assertIsNone(_audit_row(si))
