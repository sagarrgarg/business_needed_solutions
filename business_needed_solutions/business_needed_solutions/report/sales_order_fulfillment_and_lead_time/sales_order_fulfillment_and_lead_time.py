# Copyright (c) 2026, Sagar Garg and Contributors
# License: GNU General Public License v3. See license.txt

"""Sales Order Fulfillment and Lead Time.

Itemised, order-line level report answering, per Sales Person or Sales Partner:
  - what was ordered by which party (qty + amount),
  - how much of each line got billed (billed vs ordered = fulfillment %),
  - how long it took from order date to the first invoice (lead time in days).

Either a Sales Person or a Sales Partner filter is compulsory.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate_filters(filters)

	data = _get_data(filters)
	columns = _get_columns(filters)
	report_summary = _get_report_summary(data, filters)
	chart = _get_chart(data)

	return columns, data, None, chart, report_summary


def _validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("{0} is mandatory").format(_("Company")))

	if not filters.get("sales_person") and not filters.get("sales_partner"):
		frappe.throw(_("Select a <b>Sales Person</b> or a <b>Sales Partner</b> to run this report."))

	if filters.get("from_date") and filters.get("to_date"):
		if getdate(filters.from_date) > getdate(filters.to_date):
			frappe.throw(_("From Date must be before To Date"))


def _get_data(filters):
	conditions = ["so.docstatus = 1", "so.company = %(company)s"]

	if filters.get("from_date"):
		conditions.append("so.transaction_date >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("so.transaction_date <= %(to_date)s")
	if filters.get("customer"):
		conditions.append("so.customer = %(customer)s")
	if filters.get("item_group"):
		conditions.append("soi.item_group = %(item_group)s")
	if filters.get("sales_partner"):
		conditions.append("so.sales_partner = %(sales_partner)s")

	# Sales Person lives in the Sales Team child table; join only when filtered.
	if filters.get("sales_person"):
		sp_join = (
			"INNER JOIN `tabSales Team` st "
			"ON st.parent = so.name AND st.parenttype = 'Sales Order' "
			"AND st.sales_person = %(sales_person)s"
		)
		sp_select = "st.sales_person AS sales_person, st.allocated_percentage AS allocation_pct"
	else:
		sp_join = ""
		sp_select = "NULL AS sales_person, NULL AS allocation_pct"

	query = """
		SELECT
			{sp_select},
			so.sales_partner            AS sales_partner,
			so.customer                 AS customer,
			so.customer_name            AS customer_name,
			so.name                     AS sales_order,
			so.transaction_date         AS order_date,
			soi.item_code               AS item_code,
			soi.item_name               AS item_name,
			soi.uom                     AS uom,
			soi.qty                     AS ordered_qty,
			soi.base_net_amount         AS ordered_amount,
			b.billed_qty                AS billed_qty,
			b.billed_amount             AS billed_amount,
			b.first_bill_date           AS first_bill_date,
			b.first_invoice             AS first_invoice,
			b.invoices                  AS invoices
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		{sp_join}
		LEFT JOIN (
			SELECT
				sii.so_detail AS so_detail,
				SUM(sii.qty) AS billed_qty,
				SUM(sii.base_net_amount) AS billed_amount,
				MIN(si.posting_date) AS first_bill_date,
				SUBSTRING_INDEX(MIN(CONCAT(si.posting_date, '::', sii.parent)), '::', -1) AS first_invoice,
				GROUP_CONCAT(DISTINCT sii.parent ORDER BY sii.parent SEPARATOR ', ') AS invoices
			FROM `tabSales Invoice Item` sii
			INNER JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
			WHERE sii.so_detail IS NOT NULL AND sii.so_detail != ''
			GROUP BY sii.so_detail
		) b ON b.so_detail = soi.name
		WHERE {conditions}
		ORDER BY so.transaction_date, so.name, soi.idx
	""".format(
		sp_select=sp_select,
		sp_join=sp_join,
		conditions=" AND ".join(conditions),
	)

	rows = frappe.db.sql(query, filters, as_dict=True)

	for r in rows:
		ordered_qty = flt(r.ordered_qty)
		ordered_amount = flt(r.ordered_amount)
		billed_qty = flt(r.billed_qty)
		billed_amount = flt(r.billed_amount)

		r.qty_fulfillment_pct = (billed_qty / ordered_qty * 100.0) if ordered_qty else 0.0
		r.amount_fulfillment_pct = (billed_amount / ordered_amount * 100.0) if ordered_amount else 0.0
		r.open_amount = ordered_amount - billed_amount

		# Sales-person credited share (split by allocation %)
		alloc = flt(r.allocation_pct)
		if r.sales_person and alloc:
			r.credited_ordered = ordered_amount * alloc / 100.0
			r.credited_billed = billed_amount * alloc / 100.0

		if r.first_bill_date and r.order_date:
			r.order_to_bill_days = date_diff(r.first_bill_date, r.order_date)
		else:
			r.order_to_bill_days = None

	return rows


def _get_columns(filters):
	columns = []

	if filters.get("sales_person"):
		columns.append({"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 130})
	if filters.get("sales_partner"):
		columns.append({"label": _("Sales Partner"), "fieldname": "sales_partner", "fieldtype": "Link", "options": "Sales Partner", "width": 130})

	columns += [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 110},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 160},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
		{"label": _("Order Date"), "fieldname": "order_date", "fieldtype": "Date", "width": 95},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 70},
		{"label": _("Ordered Qty"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Ordered Amt"), "fieldname": "ordered_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Billed Qty"), "fieldname": "billed_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Billed Amt"), "fieldname": "billed_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Qty Fulfilled %"), "fieldname": "qty_fulfillment_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Amt Fulfilled %"), "fieldname": "amount_fulfillment_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Open Amt"), "fieldname": "open_amount", "fieldtype": "Currency", "width": 110},
	]

	if filters.get("sales_person"):
		columns += [
			{"label": _("Alloc %"), "fieldname": "allocation_pct", "fieldtype": "Percent", "width": 80},
			{"label": _("Credited Ordered"), "fieldname": "credited_ordered", "fieldtype": "Currency", "width": 120},
			{"label": _("Credited Billed"), "fieldname": "credited_billed", "fieldtype": "Currency", "width": 120},
		]

	columns += [
		{"label": _("First Invoice"), "fieldname": "first_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
		{"label": _("First Bill Date"), "fieldname": "first_bill_date", "fieldtype": "Date", "width": 100},
		{"label": _("Order → Bill (days)"), "fieldname": "order_to_bill_days", "fieldtype": "Int", "width": 120},
		{"label": _("All Invoices"), "fieldname": "invoices", "fieldtype": "Data", "width": 200},
	]

	return columns


def _get_report_summary(data, filters):
	total_ordered = sum(flt(r.ordered_amount) for r in data)
	total_billed = sum(flt(r.billed_amount) for r in data)
	open_amount = total_ordered - total_billed

	billed_lines = [r for r in data if r.order_to_bill_days is not None]
	avg_days = (sum(r.order_to_bill_days for r in billed_lines) / len(billed_lines)) if billed_lines else 0

	fully_billed = [r for r in data if flt(r.qty_fulfillment_pct) >= 99.99]
	fully_billed_pct = (len(fully_billed) / len(data) * 100.0) if data else 0

	overall_pct = (total_billed / total_ordered * 100.0) if total_ordered else 0
	currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")

	return [
		{"label": _("Total Ordered"), "value": total_ordered, "datatype": "Currency", "currency": currency, "indicator": "Blue"},
		{"label": _("Total Billed"), "value": total_billed, "datatype": "Currency", "currency": currency, "indicator": "Green"},
		{"label": _("Open (Unbilled)"), "value": open_amount, "datatype": "Currency", "currency": currency, "indicator": "Orange" if open_amount > 0 else "Green"},
		{"label": _("Overall Billed %"), "value": overall_pct, "datatype": "Percent", "indicator": "Green" if overall_pct >= 90 else "Red"},
		{"label": _("Lines Fully Billed %"), "value": fully_billed_pct, "datatype": "Percent", "indicator": "Green" if fully_billed_pct >= 90 else "Red"},
		{"label": _("Avg Order → Bill (days)"), "value": round(avg_days, 1), "datatype": "Float", "indicator": "Red" if avg_days > 15 else "Green"},
	]


def _get_chart(data):
	# Ordered vs Billed for the top customers by ordered value.
	by_customer = {}
	for r in data:
		key = r.customer_name or r.customer or "?"
		agg = by_customer.setdefault(key, {"ordered": 0.0, "billed": 0.0})
		agg["ordered"] += flt(r.ordered_amount)
		agg["billed"] += flt(r.billed_amount)

	top = sorted(by_customer.items(), key=lambda kv: kv[1]["ordered"], reverse=True)[:10]
	if not top:
		return None

	labels = [k for k, _v in top]
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Ordered"), "values": [v["ordered"] for _k, v in top]},
				{"name": _("Billed"), "values": [v["billed"] for _k, v in top]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 0},
	}
