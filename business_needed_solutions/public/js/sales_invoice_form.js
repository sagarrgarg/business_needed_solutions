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
                            method: 'business_needed_solutions.update_vehicle.update_vehicle_or_transporter',
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
        
        // BNS Internal Purchase Invoice/Receipt buttons
        // Show if: status is "BNS Internally Transferred" and docstatus == 1
        if (
            frm.doc.status === "BNS Internally Transferred" &&
            frm.doc.docstatus == 1
        ) {
            // Always show Purchase Invoice button if status is BNS Internally Transferred
            // (assume PI needs to be created when SI is generated)
            frm.add_custom_button(
                __("BNS Internal Purchase Invoice"),
                function() {
                    frappe.model.open_mapped_doc({
                        method: "business_needed_solutions.business_needed_solutions.utils.make_bns_internal_purchase_invoice",
                        frm: frm,
                    });
                },
                __("Create")
            );
            
            // Check if Purchase Receipt button should be shown
            // Show if: any item maintains stock (is_stock_item) OR if SI is made from Delivery Note
            if (frm.doc.items && frm.doc.items.length > 0) {
                // Check if SI is made from Delivery Note (items have delivery_note reference)
                let has_dn_reference = frm.doc.items.some(item => item.delivery_note);
                
                if (has_dn_reference) {
                    // Show PR button immediately if DN reference exists
                    frm.add_custom_button(
                        __("BNS Internal Purchase Receipt"),
                        function() {
                            frappe.model.open_mapped_doc({
                                method: "business_needed_solutions.business_needed_solutions.utils.make_bns_internal_purchase_receipt_from_si",
                                frm: frm,
                            });
                        },
                        __("Create")
                    );
                    frm.page.set_inner_btn_group_as_primary(__("Create"));
                } else {
                    // Check if any item maintains stock by fetching from Item doctype
                    let item_codes = frm.doc.items
                        .filter(item => item.item_code)
                        .map(item => item.item_code);
                    
                    if (item_codes.length > 0) {
                        frappe.db.get_list("Item", {
                            filters: {
                                name: ["in", item_codes],
                                is_stock_item: 1
                            },
                            fields: ["name"],
                            limit: 1
                        }).then(r => {
                            if (r && r.length > 0) {
                                frm.add_custom_button(
                                    __("BNS Internal Purchase Receipt"),
                                    function() {
                                        frappe.model.open_mapped_doc({
                                            method: "business_needed_solutions.business_needed_solutions.utils.make_bns_internal_purchase_receipt_from_si",
                                            frm: frm,
                                        });
                                    },
                                    __("Create")
                                );
                                frm.page.set_inner_btn_group_as_primary(__("Create"));
                            }
                        });
                    }
                }
            }
        }
    }
});