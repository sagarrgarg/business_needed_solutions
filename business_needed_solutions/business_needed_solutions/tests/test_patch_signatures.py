"""BNS runtime patches must accept whatever ERPNext passes, on v15 and v16.

ERPNext 16.52 added make_entry(..., defer_future_dimension_check) and
repost_gl_entries(doc, transactions), and v16 renamed get_gl_entries' warehouse_account to
inventory_account_map. A wrapper with a hard-coded signature then raises TypeError on every
stock submit or repost. These tests put a stand-in with the newer signature under each
patch and check the call reaches it unchanged, and check every installed patch against the
installed ERPNext's real signature.

Run: bench --site <site> run-tests --app business_needed_solutions \
	--module business_needed_solutions.business_needed_solutions.tests.test_patch_signatures
"""

import inspect
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from business_needed_solutions.bns_branch_accounting import utils as ba_utils
from business_needed_solutions.business_needed_solutions.overrides import warehouse_negative_stock
from business_needed_solutions.business_needed_solutions.site_gate import call_arguments

# A parameter no ERPNext version has, standing in for "whatever ERPNext adds next".
FUTURE = "bns_future_param"


class Recorder:
	"""Stand-in for an ERPNext function; remembers how it was called."""

	def __init__(self, signature_of, result=None):
		self.signature_of = signature_of
		self.result = result if result is not None else []
		self.calls = []

	def make(self):
		recorder = self
		params = inspect.signature(recorder.signature_of)

		def stand_in(*args, **kwargs):
			params.bind(*args, **kwargs)  # fail exactly like the real function would
			recorder.calls.append((args, kwargs))
			return recorder.result

		stand_in.__signature__ = params
		return stand_in


@contextmanager
def repatched(owner, attr_values: dict, flag_name: str, apply):
	"""Swap ERPNext callables for stand-ins, re-run the BNS patch over them, then restore."""
	saved = {(o, a): o.__dict__[a] if isinstance(o, type) else getattr(o, a) for o, a in attr_values}
	saved_flag = getattr(ba_utils, flag_name)
	try:
		for (o, a), value in attr_values.items():
			setattr(o, a, value)
		setattr(ba_utils, flag_name, False)
		apply()
		yield
	finally:
		for (o, a), value in saved.items():
			setattr(o, a, value)
		setattr(ba_utils, flag_name, saved_flag)


