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

// --- BNS Bulk Cancel (Background) ---
const _original_onload = frappe.listview_settings['Sales Invoice'].onload;
frappe.listview_settings['Sales Invoice'].onload = function(listview) {
    if (_original_onload) {
        try { _original_onload(listview); } catch (e) { /* ignore */ }
    }

    if (!frappe.user.has_role(["System Manager", "Accounts Manager", "Accounts User"])) {
        return;
    }

    frappe.call({
        method: "business_needed_solutions.business_needed_solutions.bulk_cancel.is_enabled",
        callback: function(r) {
            if (!r || !r.message || !r.message.enabled) return;

            listview.page.add_menu_item(__("Bulk Cancel (Background)"), function() {
                bns_open_bulk_cancel_dialog(listview);
            });

            listview.page.add_menu_item(__("Stop All Bulk Cancel Jobs"), function() {
                bns_open_stop_all_dialog();
            });
        }
    });
};

function bns_current_list_filters(listview) {
    // listview.filter_area.get() returns [[doctype, field, op, value], ...]
    try {
        return (listview.filter_area && listview.filter_area.get()) || [];
    } catch (e) {
        return [];
    }
}

function bns_format_filters_human(filters) {
    if (!filters || !filters.length) return __("(no filters — entire Sales Invoice table)");
    return filters.map(f => {
        // [doctype, fieldname, operator, value]
        const [, field, op, val] = f;
        return `<code>${frappe.utils.escape_html(field)} ${frappe.utils.escape_html(op)} ${frappe.utils.escape_html(String(val))}</code>`;
    }).join(" &nbsp; ");
}

function bns_open_bulk_cancel_dialog(listview) {
    const filters = bns_current_list_filters(listview);

    frappe.call({
        method: "business_needed_solutions.business_needed_solutions.bulk_cancel.preview",
        args: { filters: JSON.stringify(filters) },
        freeze: true,
        freeze_message: __("Counting matching Sales Invoices…"),
        callback: function(r) {
            if (!r || !r.message) return;
            const counts = r.message;
            const html = `
                <div style="line-height:1.7">
                    <div><b>${__("Current list filters")}:</b> ${bns_format_filters_human(filters)}</div>
                    <hr>
                    <div>${__("Submitted (will be cancelled)")}: <b>${counts.submitted}</b></div>
                    <div>${__("Drafts (skipped)")}: ${counts.drafts}</div>
                    <div>${__("Already cancelled (skipped)")}: ${counts.cancelled}</div>
                </div>`;

            const d = new frappe.ui.Dialog({
                title: __("Bulk Cancel Sales Invoices"),
                size: "large",
                fields: [
                    { fieldtype: "HTML", fieldname: "summary", options: html },
                    { fieldtype: "Section Break" },
                    {
                        fieldtype: "Int",
                        fieldname: "max_docs",
                        label: __("Max docs to cancel (blank = all)"),
                        description: __("Safety cap. Leave blank to cancel every matching SI.")
                    },
                    {
                        fieldtype: "Check",
                        fieldname: "confirm",
                        label: __("I understand this cancels {0} submitted invoices in the background and triggers GL reversals.", [counts.submitted]),
                    },
                ],
                primary_action_label: __("Enqueue Cancellation"),
                primary_action: function(values) {
                    if (!values.confirm) {
                        frappe.show_alert({ message: __("Tick the confirmation box first."), indicator: "orange" });
                        return;
                    }
                    if (!counts.submitted) {
                        frappe.show_alert({ message: __("Nothing to cancel."), indicator: "orange" });
                        d.hide();
                        return;
                    }
                    frappe.call({
                        method: "business_needed_solutions.business_needed_solutions.bulk_cancel.enqueue_bulk_cancel",
                        args: {
                            filters: JSON.stringify(filters),
                            max_docs: values.max_docs || null,
                        },
                        freeze: true,
                        freeze_message: __("Enqueuing background jobs…"),
                        callback: function(rr) {
                            d.hide();
                            if (rr && rr.message && rr.message.token) {
                                bns_track_bulk_cancel_progress(rr.message);
                            }
                        }
                    });
                }
            });
            d.show();
        }
    });
}

