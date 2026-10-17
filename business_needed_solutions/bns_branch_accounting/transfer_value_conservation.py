# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""
Transfer value conservation inside ERPNext's stock ledger engine.

An internal receipt (BNS DN->PR, SI->PI) must bring goods in at the value the sender
shipped them at: actual_qty x bns_transfer_rate. The BNS GL rewrite books the receipt's
Stock-in-Transit leg from the receipt's stock_value_difference, so that value has to equal
the sender's for Stock-in-Transit to net to zero across the transfer.

ERPNext prices the row with the transfer rate as its incoming rate, but when the bin was
negative before the receipt, its step is not actual_qty x rate: the negative balance is
settled at its old rate. BNS used to overwrite stock_value_difference after the engine
had run. That left stock_value behind, broke "difference == stock_value - previous
stock_value" for the row, and every repost undid it again.

This module applies the difference inside the engine, right after ERPNext priced the row.
The row's stock value, its value difference, the valuation rate (or the FIFO/LIFO queue)
and every later row move together, so each row keeps difference == step, the GL equals the
chain, and Stock Balance equals the Trial Balance.

The difference is absorbed into the bin's rate only while the result is a valid rate:
non-negative, with the value's sign matching the quantity's. That keeps value == qty x rate
on every row and never hands a later outward row a positive value difference (which ERPNext
would turn into a sign-less outgoing rate, and which the BNS DN rewrite cannot post). When
full conservation would need an invalid rate (for example, a zero-cost transfer into a
negative bin that ends positive), the representable part is applied and the rest stays
where ERPNext put it. Those rows are logged and listed by
ledger_chain_repair.find_unconserved_transfer_receipts.

Serial/batch rows are left alone: their valuation paths add qty x incoming_rate
incrementally, so the receipt's step already equals the transfer value.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime

logger = logging.getLogger(__name__)

STOCK_LEDGER_ENTRY = "Stock Ledger Entry"
REPOST_ITEM_VALUATION = "Repost Item Valuation"

# A transfer-rate repost that keeps re-queuing itself means something else rewrites the rate;
# another repost will not fix it. Stop after this many per voucher per day and log it instead.
AUTO_REPOST_DAILY_CAP = 5


@dataclass
class ConservationPlan:
	"""What the engine must change on a priced row. ``applied`` is the value moved into the
	running balance; ``residual`` is the part of the transfer value that could not be."""

	applied: float
	residual: float
	stock_value: float = 0.0
	stock_value_difference: float = 0.0
	valuation_rate: float = 0.0
	stock_queue: list | None = None  # None: queue unchanged (Moving Average)


# --------------------------------------------------------------------------------------
# Pure planning (no DB) — unit tested directly.
# --------------------------------------------------------------------------------------


def plan_transfer_value_conservation(
	*,
	qty_after: float,
	stock_value: float,
	stock_value_difference: float,
	conserved_value: float,
	valuation_method: str,
	stock_queue: list | None,
	precision: int,
) -> ConservationPlan | None:
	"""Plan the change that makes a priced row's value difference equal ``conserved_value``.

	``qty_after``, ``stock_value`` and ``stock_value_difference`` are the row as ERPNext just
	priced it. Returns None when the row already carries the conserved value.
	"""
	delta = flt(flt(conserved_value, precision) - flt(stock_value_difference, precision), precision)
	if not delta:
		return None

	value = flt(stock_value, precision)
	applied = _representable_part(delta, flt(qty_after), value)

	new_queue = None
	if applied and valuation_method in ("FIFO", "LIFO"):
		new_queue, applied = _absorb_into_queue(stock_queue, applied, flt(qty_after))
		if new_queue is None:
			applied = 0.0

	applied = flt(applied, precision)
	residual = flt(delta - applied, precision)
	if not applied:
		return ConservationPlan(applied=0.0, residual=residual)

	new_value = flt(value + applied, precision)
	return ConservationPlan(
		applied=applied,
		residual=residual,
		stock_value=new_value,
		stock_value_difference=flt(flt(stock_value_difference, precision) + applied, precision),
		# Same formula ERPNext uses after every row: value / quantity.
		valuation_rate=new_value / flt(qty_after),
		stock_queue=new_queue,
	)


