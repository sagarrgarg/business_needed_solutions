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
			hidden: 1,
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
			hidden: 1,
			on_change: function () {
				frappe.query_report.set_filter_value("group_by", "Group by Voucher (Consolidated)");
			},
		},
		{
			fieldname: "against_voucher_no",
			label: __("Against Voucher No"),
			fieldtype: "Data",
			hidden: 1,
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				let party_types = ["Customer", "Supplier"];
				let promises = party_types.map((party_type) =>
					frappe.db.get_link_options(party_type, txt)
				);
				return Promise.all(promises).then((results) => {
					let options = [].concat(...results);
					return options;
				});
			},
			on_change: function () {
				let parties = frappe.query_report.get_filter_value("party") || [];
				if (parties.length > 1) {
					let newest = parties[parties.length - 1];
					parties = [newest];
					frappe.query_report.set_filter_value("party", parties);
				}
				if (!parties.length) {
					frappe.query_report.set_filter_value("party_name", "");
					frappe.query_report.set_filter_value("tax_id", "");
					return;
				}
				let party = parties[0];
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
			hidden: 1,
			fieldtype: "Select",
			options: [
				"",
				{ label: __("Group by Voucher"), value: "Group by Voucher" },
				{ label: __("Group by Voucher (Consolidated)"), value: "Group by Voucher (Consolidated)" },
				{ label: __("Group by Account"), value: "Group by Account" },
				{ label: __("Group by Party"), value: "Group by Party" },
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
			hidden: 1,
			options: erpnext.get_presentation_currency_list(),
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			default: "",
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
			hidden: 1,
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
			hidden: 1,
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
		// Add Download Statement button after a short delay
		setTimeout(function() {
			if (!document.querySelector('.btn-download-statement')) {
				report.page.add_inner_button(__("Download Statement"), function() {
					downloadStatementPDF(report);
				}).addClass('btn-primary btn-download-statement');
			}
		}, 300);
		
		// Load statement meta on initial render
		setTimeout(function() {
			loadStatementMeta(report);
		}, 800);
	},
	
	after_datatable_render: function(datatable) {
		// Load statement meta after datatable renders
		loadStatementMeta(frappe.query_report);
	},
};

// Global storage for statement metadata (used by HTML template during PDF generation)
window._party_gl_statement_meta = null;

/**
 * Load all statement metadata from server in a single call.
 * This ensures all data is available for both screen and PDF rendering.
 */
function loadStatementMeta(report) {
	var filters = report.get_filter_values();
	
	if (!filters.party || !filters.party.length) {
		return;
	}
	
	console.log("Loading statement meta for party:", filters.party);
	
	// Call the server-side method to get all metadata
	frappe.call({
		method: "business_needed_solutions.business_needed_solutions.report.party_gl.party_gl.get_statement_meta",
		args: { filters: filters },
		async: false,  // Synchronous to ensure data is available before PDF
		callback: function(r) {
			if (r.message) {
				console.log("Statement meta loaded:", r.message);
				
				window._party_gl_statement_meta = r.message;
				
				// Store on report object for template access during PDF generation
				report._statement_meta = r.message;
				
				// Also store on frappe.query_report to ensure it's accessible
				if (frappe.query_report) {
					frappe.query_report._statement_meta = r.message;
				}
				
				// Update DOM elements with the loaded data
				updateDOMWithMeta(r.message, filters);
				
				// Update closing balance from report data
				updateClosingBalance(report);
			}
		},
		error: function(r) {
			console.error("Error loading statement meta:", r);
		}
	});
}

/**
 * Update DOM elements with metadata for on-screen display.
 */
