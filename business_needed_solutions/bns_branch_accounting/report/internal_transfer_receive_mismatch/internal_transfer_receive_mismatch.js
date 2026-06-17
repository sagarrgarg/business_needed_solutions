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
		frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_transfer_cutoff_fy")
			.then((fy) => {
				if (fy) {
					return frappe.db.get_value("Fiscal Year", fy, "year_start_date");
				}
			})
			.then((r) => {
				var startDate = r && r.message && r.message.year_start_date;
				if (startDate && report.get_filter("from_date")) {
					report.set_filter_value("from_date", startDate);
				}
			});

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

		report.page.add_inner_button(__("Fix External / Foreign-Reference Rows"), function() {
			_fixExternalPartyRows(report);
		}, __("Actions"));
	}
};

function _isExternalPartyRow(row) {
	// Both detections describe a doc treated as internal while its party master is
	// external: "External party treated as internal" (flag/status set) and
	// "Foreign-party reference" (carries a bns_inter_company_reference it shouldn't).
	var tc = (row.transfer_chain || "");
	return tc === "External party treated as internal" || tc === "Foreign-party reference";
}

function _fixExternalPartyRows(report) {
	var data = (report.data || []);
	if (!data.length) {
		frappe.msgprint(__("No report data available. Run the report first."));
		return;
	}

	var seen = {};
	var documents = [];
	for (var i = 0; i < data.length; i++) {
		var row = data[i];
		if (!row.document_type || !row.document_name || !_isExternalPartyRow(row)) {
			continue;
		}
		var key = row.document_type + "::" + row.document_name;
		if (seen[key]) {
			continue;
		}
		seen[key] = 1;
		documents.push({ voucher_type: row.document_type, voucher_no: row.document_name });
	}

	if (!documents.length) {
		frappe.msgprint(__("No external-party / foreign-reference rows found in current report data."));
		return;
	}

	frappe.confirm(
		__("This clears the internal flag / status / reference on {0} document(s) whose party master is external, and reposts their GL to the normal external pattern. Documents whose party is actually internal are skipped. Continue?", [documents.length]),
		function() {
			frappe.xcall(
				"business_needed_solutions.bns_branch_accounting.report.internal_transfer_receive_mismatch.internal_transfer_receive_mismatch.fix_external_party_internal_documents",
				{ documents: documents }
			).then(function(r) {
				if (r && r.message) {
					frappe.msgprint(r.message);
				}
			});
		}
	);
}

