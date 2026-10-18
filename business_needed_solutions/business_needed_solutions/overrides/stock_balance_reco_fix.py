"""
Runtime fix for ERPNext's Stock Balance report losing Stock Reconciliation quantities.

Bug: erpnext commit ec0a515d (10 Oct 2026, "keep dimension rows of a reconciliation
as deltas in Stock Balance", shipped in v15.123.0) guards the reconciliation branch of
``StockBalanceReport.prepare_item_warehouse_map`` with ``len(group_by_key) == 2``.
``get_group_by_key`` returns ``(company, item_code, warehouse)`` -- three parts -- so
the branch never runs. Every reconciliation row then falls through as a plain delta of
``actual_qty`` (always 0 on a reconciliation row) and the balance the reconciliation
set is lost. Values are unaffected because they flow through ``stock_value_difference``.

Observed: an item reconciled twice (+110 each) shows a closing quantity of -220 in
Stock Balance while Stock Ledger and Bin agree on 0. At one dispatch warehouse 312 of
353 report rows disagreed with Bin; every one of them had a reconciliation.

Fix: the same branch with ``len(group_by_key) == 3``. A key with no inventory-dimension
part means the row is the whole item-warehouse balance, which is what a
reconciliation's ``qty_after_transaction`` states; dimension-split rows (longer key)
keep upstream's delta treatment, which was the point of the upstream commit.

Self-retiring: the method is replaced only while the installed source still contains
the buggy test, so an upstream correction takes over without a code change here.

v15 only: ERPNext v16 keys the map by ``(item_code, warehouse)``, so ``== 2`` is correct
there, and its method has a different signature ``(self, entry, group_by_key)``. The
replacement is installed only on the v15 method shape (it takes ``item_warehouse_map``);
installing it on v16 broke the report with a TypeError.

Remove when: ERPNext fixes the condition upstream and every site runs that release.
Affected file: erpnext/stock/report/stock_balance/stock_balance.py
Affected method: StockBalanceReport.prepare_item_warehouse_map
"""

import inspect

from frappe.utils import flt

_PATCHED = False
_BUG_MARKER = "len(group_by_key) == 2"


def prepare_item_warehouse_map(self, item_warehouse_map, entry, group_by_key):
	"""v15.123.0 body with the reconciliation guard corrected to a three-part key."""
	qty_dict = item_warehouse_map[group_by_key]
	for field in self.inventory_dimensions:
		qty_dict[field] = entry.get(field)

	# An adjustment entry only writes off stock value that is stranded on an item with no
	# quantity left; it moves nothing. Its qty_after_transaction and stock_value are therefore
	# not a statement of the balance the way a real reconciliation's are, and the write-off it
	# carries lives solely in stock_value_difference. Treat it as the plain delta it is.
	if (
		entry.voucher_type == "Stock Reconciliation"
		and not entry.is_adjustment_entry
		and (not entry.batch_no or entry.serial_no or entry.serial_and_batch_bundle)
		and len(group_by_key) == 3
	):
		if entry.serial_no and entry.voucher_detail_no in self.stock_reco_voucher_wise_count:
			qty_dict.opening_qty -= self.stock_reco_voucher_wise_count.get(entry.voucher_detail_no, 0)
			qty_dict.bal_qty = 0.0
			qty_diff = flt(entry.actual_qty)
			value_diff = flt(entry.stock_value_difference)
		else:
			qty_diff = flt(entry.qty_after_transaction) - flt(qty_dict.bal_qty)
			value_diff = flt(entry.stock_value) - flt(qty_dict.bal_val)
	else:
		qty_diff = flt(entry.actual_qty)
		value_diff = flt(entry.stock_value_difference)

	if entry.posting_date < self.from_date or entry.voucher_no in self.opening_vouchers.get(
		entry.voucher_type, []
	):
		qty_dict.opening_qty += qty_diff
		qty_dict.opening_val += value_diff

	elif entry.posting_date >= self.from_date and entry.posting_date <= self.to_date:
		if flt(qty_diff, self.float_precision) >= 0:
			qty_dict.in_qty += qty_diff
		else:
			qty_dict.out_qty += abs(qty_diff)

		if flt(value_diff, self.float_precision) >= 0:
			qty_dict.in_val += value_diff
		else:
			qty_dict.out_val += abs(value_diff)

	qty_dict.val_rate = entry.valuation_rate
	qty_dict.bal_qty += qty_diff
	qty_dict.bal_val += value_diff


def installed_method_has_bug(report_cls=None) -> bool:
	"""True while the installed ERPNext still carries the two-part key test."""
	if report_cls is None:
		from erpnext.stock.report.stock_balance.stock_balance import StockBalanceReport

		report_cls = StockBalanceReport
	method = getattr(report_cls, "prepare_item_warehouse_map", None)
	if method is None or getattr(method, "_bns_patched", False):
		return False
	try:
		# The v15 shape (three-part key, buggy == 2) takes item_warehouse_map; v16's does not.
		if "item_warehouse_map" not in inspect.signature(method).parameters:
			return False
		return _BUG_MARKER in inspect.getsource(method)
	except (OSError, TypeError, ValueError):
		return False


def apply_stock_balance_reco_fix() -> None:
	"""Monkey-patch the report class in this process, once, and only while the bug is present."""
	global _PATCHED
	if _PATCHED:
		return
	try:
		from erpnext.stock.report.stock_balance.stock_balance import StockBalanceReport
	except ImportError:
		return

	if installed_method_has_bug(StockBalanceReport):
		prepare_item_warehouse_map._bns_patched = True
		StockBalanceReport.prepare_item_warehouse_map = prepare_item_warehouse_map
	_PATCHED = True