function bns_track_bulk_cancel_progress(info) {
    const { token, total } = info;
    const d = new frappe.ui.Dialog({
        title: __("Bulk Cancel Progress"),
        fields: [
            { fieldtype: "HTML", fieldname: "bar", options: `<div id="bns-bc-bar" style="margin:8px 0">${__("Starting…")}</div>` }
        ],
    });
    d.show();

    function render(state) {
        const done = state.done || 0;
        const failed = state.failed || 0;
        const tot = state.total || total || 0;
        const pct = tot ? Math.min(100, Math.round(((done + failed) / tot) * 100)) : 0;
        const $bar = d.$wrapper.find("#bns-bc-bar");
        $bar.html(`
            <div>${__("Total")}: <b>${tot}</b> &nbsp; ${__("Cancelled")}: <b>${done}</b> &nbsp; ${__("Failed")}: <b>${failed}</b></div>
            <div class="progress" style="margin-top:8px">
                <div class="progress-bar" style="width:${pct}%">${pct}%</div>
            </div>
            <div style="margin-top:8px;font-size:12px;color:#888">
                ${__("You can close this. Progress continues in background. Errors go to Error Log.")}
            </div>
        `);
    }
    render({ total: total, done: 0, failed: 0 });

    frappe.realtime.on("bns_bulk_cancel_si_progress", function(msg) {
        if (!msg || msg.token !== token) return;
        render(msg);
    });

    // Fallback poll every 10s in case realtime missed
    const poll = setInterval(function() {
        if (!d.$wrapper.is(":visible")) { clearInterval(poll); return; }
        frappe.call({
            method: "business_needed_solutions.business_needed_solutions.bulk_cancel.get_progress",
            args: { token },
            callback: function(r) { if (r && r.message) render(r.message); }
        });
    }, 10000);
}

function bns_open_stop_all_dialog() {
    frappe.call({
        method: "business_needed_solutions.business_needed_solutions.bulk_cancel.list_active_jobs",
        freeze: true,
        freeze_message: __("Scanning queue…"),
        callback: function(r) {
            if (!r || !r.message) return;
            const { queued_count, running_count } = r.message;
            const html = `
                <div style="line-height:1.7">
                    <div>${__("Queued bulk-cancel jobs")}: <b>${queued_count}</b></div>
                    <div>${__("Currently running")}: <b>${running_count}</b></div>
                    <hr>
                    <div style="color:#888;font-size:12px">
                        ${__("Queued jobs are dropped cleanly. Running jobs (mid-batch) are left alone by default — they finish their current 50-doc chunk. Force-stop only if you must (kills the active SI mid-cancel; doc may need manual cleanup).")}
                    </div>
                </div>`;
            const d = new frappe.ui.Dialog({
                title: __("Stop All Bulk Cancel Jobs"),
                fields: [
                    { fieldtype: "HTML", options: html },
                    { fieldtype: "Section Break" },
                    {
                        fieldtype: "Check",
                        fieldname: "force_running",
                        label: __("Also force-stop running jobs (DANGEROUS)"),
                    }
                ],
                primary_action_label: __("Stop"),
                primary_action: function(values) {
                    frappe.call({
                        method: "business_needed_solutions.business_needed_solutions.bulk_cancel.stop_all",
                        args: { force_running: values.force_running ? 1 : 0 },
                        freeze: true,
                        freeze_message: __("Stopping…"),
                        callback: function(rr) {
                            d.hide();
                            if (!rr || !rr.message) return;
                            const m = rr.message;
                            frappe.msgprint({
                                title: __("Done"),
                                indicator: "orange",
                                message: __("Cancelled {0} queued. Stopped {1} running. Left {2} running.",
                                    [m.cancelled_queued, m.stopped_running, m.left_running]),
                            });
                        }
                    });
                }
            });
            d.show();
        }
    });
}
