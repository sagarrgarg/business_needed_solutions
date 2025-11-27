frappe.ui.form.on('Purchase Receipt', {
    refresh: function(frm) {
        // Show button to convert to BNS Internal if supplier_delivery_note exists and GSTIN matches
        // Only for same GSTIN transfers (from DN)
        if (frm.doc.docstatus == 1 && frm.doc.supplier_delivery_note) {
            // Check if supplier_delivery_note is a Delivery Note
            frappe.db.get_value("Delivery Note", frm.doc.supplier_delivery_note, ["customer", "billing_address_gstin", "company_gstin", "is_bns_internal_customer"], (dn_result) => {
                if (dn_result && dn_result.customer) {
                    // Check if DN customer is BNS internal
                    frappe.db.get_value("Customer", dn_result.customer, "is_bns_internal_customer", (customer_result) => {
                        if (customer_result && customer_result.is_bns_internal_customer && !frm.doc.is_bns_internal_customer) {
                            // Check GSTIN match (same GSTIN only)
                            const billing_gstin = dn_result.billing_address_gstin;
                            const company_gstin = dn_result.company_gstin;
                            
                            if (billing_gstin && company_gstin && billing_gstin === company_gstin) {
                                frm.add_custom_button(__('Convert to BNS Internal'), function() {
                                    // Get DN details
                                    frappe.call({
                                        method: 'business_needed_solutions.business_needed_solutions.utils.get_delivery_note_by_supplier_delivery_note',
                                        args: {
                                            purchase_receipt: frm.doc.name
                                        },
                                        callback: function(dn_result) {
                                            let dn_details = null;
                                            let default_dn = null;
                                            
                                            if (dn_result.message && dn_result.message.found) {
                                                dn_details = dn_result.message;
                                                default_dn = dn_details.name;
                                            }
                                            
                                            const fields = [
                                                {
                                                    label: __('Delivery Note'),
                                                    fieldname: 'delivery_note',
                                                    fieldtype: 'Link',
                                                    options: 'Delivery Note',
                                                    reqd: 0,
                                                    default: default_dn,
                                                    description: __('Optional: Link existing Delivery Note'),
                                                    read_only: 1
                                                }
                                            ];
                                            
                                            // Add details section if DN found
                                            if (dn_details) {
                                                fields.push({
                                                    fieldtype: 'Section Break',
                                                    label: __('Delivery Note Details')
                                                });
                                                fields.push({
                                                    fieldtype: 'HTML',
                                                    options: `
                                                        <div style="padding: 10px; background: #f0f0f0; border-radius: 4px;">
                                                            <strong>${__('Linked Delivery Note')}:</strong> ${dn_details.name}<br>
                                                            <strong>${__('Customer')}:</strong> ${dn_details.customer || '-'}<br>
                                                            <strong>${__('Posting Date')}:</strong> ${dn_details.posting_date || '-'}<br>
                                                            <strong>${__('Grand Total')}:</strong> ${frappe.format(dn_details.grand_total || 0, {fieldtype: 'Currency'})}<br>
                                                            <strong>${__('Status')}:</strong> ${dn_details.status || '-'}
                                                        </div>
                                                    `
                                                });
                                            }
                                            
                                            const d = new frappe.ui.Dialog({
                                                title: __('Convert to BNS Internally Transferred'),
                                                fields: fields,
                                                primary_action_label: __('Convert'),
                                                primary_action(values) {
                                                    frappe.call({
                                                        method: 'business_needed_solutions.business_needed_solutions.utils.convert_purchase_receipt_to_bns_internal',
                                                        args: {
                                                            purchase_receipt: frm.doc.name,
                                                            delivery_note: values.delivery_note || frm.doc.supplier_delivery_note
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
                                            d.show();
                                        }
                                    });
                                }, __('Actions'));
                            }
                        }
                    });
                }
            });
        }
    }
});


