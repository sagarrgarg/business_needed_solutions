// Copyright (c) 2025, Business Needed Solutions and Contributors
// License: Commercial

frappe.query_reports["Internal Transfer Receive Mismatch"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 0
		},
		{
			"fieldname": "customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"reqd": 0,
			"get_query": function() {
				return {
					"filters": {
						"is_bns_internal_customer": 1
					}
				}
			}
		},
		{
			"fieldname": "company_address",
			"label": __("Company Address"),
			"fieldtype": "Link",
			"options": "Address",
			"reqd": 0
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			"reqd": 0
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 0
		}
	],
	"onload": function(report) {
		// Set up company_address query filter
		if (report.get_filter('company_address')) {
			report.get_filter('company_address').df.get_query = function() {
				return {
					query: "business_needed_solutions.bns_branch_accounting.report.internal_transfer_receive_mismatch.internal_transfer_receive_mismatch.company_address_query",
					filters: {
						"is_company_address": 1
					}
				}
			}
		}
	}
};

