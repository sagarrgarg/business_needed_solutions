// Role-gated "Edit Posting Time" action for submitted stock vouchers.
// Visible only when BNS Settings > "Allow Editing Posting Time After Submit" is ON
// and the current user holds an allowed role (server-enforced too). The change
// deletes and recreates the voucher's SLE + GL fresh at the new posting time and
// reposts downstream.
window.bns_maybe_add_posting_time_button = function (frm) {
    if (frm.doc.docstatus !== 1) return;
    frappe.call({
        method: "business_needed_solutions.business_needed_solutions.overrides.posting_time_edit.can_edit_posting_time",
        callback: function (r) {
            if (!r.message) return;
            frm.add_custom_button(__("Edit Posting Time"), function () {
                const d = new frappe.ui.Dialog({
                    title: __("Edit Posting Date / Time"),
                    fields: [
                        {
                            fieldname: "posting_date", fieldtype: "Date",
                            label: __("Posting Date"), reqd: 1, default: frm.doc.posting_date,
                        },
                        {
                            fieldname: "posting_time", fieldtype: "Time",
                            label: __("Posting Time"), reqd: 1, default: frm.doc.posting_time,
                        },
                        {
                            fieldtype: "HTML", fieldname: "note",
                            options: `<div class="text-muted small">${__(
                                "This changes a SUBMITTED document: its stock ledger and GL are deleted and recreated at the new time, and downstream entries repost. Frozen periods are refused."
                            )}</div>`,
                        },
                    ],
                    primary_action_label: __("Update & Repost"),
                    primary_action(values) {
                        frappe.confirm(
                            __("Rebuild ledgers for {0} at {1} {2}?", [frm.doc.name, values.posting_date, values.posting_time]),
                            function () {
                                frappe.call({
                                    method: "business_needed_solutions.business_needed_solutions.overrides.posting_time_edit.bns_update_posting_time",
                                    args: {
                                        doctype: frm.doctype,
                                        docname: frm.doc.name,
                                        posting_date: values.posting_date,
                                        posting_time: values.posting_time,
                                    },
                                    freeze: true,
                                    freeze_message: __("Updating &amp; enqueuing repost..."),
                                    callback: function (res) {
                                        d.hide();
                                        if (res.message && res.message.changed) {
                                            frappe.show_alert({
                                                message: __("Posting time updated; ledgers rebuilding (repost {0}).", [res.message.repost]),
                                                indicator: "green",
                                            });
                                            frm.reload_doc();
                                        } else {
                                            frappe.show_alert(__("No change."));
                                        }
                                    },
                                });
                            }
                        );
                    },
                });
                d.show();
            }, __("Actions"));
        },
    });
};
