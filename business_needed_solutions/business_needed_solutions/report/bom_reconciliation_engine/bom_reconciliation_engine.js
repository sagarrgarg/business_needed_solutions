// Copyright (c) 2026, Sagar Ratan Garg and contributors
// For license information, please see license.txt

frappe.query_reports["BOM Reconciliation Engine"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company (consuming)"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 1,
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.year_start(),
            reqd: 1,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.year_end(),
            reqd: 1,
        },
        {
            fieldname: "fg_item_group",
            label: __("FG Item Group (optional)"),
            fieldtype: "Link",
            options: "Item Group",
        },
        {
            fieldname: "fg_code_prefix",
            label: __("FG Code Prefix (optional)"),
            fieldtype: "Data",
            description: __("e.g. 'M' to scope to the Murga (M-series) finished goods"),
        },
        {
            fieldname: "negative_only",
            label: __("Negative Stock Only"),
            fieldtype: "Check",
            default: 1,
            description: __(
                "Only show components whose stock actually went negative during the period " +
                "(true negative-stock episodes), not every component with a demand/supply gap."
            ),
        },
        {
            fieldname: "supplier_stock",
            label: __("Supplier Available Stock (JSON)"),
            fieldtype: "Small Text",
            description: __(
                "Optional. Paste {\"item_code\": available_qty, ...} for the supplier company " +
                "(e.g. RKCW opening + purchases). When given, the gap is split into " +
                "Deliver-via-DN vs Unexplained."
            ),
        },
    ],

    formatter: function (value, row, column, data, default_formatter) {
        const v = default_formatter(value, row, column, data);
        if (data) {
            if (column.fieldname === "unexplained" && flt(data.unexplained) > 0.001) {
                return `<span style="color:#c0392b;font-weight:600">${v}</span>`;
            }
            if (column.fieldname === "bom_vs_actual_var" && Math.abs(flt(data.bom_vs_actual_var)) > 0.001) {
                const c = flt(data.bom_vs_actual_var) > 0 ? "#d35400" : "#2471a3";
                return `<span style="color:${c}">${v}</span>`;
            }
            if (column.fieldname === "gap" && flt(data.gap) > 0.001) {
                return `<span style="font-weight:600">${v}</span>`;
            }
        }
        return v;
    },
};
