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
  }
};
