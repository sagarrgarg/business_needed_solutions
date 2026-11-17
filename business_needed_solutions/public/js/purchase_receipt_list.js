// Extend ERPNext's Purchase Receipt list view settings (loaded before this file)
// instead of replacing them, so ERPNext's statuses, add_fields and bulk actions stay.
if (!frappe.listview_settings['Purchase Receipt']) {
    frappe.listview_settings['Purchase Receipt'] = {};
}

const bns_pr_settings = frappe.listview_settings['Purchase Receipt'];
const original_pr_get_indicator = bns_pr_settings.get_indicator;

bns_pr_settings.get_indicator = function(doc) {
    if (doc.status === "BNS Internally Transferred") {
        return [__("BNS Internally Transferred"), "purple", "status,=,BNS Internally Transferred"];
    }
    if (original_pr_get_indicator) {
        return original_pr_get_indicator(doc);
    }
};
