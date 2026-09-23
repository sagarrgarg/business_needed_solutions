// Copyright (c) 2026, Sagar Ratan Garg and contributors
// For license information, please see license.txt

frappe.query_reports["Pure Party Trial Balance"] = {
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
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
			on_change: function (query_report) {
				const fiscal_year = frappe.query_report.get_filter_value("fiscal_year");
				if (!fiscal_year) return;
				frappe.model.with_doc("Fiscal Year", fiscal_year, function () {
					const fy = frappe.model.get_doc("Fiscal Year", fiscal_year);
					frappe.query_report.set_filter_value({
						from_date: fy.year_start_date,
						to_date: fy.year_end_date,
					});
				});
			},
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[2],
			reqd: 1,
		},
		{
			fieldname: "party_type",
			label: __("Party Type"),
			fieldtype: "Select",
			options: ["", "Customer", "Supplier"],
			description: __("Leave blank to show receivables and payables together"),
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "Dynamic Link",
			get_options: function () {
				const party_type = frappe.query_report.get_filter_value("party_type");
				if (frappe.query_report.get_filter_value("party") && !party_type) {
					frappe.throw(__("Please select Party Type first"));
				}
				return party_type;
			},
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "MultiSelectList",
			options: "Account",
			get_data: function (txt) {
				return frappe.db.get_link_options("Account", txt, {
					company: frappe.query_report.get_filter_value("company"),
					account_type: ["in", ["Receivable", "Payable"]],
				});
			},
		},
		{
			fieldname: "only_pure_accounts",
			label: __("Only Receivable / Payable accounts"),
			fieldtype: "Check",
			default: 1,
			description: __("Untick to include every account carrying the party, as Trial Balance for Party does"),
		},
		{
			fieldname: "include_internal_accounts",
			label: __("Include internal branch accounts"),
			fieldtype: "Check",
			default: 0,
			description: __("BNS Internal Debtor / Internal Creditor are excluded by default"),
		},
		{
			fieldname: "knock_off_linked_parties",
			label: __("Knock off linked customer / supplier"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "match_unlinked_by_pan",
			label: __("Also knock off same-PAN parties without a Party Link"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_members",
			label: __("Show netted parties separately"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_purity_check",
			label: __("Compare with Trial Balance for Party"),
			fieldtype: "Check",
			default: 0,
			description: __("Adds the all-accounts closing and the amount sitting outside Receivable/Payable"),
		},
		{
			fieldname: "show_ageing",
			label: __("Show netted ageing"),
			fieldtype: "Check",
			default: 0,
			description: __("Ageing is struck as at the To Date, netted bucket by bucket across linked parties"),
		},
		{
			fieldname: "ageing_based_on",
			label: __("Ageing Based On"),
			fieldtype: "Select",
			options: ["Due Date", "Posting Date"],
			default: "Due Date",
			depends_on: "show_ageing",
		},
		{
			fieldname: "ranges",
			label: __("Ageing Range"),
			fieldtype: "Data",
			default: "30, 60, 90, 120",
			depends_on: "show_ageing",
		},
		{
			fieldname: "adjust_running_accounts",
			label: __("Adjust Ageing for Running Accounts (FIFO)"),
			fieldtype: "Check",
			default: 1,
			depends_on: "show_ageing",
			description: __("Same treatment as Pure Accounts Receivable / Payable Summary"),
		},
		{
			fieldname: "show_zero_balance",
			label: __("Show zero balance parties"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (data.indent === 1) {
			value = `<span style="color:var(--text-muted)">${value}</span>`;
		}
		if (column.fieldname === "purity_difference" && flt(data.purity_difference)) {
			value = `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "party_name" && data.is_knocked_off) {
			value = `<span style="font-weight:600">${value || ""}</span>`;
		}
		return value;
	},
};
