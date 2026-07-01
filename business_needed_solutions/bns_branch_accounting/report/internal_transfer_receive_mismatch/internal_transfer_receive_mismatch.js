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

		report.page.add_inner_button(__("Repair DN ↔ PR Back-References"), function() {
			_repairBackReferences(report);
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
		__("This reconciles {0} document(s) to their party master and reposts: external master -> clear internal flag/status/reference (external GL); internal master -> heal the missing doc flag (keep reference, internal GL). Continue?", [documents.length]),
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

const _BACKREF_REPAIR_METHOD =
	"business_needed_solutions.bns_branch_accounting.utils.repair_asymmetric_dn_back_references";

// "Repair DN <-> PR Back-References": completes half-written links where a PR
// already references the DN but the DN's own bns_inter_company_reference is empty
// (the 'DN <-> PR Back-Reference' rows). Preview (dry_run) -> Apply. Scoped to the
// report's current company / date filters.
function _repairBackReferences(report) {
	var f = (report.get_filter_values && report.get_filter_values()) || {};
	var scope = {
		company: f.company || null,
		from_date: f.from_date || null,
		to_date: f.to_date || null,
	};
	frappe.call({
		method: _BACKREF_REPAIR_METHOD,
		args: Object.assign({ dry_run: 1 }, scope),
		freeze: true,
		freeze_message: __("Scanning for half-linked DN ↔ PR pairs…"),
		callback: function(r) {
			if (r && r.message) {
				_showBackRefPreview(report, r.message, scope);
			}
		},
	});
}

function _renderBackRefPreview(res) {
	var esc = frappe.utils.escape_html;
	var html = '<div style="line-height:1.7">';
	html += "<div><b>" + __("To repair (PR already references DN; DN back-ref missing)") + ":</b> " + res.total_planned + "</div>";
	html += "<div><b>" + __("Skipped (ambiguous / conflict)") + ":</b> " + res.total_skipped + "</div>";

	if (res.actions && res.actions.length) {
		html += '<hr><table class="table table-bordered" style="font-size:12px"><thead><tr><th>' +
			__("Delivery Note") + "</th><th>" + __("→ Purchase Receipt") + "</th><th>" + __("Posting Date") + "</th></tr></thead><tbody>";
		res.actions.slice(0, 200).forEach(function(a) {
			html += "<tr><td>" + esc(a.name) + "</td><td>" + esc(a.purchase_receipt || "") +
				"</td><td>" + esc(String(a.posting_date || "")) + "</td></tr>";
		});
		html += "</tbody></table>";
		if (res.actions.length > 200) {
			html += '<div style="color:#888">' + __("… and {0} more", [res.actions.length - 200]) + "</div>";
		}
	}

	if (res.skipped && res.skipped.length) {
		html += "<hr><b>" + __("Skipped") + ':</b><table class="table table-bordered" style="font-size:12px"><tbody>';
		res.skipped.slice(0, 50).forEach(function(s) {
			html += '<tr><td style="white-space:nowrap">' + esc(String(s.name)) + "</td><td>" + esc(s.reason || "") + "</td></tr>";
		});
		html += "</tbody></table>";
		if (res.skipped.length > 50) {
			html += '<div style="color:#888">' + __("… and {0} more", [res.skipped.length - 50]) + "</div>";
		}
	}
	html += "</div>";
	return html;
}

function _showBackRefPreview(report, res, scope) {
	if (!res.total_planned && !res.total_skipped) {
		frappe.msgprint({
			title: __("Nothing to repair"),
			indicator: "green",
			message: __("No half-linked DN ↔ PR pairs found for the current filters."),
		});
		return;
	}

	var d = new frappe.ui.Dialog({
		title: __("Repair DN ↔ PR Back-References — Preview"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body", options: _renderBackRefPreview(res) }],
		primary_action_label: res.total_planned ? __("Apply {0} repair(s)", [res.total_planned]) : __("Close"),
		primary_action: function() {
			if (!res.total_planned) { d.hide(); return; }
			frappe.call({
				method: _BACKREF_REPAIR_METHOD,
				args: Object.assign({ dry_run: 0 }, scope),
				freeze: true,
				freeze_message: __("Repairing back-references…"),
				callback: function(r2) {
					d.hide();
					var out = r2 && r2.message;
					if (out) {
						frappe.show_alert({
							message: __("Repaired {0} DN(s); {1} skipped.", [out.total_planned, out.total_skipped]),
							indicator: out.total_planned ? "green" : "orange",
						}, 7);
						report.refresh();
					}
				},
			});
		},
	});
	d.show();
}

