function _show_backfill_result(result) {
    const status_lines = Object.entries(result.by_status || {})
        .map(([k, v]) => `<li><b>${frappe.utils.escape_html(k)}</b>: ${v}</li>`)
        .join('');
    const summary_header = result.dry_run
        ? __('<b>Dry run</b> — no Payment Entries were created or cancelled.')
        : __('<b>Live run</b> — changes were applied.');
    const rows_json = frappe.utils.escape_html(JSON.stringify(result.rows || [], null, 2));
    const html = `
        <p>${summary_header}</p>
        <p>${__('Total Purchase Invoices in scope')}: <b>${result.total || 0}</b></p>
        <ul>${status_lines || '<li>(none)</li>'}</ul>
        <details>
            <summary>${__('Detailed report')} (${(result.rows || []).length})</summary>
            <pre style="max-height: 400px; overflow: auto; font-size: 11px;">${rows_json}</pre>
        </details>
    `;
    frappe.msgprint({ title: __('Backfill Result'), message: html, wide: true });
}

// Module-level realtime listener: stays registered for the session, so a
// background backfill result lands in front of the user even if they've
// navigated away from BNS Settings. Idempotent — guarded by a flag.
if (!window._bns_auto_paid_backfill_listener) {
    window._bns_auto_paid_backfill_listener = true;
    frappe.realtime.on('bns_auto_paid_backfill_done', function(data) {
        _show_backfill_result(data);
    });
}

frappe.ui.form.on('BNS Settings', {
    refresh: function(frm) {
        // Apply List View Settings button
        frm.add_custom_button(__('Apply List View Settings'), function() {
            frm.call({
                doc: frm.doc,
                method: 'apply_settings',
                freeze: true,
                freeze_message: __('Applying Settings...'),
                callback: function(r) {
                    if (r.message) {
                        frappe.show_alert({
                            message: __('Settings Applied Successfully'),
                            indicator: 'green'
                        });
                    }
                }
            });
        }, __('Actions'));

        // GL/SLE Audit — open the audit report (cutoff set there)
        frm.add_custom_button(__('Run GL/SLE Audit'), function() {
            const route = ['query-report', 'GL SLE Audit'];
            const today = frappe.datetime.get_today();
            const default_cutoff = frappe.datetime.add_months(today, -3);
            frappe.route_options = {
                cutoff_date: default_cutoff,
                company: frappe.defaults.get_user_default('Company') || undefined,
            };
            frappe.set_route(route);
        }, __('Actions'));

        // Backfill auto-paid supplier PIs (cancel + recreate wrong-account PEs,
        // pay residuals against the supplier's configured MOP account)
        frm.add_custom_button(__('Backfill Auto-Paid Supplier PIs'), function() {
            const d = new frappe.ui.Dialog({
                title: __('Backfill Auto-Paid Supplier PIs'),
                fields: [
                    {
                        label: __('Supplier (optional)'),
                        fieldname: 'supplier',
                        fieldtype: 'Link',
                        options: 'Supplier',
                        get_query: function() {
                            return { filters: { bns_auto_paid_supplier: 1 } };
                        },
                        description: __('Leave blank to process every auto-paid supplier.'),
                    },
                    {
                        label: __('From Posting Date'),
                        fieldname: 'from_date',
                        fieldtype: 'Date',
                    },
                    {
                        label: __('To Posting Date'),
                        fieldname: 'to_date',
                        fieldtype: 'Date',
                    },
                    {
                        label: __('Dry Run (recommended first)'),
                        fieldname: 'dry_run',
                        fieldtype: 'Check',
                        default: 1,
                        description: __('When checked: plan without writing. Uncheck to actually cancel + recreate Payment Entries and pay residuals.'),
                    },
                ],
                primary_action_label: __('Run'),
                primary_action: function(values) {
                    frappe.call({
                        method: 'business_needed_solutions.business_needed_solutions.overrides.auto_paid_supplier.backfill_auto_paid_supplier',
                        args: values,
                        freeze: true,
                        freeze_message: __('Running backfill…'),
                        callback: function(r) {
                            if (!r.message) return;
                            d.hide();
                            if (r.message.enqueued) {
                                frappe.show_alert({
                                    message: __('Backfill enqueued for {0} Purchase Invoices. You will be notified when it completes.', [r.message.total || 0]),
                                    indicator: 'blue',
                                }, 10);
                            } else {
                                _show_backfill_result(r.message);
                            }
                        },
                    });
                },
            });
            d.show();
        }, __('Actions'));

        // Backdate: Clear existing address preferred flags
        frm.add_custom_button(__('Clear Existing Address Flags (Backdate)'), function() {
            frappe.confirm(
                __('This will set is_primary_address and is_shipping_address to 0 on all Address records. Use this when you have enabled "Suppress Preferred Billing & Shipping Address" and need to clear existing flags. Continue?'),
                function() {
                    frappe.call({
                        method: 'business_needed_solutions.business_needed_solutions.overrides.address_preferred_flags.clear_existing_address_flags',
                        freeze: true,
                        freeze_message: __('Clearing address flags...'),
                        callback: function(r) {
                            if (!r.exc && r.message) {
                                frappe.show_alert({
                                    message: __('Cleared flags on {0} address(es)', [r.message.updated || 0]),
                                    indicator: 'green'
                                });
                            }
                        }
                    });
                }
            );
        }, __('Actions'));
    }
});
