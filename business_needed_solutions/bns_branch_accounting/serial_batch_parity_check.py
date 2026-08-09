# Copyright (c) 2026, Sagar Garg and Contributors
# License: GNU General Public License v3. See license.txt

"""Strict 1-to-1 serial/batch parity ENFORCEMENT for BNS internal-transfer receivers.

This complements `utils.ensure_internal_batch_bundle_mapping` (which AUTO-FILLS the
receiver's Serial and Batch Bundle at validate time). That mapping only fills when
the receiver is empty; it does not block a receiver whose batch/serial was manually
set to something other than what was dispatched.

This guard runs at `before_submit` on Purchase Receipt / Purchase Invoice and, for
every serial/batch-tracked internal-transfer line, requires the receiver's serials /
batch-qty to be an EXACT 1-to-1 match of the source (DN/SI) row. Any missing/extra
serial or batch, or a batch-qty difference, is a hard error.

Source resolution reuses `_resolve_source_item_for_batch_mapping` so the check keys
off the same source row the auto-fill used. Sender bundles are Outward (negative qty)
and receiver bundles Inward (positive), so batch quantities compare on absolute value.
"""

import frappe
from frappe import _, bold
from frappe.utils import flt

_QTY_TOLERANCE = 0.0001


def enforce_internal_batch_serial_parity(doc, method=None):
	"""before_submit guard on Purchase Receipt / Purchase Invoice."""
	from business_needed_solutions.bns_branch_accounting.utils import (
		_resolve_source_item_for_batch_mapping,
		is_bns_internal_supplier,
	)

	if not is_bns_internal_supplier(doc):
		return

	for item in doc.get("items") or []:
		has_serial, has_batch = _tracking(item.item_code)
		if not (has_serial or has_batch):
			continue

		source_item = _resolve_source_item_for_batch_mapping(doc, item)
		if not source_item:
			continue

		src_serials, src_batches = _extract(source_item, has_serial, has_batch)
		if not src_serials and not src_batches:
			# Source itself carries no serial/batch (e.g. tracking enabled later) - nothing to enforce.
			continue

		tgt_serials, tgt_batches = _extract(item, has_serial, has_batch)
		_assert_serial_parity(item, src_serials, tgt_serials)
		_assert_batch_parity(item, src_batches, tgt_batches)


def _tracking(item_code):
	meta = frappe.get_cached_value("Item", item_code, ["has_serial_no", "has_batch_no"], as_dict=True) or {}
	return bool(meta.get("has_serial_no")), bool(meta.get("has_batch_no"))


def _split_serials(text):
	return {s.strip() for s in (text or "").replace(",", "\n").split("\n") if s.strip()}


def _extract(row_like, has_serial, has_batch):
	"""Return (set_of_serials, {batch_no: abs_qty}) from a doc/row (bundle or legacy)."""
	serials = set()
	batches = {}
	bundle = row_like.get("serial_and_batch_bundle")

	if bundle:
		if has_serial:
			from erpnext.stock.serial_batch_bundle import get_serial_nos_from_bundle

			serials = set(get_serial_nos_from_bundle(bundle) or [])
		if has_batch:
			from erpnext.stock.serial_batch_bundle import get_batches_from_bundle

			for batch_no, qty in (get_batches_from_bundle(bundle) or {}).items():
				batches[batch_no] = batches.get(batch_no, 0.0) + abs(flt(qty))
	else:
		if has_serial and row_like.get("serial_no"):
			serials = _split_serials(row_like.get("serial_no"))
		if has_batch and row_like.get("batch_no"):
			qty = abs(flt(row_like.get("stock_qty") or row_like.get("qty")))
			batches[row_like.get("batch_no")] = qty

	return serials, batches


def _assert_serial_parity(item, src, tgt):
	if src == tgt:
		return
	parts = []
	if src - tgt:
		parts.append(_("missing on receiver: {0}").format(_fmt(src - tgt)))
	if tgt - src:
		parts.append(_("not on source: {0}").format(_fmt(tgt - src)))
	frappe.throw(
		_("Row {0} ({1}): serial numbers must match the transferred document one-to-one - {2}.").format(
			item.idx, bold(item.item_code), "; ".join(parts)
		),
		title=_("Serial Parity Failed"),
	)


def _assert_batch_parity(item, src, tgt):
	if set(src) != set(tgt):
		parts = []
		if set(src) - set(tgt):
			parts.append(_("missing on receiver: {0}").format(_fmt(set(src) - set(tgt))))
		if set(tgt) - set(src):
			parts.append(_("not on source: {0}").format(_fmt(set(tgt) - set(src))))
		frappe.throw(
			_("Row {0} ({1}): batches must match the transferred document one-to-one - {2}.").format(
				item.idx, bold(item.item_code), "; ".join(parts)
			),
			title=_("Batch Parity Failed"),
		)

	for batch_no in src:
		if abs(flt(src[batch_no]) - flt(tgt[batch_no])) > _QTY_TOLERANCE:
			frappe.throw(
				_("Row {0} ({1}): batch {2} quantity {3} does not match the transferred quantity {4}.").format(
					item.idx, bold(item.item_code), bold(batch_no), flt(tgt[batch_no]), flt(src[batch_no])
				),
				title=_("Batch Parity Failed"),
			)


def _fmt(values):
	values = list(values)
	shown = ", ".join(values[:5])
	if len(values) > 5:
		shown += _(" (+{0} more)").format(len(values) - 5)
	return shown
