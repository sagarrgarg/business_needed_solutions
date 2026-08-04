// Copyright (c) 2026, Sagar Garg and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Sales Order Fulfillment and Lead Time"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Order Date"),
			fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
		},
		{
			fieldname: "to_date",
			label: __("To Order Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "sales_partner",
			label: __("Sales Partner"),
			fieldtype: "Link",
			options: "Sales Partner",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
	],

	onload: function (report) {
		report.page.set_indicator(__("Pick a Sales Person or Sales Partner"), "orange");
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Colour the fulfillment % columns.
		if (["qty_fulfillment_pct", "amount_fulfillment_pct"].includes(column.fieldname)) {
			const pct = flt(data && data[column.fieldname]);
			let colour = "red";
			if (pct >= 99.99) colour = "green";
			else if (pct >= 75) colour = "orange";
			value = `<span style="color:${colour};font-weight:600">${value}</span>`;
		}

		// Flag slow order-to-bill lead times.
		if (column.fieldname === "order_to_bill_days" && data && data.order_to_bill_days != null) {
			const days = cint(data.order_to_bill_days);
			if (days > 15) value = `<span style="color:red;font-weight:600">${value}</span>`;
		}

		return value;
	},
};
