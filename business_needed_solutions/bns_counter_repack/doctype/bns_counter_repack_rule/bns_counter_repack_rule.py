# Copyright (c) 2026, Sagar Ratan Garg and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class BNSCounterRepackRule(Document):
	def validate(self):
		title = _("Invalid Counter Repack Rule")
		if self.sold_item == self.bulk_item:
			frappe.throw(_("Sold Item and Bulk Item must be different items."), title=title)
		for field in ("sold_item", "bulk_item"):
			item = frappe.get_cached_value(
				"Item", self.get(field), ["is_stock_item", "has_batch_no", "has_serial_no"], as_dict=True
			)
			if not item or not cint(item.is_stock_item):
				frappe.throw(_("{0} must be a stock item.").format(frappe.bold(self.get(field))), title=title)
			# A batch or serial would need its own bundle on every repack line; not supported.
			if cint(item.has_batch_no) or cint(item.has_serial_no):
				frappe.throw(
					_("{0} is batch or serial tracked, which counter repack does not support.").format(
						frappe.bold(self.get(field))
					),
					title=title,
				)
		if not bulk_is_moving_average(self.bulk_item):
			frappe.throw(bulk_valuation_message(self.bulk_item), title=title)
		if not 0 <= flt(self.margin_percent) < 100:
			frappe.throw(_("Margin % must be at least 0 and below 100."), title=title)
		if flt(self.bulk_qty_per_unit) <= 0:
			frappe.throw(_("Bulk Qty per Unit must be more than 0."), title=title)
		if not cint(self.disabled):
			clash = frappe.db.exists(
				"BNS Counter Repack Rule",
				{
					"company": self.company,
					"sold_item": self.sold_item,
					"effective_from": self.effective_from,
					"disabled": 0,
					"name": ("!=", self.name),
				},
			)
			if clash:
				frappe.throw(
					_("{0} already has a rule effective {1}: {2}.").format(
						frappe.bold(self.sold_item), frappe.format(self.effective_from, "Date"), clash
					),
					title=title,
				)


def bulk_is_moving_average(item_code: str) -> bool:
	from erpnext.stock.utils import get_valuation_method

	return get_valuation_method(item_code) == "Moving Average"


def bulk_valuation_message(item_code: str) -> str:
	# FIFO breaks the arithmetic on repost: the repack's "whole lot" quantity is fixed at submit, so
	# a backdated purchase adds an older layer and the same quantity is then drawn from that layer
	# instead of from the lot's average. Moving Average is also what "one averaged lot" means.
	return _(
		"{0} must use Moving Average valuation. Counter repack treats it as one averaged lot; under FIFO "
		"a backdated purchase would make a posted repack draw from that purchase alone and break the "
		"balance. Set Valuation Method to Moving Average on the item (ERPNext allows FIFO to Moving "
		"Average at any time)."
	).format(frappe.bold(item_code))