def _representable_part(delta: float, qty_after: float, value: float) -> float:
	"""The part of ``delta`` the bin can hold while its value keeps the quantity's sign.

	Always the same sign as ``delta`` and never larger, so a clamp only ever conserves
	less, never something different.
	"""
	if qty_after > 0:
		if value < 0:  # already not representable; do not build on it
			return 0.0
		return delta if value + delta >= 0 else -value
	if qty_after < 0:
		if value > 0:
			return 0.0
		return delta if value + delta <= 0 else -value
	return 0.0  # a zero balance must carry zero value


def _absorb_into_queue(queue, applied: float, qty_after: float):
	"""Move ``applied`` of value into FIFO/LIFO bins without driving any rate negative.

	Returns (new_queue, absorbed). ``absorbed`` has the sign of ``applied`` and is never
	larger. Returns (None, 0) when the queue cannot take value consistently.
	"""
	bins = [[flt(b[0]), flt(b[1])] for b in (queue or []) if b and len(b) >= 2]
	if not bins:
		return None, 0.0

	if qty_after > 0:
		if any(qty < 0 or rate < 0 for qty, rate in bins):
			return None, 0.0
		if applied > 0:
			# The newest lot (end of the FIFO queue / top of the LIFO stack) is the receipt.
			if bins[-1][0] <= 0:
				return None, 0.0
			bins[-1][1] += applied / bins[-1][0]
			return bins, applied
		remaining = applied
		for b in reversed(bins):  # newest first, each lot down to a zero rate at most
			if remaining >= 0:
				break
			qty, rate = b
			if qty <= 0 or rate <= 0:
				continue
			take = max(remaining, -qty * rate)
			b[1] = max(rate + take / qty, 0.0)
			remaining -= take
		return bins, applied - remaining

	# Negative balance: ERPNext keeps it as one negative bin at the end.
	qty, rate = bins[-1]
	if qty >= 0 or rate < 0:
		return None, 0.0
	if applied > 0:
		applied = min(applied, -qty * rate)  # keep the bin's value <= 0, so its rate >= 0
		if applied <= 0:
			return None, 0.0
	bins[-1][1] = rate + applied / qty
	return bins, applied


# --------------------------------------------------------------------------------------
# Engine side — called from the BNS patch of update_entries_after.process_sle.
# --------------------------------------------------------------------------------------


def conserve_transfer_value_in_engine(engine, sle, transfer_rate, svd_before, doctype_before) -> None:
	"""Make the row ERPNext just priced carry actual_qty x transfer_rate, keeping the chain.

	``svd_before`` and ``doctype_before`` are the row's values captured before ERPNext ran.
	Works with both engine layouts: v15.123+/v16 carry the running state on the row itself
	(prev_sle_dict[key] = sle), older v15 on self.data[warehouse] (= engine.wh_data).
	"""
	if flt(sle.get("actual_qty")) <= 0 or transfer_rate is None:
		return
	if not _row_was_priced(engine, sle, doctype_before):
		return  # ERPNext returned early (e.g. negative stock not allowed); nothing to adjust
	if cint(sle.get("is_cancelled")):
		return
	if sle.get("serial_and_batch_bundle") or sle.get("serial_no") or sle.get("batch_no"):
		return  # incremental valuation paths already step by qty x incoming_rate

	precision = _currency_precision(engine)
	conserved = flt(flt(sle.get("actual_qty")) * flt(transfer_rate), precision)
	try:
		plan = plan_transfer_value_conservation(
			qty_after=flt(sle.get("qty_after_transaction")),
			stock_value=flt(sle.get("stock_value")),
			stock_value_difference=flt(sle.get("stock_value_difference")),
			conserved_value=conserved,
			valuation_method=_valuation_method(engine, sle),
			stock_queue=_load_queue(sle.get("stock_queue")),
			precision=precision,
		)
	except Exception:
		# A planning bug must not break reposting: the row keeps ERPNext's own consistent values.
		frappe.log_error(
			title=f"BNS transfer value conservation failed: {sle.get('voucher_type')} {sle.get('voucher_no')}",
			message=frappe.get_traceback(),
		)
		return

	if not plan:
		return
	if plan.residual:
		logger.warning(
			"BNS transfer value not fully conserved on %s (%s %s, %s @ %s): residual %s "
			"(applying it would need an invalid rate for qty %s)",
			sle.get("name"),
			sle.get("voucher_type"),
			sle.get("voucher_no"),
			sle.get("item_code"),
			sle.get("warehouse"),
			plan.residual,
			sle.get("qty_after_transaction"),
		)
	if not plan.applied:
		return

	# Persist first: if the write fails, nothing in memory has moved and the chain stays intact.
	_persist_row(sle.get("name"), plan)
	_apply_in_memory(engine, sle, plan)
	_flag_gl_repost(engine, sle, svd_before, precision)


