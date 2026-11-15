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

        src = _extract(source_item, has_serial, has_batch)
        if not src.serials and not src.batches:
            # Source itself carries no serial/batch (e.g. tracking enabled later) - nothing to enforce.
            continue

        tgt = _extract(item, has_serial, has_batch)
        _assert_serial_parity(item, src.serials, tgt.serials)
        _assert_batch_parity(item, src.batches, tgt.batches)
        if has_serial and has_batch:
            _assert_serial_batch_pairs(item, src.serial_batch, tgt.serial_batch)


def _tracking(item_code):
    meta = frappe.get_cached_value("Item", item_code, ["has_serial_no", "has_batch_no"], as_dict=True) or {}
    return bool(meta.get("has_serial_no")), bool(meta.get("has_batch_no"))


def _split_serials(text):
    return {s.strip() for s in (text or "").replace(",", "\n").split("\n") if s.strip()}


def _extract(row_like, has_serial, has_batch):
    """Return frappe._dict(serials=set, batches={batch_no: abs_qty}, serial_batch={serial_no: batch_no}).

    Bundle rows are read straight from `Serial and Batch Entry` and summed here.
    ERPNext's `get_batches_from_bundle` (v15 and v16) returns `frappe._dict(entries)`,
    which keeps only the LAST entry per batch: a serial+batch bundle has one entry per
    serial, so the per-batch qty collapses to one serial's qty and a serial moved to a
    different batch is invisible. Summing the rows ourselves gives the real batch qty
    and the serial -> batch pairing.
    """
    serials = set()
    batches = {}
    serial_batch = {}
    bundle = row_like.get("serial_and_batch_bundle")

    if bundle:
        for entry in _bundle_entries(bundle):
            serial_no = (entry.get("serial_no") or "").strip()
            batch_no = (entry.get("batch_no") or "").strip()
            if has_serial and serial_no:
                serials.add(serial_no)
                if has_batch and batch_no:
                    serial_batch[serial_no] = batch_no
            if has_batch and batch_no:
                batches[batch_no] = batches.get(batch_no, 0.0) + abs(flt(entry.get("qty")))
    else:
        legacy_batch = (row_like.get("batch_no") or "").strip() if has_batch else ""
        if has_serial and row_like.get("serial_no"):
            serials = _split_serials(row_like.get("serial_no"))
            if legacy_batch:
                serial_batch = {s: legacy_batch for s in serials}
        if legacy_batch:
            batches[legacy_batch] = abs(flt(row_like.get("stock_qty") or row_like.get("qty")))

    return frappe._dict(serials=serials, batches=batches, serial_batch=serial_batch)


def _bundle_entries(bundle):
    return frappe.get_all(
        "Serial and Batch Entry",
        filters={"parent": bundle},
        fields=["serial_no", "batch_no", "qty"],
        order_by="idx",
    )


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

    # Strict batch-qty equality is safe because BNS forbids partial internal receipts
    # (validate_internal_purchase_receipt_linkage / _validate_internal_pr_one_to_one_parity
    # already require receiver qty == source qty 1-to-1). If partial internal receipts are
    # ever allowed, this must relax to receiver-qty <= source-qty per batch.
    for batch_no in src:
        if abs(flt(src[batch_no]) - flt(tgt[batch_no])) > _QTY_TOLERANCE:
            frappe.throw(
                _("Row {0} ({1}): batch {2} quantity {3} does not match the transferred quantity {4}.").format(
                    item.idx, bold(item.item_code), bold(batch_no), flt(tgt[batch_no]), flt(src[batch_no])
                ),
                title=_("Batch Parity Failed"),
            )


def _assert_serial_batch_pairs(item, src, tgt):
    """Each serial must arrive in the batch it left in (serial+batch items)."""
    moved = sorted(
        f"{serial_no} ({src[serial_no]} -> {tgt[serial_no]})"
        for serial_no in set(src) & set(tgt)
        if src[serial_no] != tgt[serial_no]
    )
    if not moved:
        return
    frappe.throw(
        _("Row {0} ({1}): serial numbers must stay in the batch they were transferred in - {2}.").format(
            item.idx, bold(item.item_code), _fmt(moved)
        ),
        title=_("Batch Parity Failed"),
    )


def _fmt(values):
    values = list(values)
    shown = ", ".join(values[:5])
    if len(values) > 5:
        shown += _(" (+{0} more)").format(len(values) - 5)
    return shown
