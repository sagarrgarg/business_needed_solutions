"""
BNS Counter Repack — sort a grade out of a bulk lot at the moment it is billed.

Hing is bought as one bulk item (A) whose lots range from about ₹1,000 to ₹30,000 per kg, so A's
book rate is an average of everything bought. At the counter the customer sorts or mixes grades and
takes them; the invoice names the grade sold (B). Book cost is the one thing the business knows
for sure: a fixed margin per product. So when a Sales Invoice row has Repack from Bulk ticked, a
Repack is posted just before the invoice's own stock ledger entries:

	A out  (the whole remaining lot in that warehouse)
	B in   (the sold quantity, at net rate x (1 - margin %), typed)
	A in   (the rest of the lot, as the plug: whatever value A had, less B's cost)

The invoice then sells B at exactly that cost, so its gross margin is the configured margin, and
the lot keeps the rest of the value. Nothing reaches Stock Adjustment: the plug is the same one
Stock Value Conservation uses (overrides/stock_value_conservation.py), which also re-derives it on
every repost.

Why the whole lot and not just what the customer handled: the value arithmetic is the same for any
quantity, but only the whole lot keeps the leftover's rate near the lot's average. A small
leftover would carry an extreme or negative rate, and the usual case — the customer takes all of
what they picked — would leave no leftover to plug at all.
"""

from collections import OrderedDict

import frappe
from frappe import _
from frappe.utils import cint, flt


def get_rule(company: str, sold_item: str, posting_date):
	"""The rule for this sold item that covers posting_date: the latest effective one."""
	rules = frappe.get_all(
		"BNS Counter Repack Rule",
		filters={
			"company": company,
			"sold_item": sold_item,
			"disabled": 0,
			"effective_from": ("<=", posting_date),
		},
		fields=["name", "bulk_item", "margin_percent", "bulk_qty_per_unit", "effective_from"],
		order_by="effective_from desc",
		limit=1,
	)
	return rules[0] if rules else None


def flagged_rows(invoice) -> list:
	return [d for d in invoice.get("items") if cint(d.get("bns_counter_repack"))]


def unit_cost(row, margin_percent: float) -> float:
	"""Cost per stock unit of the sold item: net rate (after discount, before tax, company currency)
	per stock unit, less the margin on the sale price."""
	per_stock_unit = flt(row.base_net_rate) / (flt(row.conversion_factor) or 1.0)
	return per_stock_unit * (1 - flt(margin_percent) / 100)


def is_internal_sale(invoice) -> bool:
	"""The invoice's own flag, or its customer's: the flag on the document is not always set."""
	if cint(invoice.get("is_bns_internal_customer")):
		return True
	customer = invoice.get("customer")
	return bool(customer and cint(frappe.get_cached_value("Customer", customer, "is_bns_internal_customer")))


def margin_for(invoice, rule) -> float:
	"""The rule's margin, or none on an internal sale: BNS values an internal sale's stock at its
	transfer rate, so the grade must come in at that rate or the gap lands on Stock Adjustment."""
	return 0.0 if is_internal_sale(invoice) else flt(rule.margin_percent)


def plan(invoice, rules: dict) -> list:
	"""Group the ticked rows into one repack per (bulk item, warehouse).

	One repack may carry only one plug, and the plug is the bulk item's leftover in that warehouse,
	so rows that draw on different lots need different repacks. rules maps row.name -> rule.
	"""
	groups: OrderedDict = OrderedDict()
	for row in flagged_rows(invoice):
		rule = rules[row.name]
		key = (rule.bulk_item, row.warehouse)
		group = groups.setdefault(
			key,
			frappe._dict(
				bulk_item=rule.bulk_item, warehouse=row.warehouse, lines=[], bulk_needed=0.0, cost=0.0
			),
		)
		qty = flt(row.stock_qty)
		rate = unit_cost(row, margin_for(invoice, rule))
		group.lines.append(frappe._dict(row=row, sold_item=row.item_code, qty=qty, rate=rate, rule=rule.name))
		group.bulk_needed += qty * flt(rule.bulk_qty_per_unit)
		group.cost += qty * rate
	return list(groups.values())


def check_group(group, lot, sold_item_stock: dict, fmt) -> None:
	"""Refuse the bill when the repack cannot be posted honestly.

	lot: the bulk item's qty and value in the warehouse at the posting time.
	sold_item_stock: sold item -> its qty in the warehouse at the posting time.
	fmt: money formatter.
	"""
	title = _("Counter Repack Not Possible")
	for line in group.lines:
		held = flt(sold_item_stock.get(line.sold_item))
		if held:
			frappe.throw(
				_(
					"Row {0}: {1} already has {2} in {3}. Counter repack creates this grade from the bulk "
					"lot and sells it at once, so its cost is exactly the margin cost only while it holds no "
					"stock of its own. Sell it from stock without Repack from Bulk, or clear that stock first."
				).format(line.row.idx, frappe.bold(line.sold_item), held, group.warehouse),
				title=title,
			)

	if flt(lot.qty) <= flt(group.bulk_needed):
		frappe.throw(
			_(
				"{0} in {1} has {2} in stock, but these rows need {3} of it and something must be left "
				"to carry the rest of the lot's value."
			).format(frappe.bold(group.bulk_item), group.warehouse, flt(lot.qty), flt(group.bulk_needed)),
			title=title,
		)

	leftover_value = flt(lot.value) - flt(group.cost)
	if leftover_value <= 0:
		frappe.throw(
			_(
				"{0} in {1} holds {2} of stock worth {3}. At the margins on its Counter Repack Rules this "
				"bill takes {4} of that value, which would leave {5}. The margins are too low for what "
				"this lot cost, or the lot's value is wrong: correct the rule or the lot before billing."
			).format(
				frappe.bold(group.bulk_item),
				group.warehouse,
				flt(lot.qty),
				fmt(lot.value),
				fmt(group.cost),
				fmt(leftover_value),
			),
			title=title,
		)


def stock_entry_dict(invoice, group, lot) -> dict:
	"""The repack: the whole lot out, each sold grade in at its margin cost, the rest of the lot back
	in as the plug (Set Basic Rate Manually unticked)."""
	items = [
		{
			"item_code": group.bulk_item,
			"s_warehouse": group.warehouse,
			"qty": flt(lot.qty),
			"transfer_qty": flt(lot.qty),
			"conversion_factor": 1,
		}
	]
	for line in group.lines:
		items.append(
			{
				"item_code": line.sold_item,
				"t_warehouse": group.warehouse,
				"qty": line.qty,
				"transfer_qty": line.qty,
				"conversion_factor": 1,
				"basic_rate": line.rate,
				"set_basic_rate_manually": 1,
				"is_finished_item": 1,
			}
		)
	items.append(
		{
			"item_code": group.bulk_item,
			"t_warehouse": group.warehouse,
			"qty": flt(lot.qty) - flt(group.bulk_needed),
			"transfer_qty": flt(lot.qty) - flt(group.bulk_needed),
			"conversion_factor": 1,
			"is_finished_item": 1,
		}
	)
	for d in items:
		d["uom"] = d["stock_uom"] = frappe.get_cached_value("Item", d["item_code"], "stock_uom")
	return {
		"doctype": "Stock Entry",
		"purpose": "Repack",
		"stock_entry_type": "Repack",
		"company": invoice.company,
		"set_posting_time": 1,
		"posting_date": invoice.posting_date,
		"posting_time": invoice.posting_time,
		"remarks": _("Counter repack for Sales Invoice {0}").format(invoice.name),
		"items": items,
	}
