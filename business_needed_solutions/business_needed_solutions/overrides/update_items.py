"""
Business Needed Solutions - Custom Update Items for Sales Order / Purchase Order

This module provides a BNS-controlled alternative to ERPNext's "Update Items"
flow, allowing updates based on:
- Price List Rate
- Discount fields (Single: discount_percentage, Triple: custom_d1_/custom_d2_/custom_d3_ for Sales Order)

It reuses ERPNext's core post-update behaviors (taxes/totals recalculation,
status updates, reserved stock updates) to stay consistent with standard logic.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _, bold
from frappe.model.workflow import get_workflow_name, is_transition_condition_satisfied
from frappe.utils import cint, flt, get_link_to_form, getdate

from erpnext.buying.utils import update_last_purchase_rate
from erpnext.controllers.accounts_controller import (
	set_order_defaults,
	validate_and_delete_children,
)
from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
from erpnext.stock.get_item_details import get_conversion_factor, get_item_details, get_item_warehouse


@frappe.whitelist()
def get_item_details_for_update_items_dialog(args, doc=None):
	"""
	BNS wrapper for get_item_details used by Update Items dialog.
	Ensures correct args structure (handles nested args from client) and returns
	price_list_rate, uom, conversion_factor, stock_uom, item_name, qty.
	When UOM differs from stock UOM and no separate Item Price exists for that UOM,
	ERPNext's get_item_details factors the price by conversion_factor automatically.
	"""
	if isinstance(args, str):
		args = json.loads(args)
	args = frappe._dict(args)

	# Handle nested structure from client: { args: {...}, doc: {...} }
	inner_args = args.get("args")
	if inner_args is not None:
		args = frappe._dict(inner_args)
	if doc is None and args.get("doc"):
		doc = args.get("doc")

	if isinstance(doc, str):
		doc = json.loads(doc) if doc else None

	if not args.get("item_code"):
		return None

	return get_item_details(args, doc=doc)


def _get_discount_type() -> str:
	"""Return BNS discount type (Single / Triple Compounded)."""
	return (
		frappe.db.get_single_value("BNS Settings", "discount_type", cache=True) or "Single"
	)


def _validate_uom_in_additional_uoms(item_code: str, uom: str) -> None:
	"""Validate that `uom` is part of the Item's stock uom or additional uoms."""
	if not item_code or not uom:
		return

	item = frappe.get_doc("Item", item_code)
	allowed = {item.stock_uom} if item.stock_uom else set()
	for row in item.get("uoms") or []:
		if row.uom:
			allowed.add(row.uom)

	if allowed and uom not in allowed:
		frappe.throw(
			_("UOM {0} is not allowed for Item {1}. Allowed UOMs: {2}").format(
				bold(uom),
				bold(item_code),
				", ".join(sorted(allowed)),
			)
		)


def _compute_rate_from_price_list(
	parent_doctype: str,
	discount_type: str,
	price_list_rate: float,
	discount_percentage: float = 0.0,
	d1: float = 0.0,
	d2: float = 0.0,
	d3: float = 0.0,
) -> Tuple[float, float]:
	"""
	Compute (rate, computed_discount_percentage) using BNS rules.

	- Single: rate = price_list_rate * (1 - discount_percentage/100)
	- Triple Compounded (Sales Order only): apply d1, d2, d3 sequentially
	- Purchase Order in Triple mode: no triple discount fields exist; treat as no discount.
	"""
	price_list_rate = flt(price_list_rate)

	if discount_type == "Single":
		discount_percentage = flt(discount_percentage)
		return price_list_rate * (1 - discount_percentage / 100.0), discount_percentage

	# Triple mode
	if parent_doctype == "Purchase Order":
		return price_list_rate, 0.0

	# Sales Order
	rate = price_list_rate
	for d in (flt(d1), flt(d2), flt(d3)):
		rate *= 1 - d / 100.0

	computed_disc = (100.0 - (rate / price_list_rate * 100.0)) if price_list_rate else 0.0
	return rate, computed_disc


