# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _, msgprint, qb
from frappe.query_builder import Criterion

from erpnext import get_company_currency


def execute(filters=None):
	if not filters:
		filters = {}

	columns = get_columns(filters)
	entries = get_entries(filters)
	item_details = get_item_details()
	price_list_rates = get_price_list_rates(filters)
	data = []

	company_currency = get_company_currency(filters.get("company"))

	# Group by item if filter is set
	if filters.get("group_by") == "Item":
		data = group_by_item(entries, item_details, price_list_rates, filters, company_currency)
	else:
		for d in entries:
			if d.stock_qty > 0 or filters.get("show_return_entries", 0):
				item_detail = item_details.get(d.item_code, {})
				item_code_display = f"{d.item_code}: {item_detail.get('item_name', '')}" if item_detail.get('item_name') else d.item_code
				
				# Get price list rate if price list is selected
				price_list_rate = None
				expected_amount = None
				if filters.get("price_list"):
					price_list_rate = price_list_rates.get(d.item_code)
					if price_list_rate:
						expected_amount = price_list_rate * d.stock_qty
				
				row = [
					d.name,
					d.customer,
					d.posting_date,
					item_code_display,
					d.stock_qty,
					item_detail.get("stock_uom"),
					d.base_net_amount,
					d.sales_person,
				]
				
				# Add price list columns if price list filter is selected
				if filters.get("price_list"):
					row.append(price_list_rate)
					# Add "% Less" column when group_by = Item
					if filters.get("group_by") == "Item":
						row.append("")  # Empty for "% Less"
					row.append(expected_amount)
				
				row.append(company_currency)
				data.append(row)

	if data:
		total_row = [""] * len(data[0])
		data.append(total_row)

	return columns, data