class TestPatchSignatures(FrappeTestCase):
	def test_make_entry_forwards_v16_52_keyword(self):
		import erpnext.stock.stock_ledger as sl

		warehouse_negative_stock.apply_patches()

		def v16_52(
			args,
			allow_negative_stock=False,
			via_landed_cost_voucher=False,
			defer_future_dimension_check=False,
			**future,
		):
			pass

		original = sl._original_make_entry
		recorder = Recorder(v16_52, result="sle")
		sl._original_make_entry = recorder.make()
		try:
			result = sl.make_entry({"warehouse": None}, False, False, defer_future_dimension_check=True)
			sl.make_entry({"warehouse": None}, allow_negative_stock=True, **{FUTURE: 1})
		finally:
			sl._original_make_entry = original

		self.assertEqual(result, "sle")
		self.assertEqual(
			recorder.calls[0], (({"warehouse": None}, False, False), {"defer_future_dimension_check": True})
		)
		self.assertEqual(recorder.calls[1][1], {"allow_negative_stock": True, FUTURE: 1})

	def test_validate_negative_qty_forwards_new_arguments(self):
		import erpnext.stock.stock_ledger as sl

		warehouse_negative_stock.apply_patches()

		def newer(args, allow_negative_stock=False, **future):
			pass

		original = sl._original_validate_negative_qty_in_future_sle
		recorder = Recorder(newer)
		sl._original_validate_negative_qty_in_future_sle = recorder.make()
		try:
			with mock.patch.object(warehouse_negative_stock, "validate_warehouse_negative_stock"):
				sl.validate_negative_qty_in_future_sle({"warehouse": None}, True, **{FUTURE: 2})
		finally:
			sl._original_validate_negative_qty_in_future_sle = original
		self.assertEqual(recorder.calls[0], (({"warehouse": None}, True), {FUTURE: 2}))

	def test_repost_gl_entries_forwards_transactions(self):
		from erpnext.stock.doctype.repost_item_valuation import repost_item_valuation as riv

		def v16_52(doc, transactions=None):
			pass

		recorder = Recorder(v16_52)
		doc = SimpleNamespace(name="RIV-TEST")
		with (
			repatched(
				riv,
				{(riv, "repost_gl_entries"): recorder.make()},
				"_BNS_REPOST_GL_FAILSAFE_PATCHED",
				ba_utils._apply_bns_repost_gl_failsafe_patch,
			),
			mock.patch.object(ba_utils, "_run_bns_gl_repost_correction") as correction,
			mock.patch.object(ba_utils, "_release_bns_repost_lock") as release,
		):
			riv.repost_gl_entries(doc, [("Sales Invoice", "SI-1")])
			riv.repost_gl_entries(doc, transactions=[("Delivery Note", "DN-1")])
			riv.repost_gl_entries(doc)

		self.assertEqual(recorder.calls[0], ((doc, [("Sales Invoice", "SI-1")]), {}))
		self.assertEqual(recorder.calls[1], ((doc,), {"transactions": [("Delivery Note", "DN-1")]}))
		self.assertEqual(recorder.calls[2], ((doc,), {}))
		self.assertEqual(correction.call_count, 3)  # BNS correction still runs after each
		self.assertEqual(release.call_count, 3)

	def test_get_gl_entries_forward_keyword_calls(self):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
		from erpnext.controllers.stock_controller import StockController
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt

		def stock(self, inventory_account_map=None, default_expense_account=None, default_cost_center=None):
			pass

		def pr(self, inventory_account_map=None, via_landed_cost_voucher=False):
			pass

		def inv(self, inventory_account_map=None):
			pass

		recorders = {
			StockController: Recorder(stock, ["gl"]),
			PurchaseReceipt: Recorder(pr, ["gl"]),
			PurchaseInvoice: Recorder(inv, ["gl"]),
			SalesInvoice: Recorder(inv, ["gl"]),
		}
		swaps = {(cls, "get_gl_entries"): rec.make() for cls, rec in recorders.items()}
		passthrough = lambda doc, gl: gl  # noqa: E731
		with (
			repatched(None, swaps, "_BNS_INTERNAL_GL_PATCHED", ba_utils._apply_bns_internal_gl_rewrite_patch),
			mock.patch.object(ba_utils, "_rewrite_bns_internal_dn_gl_entries", side_effect=passthrough),
			mock.patch.object(ba_utils, "_rewrite_bns_internal_pr_gl_entries", side_effect=passthrough),
			mock.patch.object(ba_utils, "_rewrite_bns_internal_pi_gl_entries", side_effect=passthrough),
			mock.patch.object(ba_utils, "_rewrite_bns_internal_si_gl_entries", side_effect=passthrough),
			mock.patch.object(ba_utils, "append_asset_transfer_gl_entries", side_effect=passthrough),
		):
			doc = SimpleNamespace(doctype="Delivery Note")
			self.assertEqual(StockController.get_gl_entries(doc, inventory_account_map={"a": 1}), ["gl"])
			PurchaseReceipt.get_gl_entries(doc, {"a": 1}, via_landed_cost_voucher=True)
			PurchaseInvoice.get_gl_entries(doc, inventory_account_map={"a": 1})
			SalesInvoice.get_gl_entries(doc)

		self.assertEqual(recorders[StockController].calls[0][1], {"inventory_account_map": {"a": 1}})
		self.assertEqual(
			recorders[PurchaseReceipt].calls[0], ((doc, {"a": 1}), {"via_landed_cost_voucher": True})
		)
		self.assertEqual(recorders[PurchaseInvoice].calls[0][1], {"inventory_account_map": {"a": 1}})
		self.assertEqual(recorders[SalesInvoice].calls[0], ((doc,), {}))

	def test_sticky_status_reads_arguments_by_name(self):
		def newer(self, update=False, status=None, update_modified=True, **future):
			self.status = status or "Unpaid"

		recorder = Recorder(newer)
		stand_in = recorder.make()

		def original(self, *args, **kwargs):
			stand_in(self, *args, **kwargs)
			bound = call_arguments(newer, self, *args, **kwargs)
			self.status = bound.get("status") or "Unpaid"

		original.__signature__ = inspect.signature(newer)
		patched = ba_utils._wrap_bns_sticky_set_status(original)
		doc = SimpleNamespace(name="SI-T", status=None)
		with mock.patch.object(ba_utils, "_bns_should_hold_internal_status", return_value=True):
			patched(doc, False, None, True, **{FUTURE: 3})  # recompute: BNS holds its status
			self.assertEqual(doc.status, "BNS Internally Transferred")
			patched(doc, status="Cancelled")  # explicit status: respected
			self.assertEqual(doc.status, "Cancelled")
		self.assertEqual(recorder.calls[0], ((doc, False, None, True), {FUTURE: 3}))

	def test_installed_patches_accept_erpnext_signatures(self):
		"""Every installed BNS patch accepts the full current ERPNext signature."""
		ba_utils.apply_bns_runtime_patches()
		warehouse_negative_stock.apply_patches()
		for owner, name, gated in _installed_patches():
			original = getattr(gated, "_bns_original", None)
			replacement = getattr(gated, "__wrapped__", None)
			if not (original and replacement):
				continue
			with self.subTest(patch=f"{getattr(owner, '__name__', owner)}.{name}"):
				_assert_accepts(self, replacement, original)


