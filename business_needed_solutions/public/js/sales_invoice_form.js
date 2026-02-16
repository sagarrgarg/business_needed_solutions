frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        // Show button to convert to BNS Internal if customer is BNS internal but SI is not marked
        // OR if SI is marked but status is not "BNS Internally Transferred"
        if (frm.doc.docstatus == 1) {
            frappe.db.get_value("Customer", frm.doc.customer, "is_bns_internal_customer", (r) => {
                if (r && r.is_bns_internal_customer) {
                    // Check if SI needs conversion: either flag not set OR flag set but status not updated
                    const needs_conversion = !frm.doc.is_bns_internal_customer || 
                                           (frm.doc.is_bns_internal_customer && frm.doc.status !== "BNS Internally Transferred");
                    
                    if (needs_conversion) {
                    frm.add_custom_button(__('Convert to BNS Internal'), function() {
                        // Check if PI exists with supplier_invoice_number matching SI name
                        frappe.call({
                            method: 'business_needed_solutions.bns_branch_accounting.utils.get_purchase_invoice_by_supplier_invoice',
                            args: {
                                sales_invoice: frm.doc.name
                            },
                            callback: function(pi_result) {
                                let pi_details = null;
                                let default_pi = null;
                                
                                if (pi_result.message && pi_result.message.found) {
                                    pi_details = pi_result.message;
                                    default_pi = pi_details.name;
                                }
                                
                                const fields = [
                                    {
                                        label: __('Purchase Invoice'),
                                        fieldname: 'purchase_invoice',
                                        fieldtype: 'Link',
                                        options: 'Purchase Invoice',
                                        reqd: 0,
                                        default: default_pi,
                                        description: __('Optional: Link existing Purchase Invoice')
                                    }
                                ];
                                
                                // Add details section if PI found
                                if (pi_details) {
                                    fields.push({
                                        fieldtype: 'Section Break',
                                        label: __('Purchase Invoice Details')
                                    });
                                    fields.push({
                                        fieldtype: 'HTML',
                                        options: `
                                            <div style="padding: 10px; background: #f0f0f0; border-radius: 4px;">
                                                <strong>${__('Found Purchase Invoice')}:</strong> ${pi_details.name}<br>
                                                <strong>${__('Supplier')}:</strong> ${pi_details.supplier || '-'}<br>
                                                <strong>${__('Posting Date')}:</strong> ${pi_details.posting_date || '-'}<br>
                                                <strong>${__('Grand Total')}:</strong> ${frappe.format(pi_details.grand_total || 0, {fieldtype: 'Currency'})}<br>
                                                <strong>${__('Status')}:</strong> ${pi_details.status || '-'}
                                            </div>
                                        `
                                    });
                                }
                                
                                const d = new frappe.ui.Dialog({
                                    title: __('Convert to BNS Internally Transferred'),
                                    fields: fields,
                                    primary_action_label: __('Convert'),
                                    primary_action(values) {
                                        if (values.purchase_invoice) {
                                            // Validate items match before converting
                                            frappe.call({
                                                method: 'business_needed_solutions.bns_branch_accounting.utils.validate_si_pi_items_match',
                                                args: {
                                                    sales_invoice: frm.doc.name,
                                                    purchase_invoice: values.purchase_invoice
                                                },
                                                callback: function(validation_result) {
                                                    if (validation_result.message && !validation_result.message.match) {
                                                        frappe.msgprint({
                                                            title: __('Validation Failed'),
                                                            message: validation_result.message.message || __('Items and quantities do not match'),
                                                            indicator: 'red'
                                                        });
                                                        return;
                                                    }
                                                    
                                                    // Proceed with conversion
                                                    frappe.call({
                                                        method: 'business_needed_solutions.bns_branch_accounting.utils.convert_sales_invoice_to_bns_internal',
                                                        args: {
                                                            sales_invoice: frm.doc.name,
                                                            purchase_invoice: values.purchase_invoice
                                                        },
                                                        freeze: true,
                                                        freeze_message: __('Converting...'),
                                                        callback: function(r) {
                                                            if (!r.exc) {
                                                                frappe.show_alert({
                                                                    message: r.message.message || __('Converted successfully'),
                                                                    indicator: 'green'
                                                                });
                                                                frm.reload_doc();
                                                                d.hide();
                                                            }
                                                        }
                                                    });
                                                }
                                            });
                                        } else {
                                            // No PI provided, just convert SI
                                            frappe.call({
                                                method: 'business_needed_solutions.bns_branch_accounting.utils.convert_sales_invoice_to_bns_internal',
                                                args: {
                                                    sales_invoice: frm.doc.name,
                                                    purchase_invoice: null
                                                },
                                                freeze: true,
                                                freeze_message: __('Converting...'),
                                                callback: function(r) {
                                                    if (!r.exc) {
                                                        frappe.show_alert({
                                                            message: r.message.message || __('Converted successfully'),
                                                            indicator: 'green'
                                                        });
                                                        frm.reload_doc();
                                                        d.hide();
                                                    }
                                                }
                                            });
                                        }
                                    }
                                });
                                d.show();
                            }
                        });
                    }, __('Actions'));
                    }
                }
            });
        }
        
        // Link/Unlink with Purchase Invoice buttons
        if (frm.doc.docstatus == 1) {
            if (frm.doc.bns_inter_company_reference) {
                // Show Unlink button if already linked
                frm.add_custom_button(__('Unlink Purchase Invoice'), function() {
                    frappe.confirm(
                        __('Are you sure you want to unlink this Sales Invoice from Purchase Invoice {0}?', frm.doc.bns_inter_company_reference),
                        function() {
                            frappe.call({
                                method: 'business_needed_solutions.bns_branch_accounting.utils.unlink_si_pi',
                                args: {
                                    sales_invoice: frm.doc.name
                                },
                                freeze: true,
                                freeze_message: __('Unlinking...'),
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: r.message.message || __('Unlinked successfully'),
                                            indicator: 'green'
                                        });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }, __('Actions'));
            } else {
                // Check if there's a PI with bill_no matching SI name
                frappe.call({
                    method: 'business_needed_solutions.bns_branch_accounting.utils.get_purchase_invoice_by_supplier_invoice',
                    args: {
                        sales_invoice: frm.doc.name
                    },
                    callback: function(pi_result) {
                        // Only show link button if PI found with matching bill_no
                        if (pi_result.message && pi_result.message.found) {
                            frm.add_custom_button(__('Link Purchase Invoice'), function() {
                                const fields = [
                                    {
                                        label: __('Purchase Invoice'),
                                        fieldname: 'purchase_invoice',
                                        fieldtype: 'Link',
                                        options: 'Purchase Invoice',
                                        reqd: 1,
                                        default: pi_result.message.name,
                                        get_filters: function() {
                                            const filters = {
                                                'docstatus': 1
                                            };
                                            // Filter by company match
                                            if (frm.doc.company) {
                                                filters['company'] = frm.doc.company;
                                            }
                                            // Filter by date: PI posting_date should be >= SI posting_date
                                            if (frm.doc.posting_date) {
                                                filters['posting_date'] = ['>=', frm.doc.posting_date];
                                            }
                                            // Filter by bill_no matching SI name
                                            if (frm.doc.name) {
                                                filters['bill_no'] = frm.doc.name;
                                            }
                                            return filters;
                                        },
                                        description: __('Purchase Invoice with matching supplier invoice number')
                                    }
                                ];
                                
                                const d = new frappe.ui.Dialog({
                                    title: __('Link Purchase Invoice'),
                                    fields: fields,
                                    primary_action_label: __('Link'),
                                    primary_action(values) {
                                        if (!values.purchase_invoice) {
                                            frappe.msgprint({
                                                title: __('Validation Error'),
                                                message: __('Purchase Invoice is required'),
                                                indicator: 'red'
                                            });
                                            return;
                                        }
                                        
                                        frappe.call({
                                            method: 'business_needed_solutions.bns_branch_accounting.utils.link_si_pi',
                                            args: {
                                                sales_invoice: frm.doc.name,
                                                purchase_invoice: values.purchase_invoice
                                            },
                                            freeze: true,
                                            freeze_message: __('Linking...'),
                                            callback: function(r) {
                                                if (!r.exc) {
                                                    frappe.show_alert({
                                                        message: r.message.message || __('Linked successfully'),
                                                        indicator: 'green'
                                                    });
                                                    frm.reload_doc();
                                                    d.hide();
                                                }
                                            }
                                        });
                                    }
                                });
                                d.show();
                            }, __('Actions'));
                        }
                    }
                });
            }
        }
        
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
                            default: frm.doc.transporter,
                            reqd: 0,
                            get_query: () => {
                                return {
                                    filters: {
                                        is_transporter: 1
                                    }
                                };
                            }
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
                                transporter: values.transporter
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
                        method: "business_needed_solutions.bns_branch_accounting.utils.make_bns_internal_purchase_invoice",
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
                                method: "business_needed_solutions.bns_branch_accounting.utils.make_bns_internal_purchase_receipt_from_si",
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
                                            method: "business_needed_solutions.bns_branch_accounting.utils.make_bns_internal_purchase_receipt_from_si",
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