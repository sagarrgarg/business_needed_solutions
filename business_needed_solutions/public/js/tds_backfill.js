// Role-gated "Backfill TDS" action for a submitted Purchase Invoice.
// Visible only when BNS Settings > "Allow Backfilling TDS on Submitted Purchase
// Invoices" is ON and the user holds an allowed role (server-enforced too).
// Shows a read-only preview first; applying unreconciles payments, adds the TDS
// tax row, recomputes totals, and posts only the incremental TDS GL.
window.bns_maybe_add_tds_backfill_button = function (frm) {
    if (frm.doc.docstatus !== 1) return;
    frappe.call({
        method: "business_needed_solutions.business_needed_solutions.overrides.tds_backfill.can_backfill_tds",
        callback: function (r) {
            if (!r.message) return;
            frm.add_custom_button(__("Backfill TDS"), function () {
                frappe.call({
                    method: "business_needed_solutions.business_needed_solutions.overrides.tds_backfill.preview_tds_backfill",
                    args: { name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Computing TDS..."),
                    callback: function (res) {
                        const p = res.message || {};
                        bns_show_tds_preview_dialog(frm, p);
                    },
                });
            }, __("Create"));
        },
    });
};

function bns_show_tds_preview_dialog(frm, p) {
    const fmt = (v) => format_currency(v, frappe.boot.sysdefaults.currency);
    const warn = (p.warnings || []).map((w) => `<li>${frappe.utils.escape_html(w)}</li>`).join("");
    const pv = (p.paying_vouchers || []).map((v) => `${v.type} ${v.name}`).join(", ") || "—";
    const canApply = flt(p.tds_amount) > 0 && !p.already_has_tds;

    const html = `
        <table class="table table-bordered">
          <tr><td>${__("Supplier")}</td><td>${frappe.utils.escape_html(p.supplier || "")}</td></tr>
          <tr><td>${__("TDS Category")}</td><td>${frappe.utils.escape_html(p.category || "—")}</td></tr>
          <tr><td>${__("Computed TDS")}</td><td><b>${fmt(p.tds_amount)}</b></td></tr>
          <tr><td>${__("Grand Total")}</td><td>${fmt(p.grand_total)} → <b>${fmt(p.new_grand_total)}</b></td></tr>
          <tr><td>${__("Outstanding")}</td><td>${fmt(p.outstanding_amount)} → <b>${fmt(p.new_outstanding)}</b></td></tr>
          <tr><td>${__("Payments to unreconcile")}</td><td>${frappe.utils.escape_html(pv)}</td></tr>
        </table>
        ${warn ? `<div class="text-warning"><b>${__("Notes")}</b><ul>${warn}</ul></div>` : ""}`;

    const d = new frappe.ui.Dialog({
        title: __("Backfill TDS — {0}", [frm.doc.name]),
        fields: [{ fieldtype: "HTML", fieldname: "body", options: html }],
        primary_action_label: canApply ? __("Apply TDS") : __("Close"),
        primary_action() {
            if (!canApply) { d.hide(); return; }
            frappe.confirm(
                __("Add TDS of {0} to submitted {1}? Payments will be unreconciled and the incremental TDS GL posted.", [fmt(p.tds_amount), frm.doc.name]),
                function () {
                    frappe.call({
                        method: "business_needed_solutions.business_needed_solutions.overrides.tds_backfill.apply_tds_backfill",
                        args: { name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Applying TDS..."),
                        callback: function (res) {
                            d.hide();
                            const m = res.message || {};
                            if (m.changed) {
                                frappe.show_alert({ message: __("TDS {0} applied.", [fmt(m.tds_amount)]), indicator: "green" });
                                frm.reload_doc();
                            } else {
                                frappe.msgprint(m.reason || __("No change."));
                            }
                        },
                    });
                }
            );
        },
    });
    d.show();
}