def _installed_patches():
	import erpnext.stock.stock_ledger as sl
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
	from erpnext.controllers.buying_controller import BuyingController
	from erpnext.controllers.stock_controller import StockController
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
	from erpnext.stock.doctype.repost_item_valuation import repost_item_valuation as riv

	targets = [
		(sl, "make_entry"),
		(sl, "validate_negative_qty_in_future_sle"),
		(sl.update_entries_after, "validate_negative_stock"),
		(sl.update_entries_after, "process_sle"),
		(sl.update_entries_after, "get_incoming_outgoing_rate_from_transaction"),
		(StockController, "get_gl_entries"),
		(PurchaseReceipt, "get_gl_entries"),
		(PurchaseInvoice, "get_gl_entries"),
		(SalesInvoice, "get_gl_entries"),
		(riv, "repost_gl_entries"),
		(riv, "notify_error_to_stock_managers"),
		(BuyingController, "process_fixed_asset"),
		(SalesInvoice, "process_asset_depreciation"),
		(SalesInvoice, "set_status"),
		(PurchaseInvoice, "set_status"),
	]
	for owner, name in targets:
		fn = owner.__dict__.get(name) if isinstance(owner, type) else getattr(owner, name, None)
		if fn is not None:
			yield owner, name, fn


def _assert_accepts(case, replacement, original):
	"""The replacement binds every way the original can be called."""
	orig = inspect.signature(original)
	repl = inspect.signature(replacement)
	positional, keywords = [], {}
	for p in orig.parameters.values():
		if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
			continue
		if p.kind == p.KEYWORD_ONLY:
			keywords[p.name] = object()
		else:
			positional.append(object())
	try:
		repl.bind(*positional, **keywords)  # all positional
		first = [object()] if positional else []
		named = {
			p.name: object()
			for p in list(orig.parameters.values())[1:]
			if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.POSITIONAL_ONLY)
		}
		repl.bind(*first, **named)  # first positional, rest by name
	except TypeError as e:
		case.fail(f"replacement{repl} cannot take a call to original{orig}: {e}")


if __name__ == "__main__":
	unittest.main()
