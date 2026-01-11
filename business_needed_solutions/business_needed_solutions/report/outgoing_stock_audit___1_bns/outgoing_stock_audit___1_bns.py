# Copyright (c) 2025, Sagar Ratan Garg and contributors
# For license information, please see license.txt

"""
Outgoing Stock Audit Report - Negative Stock & Sale vs Valuation

This report detects two critical issues for stock transactions:
1. Negative Stock: When a voucher posts into negative stock (qty_after_transaction < 0)
2. Sale Above Valuation: When Sales Invoice selling rate exceeds valuation rate at posting time

The report analyzes voucher transactions (SI/PI/DN/PR) and their corresponding
Stock Ledger Entries to identify these anomalies without depending on Stock Entry
corrections or grade slabs.

Note: Uses net_rate (excluding GST) from child tables for accurate rate comparison.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate
from frappe.query_builder import DocType
from collections import defaultdict


def execute(filters=None):
	"""
	Main entry point for the report.
	
	Args:
		filters: Dictionary containing report filters
		
	Returns:
		tuple: (columns, data) where columns is list of column definitions
		       and data is list of dictionaries containing report data
	"""
	if not filters:
		filters = {}
	
	# Validate required filters
	if not filters.get("company"):
		frappe.throw(_("Please select Company"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Please select From Date and To Date"))
	
	# Get items based on filters
	items = get_items(filters)
	if not items:
		frappe.msgprint(_("No items found matching the filters"))
		return get_columns(), []
	
	# Get voucher items
	voucher_items = get_voucher_items(filters, items)
	if not voucher_items:
		return get_columns(), []
	
	# Bulk fetch SLE data
	sle_data = get_sle_data_bulk(voucher_items, items)
	
	# Build report data by matching vouchers with SLE
	data = build_report_data(voucher_items, sle_data)
	
	# Filter out rows with no errors (both flags = 0)
	data = [row for row in data if row.get("is_negative_stock") == 1 or row.get("is_sale_below_valuation") == 1]
	
	# Sort by posting_date ascending, then voucher_no
	data.sort(key=lambda x: (
		getdate(x.get("posting_date") or "1900-01-01"),
		x.get("voucher_no", "")
	))
	
	return get_columns(), data


def get_columns():
	"""Define report columns."""
	return [
		{
			"label": _("Posting Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 100
		},
		{
			"label": _("Voucher Type"),
			"fieldname": "voucher_type",
			"fieldtype": "Data",
			"width": 120
		},
		{
			"label": _("Voucher No"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 150
		},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 140
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 180
		},
		{
			"label": _("Stock Qty"),
			"fieldname": "stock_qty",
			"fieldtype": "Float",
			"width": 100,
			"precision": 3
		},
		{
			"label": _("Stock UOM"),
			"fieldname": "stock_uom",
			"fieldtype": "Link",
			"options": "UOM",
			"width": 100
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 140
		},
		{
			"label": _("Valuation Rate"),
			"fieldname": "valuation_rate",
			"fieldtype": "Currency",
			"width": 120,
			"precision": 2
		},
		{
			"label": _("Qty After Transaction"),
			"fieldname": "qty_after_transaction",
			"fieldtype": "Float",
			"width": 130,
			"precision": 3
		},
		{
			"label": _("Selling Rate"),
			"fieldname": "selling_rate",
			"fieldtype": "Currency",
			"width": 120,
			"precision": 2
		},
		{
			"label": _("Gross Margin Proxy"),
			"fieldname": "gross_margin_proxy",
			"fieldtype": "Currency",
			"width": 130,
			"precision": 2
		},
		{
			"label": _("Is Negative Stock"),
			"fieldname": "is_negative_stock",
			"fieldtype": "Check",
			"width": 120
		},
		{
			"label": _("Is Sale Below Valuation"),
			"fieldname": "is_sale_below_valuation",
			"fieldtype": "Check",
			"width": 160
		},
		{
			"label": _("Owner"),
			"fieldname": "owner",
			"fieldtype": "Link",
			"options": "User",
			"width": 120
		}
	]


def get_items(filters):
	"""
	Get list of item codes based on filters.
	
	Args:
		filters: Report filters dictionary
		
	Returns:
		list: List of item codes
	"""
	Item = DocType("Item")
	query = frappe.qb.from_(Item).select(Item.name)
	
	# Filter by item group if provided
	if filters.get("item_group"):
		query = query.where(Item.item_group == filters.item_group)
	
	# Filter by specific item codes if provided
	if filters.get("item_code"):
		item_codes = filters.item_code
		if isinstance(item_codes, str):
			item_codes = [item_codes]
		query = query.where(Item.name.isin(item_codes))
	
	# Only stock items
	query = query.where(Item.is_stock_item == 1)
	
	results = query.run(as_dict=True)
	return [row.name for row in results]


def get_voucher_items(filters, items):
	"""
	Fetch voucher items (SI/PI/DN/PR) for items in the date range.
	
	Args:
		filters: Report filters dictionary
		items: List of item codes
		
	Returns:
		list: List of dictionaries containing voucher item data
	"""
	if not items:
		return []
	
	include_doctypes = filters.get("include_doctypes", [])
	if isinstance(include_doctypes, str):
		include_doctypes = [include_doctypes]
	if not include_doctypes:
		include_doctypes = ["Sales Invoice", "Purchase Invoice"]
	
	voucher_items = []
	from_date = getdate(filters.from_date)
	to_date = getdate(filters.to_date)
	
	# Get Sales Invoice Items
	if "Sales Invoice" in include_doctypes:
		si_items = get_sales_invoice_items(filters, items, from_date, to_date)
		voucher_items.extend(si_items)
	
	# Get Purchase Invoice Items
	if "Purchase Invoice" in include_doctypes:
		pi_items = get_purchase_invoice_items(filters, items, from_date, to_date)
		voucher_items.extend(pi_items)
	
	# Get Delivery Note Items
	if "Delivery Note" in include_doctypes:
		dn_items = get_delivery_note_items(filters, items, from_date, to_date)
		voucher_items.extend(dn_items)
	
	# Get Purchase Receipt Items
	if "Purchase Receipt" in include_doctypes:
		pr_items = get_purchase_receipt_items(filters, items, from_date, to_date)
		voucher_items.extend(pr_items)
	
	return voucher_items


def get_sales_invoice_items(filters, items, from_date, to_date):
	"""Get Sales Invoice items - using net_rate (excluding GST)."""
	SI = DocType("Sales Invoice")
	SII = DocType("Sales Invoice Item")
	
	query = (
		frappe.qb.from_(SI)
		.join(SII).on(SI.name == SII.parent)
		.select(
			SII.name.as_("voucher_detail_no"),
			SI.posting_date,
			SI.posting_time,
			SI.name.as_("voucher_no"),
			SII.item_code,
			SII.item_name,
			SII.warehouse,
			SII.stock_qty,
			SII.stock_uom,
			SII.net_rate.as_("selling_rate"),  # Use net_rate (excluding GST)
			SI.owner,
			SI.company,
			SI.is_return
		)
		.where(
			(SI.docstatus == 1) &
			(SI.posting_date[from_date:to_date]) &
			(SII.item_code.isin(items)) &
			(SI.company == filters.company)
		)
	)
	
	# Apply warehouse filter if provided
	if filters.get("warehouse"):
		query = query.where(SII.warehouse == filters.warehouse)
	
	results = query.run(as_dict=True)
	# Add voucher_type in Python
	for row in results:
		row["voucher_type"] = "Sales Invoice"
	return results


def get_purchase_invoice_items(filters, items, from_date, to_date):
	"""Get Purchase Invoice items - using net_rate (excluding GST)."""
	PI = DocType("Purchase Invoice")
	PII = DocType("Purchase Invoice Item")
	
	query = (
		frappe.qb.from_(PI)
		.join(PII).on(PI.name == PII.parent)
		.select(
			PII.name.as_("voucher_detail_no"),
			PI.posting_date,
			PI.posting_time,
			PI.name.as_("voucher_no"),
			PII.item_code,
			PII.item_name,
			PII.warehouse,
			PII.stock_qty,
			PII.stock_uom,
			PII.net_rate.as_("purchase_rate"),  # Use net_rate (excluding GST)
			PI.owner,
			PI.company,
			PI.is_return
		)
		.where(
			(PI.docstatus == 1) &
			(PI.posting_date[from_date:to_date]) &
			(PII.item_code.isin(items)) &
			(PI.company == filters.company)
		)
	)
	
	# Apply warehouse filter if provided
	if filters.get("warehouse"):
		query = query.where(PII.warehouse == filters.warehouse)
	
	results = query.run(as_dict=True)
	# Add voucher_type in Python
	for row in results:
		row["voucher_type"] = "Purchase Invoice"
	return results


def get_delivery_note_items(filters, items, from_date, to_date):
	"""Get Delivery Note items - using net_rate (excluding GST)."""
	DN = DocType("Delivery Note")
	DNI = DocType("Delivery Note Item")
	
	query = (
		frappe.qb.from_(DN)
		.join(DNI).on(DN.name == DNI.parent)
		.select(
			DNI.name.as_("voucher_detail_no"),
			DN.posting_date,
			DN.posting_time,
			DN.name.as_("voucher_no"),
			DNI.item_code,
			DNI.item_name,
			DNI.warehouse,
			DNI.stock_qty,
			DNI.stock_uom,
			DNI.net_rate.as_("selling_rate"),  # Use net_rate (excluding GST)
			DN.owner,
			DN.company,
			DN.is_return
		)
		.where(
			(DN.docstatus == 1) &
			(DN.posting_date[from_date:to_date]) &
			(DNI.item_code.isin(items)) &
			(DN.company == filters.company)
		)
	)
	
	# Apply warehouse filter if provided
	if filters.get("warehouse"):
		query = query.where(DNI.warehouse == filters.warehouse)
	
	results = query.run(as_dict=True)
	# Add voucher_type in Python
	for row in results:
		row["voucher_type"] = "Delivery Note"
	return results


def get_purchase_receipt_items(filters, items, from_date, to_date):
	"""Get Purchase Receipt items - using net_rate (excluding GST)."""
	PR = DocType("Purchase Receipt")
	PRI = DocType("Purchase Receipt Item")
	
	query = (
		frappe.qb.from_(PR)
		.join(PRI).on(PR.name == PRI.parent)
		.select(
			PRI.name.as_("voucher_detail_no"),
			PR.posting_date,
			PR.posting_time,
			PR.name.as_("voucher_no"),
			PRI.item_code,
			PRI.item_name,
			PRI.warehouse,
			PRI.stock_qty,
			PRI.stock_uom,
			PRI.net_rate.as_("purchase_rate"),  # Use net_rate (excluding GST)
			PR.owner,
			PR.company,
			PR.is_return
		)
		.where(
			(PR.docstatus == 1) &
			(PR.posting_date[from_date:to_date]) &
			(PRI.item_code.isin(items)) &
			(PR.company == filters.company)
		)
	)
	
	# Apply warehouse filter if provided
	if filters.get("warehouse"):
		query = query.where(PRI.warehouse == filters.warehouse)
	
	results = query.run(as_dict=True)
	# Add voucher_type in Python
	for row in results:
		row["voucher_type"] = "Purchase Receipt"
	return results


def get_sle_data_bulk(voucher_items, items):
	"""
	Bulk fetch Stock Ledger Entry data for all vouchers.
	
	Args:
		voucher_items: List of voucher item dictionaries
		items: List of item codes
		
	Returns:
		dict: Dictionary keyed by (voucher_type, voucher_no, item_code, warehouse, voucher_detail_no)
		      containing SLE data
	"""
	if not voucher_items:
		return {}
	
	# Collect unique voucher identifiers
	voucher_types = set()
	voucher_nos = set()
	
	for item in voucher_items:
		voucher_types.add(item.get("voucher_type"))
		voucher_nos.add(item.get("voucher_no"))
	
	if not voucher_types or not voucher_nos:
		return {}
	
	SLE = DocType("Stock Ledger Entry")
	
	query = (
		frappe.qb.from_(SLE)
		.select(
			SLE.voucher_type,
			SLE.voucher_no,
			SLE.voucher_detail_no,
			SLE.item_code,
			SLE.warehouse,
			SLE.valuation_rate,
			SLE.qty_after_transaction,
			SLE.actual_qty,
			SLE.posting_date,
			SLE.posting_time
		)
		.where(
			(SLE.is_cancelled == 0) &
			(SLE.voucher_type.isin(list(voucher_types))) &
			(SLE.voucher_no.isin(list(voucher_nos))) &
			(SLE.item_code.isin(items))
		)
	)
	
	sle_rows = query.run(as_dict=True)
	
	# Index SLE data by key for fast lookup
	sle_dict = defaultdict(list)
	for sle in sle_rows:
		key = (
			sle.voucher_type,
			sle.voucher_no,
			sle.item_code,
			sle.warehouse,
			sle.voucher_detail_no or ""
		)
		sle_dict[key].append(sle)
	
	return sle_dict


def build_report_data(voucher_items, sle_data):
	"""
	Build report data by matching voucher items with SLE data.
	
	Args:
		voucher_items: List of voucher item dictionaries
		sle_data: Dictionary of SLE data indexed by voucher keys
		
	Returns:
		list: List of dictionaries containing report rows
	"""
	report_data = []
	
	for item in voucher_items:
		voucher_type = item.get("voucher_type")
		voucher_no = item.get("voucher_no")
		item_code = item.get("item_code")
		warehouse = item.get("warehouse")
		voucher_detail_no = item.get("voucher_detail_no", "")
		
		# Find matching SLE rows
		key = (voucher_type, voucher_no, item_code, warehouse, voucher_detail_no)
		matching_sles = sle_data.get(key, [])
		
		# Initialize report row
		row = {
			"posting_date": item.get("posting_date"),
			"voucher_type": voucher_type,
			"voucher_no": voucher_no,
			"item_code": item_code,
			"item_name": item.get("item_name"),
			"stock_qty": flt(item.get("stock_qty")),
			"stock_uom": item.get("stock_uom"),
			"warehouse": warehouse,
			"valuation_rate": None,
			"qty_after_transaction": None,
			"selling_rate": None,
			"gross_margin_proxy": None,
			"is_negative_stock": 0,
			"is_sale_below_valuation": 0,
			"owner": item.get("owner")
		}
		
		# Process matching SLE rows
		if matching_sles:
			# Get valuation rate and qty_after_transaction from SLE
			# Use the last SLE entry (most recent) for this voucher item
			latest_sle = matching_sles[-1]
			
			valuation_rate = flt(latest_sle.get("valuation_rate"))
			qty_after_transaction = flt(latest_sle.get("qty_after_transaction"))
			
			row["valuation_rate"] = valuation_rate if valuation_rate > 0 else None
			row["qty_after_transaction"] = qty_after_transaction
			
			# Check for negative stock across all matching SLEs
			for sle in matching_sles:
				if flt(sle.get("qty_after_transaction")) < 0:
					row["is_negative_stock"] = 1
					break
		else:
			# No SLE found - might be a non-stock item or missing entry
			row["valuation_rate"] = None
			row["qty_after_transaction"] = None
		
		# For Sales Invoice and Delivery Note: Check sale below valuation
		# Use net_rate (already fetched as selling_rate for SI/DN)
		if voucher_type in ["Sales Invoice", "Delivery Note"] and not item.get("is_return"):
			selling_rate = flt(item.get("selling_rate"))  # This is net_rate from child table
			valuation_rate = row.get("valuation_rate")
			
			if selling_rate and valuation_rate and valuation_rate > 0:
				row["selling_rate"] = selling_rate
				# Gross margin = selling_rate - valuation_rate (can be negative)
				row["gross_margin_proxy"] = selling_rate - valuation_rate
				
				# Flag if selling rate is below valuation rate (loss situation)
				if selling_rate < valuation_rate:
					row["is_sale_below_valuation"] = 1
			elif selling_rate:
				row["selling_rate"] = selling_rate
				row["gross_margin_proxy"] = None
		
		report_data.append(row)
	
	return report_data
