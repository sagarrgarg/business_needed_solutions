frappe.ui.form.on('Purchase Invoice', {
    refresh: function(frm) {
        // Show button to convert to BNS Internal if supplier is BNS internal but PI is not marked
        if (frm.doc.docstatus == 1) {
            frappe.db.get_value("Supplier", frm.doc.supplier, "is_bns_internal_supplier", (r) => {
                if (r && r.is_bns_internal_supplier && !frm.doc.is_bns_internal_supplier) {
                    frm.add_custom_button(__('Convert to BNS Internal'), function() {
                        // Check if SI exists with name matching PI's bill_no
                        frappe.call({
                            method: 'business_needed_solutions.business_needed_solutions.utils.get_sales_invoice_by_bill_no',
                            args: {
                                purchase_invoice: frm.doc.name
                            },
                            callback: function(si_result) {
                                let si_details = null;
                                let default_si = null;
                                
                                if (si_result.message && si_result.message.found) {
                                    si_details = si_result.message;
                                    default_si = si_details.name;
                                }
                                
                                const fields = [
                                    {
                                        label: __('Sales Invoice'),
                                        fieldname: 'sales_invoice',
                                        fieldtype: 'Link',
                                        options: 'Sales Invoice',
                                        reqd: 0,
                                        default: default_si,
                                        description: __('Optional: Link existing Sales Invoice')
                                    }
                                ];
                                
                                // Add details section if SI found
                                if (si_details) {
                                    fields.push({
                                        fieldtype: 'Section Break',
                                        label: __('Sales Invoice Details')
                                    });
                                    fields.push({
                                        fieldtype: 'HTML',
                                        options: `
                                            <div style="padding: 10px; background: #f0f0f0; border-radius: 4px;">
                                                <strong>${__('Found Sales Invoice')}:</strong> ${si_details.name}<br>
                                                <strong>${__('Customer')}:</strong> ${si_details.customer || '-'}<br>
                                                <strong>${__('Posting Date')}:</strong> ${si_details.posting_date || '-'}<br>
                                                <strong>${__('Grand Total')}:</strong> ${frappe.format(si_details.grand_total || 0, {fieldtype: 'Currency'})}<br>
                                                <strong>${__('Status')}:</strong> ${si_details.status || '-'}
                                            </div>
                                        `
                                    });
                                }
                                
                                const d = new frappe.ui.Dialog({
                                    title: __('Convert to BNS Internally Transferred'),
                                    fields: fields,
                                    primary_action_label: __('Convert'),
                                    primary_action(values) {
                                        if (values.sales_invoice) {
                                            // Validate items match before converting
                                            frappe.call({
                                                method: 'business_needed_solutions.business_needed_solutions.utils.validate_si_pi_items_match',
                                                args: {
                                                    sales_invoice: values.sales_invoice,
                                                    purchase_invoice: frm.doc.name
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
                                                        method: 'business_needed_solutions.business_needed_solutions.utils.convert_purchase_invoice_to_bns_internal',
                                                        args: {
                                                            purchase_invoice: frm.doc.name,
                                                            sales_invoice: values.sales_invoice
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
                                            // No SI provided, just convert PI
                                            frappe.call({
                                                method: 'business_needed_solutions.business_needed_solutions.utils.convert_purchase_invoice_to_bns_internal',
                                                args: {
                                                    purchase_invoice: frm.doc.name,
                                                    sales_invoice: null
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
            });
        }
    }
});

