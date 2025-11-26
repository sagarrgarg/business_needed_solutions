// Extend ERPNext's Purchase Invoice list view settings
if (!frappe.listview_settings['Purchase Invoice']) {
    frappe.listview_settings['Purchase Invoice'] = {};
}

const original_get_indicator_pi = frappe.listview_settings['Purchase Invoice'].get_indicator;
frappe.listview_settings['Purchase Invoice'].get_indicator = function(doc) {
    if (doc.status === "BNS Internally Transferred") {
        return [__("BNS Internally Transferred"), "purple", "status,=,BNS Internally Transferred"];
    }
    // Fall back to original ERPNext indicator logic
    if (original_get_indicator_pi) {
        return original_get_indicator_pi(doc);
    }
    // Default fallback
    const status_colors = {
        Unpaid: "orange",
        Paid: "green",
        Return: "gray",
        Overdue: "red",
        "Partly Paid": "yellow",
        "Internal Transfer": "darkgrey",
    };
    if (status_colors[doc.status]) {
        return [__(doc.status), status_colors[doc.status], "status,=," + doc.status];
    }
};