function updateDOMWithMeta(meta, filters) {
	var currency = filters.presentation_currency || frappe.boot.sysdefaults.currency;
	
	// Company Info
	if (meta.company) {
		var logoContainer = document.getElementById("company-logo-container");
		if (logoContainer && meta.company.logo) {
			logoContainer.innerHTML = '<img src="' + meta.company.logo + '" height="125px" width="150px">';
		}
		
		var nameDisplay = document.getElementById("company-name-display");
		if (nameDisplay) {
			nameDisplay.innerHTML = '<b>' + (meta.company.name || '') + '</b>';
		}
		
		var pkaDisplay = document.getElementById("company-previously-known-as");
		if (pkaDisplay && meta.company.previously_known_as) {
			pkaDisplay.innerHTML = "Previously Known As: " + meta.company.previously_known_as;
		}
		
		// PAN and COI
		var panCoiDisplay = document.getElementById("company-pan-coi");
		if (panCoiDisplay) {
			var parts = [];
			if (meta.company.pan) parts.push('<strong>PAN:</strong> ' + meta.company.pan);
			if (meta.company.gstin) parts.push('<strong>GSTIN:</strong> ' + meta.company.gstin);
			if (meta.company.date_of_incorporation) parts.push('<strong>COI:</strong> ' + frappe.datetime.str_to_user(meta.company.date_of_incorporation));
			panCoiDisplay.innerHTML = parts.join(' | ');
		}
	}
	
	// Party Info - in header
	if (meta.party) {
		var partyAddrHeader = document.getElementById("party-address-header");
		if (partyAddrHeader) {
			partyAddrHeader.innerHTML = meta.party.address || '';
		}
	}
	
	// Company details
	if (meta.company) {
		var companyDetails = document.getElementById("company-details");
		if (companyDetails) {
			var parts = [];
			if (meta.company.pan) parts.push('PAN: ' + meta.company.pan);
			if (meta.company.gstin) parts.push('GSTIN: ' + meta.company.gstin);
			var html = parts.join(' | ');
			
			var parts2 = [];
			if (meta.company.cin) parts2.push('CIN: ' + meta.company.cin);
			if (meta.company.msme_no) {
				var msmeText = 'MSME: ' + meta.company.msme_no;
				if (meta.company.msme_type) msmeText += ' (' + meta.company.msme_type + ')';
				parts2.push(msmeText);
			}
			if (parts2.length > 0) {
				html += '<br>' + parts2.join(' | ');
			}
			companyDetails.innerHTML = html;
		}
	}
	
	// Bank Details (for Customers)
	if (meta.bank_details && Object.keys(meta.bank_details).length > 0) {
		var bankContainer = document.getElementById("bank-details-container");
		if (bankContainer) {
			bankContainer.style.display = "block";
		}
		
		var bankContent = document.getElementById("bank-details-content");
		if (bankContent) {
			var bank = meta.bank_details;
			var html = '';
			if (bank.bank) html += '<div class="bank-row"><span class="bank-label">Bank Name:</span> ' + bank.bank + '</div>';
			if (bank.account_name) html += '<div class="bank-row"><span class="bank-label">Account Name:</span> ' + bank.account_name + '</div>';
			if (bank.bank_account_no) html += '<div class="bank-row"><span class="bank-label">Account Number:</span> ' + bank.bank_account_no + '</div>';
			if (bank.branch_code) html += '<div class="bank-row"><span class="bank-label">Branch/IFSC:</span> ' + bank.branch_code + '</div>';
			if (bank.iban) html += '<div class="bank-row"><span class="bank-label">IBAN:</span> ' + bank.iban + '</div>';
			bankContent.innerHTML = html;
		}
	}
}

/**
 * Update closing balance from report data.
 */
function updateClosingBalance(report) {
	if (!report.data || !report.data.length) return;
	
	// Find the last row which should be the closing balance
	var lastRow = report.data[report.data.length - 1];
	
	// The balance field is formatted as "123.45 Dr" or "123.45 Cr"
	var closingBalance = lastRow.balance || '';
	
	var container = document.getElementById("closing-balance-display");
	if (container && closingBalance) {
		container.innerHTML = closingBalance;
	}
	
	// Also store it in meta for PDF
	if (report._statement_meta) {
		report._statement_meta.closing_balance = closingBalance;
	}
	if (window._party_gl_statement_meta) {
		window._party_gl_statement_meta.closing_balance = closingBalance;
	}
}

/**
 * Download Statement as PDF.
 * Ensures meta data is loaded before triggering PDF generation.
 */
async function downloadStatementPDF(report) {
	var filters = report.get_filter_values();
	
	if (!filters.party || !filters.party.length) {
		frappe.msgprint(__("Please select a Party first"));
		return;
	}
	
	if (!report.data || !report.data.length) {
		frappe.msgprint(__("Please run the report first"));
		return;
	}
	
	// Ensure meta is loaded (synchronous call)
	if (!window._party_gl_statement_meta) {
		loadStatementMeta(report);
	}
	
	// Store original get_filter_values function
	var original_get_filter_values = frappe.query_report.get_filter_values;
	
	// Override temporarily to return clean filter values (fixes toString() error on undefined)
	frappe.query_report.get_filter_values = function() {
		var vals = original_get_filter_values.call(frappe.query_report);
		Object.keys(vals).forEach(function(key) {
			if (vals[key] === undefined || vals[key] === null) {
				vals[key] = "";
			}
		});
		return vals;
	};
	
	// Trigger PDF generation
	var print_settings = {
		orientation: "Portrait"
	};
	
	try {
		await frappe.query_report.pdf_report(print_settings);
	} catch(e) {
		console.error("PDF generation error:", e);
		frappe.msgprint(__("Error generating PDF: ") + e.message);
	} finally {
		// Restore original function
		frappe.query_report.get_filter_values = original_get_filter_values;
	}
}

erpnext.utils.add_dimensions("Party GL", 15);
