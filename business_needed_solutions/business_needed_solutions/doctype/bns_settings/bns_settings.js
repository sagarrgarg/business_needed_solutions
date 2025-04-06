// Copyright (c) 2025, Sagar Ratan Garg and contributors
// For license information, please see license.txt

// frappe.ui.form.on("BNS Settings", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('BNS Settings', {
    refresh: function(frm) {
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
    }
});