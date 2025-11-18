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
	onload: function(report) {
		// Load company and party details for header
		report.on("after_render", function() {
			loadHeaderDetails(report);
		});
		// Also load immediately
		setTimeout(function() {
			loadHeaderDetails(report);
		}, 500);
	},
};

function loadHeaderDetails(report) {
	var company = report.get_filter_value("company");
	var party = report.get_filter_value("party");
	
	if (company) {
		frappe.call({
			method: "frappe.client.get",
			args: {
				doctype: "Company",
				name: company,
				fields: ["logo_for_printing", "bns_previously_known_as"]
			},
			callback: function(r) {
				if (r.message) {
					var company_data = r.message;
					
					// Load logo
					var logoContainer = document.getElementById("company-logo-container");
					if (logoContainer && company_data.logo_for_printing) {
						logoContainer.innerHTML = '<div><img height="125px" width="150px" src="' + company_data.logo_for_printing + '"></div>';
					}
					
					// Load previously known as
					var previouslyKnownAs = document.getElementById("company-previously-known-as");
					if (previouslyKnownAs && company_data.bns_previously_known_as) {
						previouslyKnownAs.innerHTML = "Previously Known As: " + company_data.bns_previously_known_as;
					}
				}
			}
		});
	}
	
	if (party && party.length > 0) {
		var party_name = party[0];
		
		// Determine party type
		frappe.db.exists("Customer", party_name).then(function(is_customer) {
			var party_type = is_customer ? "Customer" : "Supplier";
			
			// Get primary address
			frappe.call({
				method: "frappe.contacts.doctype.address.address.get_default_address",
				args: {
					doctype: party_type,
					name: party_name
				},
				callback: function(addr_r) {
					if (addr_r.message) {
						frappe.call({
							method: "frappe.client.get",
							args: {
								doctype: "Address",
								name: addr_r.message,
								fields: ["address_line1", "address_line2", "city", "state", "pincode", "country"]
							},
							callback: function(addr_detail_r) {
								if (addr_detail_r.message) {
									var addr = addr_detail_r.message;
									var addressContainer = document.getElementById("party-address-container");
									if (addressContainer && addr.address_line1) {
										var html = '<p style="margin-bottom:2px;">' + addr.address_line1;
										if (addr.address_line2) {
											html += ' ' + addr.address_line2 + '<br>';
										} else {
											html += '<br>';
										}
										html += addr.city + ', ' + addr.state + ', ' + addr.country + ': ' + addr.pincode + '</p>';
										addressContainer.innerHTML = html;
									}
								}
							}
						});
					}
				}
			});
		});
	}
}

erpnext.utils.add_dimensions("Party GL", 15);