@frappe.whitelist()
def update_child_items(
	parent_doctype: str,
	trans_items: str,
	parent_doctype_name: str,
	child_docname: str = "items",
):
	"""
	Update Sales Order / Purchase Order items after submit using BNS fields.

	Args:
		parent_doctype: "Sales Order" or "Purchase Order"
		trans_items: JSON string of rows from the Update Items dialog
		parent_doctype_name: Document name
		child_docname: child table fieldname (default: "items")
	"""

	def check_doc_permissions(doc, perm_type: str = "create") -> None:
		try:
			doc.check_permission(perm_type)
		except frappe.PermissionError:
			actions = {"create": "add", "write": "update"}
			frappe.throw(
				_("You do not have permissions to {0} items in a {1}.").format(
					actions.get(perm_type, perm_type), parent_doctype
				),
				title=_("Insufficient Permissions"),
			)

	def validate_workflow_conditions(doc) -> None:
		workflow = get_workflow_name(doc.doctype)
		if not workflow:
			return

		workflow_doc = frappe.get_doc("Workflow", workflow)
		current_state = doc.get(workflow_doc.workflow_state_field)
		roles = frappe.get_roles()

		transitions = []
		for transition in workflow_doc.transitions:
			if transition.next_state == current_state and transition.allowed in roles:
				if not is_transition_condition_satisfied(transition, doc):
					continue
				transitions.append(transition.as_dict())

		if not transitions:
			frappe.throw(
				_("You are not allowed to update as per the conditions set in {0} Workflow.").format(
					get_link_to_form("Workflow", workflow)
				),
				title=_("Insufficient Permissions"),
			)

	def get_new_child_item(item_row: Dict[str, Any]):
		child_doctype = "Sales Order Item" if parent_doctype == "Sales Order" else "Purchase Order Item"
		return set_order_defaults(parent_doctype, parent_doctype_name, child_doctype, child_docname, item_row)

	def is_allowed_zero_qty() -> bool:
		if parent_doctype == "Sales Order":
			return frappe.db.get_single_value("Selling Settings", "allow_zero_qty_in_sales_order") or False
		if parent_doctype == "Purchase Order":
			return frappe.db.get_single_value("Buying Settings", "allow_zero_qty_in_purchase_order") or False
		return False

	def validate_quantity(child_item, new_data: Dict[str, Any]) -> None:
		if not flt(new_data.get("qty")) and not is_allowed_zero_qty():
			frappe.throw(
				_("Row #{0}: Quantity for Item {1} cannot be zero.").format(
					new_data.get("idx"), bold(new_data.get("item_code"))
				),
				title=_("Invalid Qty"),
			)

		if parent_doctype == "Sales Order" and flt(new_data.get("qty")) < flt(child_item.delivered_qty):
			frappe.throw(_("Cannot set quantity less than delivered quantity"))

		if parent_doctype == "Purchase Order" and flt(new_data.get("qty")) < flt(child_item.received_qty):
			frappe.throw(_("Cannot set quantity less than received quantity"))

	def validate_fg_item_for_subcontracting(new_data: Dict[str, Any], is_new: bool) -> None:
		# Keep parity with ERPNext validations, but avoid KeyError if field absent.
		if is_new and not new_data.get("fg_item"):
			frappe.throw(
				_("Finished Good Item is not specified for service item {0}").format(
					new_data.get("item_code")
				)
			)

		if new_data.get("fg_item") and is_new:
			is_sub_contracted_item, default_bom = frappe.db.get_value(
				"Item", new_data["fg_item"], ["is_sub_contracted_item", "default_bom"]
			)
			if not is_sub_contracted_item:
				frappe.throw(
					_("Finished Good Item {0} must be a sub-contracted item").format(new_data["fg_item"])
				)
			if not default_bom:
				frappe.throw(_("Default BOM not found for FG Item {0}").format(new_data["fg_item"]))

		if new_data.get("fg_item") and not flt(new_data.get("fg_item_qty")):
			frappe.throw(_("Finished Good Item {0} Qty can not be zero").format(new_data["fg_item"]))

	if parent_doctype not in ("Sales Order", "Purchase Order"):
		frappe.throw(_("BNS Update Items is supported only for Sales Order and Purchase Order."))

	if not cint(
		frappe.db.get_single_value("BNS Settings", "enable_custom_update_items_po_so", cache=True)
	):
		frappe.throw(
			_("Please enable {0} in BNS Settings first.").format(
				bold(_("Enable BNS Update Items for Sales/Purchase Orders"))
			)
		)

	discount_type = _get_discount_type()
	data: List[Dict[str, Any]] = json.loads(trans_items or "[]")

	any_qty_changed = False
	items_added_or_removed = False
	any_conversion_factor_changed = False

	parent = frappe.get_doc(parent_doctype, parent_doctype_name)
	check_doc_permissions(parent, "write")

	_removed_items = validate_and_delete_children(parent, data)
	items_added_or_removed |= bool(_removed_items)

	for d in data:
		new_child_flag = False

		if not d.get("item_code"):
			continue

		# Validate UOM constraint (additional uoms + stock uom only)
		if d.get("uom"):
			_validate_uom_in_additional_uoms(d.get("item_code"), d.get("uom"))

		# Prepare computed rate based on price list + discounts (BNS)
		plr = flt(d.get("price_list_rate"))
		disc = flt(d.get("discount_percentage"))
		d1 = flt(d.get("custom_d1_"))
		d2 = flt(d.get("custom_d2_"))
		d3 = flt(d.get("custom_d3_"))

		computed_rate, computed_disc = _compute_rate_from_price_list(
			parent_doctype=parent_doctype,
			discount_type=discount_type,
			price_list_rate=plr,
			discount_percentage=disc,
			d1=d1,
			d2=d2,
			d3=d3,
		)
		d["rate"] = computed_rate
		d["_bns_computed_discount_percentage"] = computed_disc  # for internal compare only

		if not d.get("docname"):
			new_child_flag = True
			items_added_or_removed = True
			check_doc_permissions(parent, "create")
			child_item = get_new_child_item(d)
			item_code_changed = False  # New row: no item change, only add
		else:
			check_doc_permissions(parent, "write")
			child_item = frappe.get_doc(parent_doctype + " Item", d.get("docname"))

			# Handle item_code change on existing row (validate + refresh item details)
			item_code_changed = child_item.item_code != d.get("item_code")
			if item_code_changed:
				# Validate row can be changed (not delivered/received/billed)
				if parent_doctype == "Sales Order":
					if flt(child_item.delivered_qty):
						frappe.throw(
							_("Row #{0}: Cannot change Item Code for item {1} which has already been delivered.").format(
								child_item.idx, bold(child_item.item_code)
							)
						)
					if flt(child_item.work_order_qty):
						frappe.throw(
							_("Row #{0}: Cannot change Item Code for item {1} which has work order assigned to it.").format(
								child_item.idx, bold(child_item.item_code)
							)
						)
					if flt(child_item.ordered_qty):
						frappe.throw(
							_("Row #{0}: Cannot change Item Code for item {1} which is assigned to customer's purchase order.").format(
								child_item.idx, bold(child_item.item_code)
							)
						)
				elif parent_doctype == "Purchase Order":
					if flt(child_item.received_qty):
						frappe.throw(
							_("Row #{0}: Cannot change Item Code for item {1} which has already been received.").format(
								child_item.idx, bold(child_item.item_code)
							)
						)

				if flt(child_item.billed_amt):
					frappe.throw(
						_("Row #{0}: Cannot change Item Code for item {1} which has already been billed.").format(
							child_item.idx, bold(child_item.item_code)
						)
					)

				# Refresh item details using get_item_details (like ERPNext does for new rows)
				item_details_args = {
					"item_code": d.get("item_code"),
					"set_warehouse": parent.get("set_warehouse"),
					"customer": parent.get("customer") or parent.get("party_name"),
					"quotation_to": parent.get("quotation_to"),
					"supplier": parent.get("supplier"),
					"currency": parent.get("currency"),
					"is_internal_supplier": parent.get("is_internal_supplier"),
					"is_internal_customer": parent.get("is_internal_customer"),
					"conversion_rate": parent.get("conversion_rate"),
					"price_list": (
						parent.get("selling_price_list") if parent_doctype == "Sales Order" else parent.get("buying_price_list")
					),
					"price_list_currency": parent.get("price_list_currency"),
					"plc_conversion_rate": parent.get("plc_conversion_rate"),
					"company": parent.get("company"),
					"order_type": parent.get("order_type"),
					"is_pos": cint(parent.get("is_pos")),
					"is_return": cint(parent.get("is_return")),
					"is_subcontracted": parent.get("is_subcontracted"),
					"ignore_pricing_rule": parent.get("ignore_pricing_rule"),
					"doctype": parent_doctype,
					"name": parent.name,
					"qty": d.get("qty") or 1,
					"uom": d.get("uom"),
					"pos_profile": cint(parent.get("is_pos")) and parent.get("pos_profile") or "",
					"tax_category": parent.get("tax_category"),
					"child_doctype": parent_doctype + " Item",
					"is_old_subcontracting_flow": parent.get("is_old_subcontracting_flow"),
				}

				item_details = get_item_details(item_details_args, doc=parent.as_dict())
				if item_details:
					# Update child_item with new item details (like set_order_defaults does)
					item_doc = frappe.get_doc("Item", d.get("item_code"))
					for field in ("item_code", "item_name", "description", "item_group"):
						if field in item_details:
							setattr(child_item, field, item_details[field])

					# Update UOM/stock_uom/conversion_factor from item_details
					if item_details.get("stock_uom"):
						child_item.stock_uom = item_details["stock_uom"]
					if item_details.get("uom"):
						child_item.uom = item_details["uom"]
					if item_details.get("conversion_factor"):
						child_item.conversion_factor = flt(item_details["conversion_factor"])

					# Update warehouse (like set_order_defaults does)
					child_item.warehouse = get_item_warehouse(item_doc, parent, overwrite_warehouse=True)
					if parent_doctype == "Sales Order" and not child_item.warehouse:
						frappe.throw(
							_(
								"Cannot find a default warehouse for item {0}. Please set one in the Item Master or in Stock Settings."
							).format(bold(d.get("item_code")))
						)

					# Update tax template (like set_order_defaults does)
					from erpnext.controllers.accounts_controller import (
						add_taxes_from_tax_template,
						set_child_tax_template_and_map,
					)

					set_child_tax_template_and_map(item_doc, child_item, parent)
					add_taxes_from_tax_template(child_item, parent)

					# Update price_list_rate from item_details (but preserve user-entered value if provided)
					if item_details.get("price_list_rate") is not None and d.get("price_list_rate") is None:
						child_item.price_list_rate = flt(item_details["price_list_rate"])

				items_added_or_removed = True  # Item change counts as modification

			prev_rate, new_rate = flt(child_item.get("rate")), flt(d.get("rate"))
			prev_qty, new_qty = flt(child_item.get("qty")), flt(d.get("qty"))
			prev_con_fac, new_con_fac = (
				flt(child_item.get("conversion_factor")),
				flt(d.get("conversion_factor")),
			)
			prev_uom, new_uom = child_item.get("uom"), d.get("uom")
			prev_price_list_rate, new_price_list_rate = (
				flt(child_item.get("price_list_rate")),
				flt(d.get("price_list_rate")),
			)

			if parent_doctype == "Sales Order":
				prev_date, new_date = child_item.get("delivery_date"), d.get("delivery_date")
			else:
				prev_date, new_date = child_item.get("schedule_date"), d.get("schedule_date")

			# Discount comparisons
			prev_discount_percentage = flt(child_item.get("discount_percentage"))
			new_discount_percentage = flt(d.get("discount_percentage")) if discount_type == "Single" else flt(
				d.get("_bns_computed_discount_percentage")
			)

			prev_d1 = flt(getattr(child_item, "custom_d1_", 0))
			prev_d2 = flt(getattr(child_item, "custom_d2_", 0))
			prev_d3 = flt(getattr(child_item, "custom_d3_", 0))
			new_d1 = flt(d.get("custom_d1_"))
			new_d2 = flt(d.get("custom_d2_"))
			new_d3 = flt(d.get("custom_d3_"))

			rate_unchanged = prev_rate == new_rate
			qty_unchanged = prev_qty == new_qty
			uom_unchanged = prev_uom == new_uom
			conversion_factor_unchanged = prev_con_fac == new_con_fac
			any_conversion_factor_changed |= not conversion_factor_unchanged
			date_unchanged = prev_date == getdate(new_date) if prev_date and new_date else False
			price_list_rate_unchanged = prev_price_list_rate == new_price_list_rate
			discount_unchanged = prev_discount_percentage == new_discount_percentage
			triple_discount_unchanged = (
				parent_doctype != "Sales Order"
				or discount_type == "Single"
				or (prev_d1 == new_d1 and prev_d2 == new_d2 and prev_d3 == new_d3)
			)

			# Skip if nothing changed (but always process item_code changes)
			if (
				not item_code_changed
				and rate_unchanged
				and qty_unchanged
				and conversion_factor_unchanged
				and uom_unchanged
				and date_unchanged
				and price_list_rate_unchanged
				and discount_unchanged
				and triple_discount_unchanged
			):
				continue

		validate_quantity(child_item, d)
		if flt(child_item.get("qty")) != flt(d.get("qty")):
			any_qty_changed = True

		# Subcontracting (new flow) support
		if (
			parent.doctype == "Purchase Order"
			and parent.is_subcontracted
			and not parent.is_old_subcontracting_flow
		):
			validate_fg_item_for_subcontracting(d, new_child_flag)
			if d.get("fg_item_qty") is not None:
				child_item.fg_item_qty = flt(d.get("fg_item_qty"))
			if new_child_flag and d.get("fg_item"):
				child_item.fg_item = d.get("fg_item")

		# Base updates
		child_item.qty = flt(d.get("qty"))

		# UOM / Conversion factor updates
		if d.get("conversion_factor"):
			if child_item.stock_uom == child_item.uom:
				child_item.conversion_factor = 1
			else:
				child_item.conversion_factor = flt(
					d.get("conversion_factor"), child_item.precision("conversion_factor") or 2
				)

		if d.get("uom"):
			child_item.uom = d.get("uom")
			conversion_factor = flt(
				get_conversion_factor(child_item.item_code, child_item.uom).get("conversion_factor")
			)
			child_item.conversion_factor = (
				flt(d.get("conversion_factor"), child_item.precision("conversion_factor") or 2)
				or conversion_factor
			)

		# Price List Rate: use provided value, else fetch from get_item_details (handles new rows + UOM conversion)
		# get_item_details factors price by conversion_factor when no separate Item Price for selected UOM
		if d.get("price_list_rate") is not None:
			plr_precision = child_item.precision("price_list_rate") or 2
			child_item.price_list_rate = flt(d.get("price_list_rate"), plr_precision)
		else:
			item_details_args = {
				"item_code": d.get("item_code"),
				"set_warehouse": parent.get("set_warehouse"),
				"customer": parent.get("customer") or parent.get("party_name"),
				"quotation_to": parent.get("quotation_to"),
				"supplier": parent.get("supplier"),
				"currency": parent.get("currency"),
				"is_internal_supplier": parent.get("is_internal_supplier"),
				"is_internal_customer": parent.get("is_internal_customer"),
				"conversion_rate": parent.get("conversion_rate"),
				"price_list": (
					parent.get("selling_price_list") if parent_doctype == "Sales Order" else parent.get("buying_price_list")
				),
				"price_list_currency": parent.get("price_list_currency"),
				"plc_conversion_rate": parent.get("plc_conversion_rate"),
				"company": parent.get("company"),
				"order_type": parent.get("order_type"),
				"is_pos": cint(parent.get("is_pos")),
				"is_return": cint(parent.get("is_return")),
				"is_subcontracted": parent.get("is_subcontracted"),
				"ignore_pricing_rule": parent.get("ignore_pricing_rule"),
				"doctype": parent_doctype,
				"name": parent.name,
				"qty": d.get("qty") or 1,
				"uom": d.get("uom") or child_item.uom,
				"pos_profile": cint(parent.get("is_pos")) and parent.get("pos_profile") or "",
				"tax_category": parent.get("tax_category"),
				"child_doctype": parent_doctype + " Item",
				"is_old_subcontracting_flow": parent.get("is_old_subcontracting_flow"),
			}
			item_details = get_item_details(item_details_args, doc=parent.as_dict())
			if item_details and item_details.get("price_list_rate") is not None:
				plr_precision = child_item.precision("price_list_rate") or 2
				child_item.price_list_rate = flt(item_details["price_list_rate"], plr_precision)
				# Recompute rate when client sent 0 (no price_list_rate to compute from)
				if not flt(d.get("rate")):
					computed_rate, _ = _compute_rate_from_price_list(
						parent_doctype=parent_doctype,
						discount_type=discount_type,
						price_list_rate=child_item.price_list_rate,
						discount_percentage=flt(d.get("discount_percentage")),
						d1=flt(d.get("custom_d1_")),
						d2=flt(d.get("custom_d2_")),
						d3=flt(d.get("custom_d3_")),
					)
					d["rate"] = computed_rate

		# Discounts (BNS)

		if discount_type == "Single":
			if d.get("discount_percentage") is not None:
				disc_precision = child_item.precision("discount_percentage") or 2
				child_item.discount_percentage = flt(d.get("discount_percentage"), disc_precision)

			# Clear triple discount fields if present
			for fn in ("custom_d1_", "custom_d2_", "custom_d3_"):
				if hasattr(child_item, fn):
					setattr(child_item, fn, 0)
		else:
			# Triple discounts only exist on Sales Order items in BNS
			if parent_doctype == "Sales Order":
				for fn in ("custom_d1_", "custom_d2_", "custom_d3_"):
					if hasattr(child_item, fn):
						setattr(child_item, fn, flt(d.get(fn)))

		# Rate from computed value (with billed amount safety check like ERPNext)
		rate_precision = child_item.precision("rate") or 2
		qty_precision = child_item.precision("qty") or 2
		row_rate = flt(d.get("rate"), rate_precision)

		# Rate of unit price (zero qty allowed) items can't be changed
		prev_rate = flt(child_item.get("rate"))
		if prev_rate != row_rate and not child_item.get("qty") and is_allowed_zero_qty():
			frappe.throw(_("Rate of '{0}' items cannot be changed").format(bold(_("Unit Price"))))

		amount_below_billed_amt = flt(child_item.billed_amt, rate_precision) > flt(
			row_rate * flt(d.get("qty"), qty_precision), rate_precision
		)
		if amount_below_billed_amt and row_rate > 0.0:
			frappe.throw(
				_(
					"Row #{0}: Cannot set Rate if the billed amount is greater than the amount for Item {1}."
				).format(child_item.idx, child_item.item_code)
			)

		child_item.rate = row_rate

		# Date fields
		if d.get("delivery_date") and parent_doctype == "Sales Order":
			child_item.delivery_date = d.get("delivery_date")

		if d.get("schedule_date") and parent_doctype == "Purchase Order":
			child_item.schedule_date = d.get("schedule_date")

		# Ensure discount_amount/margins match price_list_rate vs rate
		if flt(child_item.price_list_rate):
			if flt(child_item.rate) > flt(child_item.price_list_rate):
				child_item.discount_percentage = 0
				child_item.margin_type = "Amount"
				child_item.margin_rate_or_amount = flt(
					child_item.rate - child_item.price_list_rate,
					child_item.precision("margin_rate_or_amount"),
				)
				child_item.rate_with_margin = child_item.rate
			else:
				child_item.discount_percentage = flt(
					(1 - flt(child_item.rate) / flt(child_item.price_list_rate)) * 100.0,
					child_item.precision("discount_percentage"),
				)
				child_item.discount_amount = flt(child_item.price_list_rate) - flt(child_item.rate)
				child_item.margin_type = ""
				child_item.margin_rate_or_amount = 0
				child_item.rate_with_margin = 0

		child_item.flags.ignore_validate_update_after_submit = True
		if new_child_flag:
			parent.load_from_db()
			child_item.idx = len(parent.items) + 1
			child_item.insert()
		else:
			child_item.save()

	# Recalculate and update statuses (mirrors ERPNext update_child_qty_rate)
	parent.reload()
	parent.flags.ignore_validate_update_after_submit = True
	parent.set_qty_as_per_stock_uom()
	parent.calculate_taxes_and_totals()
	parent.set_total_in_words()
	if parent_doctype == "Sales Order":
		make_packing_list(parent)
		parent.set_gross_profit()

	frappe.get_doc("Authorization Control").validate_approving_authority(
		parent.doctype, parent.company, parent.base_grand_total
	)

	parent.set_payment_schedule()
	if parent_doctype == "Purchase Order":
		parent.validate_minimum_order_qty()
		parent.validate_budget()
		if parent.is_against_so():
			parent.update_status_updater()
	else:
		parent.check_credit_limit()

	# reset index of child table
	for idx, row in enumerate(parent.get(child_docname), start=1):
		row.idx = idx

	parent.save()

	if parent_doctype == "Purchase Order":
		update_last_purchase_rate(parent, is_submit=1)
		if any_qty_changed or items_added_or_removed or any_conversion_factor_changed:
			parent.update_prevdoc_status()
		parent.update_requested_qty()
		parent.update_ordered_qty()
		parent.update_ordered_and_reserved_qty()
		parent.update_receiving_percentage()
		if parent.is_subcontracted:
			if parent.is_old_subcontracting_flow:
				supplied_items_processed = any(
					item.supplied_qty or item.consumed_qty or item.returned_qty
					for item in parent.supplied_items
				)
				update_supplied_items = any_qty_changed or items_added_or_removed or any_conversion_factor_changed
				if update_supplied_items and supplied_items_processed:
					frappe.throw(_("Item qty can not be updated as raw materials are already processed."))

				if update_supplied_items:
					parent.update_reserved_qty_for_subcontract()
					parent.create_raw_materials_supplied()

				parent.save()
			else:
				if not parent.can_update_items():
					frappe.throw(
						_(
							"Items cannot be updated as Subcontracting Order is created against the Purchase Order {0}."
						).format(bold(parent.name))
					)
	else:
		parent.validate_selling_price()
		parent.validate_for_duplicate_items()
		parent.validate_warehouse()
		parent.update_reserved_qty()
		parent.update_project()
		parent.update_prevdoc_status("submit")
		parent.update_delivery_status()

	parent.reload()
	validate_workflow_conditions(parent)

	parent.update_blanket_order()
	parent.update_billing_percentage()
	parent.set_status()

	parent.validate_uom_is_integer("uom", "qty")
	parent.validate_uom_is_integer("stock_uom", "stock_qty")

	# Cancel & recreate Stock Reservation Entries if needed
	if parent_doctype == "Sales Order":
		from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
			cancel_stock_reservation_entries,
			has_reserved_stock,
		)

		if has_reserved_stock(parent.doctype, parent.name):
			cancel_stock_reservation_entries(parent.doctype, parent.name)
			if parent.per_picked == 0:
				parent.create_stock_reservation_entries()

	return True

