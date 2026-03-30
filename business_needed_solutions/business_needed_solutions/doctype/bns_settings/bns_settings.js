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