def get_columns(filters):
	if not filters.get("doc_type"):
		msgprint(_("Please select the document type first"), raise_exception=1)

	columns = [
		{
			"label": _(filters["doc_type"]),
			"options": filters["doc_type"],
			"fieldname": frappe.scrub(filters["doc_type"]),
			"fieldtype": "Link",
			"width": 140,
		},
		{
			"label": _("Customer"),
			"options": "Customer",
			"fieldname": "customer",
			"fieldtype": "Link",
			"width": 140,
		},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 140},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Data",
			"width": 200,
		},
		{"label": _("Total Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 140},
		{
			"label": _("Total Qty UOM"),
			"fieldname": "qty_uom",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Amount"),
			"options": "currency",
			"fieldname": "amount",
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"label": _("Sales Person"),
			"options": "Sales Person",
			"fieldname": "sales_person",
			"fieldtype": "Link",
			"width": 140,
		},
	]
	
	# Add price list columns if price list filter is selected
	if filters.get("price_list"):
		columns.append({
			"label": _("Expected Price List Rate Per Item"),
			"options": "currency",
			"fieldname": "expected_price_list_rate",
			"fieldtype": "Currency",
			"width": 180,
		})
		# Add "% Less" column when group_by = Item
		if filters.get("group_by") == "Item":
			columns.append({
				"label": _("% Less"),
				"fieldname": "percent_less",
				"fieldtype": "Data",
				"width": 100,
			})
		columns.append({
			"label": _("Expected Amount"),
			"options": "currency",
			"fieldname": "expected_amount",
			"fieldtype": "Currency",
			"width": 140,
		})
	
	columns.append({
		"label": _("Currency"),
		"options": "Currency",
		"fieldname": "currency",
		"fieldtype": "Link",
		"hidden": 1,
	})

	return columns


def get_entries(filters):
	date_field = filters["doc_type"] == "Sales Order" and "transaction_date" or "posting_date"
	if filters["doc_type"] == "Sales Order":
		qty_field = "delivered_qty"
	else:
		qty_field = "qty"
	conditions, values = get_conditions(filters, date_field)

	entries = frappe.db.sql(
		"""
		SELECT
			dt.name, dt.customer, dt.{} as posting_date, dt_item.item_code,
			st.sales_person, st.allocated_percentage, dt_item.warehouse, dt_item.uom,
		CASE
			WHEN dt.status = "Closed" THEN dt_item.{} * dt_item.conversion_factor
			ELSE dt_item.stock_qty
		END as stock_qty,
		CASE
			WHEN dt.status = "Closed" THEN (dt_item.base_net_rate * dt_item.{} * dt_item.conversion_factor)
			ELSE dt_item.base_net_amount
		END as base_net_amount,
		CASE
			WHEN dt.status = "Closed" THEN ((dt_item.base_net_rate * dt_item.{} * dt_item.conversion_factor) * st.allocated_percentage/100)
			ELSE dt_item.base_net_amount * st.allocated_percentage/100
		END as contribution_amt
		FROM
			`tab{}` dt, `tab{} Item` dt_item, `tabSales Team` st
		WHERE
			st.parent = dt.name and dt.name = dt_item.parent and st.parenttype = {}
			and dt.docstatus = 1 {} order by st.sales_person, dt.name desc
		""".format(
			date_field,
			qty_field,
			qty_field,
			qty_field,
			filters["doc_type"],
			filters["doc_type"],
			"%s",
			conditions,
		),
		tuple([filters["doc_type"], *values]),
		as_dict=1,
	)

	return entries


def get_conditions(filters, date_field):
	conditions = [""]
	values = []

	for field in ["company", "customer"]:
		if filters.get(field):
			conditions.append(f"dt.{field}=%s")
			values.append(filters[field])

	if filters.get("sales_person"):
		lft, rgt = frappe.get_value("Sales Person", filters.get("sales_person"), ["lft", "rgt"])
		conditions.append(
			f"exists(select name from `tabSales Person` where lft >= {lft} and rgt <= {rgt} and name=st.sales_person)"
		)

	if filters.get("from_date"):
		conditions.append(f"dt.{date_field}>=%s")
		values.append(filters["from_date"])

	if filters.get("to_date"):
		conditions.append(f"dt.{date_field}<=%s")
		values.append(filters["to_date"])

	items = get_items(filters)
	if items:
		conditions.append("dt_item.item_code in (%s)" % ", ".join(["%s"] * len(items)))
		values += items
	else:
		# return empty result, if no items are fetched after filtering on 'item group' and 'brand'
		conditions.append("dt_item.item_code = Null")

	return " and ".join(conditions), values


def get_items(filters):
	item = qb.DocType("Item")

	item_query_conditions = []
	if filters.get("item_group"):
		# Handle 'Parent' nodes as well.
		item_group = qb.DocType("Item Group")
		lft, rgt = frappe.db.get_all(
			"Item Group", filters={"name": filters.get("item_group")}, fields=["lft", "rgt"], as_list=True
		)[0]
		item_group_query = (
			qb.from_(item_group)
			.select(item_group.name)
			.where((item_group.lft >= lft) & (item_group.rgt <= rgt))
		)
		item_query_conditions.append(item.item_group.isin(item_group_query))
	if filters.get("brand"):
		item_query_conditions.append(item.brand == filters.get("brand"))

	items = qb.from_(item).select(item.name).where(Criterion.all(item_query_conditions)).run()
	return items


def get_item_details():
	item_details = {}
	for d in frappe.db.sql("""SELECT `name`, `item_group`, `brand`, `item_name`, `stock_uom` FROM `tabItem`""", as_dict=1):
		item_details.setdefault(d.name, d)

	return item_details


def group_by_item(entries, item_details, price_list_rates, filters, company_currency):
	"""Group entries by item and UOM, sum quantities and amounts"""
	grouped_data = {}
	
	for d in entries:
		if d.stock_qty > 0 or filters.get("show_return_entries", 0):
			item_code = d.item_code
			# Use UOM from transaction, fallback to stock_uom if not available
			uom = getattr(d, 'uom', None) or item_details.get(item_code, {}).get('stock_uom', '')
			# Create unique key combining item_code and UOM
			group_key = f"{item_code}|{uom}"
			
			if group_key not in grouped_data:
				item_detail = item_details.get(item_code, {})
				item_code_display = f"{item_code}: {item_detail.get('item_name', '')}" if item_detail.get('item_name') else item_code
				
				grouped_data[group_key] = {
					"item_code": item_code,
					"item_code_display": item_code_display,
					"uom": uom,
					"stock_qty": 0,
					"base_net_amount": 0,
					"price_list_rate": price_list_rates.get(item_code) if filters.get("price_list") else None,
				}
			
			grouped_data[group_key]["stock_qty"] += d.stock_qty
			grouped_data[group_key]["base_net_amount"] += d.base_net_amount
	
	# Convert grouped data to rows, sorted by item code and UOM
	data = []
	# Excel row number starts at 2 (row 1 is header, accounting for potential filter rows)
	# We'll use ROW() function to get current row dynamically
	for idx, group_key in enumerate(sorted(grouped_data.keys())):
		item_data = grouped_data[group_key]
		expected_amount = None
		if item_data["price_list_rate"]:
			expected_amount = item_data["price_list_rate"] * item_data["stock_qty"]
		
		row = [
			"",  # Document name
			"",  # Customer
			"",  # Posting Date
			item_data["item_code_display"],
			item_data["stock_qty"],
			item_data["uom"],
			item_data["base_net_amount"],
			"",  # Sales Person
		]
		
		# Add price list columns if price list filter is selected
		if filters.get("price_list"):
			row.append(item_data["price_list_rate"])
			# Add "% Less" column when group_by = Item
			if filters.get("group_by") == "Item":
				row.append("")  # Empty for "% Less" - user will fill this
				# Add Excel formula for Expected Amount: Expected Price List Rate × Total Qty × (1 - % Less)
				# Column positions: I=Expected Price List Rate, E=Total Qty, J=% Less, K=Expected Amount
				# Row number calculation: idx + 2 (idx starts at 0, +1 for header, +1 for 1-based Excel)
				# Note: If filters are included in export, row numbers will be offset, but Excel will still work
				row_num = idx + 2
				# Formula: If % Less is blank or 0, use base calculation, else apply discount
				# Using ISBLANK and =0 check for better compatibility
				if item_data["price_list_rate"]:
					# Create formula as string - openpyxl will recognize strings starting with "=" as formulas
					expected_amount_formula = f"=IF(OR(ISBLANK(J{row_num}),J{row_num}=0),I{row_num}*E{row_num},I{row_num}*E{row_num}*(1-J{row_num}))"
					row.append(expected_amount_formula)
				else:
					row.append(None)
			else:
				row.append(expected_amount)
		
		row.append(company_currency)
		data.append(row)
	
	return data


def get_price_list_rates(filters):
	"""Get price list rates for items from the selected price list"""
	if not filters.get("price_list"):
		return {}
	
	price_list_rates = {}
	item_prices = frappe.db.sql(
		"""
		SELECT `item_code`, `price_list_rate`, `uom`
		FROM `tabItem Price`
		WHERE `price_list` = %s
		ORDER BY `item_code`, `modified` DESC
		""",
		(filters.get("price_list"),),
		as_dict=1,
	)
	
	# Get item stock UOMs for matching
	item_stock_uoms = {}
	items = frappe.db.sql("""SELECT `name`, `stock_uom` FROM `tabItem`""", as_dict=1)
	for item in items:
		item_stock_uoms[item.name] = item.stock_uom
	
	for price in item_prices:
		# If price not set for this item yet, or if this price matches stock UOM, use it
		if price.item_code not in price_list_rates:
			price_list_rates[price.item_code] = price.price_list_rate
		elif price.uom == item_stock_uoms.get(price.item_code):
			# Prefer price with matching stock UOM
			price_list_rates[price.item_code] = price.price_list_rate
	
	return price_list_rates

