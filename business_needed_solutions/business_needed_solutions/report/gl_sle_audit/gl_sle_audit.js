// Copyright (c) 2026, Sagar Ratan Garg and contributors
// For license information, please see license.txt

frappe.query_reports["GL SLE Audit"] = {
    filters: [
        {
            fieldname: "cutoff_date",
            label: __("Cutoff Date (posting_date >=)"),
            fieldtype: "Date",
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
            reqd: 0,
        },
        // No Doctypes filter — the audit always scans every doctype in
        // AUDIT_SPEC (SI, PI, DN, PR, Stock Entry, Stock Reconciliation,
        // Journal Entry, Landed Cost Voucher, Payment Entry). When the JS
        // sends an empty / undefined doctypes value, audit_gl_sle defaults
        // to list(AUDIT_SPEC.keys()).
        {
            fieldname: "statuses",
            label: __("Statuses"),
            fieldtype: "MultiSelectList",
            get_data: function () {
                return [
                    { value: "Missing GL", description: "" },
                    { value: "Missing SLE", description: "" },
                    { value: "Missing GL & SLE", description: "" },
                    { value: "Imbalanced GL", description: "sum(dr) ≠ sum(cr)" },
                ];
            },
            default: [],
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        {
            fieldname: "limit",
            label: __("Max Flagged Rows per Doctype"),
            fieldtype: "Int",
            default: 50000,
            description: __("Caps the number of flagged rows returned per doctype. The full document set within the Cutoff Date is always scanned — older documents are never hidden by this limit."),
        },
    ],

    formatter: function (value, row, column, data, default_formatter) {
        const v = default_formatter(value, row, column, data);
        if (column.fieldname === "status" && data && data.status) {
            const s = data.status;
            if (s.startsWith("Missing")) {
                return `<span style="color:#c0392b;font-weight:600">${v}</span>`;
            }
            if (s.startsWith("Imbalanced")) {
                return `<span style="color:#d35400;font-weight:600">${v}</span>`;
            }
            if (s.startsWith("AUDIT ERROR")) {
                return `<span style="color:#7f1d1d;font-weight:700">${v}</span>`;
            }
        }
        return v;
    },

    onload: function (report) {
        report.page.add_inner_button(
            __("Preview Repair (Dry Run)"),
            () => bns_repair_action(report, true),
            __("Repair"),
        );

        report.page.add_inner_button(
            __("Repair Missing Only"),
            () => bns_repair_action(report, false, { fix_missing: 1, fix_imbalanced: 0 }),
            __("Repair"),
        );

        report.page.add_inner_button(
            __("Repair Missing + Imbalanced"),
            () => bns_repair_action(report, false, { fix_missing: 1, fix_imbalanced: 1 }),
            __("Repair"),
        );
    },
};

function bns_repair_action(report, dry_run, fixFlags) {
    fixFlags = fixFlags || { fix_missing: 1, fix_imbalanced: 0 };

    const data = (report.data || []).filter((r) => r && r.doctype && r.name);
    if (!data.length) {
        frappe.msgprint(__("Run the report first; no rows to repair."));
        return;
    }

    const cutoff = report.get_filter_value("cutoff_date");
    if (!cutoff && !dry_run) {
        frappe.msgprint(__("Set a Cutoff Date before running a real repair. Audit logs the cutoff with the repair action."));
        return;
    }

    const label = dry_run ? __("Preview") : __("Apply Repair");
    const msg = dry_run
        ? __("Preview repair plan for {0} row(s)? This does not change any data.", [data.length])
        : __("Repair {0} row(s) with cutoff {1}?<br><br>This will re-run make_gl_entries / update_stock_ledger on each doc. The cutoff is logged with the action.", [data.length, cutoff]);

    frappe.confirm(msg, function () {
        const docs = data.map((r) => ({ doctype: r.doctype, name: r.name, status: r.status }));
        frappe.call({
            method: "business_needed_solutions.business_needed_solutions.gl_sle_audit.repair_gl_sle",
            args: {
                docs: JSON.stringify(docs),
                cutoff_date: cutoff || null,
                fix_missing: fixFlags.fix_missing,
                fix_imbalanced: fixFlags.fix_imbalanced,
                dry_run: dry_run ? 1 : 0,
            },
            freeze: true,
            freeze_message: dry_run ? __("Building preview...") : __("Repairing — this may take a while..."),
            callback: function (r) {
                if (!r.message) return;
                const m = r.message;

                // Background-mode path: server enqueued the job and returned
                // {queued: true, job_name}. Subscribe to realtime events and
                // show a live progress dialog.
                if (m.queued) {
                    bns_show_repair_progress_dialog(report, m);
                    return;
                }

                const repaired = (m.repaired || []).length;
                const skipped = (m.skipped || []).length;
                const errors = (m.errors || []).length;

                // Tally actual mutations from details payload.
                let actuallyChanged = 0;
                let alreadyOk = 0;
                (m.repaired || []).forEach(function (row) {
                    const d = row.details || {};
                    const ran = (d.actions_run || []).length;
                    if (ran > 0) actuallyChanged += 1;
                    else alreadyOk += 1;
                });

                // Build per-doc detail rows for the first 20 results.
                let rowsHtml = "";
                (m.repaired || []).slice(0, 20).forEach(function (row) {
                    const d = row.details || {};
                    const ran = (d.actions_run || []).join(", ") || "—";
                    const sk = (d.skipped || []).map(function (s) { return s.step + " (" + s.reason + ")"; }).join("; ") || "—";
                    rowsHtml += `<tr>
                        <td>${frappe.utils.escape_html(row.doctype)}</td>
                        <td>${frappe.utils.escape_html(row.name)}</td>
                        <td>${d.live_gl_before ?? "?"} → ${d.live_gl_after ?? "?"}</td>
                        <td>${d.live_sle_before ?? "?"} → ${d.live_sle_after ?? "?"}</td>
                        <td>${frappe.utils.escape_html(ran)}</td>
                        <td>${frappe.utils.escape_html(sk)}</td>
                    </tr>`;
                });
                let errorsHtml = "";
                (m.errors || []).slice(0, 10).forEach(function (e) {
                    errorsHtml += `<tr>
                        <td>${frappe.utils.escape_html(e.doctype)}</td>
                        <td>${frappe.utils.escape_html(e.name)}</td>
                        <td colspan="4" style="color:#c0392b">${frappe.utils.escape_html(e.error)}</td>
                    </tr>`;
                });

                frappe.msgprint({
                    title: dry_run ? __("Repair Preview") : __("Repair Result"),
                    indicator: errors ? "red" : (actuallyChanged ? "green" : "orange"),
                    message: `
                        <div>
                            <p><b>${label}</b> · cutoff=${m.cutoff_date || "(none)"} · fix_missing=${m.fix_missing ? "Y" : "N"} · fix_imbalanced=${m.fix_imbalanced ? "Y" : "N"} · dry_run=${m.dry_run ? "Y" : "N"}</p>
                            <p>
                                ${__("Attempted")}: <b>${m.attempted}</b> ·
                                ${__("Mutated")}: <b style="color:#16a34a">${actuallyChanged}</b> ·
                                ${__("Already OK / no-op")}: <b>${alreadyOk}</b> ·
                                ${__("Skipped by filter")}: <b>${skipped}</b> ·
                                ${__("Errors")}: <b style="color:${errors ? '#c0392b' : 'inherit'}">${errors}</b>
                            </p>
                            ${rowsHtml ? `<table class="table table-condensed" style="font-size:11px"><thead><tr><th>Doctype</th><th>Name</th><th>GL</th><th>SLE</th><th>Actions Run</th><th>Skipped Steps</th></tr></thead><tbody>${rowsHtml}</tbody></table>` : ""}
                            ${errorsHtml ? `<p><b>${__("Errors")}:</b></p><table class="table table-condensed" style="font-size:11px"><tbody>${errorsHtml}</tbody></table>` : ""}
                            ${(m.repaired || []).length > 20 ? `<p style="color:#666">(showing first 20 of ${(m.repaired || []).length})</p>` : ""}
                        </div>`,
                    wide: true,
                });
                if (!dry_run && actuallyChanged) {
                    report.refresh();
                }
            },
        });
    });
}

function bns_show_repair_progress_dialog(report, queueResp) {
    // Live progress dialog for background-mode repairs.
    // Subscribes to `gl_sle_repair_progress` (per-doc tick) and
    // `gl_sle_repair_done` (final result) realtime events.
    const total = queueResp.attempted || 0;
    const jobName = queueResp.job_name || "";

    const dlg = new frappe.ui.Dialog({
        title: __("Repair Running in Background"),
        size: "large",
        fields: [
            { fieldtype: "HTML", fieldname: "info" },
            { fieldtype: "HTML", fieldname: "bar" },
            { fieldtype: "HTML", fieldname: "log" },
        ],
        primary_action_label: __("Close"),
        primary_action: () => dlg.hide(),
    });

    dlg.show();
    dlg.fields_dict.info.$wrapper.html(`
        <div style="margin-bottom:8px">
            <p><b>${__("Job queued")}:</b> ${frappe.utils.escape_html(jobName)}</p>
            <p>${__("Repairing")} <b>${total}</b> ${__("documents on the long queue.")}
               ${__("You can close this dialog — the job will keep running and you'll be notified when it finishes.")}</p>
        </div>
    `);
    dlg.fields_dict.bar.$wrapper.html(`
        <div class="progress" style="height:18px">
            <div class="bns-progress-bar progress-bar progress-bar-striped active"
                 role="progressbar" style="width:0%">0 / ${total}</div>
        </div>
        <p class="bns-progress-status" style="font-size:11px;color:#666;margin-top:6px">${__("Waiting for worker...")}</p>
    `);
    dlg.fields_dict.log.$wrapper.html(`
        <div class="bns-progress-tally" style="margin-top:10px">
            <span class="badge badge-success">${__("Repaired")}: <b class="bns-cnt-repaired">0</b></span>
            <span class="badge badge-warning">${__("Skipped")}: <b class="bns-cnt-skipped">0</b></span>
            <span class="badge badge-danger">${__("Errors")}: <b class="bns-cnt-errors">0</b></span>
        </div>
        <pre class="bns-progress-tail" style="margin-top:10px;max-height:200px;overflow:auto;font-size:11px;background:#f8f9fa;padding:8px;border-radius:4px"></pre>
    `);

    const counters = { repaired: 0, skipped: 0, error: 0 };
    let tailLines = [];

    const progressHandler = (data) => {
        if (counters.hasOwnProperty(data.outcome)) {
            counters[data.outcome] += 1;
        }
        dlg.$wrapper.find(".bns-cnt-repaired").text(counters.repaired);
        dlg.$wrapper.find(".bns-cnt-skipped").text(counters.skipped);
        dlg.$wrapper.find(".bns-cnt-errors").text(counters.error);

        const pct = data.percent || 0;
        dlg.$wrapper.find(".bns-progress-bar")
            .css("width", pct + "%")
            .text(`${data.current} / ${data.total}  (${pct}%)`);
        dlg.$wrapper.find(".bns-progress-status").text(
            `${data.outcome}: ${data.doctype || ""} ${data.name || ""}`,
        );

        tailLines.push(`[${data.current}/${data.total}] ${data.outcome.padEnd(8)} ${data.doctype || ""} ${data.name || ""}`);
        if (tailLines.length > 50) tailLines = tailLines.slice(-50);
        dlg.$wrapper.find(".bns-progress-tail").text(tailLines.join("\n"));
    };

    const doneHandler = (result) => {
        dlg.$wrapper.find(".bns-progress-bar")
            .removeClass("active progress-bar-striped")
            .addClass(result.errors && result.errors.length ? "progress-bar-danger" : "progress-bar-success")
            .css("width", "100%")
            .text(__("Done"));
        const r = (result.repaired || []).length;
        const s = (result.skipped || []).length;
        const e = (result.errors || []).length;
        dlg.fields_dict.info.$wrapper.append(`
            <div class="alert alert-${e ? 'danger' : 'success'}" style="margin-top:10px">
                <b>${__("Repair Complete")}</b> · ${__("Attempted")}: ${result.attempted}
                · ${__("Repaired")}: ${r} · ${__("Skipped")}: ${s} · ${__("Errors")}: ${e}
            </div>
        `);
        if (e && result.errors[0]) {
            dlg.fields_dict.log.$wrapper.append(
                `<p style="color:#c0392b;margin-top:8px">${__("First error")}: ${frappe.utils.escape_html(result.errors[0].error || "")}</p>`,
            );
        }
        // Auto-refresh the report so the user sees fewer rows.
        report.refresh();

        // Cleanup listeners.
        frappe.realtime.off("gl_sle_repair_progress", progressHandler);
        frappe.realtime.off("gl_sle_repair_done", doneHandler);
    };

    frappe.realtime.on("gl_sle_repair_progress", progressHandler);
    frappe.realtime.on("gl_sle_repair_done", doneHandler);

    // Poll fallback. Realtime events can be lost (subscribe-after-publish
    // race, SocketIO reconnect, multi-tab session). Polling the cached
    // progress/result every 3s makes the dialog recover deterministically.
    let pollInterval = null;
    let lastPolledCurrent = -1;
    const poll = () => {
        frappe.call({
            method: "business_needed_solutions.business_needed_solutions.gl_sle_audit.get_repair_status",
            args: { job_name: jobName },
            freeze: false,
            no_spinner: true,
            callback: (r) => {
                const m = r.message || {};
                if (!m.found) return;
                if (m.progress && m.progress.current !== lastPolledCurrent) {
                    lastPolledCurrent = m.progress.current;
                    progressHandler(m.progress);
                }
                if (m.done && m.result) {
                    doneHandler(m.result);
                    if (pollInterval) {
                        clearInterval(pollInterval);
                        pollInterval = null;
                    }
                }
            },
        });
    };
    pollInterval = setInterval(poll, 3000);
    // Kick a poll immediately so a finished job shows up without waiting 3s.
    setTimeout(poll, 250);

    dlg.$wrapper.on("hidden.bs.modal", () => {
        frappe.realtime.off("gl_sle_repair_progress", progressHandler);
        frappe.realtime.off("gl_sle_repair_done", doneHandler);
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    });
}
