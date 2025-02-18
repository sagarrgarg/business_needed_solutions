// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Party GL"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		// {
		// 	fieldname: "finance_book",
		// 	label: __("Finance Book"),
		// 	fieldtype: "Link",
		// 	options: "Finance Book",
		// },
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
			width: "60px",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			width: "60px",
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "MultiSelectList",
			hidden:1,
			options: "Account",
			get_data: function (txt) {
				return frappe.db.get_link_options("Account", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "voucher_no",
			label: __("Voucher No"),
			fieldtype: "Data",
			hidden:1,
			on_change: function () {
				frappe.query_report.set_filter_value("group_by", "Group by Voucher (Consolidated)");
			},
		},
		{
			fieldname: "against_voucher_no",
			label: __("Against Voucher No"),
			fieldtype: "Data",
			hidden:1,
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "MultiSelectList",
		
			get_data: function (txt) {
				// Hardcode the party types to be "Customer" and "Supplier"
				let party_types = ["Customer", "Supplier"];
		
				// For each type, fetch matching options
				let promises = party_types.map((party_type) =>
					frappe.db.get_link_options(party_type, txt)
				);
		
				// Merge the lists from each doctype
				return Promise.all(promises).then((results) => {
					let options = [].concat(...results);
					return options;
				});
			},
		
			on_change: function () {
				// Get the current list of selected parties
				let parties = frappe.query_report.get_filter_value("party") || [];
		
				// If the user selects more than one item,
				// keep ONLY the newly selected item (the last in the array)
				if (parties.length > 1) {
					let newest = parties[parties.length - 1];
					parties = [newest];
					frappe.query_report.set_filter_value("party", parties);
				}
		
				// Now `parties` has either 0 or 1 item
				if (!parties.length) {
					// If nothing is selected, clear the dependent fields
					frappe.query_report.set_filter_value("party_name", "");
					frappe.query_report.set_filter_value("tax_id", "");
					return;
				}
		
				// We have exactly 1 selected party now
				let party = parties[0];
		
				// Check if it's a Customer or Supplier, fetch name & tax_id
				let party_types = ["Customer", "Supplier"];
				party_types.forEach((party_type) => {
					frappe.db.exists(party_type, party).then((exists) => {
						if (exists) {
							let fieldname = erpnext.utils.get_party_name(party_type) || "name";
		
							frappe.db.get_value(party_type, party, fieldname, function (value) {
								frappe.query_report.set_filter_value("party_name", value[fieldname]);
							});
		
							frappe.db.get_value(party_type, party, "tax_id", function (value) {
								frappe.query_report.set_filter_value("tax_id", value["tax_id"]);
							});
						}
					});
				});
			},
		},
		
		
		
		{
			fieldname: "party_name",
			label: __("Party Name"),
			fieldtype: "Data",
			hidden: 1,
		},
		{
			fieldtype: "Break",
		},
		{
			fieldname: "group_by",
			label: __("Group by"),
			hidden:1,
			fieldtype: "Select",
			options: [
				"",
				{
					label: __("Group by Voucher"),
					value: "Group by Voucher",
				},
				{
					label: __("Group by Voucher (Consolidated)"),
					value: "Group by Voucher (Consolidated)",
				},
				{
					label: __("Group by Account"),
					value: "Group by Account",
				},
				{
					label: __("Group by Party"),
					value: "Group by Party",
				},
			],
			default: "Group by Voucher (Consolidated)",
		},
		{
			fieldname: "tax_id",
			label: __("Tax Id"),
			fieldtype: "Data",
			hidden: 1,
		},
		{
			fieldname: "presentation_currency",
			label: __("Currency"),
			fieldtype: "Select",
			hidden:1,
			options: erpnext.get_presentation_currency_list(),
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			default:"",
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Cost Center", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "project",
			label: __("Project"),
			hidden:1,
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				return frappe.db.get_link_options("Project", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "include_dimensions",
			label: __("Consider Accounting Dimensions"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "show_opening_entries",
			label: __("Show Opening Entries"),
			fieldtype: "Check",
		},
		{
			fieldname: "include_default_book_entries",
			label: __("Include Default FB Entries"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "show_cancelled_entries",
			label: __("Show Cancelled Entries"),
			fieldtype: "Check",
			hidden:1,
		},
		{
			fieldname: "show_net_values_in_party_account",
			label: __("Show Net Values in Party Account"),
			fieldtype: "Check",
		},
		{
			fieldname: "add_values_in_transaction_currency",
			label: __("Add Columns in Transaction Currency"),
			fieldtype: "Check",
		},
		{
			fieldname: "show_remarks",
			label: __("Show Remarks"),
			fieldtype: "Check",
		},
		{
			fieldname: "ignore_err",
			label: __("Ignore Exchange Rate Revaluation Journals"),
			fieldtype: "Check",
		},
		{
			fieldname: "ignore_cr_dr_notes",
			label: __("Ignore System Generated Credit / Debit Notes"),
			fieldtype: "Check",
		},
	],
};

erpnext.utils.add_dimensions("Party GL", 15);