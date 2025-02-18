frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        // Only show button if the e-Waybill status is 'Pending' or 'Not Applicable'
        if (["Pending", "Not Applicable"].includes(frm.doc.e_waybill_status)) {
            frm.add_custom_button(__('Update Vehicle/Transporter Info'), function() {
                // Open a dialog to take input from the user
                const d = new frappe.ui.Dialog({
                    title: __('Update Vehicle or Transporter Details'),
                    fields: [
                        {
                            label: 'Vehicle No',
                            fieldname: 'vehicle_no',
                            fieldtype: 'Data',
                            default: frm.doc.vehicle_no,  // Set default value from form
                            reqd: 0
                        },
                        {
                            label: 'Transporter',
                            fieldname: 'transporter',
                            fieldtype: 'Link',
                            options: 'Supplier',
                            default: frm.doc.transporter,  // Set default value from form
                            reqd: 0,
                            get_query: () => {
                                return {
                                    filters: {
                                        is_transporter: 1
                                    }
                                };
                            }
                        },
                        {
                            label: 'GST Transporter ID',
                            fieldname: 'gst_transporter_id',
                            fieldtype: 'Data',
                            default: frm.doc.gst_transporter_id,  // Set default value from form
                            depends_on: 'eval: doc.transporter',
                            reqd: 0
                        }
                    ],
                    primary_action_label: __('Update'),
                    primary_action(values) {
                        // Call the server-side method to update vehicle/transporter info
                        frappe.call({
                            method: 'custom_transport_change_allow.update_vehicle.update_vehicle_or_transporter',
                            args: {
                                doctype: frm.doctype,
                                docname: frm.doc.name,
                                vehicle_no: values.vehicle_no,
                                transporter: values.transporter,
                                gst_transporter_id: values.gst_transporter_id
                            },
                            callback: function(r) {
                                if (!r.exc) {
                                    frm.reload_doc();
                                    d.hide();
                                }
                            }
                        });
                    }
                });

                d.show();
            }, __('e-Waybill'));
        }
    }
});