frappe.listview_settings['Delivery Note'] = {
    // Pull per_billed + gstins so the bulk-action client-side eligibility hint is
    // accurate (server re-checks authoritatively anyway).
    add_fields: ["per_billed", "company_gstin", "billing_address_gstin"],

    get_indicator: function(doc) {
        if (doc.status === "BNS Internally Transferred") {
            return [__("BNS Internally Transferred"), "purple", "status,=,BNS Internally Transferred"];
        } else if (doc.status === "Draft") {
            return [__("Draft"), "red", "status,=,Draft"];
        } else if (doc.status === "To Bill") {
            return [__("To Bill"), "orange", "status,=,To Bill"];
        } else if (doc.status === "Completed") {
            return [__("Completed"), "green", "status,=,Completed"];
        } else if (doc.status === "Return Issued") {
            return [__("Return Issued"), "grey", "status,=,Return Issued"];
        } else if (doc.status === "Cancelled") {
            return [__("Cancelled"), "red", "status,=,Cancelled"];
        } else if (doc.status === "Closed") {
            return [__("Closed"), "green", "status,=,Closed"];
        }
    },

    onload: function(listview) {
        // Bulk "Switch to Diff GSTIN Internal Transfer": appears in the multi-select
        // Actions dropdown. Only enabled when the org setting is ON.
        frappe.db.get_single_value('BNS Branch Accounting Settings', 'allow_different_gstin_dn_to_pr')
            .then((global_on) => {
                if (!global_on) {
                    return;
                }
                listview.page.add_actions_menu_item(
                    __('Switch to Diff GSTIN Internal Transfer'),
                    () => bns_bulk_switch_diff_gstin(listview),
                    false
                );
            });
    },
};

function bns_bulk_switch_diff_gstin(listview) {
    const items = listview.get_checked_items() || [];
    if (!items.length) {
        frappe.show_alert({ message: __('Select one or more Delivery Notes first.'), indicator: 'orange' });
        return;
    }

    // Client-side hint only: submitted, "To Bill", 0% billed. Server re-checks
    // internal-customer + diff-GSTIN + cutoff authoritatively and skips the rest.
    const eligible = items.filter(
        (d) => d.docstatus === 1 && d.status === 'To Bill' && !flt(d.per_billed)
    );
    const names = eligible.map((d) => d.name);
    const skipped_client = items.length - names.length;

    if (!names.length) {
        frappe.msgprint({
            title: __('Nothing eligible'),
            indicator: 'orange',
            message: __(
                'None of the {0} selected Delivery Notes are submitted "To Bill" with 0% billed.',
                [items.length]
            ),
        });
        return;
    }

    frappe.warn(
        __('Switch {0} Delivery Note(s) to Diff GSTIN Internal Transfer?', [names.length]),
        __(
            'These submitted "To Bill" DNs (0% billed) will be flagged and switched to ' +
            '"BNS Internally Transferred", rewriting each DN\'s GL to the internal pattern ' +
            '(where the posting date is past the Accounting Rewrite cutoff). Only inter-state ' +
            '(diff-GSTIN) internal-customer DNs qualify — ineligible ones are skipped server-side. ' +
            '{0} of your selection were already excluded (not "To Bill" / already billed). ' +
            'This runs in the background.',
            [skipped_client]
        ),
        () => {
            frappe.call({
                method: 'business_needed_solutions.bns_branch_accounting.utils.bulk_switch_diff_gstin_dns',
                args: { delivery_notes: JSON.stringify(names) },
                freeze: true,
                freeze_message: __('Enqueuing…'),
                callback: function(r) {
                    if (r && r.message && r.message.token) {
                        bns_track_diff_gstin_bulk(r.message, listview);
                    }
                },
            });
        },
        __('Switch'),
        true
    );
}

function bns_track_diff_gstin_bulk(info, listview) {
    const token = info.token;
    const total0 = info.total;
    const d = new frappe.ui.Dialog({
        title: __('Switch to Diff GSTIN Internal Transfer — Progress'),
        fields: [
            { fieldtype: 'HTML', fieldname: 'bar', options: `<div id="bns-dg-bar" style="margin:8px 0">${__('Starting…')}</div>` },
        ],
    });
    d.show();

    function render(state) {
        const tot = state.total || total0 || 0;
        const done = state.done || 0;
        const switched = state.switched || 0;
        const skipped = state.skipped || 0;
        const failed = state.failed || 0;
        const pct = tot ? Math.min(100, Math.round((done / tot) * 100)) : 0;
        d.$wrapper.find('#bns-dg-bar').html(`
            <div>${__('Total')}: <b>${tot}</b> &nbsp; ${__('Switched')}: <b>${switched}</b>
                &nbsp; ${__('Skipped')}: <b>${skipped}</b> &nbsp; ${__('Failed')}: <b>${failed}</b></div>
            <div class="progress" style="margin-top:8px">
                <div class="progress-bar" style="width:${pct}%">${pct}%</div>
            </div>
            <div style="margin-top:8px;font-size:12px;color:#888">
                ${__('You can close this. Work continues in the background. Failures go to Error Log.')}
            </div>
        `);
        if (state.finished) {
            frappe.show_alert({
                message: __('Done — switched {0}, skipped {1}, failed {2}.', [switched, skipped, failed]),
                indicator: failed ? 'orange' : 'green',
            }, 7);
            if (listview) listview.refresh();
        }
    }
    render({ total: total0, done: 0, switched: 0, skipped: 0, failed: 0 });

    frappe.realtime.on('bns_diff_gstin_bulk_progress', function(msg) {
        if (!msg || msg.token !== token) return;
        render(msg);
    });

    const poll = setInterval(function() {
        if (!d.$wrapper.is(':visible')) { clearInterval(poll); return; }
        frappe.call({
            method: 'business_needed_solutions.bns_branch_accounting.utils.bulk_switch_diff_gstin_progress',
            args: { token: token },
            callback: function(r) {
                if (r && r.message && r.message.total !== undefined) {
                    render(r.message);
                    if (r.message.finished) clearInterval(poll);
                }
            },
        });
    }, 10000);
}
