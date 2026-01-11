// Copyright (c) 2025, Sagar Ratan Garg and contributors
// For license information, please see license.txt

frappe.query_reports["Outgoing Stock Audit - 1 BNS"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1
		},
		{
			"fieldname": "warehouse",
			"label": __("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse",
			"get_query": function() {
				const company = frappe.query_report.get_filter_value('company');
				return {
					filters: { 'company': company }
				}
			}
		},
		{
			"fieldname": "item_group",
			"label": __("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group"
		},
		{
			"fieldname": "item_code",
			"label": __("Item Code"),
			"fieldtype": "MultiSelectList",
			"options": "Item",
			"get_data": async function(txt) {
				const item_group = frappe.query_report.get_filter_value('item_group');
				const company = frappe.query_report.get_filter_value('company');
				
				let filters = {
					'is_stock_item': 1
				};
				if (item_group) filters['item_group'] = item_group;
				
				let { message: data } = await frappe.call({
					method: "erpnext.controllers.queries.item_query",
					args: {
						doctype: "Item",
						txt: txt,
						searchfield: "name",
						start: 0,
						page_len: 20,
						filters: filters,
						as_dict: 1
					}
				});
				
				return (data || []).map(({ name, ...rest }) => ({
					value: name,
					description: Object.values(rest).filter(Boolean).join(" - ")
				}));
			}
		},
		{
			"fieldname": "include_doctypes",
			"label": __("Include DocTypes"),
			"fieldtype": "MultiSelectList",
			"options": "Sales Invoice\nPurchase Invoice\nDelivery Note\nPurchase Receipt",
			"default": ["Sales Invoice", "Purchase Invoice"]
		}
	]
};
