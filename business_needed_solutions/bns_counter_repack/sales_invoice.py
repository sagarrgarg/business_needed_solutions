"""Sales Invoice doc_events for BNS Counter Repack. The arithmetic lives in counter_repack.py."""

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money

from business_needed_solutions.bns_counter_repack import counter_repack as cr
from business_needed_solutions.business_needed_solutions.overrides import stock_value_conservation as svc

TITLE = _("Counter Repack")


def validate_invoice(invoice, method=None) -> None:
	"""validate: everything that can be checked before stock is touched, so the counter sees it on save."""
	rows = cr.flagged_rows(invoice)
	if not rows:
		return
	if cint(invoice.get("is_return")):
		frappe.throw(_("A return cannot repack from bulk. Untick Repack from Bulk on its rows."), title=TITLE)
	if not cint(invoice.get("update_stock")):
		frappe.throw(
			_("Repack from Bulk moves stock at submit, so the invoice needs Update Stock ticked."),
			title=TITLE,
		)
	rule = svc.get_active_rule(invoice.company, invoice.posting_date)
	if not rule or not cint(rule.get("apply_to_repack")):
		frappe.throw(
			_(
				"Repack from Bulk needs Stock Value Conservation switched on for {0} and for Repack, "
				"effective on {1} (BNS Settings → Manufacturing). It balances the leftover lot."
			).format(frappe.bold(invoice.company), frappe.format(invoice.posting_date, "Date")),
			title=TITLE,
		)
	for row in rows:
		_rule_for(invoice, row)


def create_repacks(invoice, method=None) -> None:
	"""before_submit: post one repack per (bulk item, warehouse), ahead of the invoice's own stock
	ledger entries, and link it on every row it serves.

	Runs in the invoice's transaction: if anything after this fails, the repacks roll back with it.
	"""
	rows = cr.flagged_rows(invoice)
	if not rows:
		return
	validate_invoice(invoice)
	rules = {row.name: _rule_for(invoice, row) for row in rows}
	currency = frappe.get_cached_value("Company", invoice.company, "default_currency")

	def fmt(value):
		return fmt_money(value, currency=currency)

	for group in cr.plan(invoice, rules):
		lot = _position(group.bulk_item, group.warehouse, invoice, lock=True)
		held = {
			line.sold_item: _position(line.sold_item, group.warehouse, invoice).qty for line in group.lines
		}
		cr.check_group(group, lot, held, fmt)

		repack = frappe.get_doc(cr.stock_entry_dict(invoice, group, lot))
		# Whoever may submit this stock-updating invoice may move its stock; the repack is part of it.
		repack.flags.ignore_permissions = True
		repack.insert()
		repack.submit()
		for line in group.lines:
			line.row.bns_counter_repack_entry = repack.name


def cancel_repacks(invoice, method=None) -> None:
	"""on_cancel: the invoice has already put the sold grades back; now undo the repacks that made them."""
	names = sorted(
		{d.get("bns_counter_repack_entry") for d in invoice.get("items") if d.get("bns_counter_repack_entry")}
	)
	for name in names:
		repack = frappe.get_doc("Stock Entry", name)
		if repack.docstatus == 1:
			repack.flags.ignore_permissions = True
			repack.cancel()


def _rule_for(invoice, row):
	from business_needed_solutions.bns_counter_repack.doctype.bns_counter_repack_rule.bns_counter_repack_rule import (
		bulk_is_moving_average,
		bulk_valuation_message,
	)

	rule = cr.get_rule(invoice.company, row.item_code, invoice.posting_date)
	if not rule:
		frappe.throw(
			_("Row {0}: no Counter Repack Rule for {1} effective on {2}.").format(
				row.idx, frappe.bold(row.item_code), frappe.format(invoice.posting_date, "Date")
			),
			title=TITLE,
		)
	# Re-checked here because an item with no transactions can still be switched back to FIFO.
	if not bulk_is_moving_average(rule.bulk_item):
		frappe.throw(bulk_valuation_message(rule.bulk_item), title=TITLE)
	return rule


def _position(item_code: str, warehouse: str, invoice, lock: bool = False):
	"""Quantity and value of an item in a warehouse at the invoice's posting time."""
	from erpnext.stock.stock_ledger import get_previous_sle

	sle = get_previous_sle(
		{
			"item_code": item_code,
			"warehouse": warehouse,
			"posting_date": invoice.posting_date,
			"posting_time": invoice.posting_time,
		},
		for_update=lock,
	)
	return frappe._dict(qty=flt(sle.get("qty_after_transaction")), value=flt(sle.get("stock_value")))
