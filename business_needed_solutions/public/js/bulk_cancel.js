// BNS Bulk Cancel (Background) — list-view UI.
//
// Loaded globally via app_include_js (so the ?v= query param reliably busts the
// browser cache on every release). It attaches its menu items on *route change*
// to a supported list view — NOT via listview_settings[doctype].onload, because
// a global script runs once at desk boot, BEFORE ERPNext's per-doctype list JS,
// which reassigns listview_settings[doctype] and would wipe a pre-set onload
// with no chance to re-wrap. The router approach re-runs on every navigation.

(function () {
    const M = "business_needed_solutions.business_needed_solutions.bulk_cancel";
    const SUPPORTED = [
        "Sales Invoice",
        "Purchase Invoice",
        "Delivery Note",
        "Purchase Receipt",
        "Stock Entry",
        "Journal Entry",
        "Payment Entry",
    ];

    function bns_attach_bulk_cancel(listview) {
        const doctype = listview.doctype;

        // Guard: don't add the menu items twice for the same list instance.
        if (listview.__bns_bc_added) return;

        // Only show to users who can actually cancel this doctype (backend
        // re-checks the cancel permission on every call regardless).
        if (!frappe.model.can_cancel(doctype)) return;

        listview.__bns_bc_added = true;

        frappe.call({
            method: M + ".is_enabled",
            args: { doctype: doctype },
            callback: function (r) {
                if (!r || !r.message || !r.message.enabled) return;

                listview.page.add_menu_item(__("Bulk Cancel (Background)"), function () {
                    bns_open_bulk_cancel_dialog(listview, doctype);
                });

                listview.page.add_menu_item(__("Stop All Bulk Cancel Jobs"), function () {
                    bns_open_stop_all_dialog(doctype);
                });
            },
        });
    }

    function bns_current_list_filters(listview) {
        // listview.filter_area.get() returns [[doctype, field, op, value], ...]
        try {
            return (listview.filter_area && listview.filter_area.get()) || [];
        } catch (e) {
            return [];
        }
    }

    function bns_format_filters_human(filters) {
        return filters
            .map(function (f) {
                const field = f[1], op = f[2], val = f[3];
                return `<code>${frappe.utils.escape_html(field)} ${frappe.utils.escape_html(op)} ${frappe.utils.escape_html(String(val))}</code>`;
            })
            .join(" &nbsp; ");
    }

    function bns_open_bulk_cancel_dialog(listview, doctype) {
        const filters = bns_current_list_filters(listview);

        frappe.call({
            method: M + ".preview",
            args: { doctype: doctype, filters: JSON.stringify(filters) },
            freeze: true,
            freeze_message: __("Counting matching {0}…", [doctype]),
            callback: function (r) {
                if (!r || !r.message) return;
                const counts = r.message;
                const filters_human = filters && filters.length
                    ? bns_format_filters_human(filters)
                    : __("(no filters — entire {0} table)", [doctype]);
                const html = `
                    <div style="line-height:1.7">
                        <div><b>${__("Current list filters")}:</b> ${filters_human}</div>
                        <hr>
                        <div>${__("Submitted (will be cancelled)")}: <b>${counts.submitted}</b></div>
                        <div>${__("Drafts (skipped)")}: ${counts.drafts}</div>
                        <div>${__("Already cancelled (skipped)")}: ${counts.cancelled}</div>
                    </div>`;

                const d = new frappe.ui.Dialog({
                    title: __("Bulk Cancel {0}", [doctype]),
                    size: "large",
                    fields: [
                        { fieldtype: "HTML", fieldname: "summary", options: html },
                        { fieldtype: "Section Break" },
                        {
                            fieldtype: "Int",
                            fieldname: "max_docs",
                            label: __("Max docs to cancel (blank = all)"),
                            description: __("Safety cap. Leave blank to cancel every matching document."),
                        },
                        {
                            fieldtype: "Check",
                            fieldname: "confirm",
                            label: __(
                                "I understand this cancels {0} submitted documents in the background and triggers GL/stock reversals.",
                                [counts.submitted]
                            ),
                        },
                    ],
                    primary_action_label: __("Enqueue Cancellation"),
                    primary_action: function (values) {
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
                            method: M + ".enqueue_bulk_cancel",
                            args: {
                                doctype: doctype,
                                filters: JSON.stringify(filters),
                                max_docs: values.max_docs || null,
                            },
                            freeze: true,
                            freeze_message: __("Enqueuing background jobs…"),
                            callback: function (rr) {
                                d.hide();
                                if (rr && rr.message && rr.message.token) {
                                    bns_track_bulk_cancel_progress(rr.message);
                                }
                            },
                        });
                    },
                });
                d.show();
            },
        });
    }

    function bns_track_bulk_cancel_progress(info) {
        const token = info.token;
        const total0 = info.total;
        const d = new frappe.ui.Dialog({
            title: __("Bulk Cancel Progress"),
            fields: [
                { fieldtype: "HTML", fieldname: "bar", options: `<div id="bns-bc-bar" style="margin:8px 0">${__("Starting…")}</div>` },
            ],
        });
        d.show();

        function render(state) {
            const done = state.done || 0;
            const failed = state.failed || 0;
            const tot = state.total || total0 || 0;
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
        render({ total: total0, done: 0, failed: 0 });

        frappe.realtime.on("bns_bulk_cancel_progress", function (msg) {
            if (!msg || msg.token !== token) return;
            render(msg);
        });

        // Fallback poll every 10s in case realtime missed
        const poll = setInterval(function () {
            if (!d.$wrapper.is(":visible")) {
                clearInterval(poll);
                return;
            }
            frappe.call({
                method: M + ".get_progress",
                args: { token: token },
                callback: function (r) {
                    if (r && r.message) render(r.message);
                },
            });
        }, 10000);
    }

    function bns_open_stop_all_dialog(doctype) {
        frappe.call({
            method: M + ".list_active_jobs",
            args: { doctype: doctype },
            freeze: true,
            freeze_message: __("Scanning queue…"),
            callback: function (r) {
                if (!r || !r.message) return;
                const queued_count = r.message.queued_count;
                const running_count = r.message.running_count;
                const html = `
                    <div style="line-height:1.7">
                        <div>${__("Queued bulk-cancel jobs")} (${frappe.utils.escape_html(doctype)}): <b>${queued_count}</b></div>
                        <div>${__("Currently running")}: <b>${running_count}</b></div>
                        <hr>
                        <div style="color:#888;font-size:12px">
                            ${__("Queued jobs are dropped cleanly. Running jobs (mid-batch) are left alone by default — they finish their current 50-doc chunk. Force-stop only if you must (kills the active doc mid-cancel; doc may need manual cleanup).")}
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
                        },
                    ],
                    primary_action_label: __("Stop"),
                    primary_action: function (values) {
                        frappe.call({
                            method: M + ".stop_all",
                            args: { doctype: doctype, force_running: values.force_running ? 1 : 0 },
                            freeze: true,
                            freeze_message: __("Stopping…"),
                            callback: function (rr) {
                                d.hide();
                                if (!rr || !rr.message) return;
                                const m = rr.message;
                                frappe.msgprint({
                                    title: __("Done"),
                                    indicator: "orange",
                                    message: __("Cancelled {0} queued. Stopped {1} running. Left {2} running.", [
                                        m.cancelled_queued,
                                        m.stopped_running,
                                        m.left_running,
                                    ]),
                                });
                            },
                        });
                    },
                });
                d.show();
            },
        });
    }

    // --- Attach on navigation to a supported list view ---
    function bns_on_route() {
        const route = frappe.get_route() || [];
        if (route[0] !== "List") return;
        const doctype = route[1];
        if (SUPPORTED.indexOf(doctype) === -1) return;

        // cur_list may lag the route change; retry briefly until it's the right list.
        let tries = 0;
        (function wait() {
            if (typeof cur_list !== "undefined" && cur_list && cur_list.doctype === doctype && cur_list.page) {
                bns_attach_bulk_cancel(cur_list);
                return;
            }
            if (tries++ < 40) setTimeout(wait, 50);
        })();
    }

    frappe.router.on("change", bns_on_route);
    bns_on_route(); // handle a full-page load that lands directly on a list
})();
