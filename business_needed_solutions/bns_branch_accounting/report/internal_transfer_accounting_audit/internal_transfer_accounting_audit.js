// Copyright (c) 2026, Business Needed Solutions and Contributors
// License: Commercial

frappe.query_reports["Internal Transfer Accounting Audit"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      default: frappe.defaults.get_user_default("Company"),
      reqd: 0
    },
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
      reqd: 0
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
      reqd: 0
    },
    {
      fieldname: "document_type",
      label: __("Document Type"),
      fieldtype: "Select",
      options: "\nDelivery Note\nSales Invoice\nPurchase Receipt\nPurchase Invoice",
      reqd: 0
    }
  ],

  onload(report) {
    if (report.get_filter("from_date") && !report.get_filter_value("from_date")) {
      frappe.db.get_single_value("BNS Branch Accounting Settings", "internal_validation_cutoff_date")
        .then((cutoffDate) => {
          if (cutoffDate && report.get_filter("from_date") && !report.get_filter_value("from_date")) {
            report.set_filter_value("from_date", cutoffDate);
          }
        });
    }

    report.page.add_inner_button(__("Repost SLE"), function () {
      _triggerBulkRepost(report, "sle");
    }, __("Actions"));

    report.page.add_inner_button(__("Repost GL"), function () {
      _triggerBulkRepost(report, "gl");
    }, __("Actions"));
  }
};

function _triggerBulkRepost(report, repostType) {
  var data = report.data || [];
  if (!data.length) {
    frappe.msgprint(__("No audit data available. Run the report first."));
    return;
  }

  var documents = [];
  var deviationFilter = repostType === "sle" ? _hasSleDeviation : _hasGlDeviation;

  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    if (row.document_type && row.document_name && deviationFilter(row)) {
      documents.push({
        voucher_type: row.document_type,
        voucher_no: row.document_name
      });
    }
  }

  if (!documents.length) {
    frappe.msgprint(
      repostType === "sle"
        ? __("No documents with SLE deviations found in current report data.")
        : __("No documents with GL deviations found in current report data.")
    );
    return;
  }

  var label = repostType === "sle" ? __("SLE") : __("GL");
  frappe.confirm(
    __("This will enqueue {0} repost for {1} document(s) as a background job. Continue?", [label, documents.length]),
    function () {
      var method = repostType === "sle"
        ? "business_needed_solutions.bns_branch_accounting.report.internal_transfer_accounting_audit.internal_transfer_accounting_audit.repost_sle_for_audit_documents"
        : "business_needed_solutions.bns_branch_accounting.report.internal_transfer_accounting_audit.internal_transfer_accounting_audit.repost_gl_for_audit_documents";

      frappe.xcall(method, { documents: documents }).then(function (r) {
        if (r && r.message) {
          frappe.msgprint(r.message);
        } else if (r && r.success) {
          frappe.msgprint(r.message || __("Repost job enqueued."));
        }
      });
    }
  );
}

function _hasSleDeviation(row) {
  var dt = (row.deviation_type || "").toLowerCase();
  return dt === "sle mismatch" || dt === "both" || !!(row.sle_issue);
}

function _hasGlDeviation(row) {
  var dt = (row.deviation_type || "").toLowerCase();
  return dt === "gl mismatch" || dt === "gl missing" || dt === "both";
}
