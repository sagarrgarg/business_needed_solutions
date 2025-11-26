// Extend ERPNext's Sales Invoice list view settings
if (!frappe.listview_settings['Sales Invoice']) {
    frappe.listview_settings['Sales Invoice'] = {};
}

const original_get_indicator = frappe.listview_settings['Sales Invoice'].get_indicator;
frappe.listview_settings['Sales Invoice'].get_indicator = function(doc) {
    if (doc.status === "BNS Internally Transferred") {
        return [__("BNS Internally Transferred"), "purple", "status,=,BNS Internally Transferred"];
    }
    // Fall back to original ERPNext indicator logic
    if (original_get_indicator) {
        return original_get_indicator(doc);
    }
    // Default fallback
    const status_colors = {
        Draft: "red",
        Unpaid: "orange",
        Paid: "green",
        Return: "gray",
        "Credit Note Issued": "gray",
        "Unpaid and Discounted": "orange",
        "Partly Paid and Discounted": "yellow",
        "Overdue and Discounted": "red",
        Overdue: "red",
        "Partly Paid": "yellow",
        "Internal Transfer": "darkgrey",
    };
    return [__(doc.status), status_colors[doc.status] || "gray", "status,=," + doc.status];
};