def _row_was_priced(engine, sle, doctype_before) -> bool:
	key = (sle.get("item_code"), sle.get("warehouse"))
	prev_sle_dict = getattr(engine, "prev_sle_dict", None)
	if isinstance(prev_sle_dict, dict) and prev_sle_dict.get(key) is sle:
		return True  # v15.123+/v16: the priced row becomes the next row's previous entry
	# Older v15 marks the row just before writing it.
	return doctype_before != STOCK_LEDGER_ENTRY and sle.get("doctype") == STOCK_LEDGER_ENTRY


def _currency_precision(engine) -> int:
	precision = getattr(engine, "currency_precision", None)
	if precision is None:
		from frappe.model.meta import get_field_precision

		precision = get_field_precision(frappe.get_meta(STOCK_LEDGER_ENTRY).get_field("stock_value"))
	return cint(precision) or 2


def _valuation_method(engine, sle) -> str:
	method = getattr(engine, "valuation_method", None)
	if method:
		return method
	from erpnext.stock.utils import get_valuation_method

	try:
		return get_valuation_method(sle.get("item_code"), sle.get("company"))
	except TypeError:  # older signature: (item_code)
		return get_valuation_method(sle.get("item_code"))


def _load_queue(raw):
	if not raw:
		return []
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except ValueError:
			return []
	return raw if isinstance(raw, list) else []


def _persist_row(sle_name, plan: ConservationPlan) -> None:
	table = frappe.qb.DocType(STOCK_LEDGER_ENTRY)
	query = (
		frappe.qb.update(table)
		.set(table.stock_value, plan.stock_value)
		.set(table.stock_value_difference, plan.stock_value_difference)
		.set(table.valuation_rate, plan.valuation_rate)
	)
	if plan.stock_queue is not None:
		query = query.set(table.stock_queue, json.dumps(plan.stock_queue))
	# Same guard as ERPNext: never revive an entry cancelled while the repost was running.
	query.where((table.name == sle_name) & (table.is_cancelled == 0)).run()


def _apply_in_memory(engine, sle, plan: ConservationPlan) -> None:
	holders = [sle]
	wh_data = getattr(engine, "wh_data", None)
	if wh_data is not None and wh_data is not sle:
		holders.append(wh_data)
	for holder in holders:
		holder.stock_value = plan.stock_value
		holder.valuation_rate = plan.valuation_rate
		holder.prev_stock_value = plan.stock_value
		if plan.stock_queue is not None:
			queue = [list(b) for b in plan.stock_queue]
			# The row stores its queue as JSON (the next row json.loads it); wh_data keeps a list.
			holder.stock_queue = json.dumps(queue) if holder is sle else queue
	sle.stock_value_difference = plan.stock_value_difference


def _flag_gl_repost(engine, sle, svd_before, precision: int) -> None:
	"""ERPNext only queues a GL repost for a dependent voucher when its own pricing changed the
	row. Ours may have changed it on top of that, so flag it the same way."""
	if flt(sle.get("stock_value_difference"), precision) == flt(svd_before, precision):
		return
	affected = getattr(engine, "repost_affected_transaction", None)
	if not isinstance(affected, set):
		return  # older v15 records every processed voucher up front
	args = getattr(engine, "args", None) or {}
	if args.get("item_code") == sle.get("item_code") and args.get("warehouse") == sle.get("warehouse"):
		return  # the repost's own item-warehouse: its vouchers are reposted as directly dependent
	import erpnext

	if not cint(erpnext.is_perpetual_inventory_enabled(sle.get("company"))):
		return
	affected.add((sle.get("voucher_type"), sle.get("voucher_no")))


# --------------------------------------------------------------------------------------
# Repost queueing — replaces the hand-written SLE overwrite in the transfer-rate syncs.
# --------------------------------------------------------------------------------------


def rate_precision() -> int:
	from frappe.model.meta import get_field_precision

	return cint(get_field_precision(frappe.get_meta(STOCK_LEDGER_ENTRY).get_field("incoming_rate"))) or 9


def queue_transfer_rate_repost(voucher_type: str, voucher_no: str, *, context: str = "") -> bool:
	"""Queue one Transaction-based Repost Item Valuation for ``voucher``, at most once at a time.

	Returns True when a repost was queued. Skips when one is already pending for the voucher,
	and stops (logging an error) after AUTO_REPOST_DAILY_CAP reposts in 24 hours, which would
	mean the rate is being rewritten somewhere a repost cannot fix.
	"""
	base = {"voucher_type": voucher_type, "voucher_no": voucher_no, "docstatus": 1}
	if frappe.db.exists(REPOST_ITEM_VALUATION, {**base, "status": ("in", ("Queued", "In Progress"))}):
		return False

	since = add_to_date(now_datetime(), hours=-24)
	if frappe.db.count(REPOST_ITEM_VALUATION, {**base, "creation": (">=", since)}) >= AUTO_REPOST_DAILY_CAP:
		frappe.log_error(
			title=f"BNS transfer-rate repost cap reached: {voucher_type} {voucher_no}",
			message=(
				f"{AUTO_REPOST_DAILY_CAP} reposts in 24 hours did not settle the transfer rate on "
				f"{voucher_type} {voucher_no} (context: {context}). Check what rewrites its "
				"incoming rate; no further automatic repost will be queued today."
			),
		)
		return False

	doc = frappe.db.get_value(
		voucher_type, voucher_no, ["posting_date", "posting_time", "company", "docstatus"], as_dict=True
	)
	if not doc or doc.docstatus != 1:
		return False

	from erpnext.controllers.stock_controller import create_repost_item_valuation_entry

	savepoint = "bns_transfer_rate_repost"
	frappe.db.savepoint(savepoint)
	try:
		create_repost_item_valuation_entry(
			{
				"based_on": "Transaction",
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
				"posting_date": doc.posting_date,
				"posting_time": doc.posting_time or "00:00:00",
				"company": doc.company,
				"allow_zero_rate": 1,
			}
		)
	except Exception:
		if _in_test():
			raise
		# The stale rate stays visible (SLE incoming_rate != transfer rate), so the next sync or
		# the chain repair tool retries. Never fail the submit / repost hook that called us.
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(
			title=f"BNS transfer-rate repost could not be queued: {voucher_type} {voucher_no}",
			message=frappe.get_traceback(),
		)
		return False

	logger.info("Queued transfer-rate repost for %s %s (%s)", voucher_type, voucher_no, context)
	return True


def _in_test() -> bool:
	return bool(getattr(frappe, "in_test", False) or frappe.flags.in_test)
