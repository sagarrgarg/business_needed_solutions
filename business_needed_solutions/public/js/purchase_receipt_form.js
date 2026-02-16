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
                        if (customer_result && customer_result.is_bns_internal_customer) {
                            // Check if PR needs conversion: either flag not set OR flag set but status not updated
                            const needs_conversion = !frm.doc.is_bns_internal_supplier || 
                                                   (frm.doc.is_bns_internal_supplier && frm.doc.status !== "BNS Internally Transferred");
                            
                            if (needs_conversion) {
                                // Check GSTIN match (same GSTIN only)
                                const billing_gstin = dn_result.billing_address_gstin;
                                const company_gstin = dn_result.company_gstin;
                                
                                if (billing_gstin && company_gstin && billing_gstin === company_gstin) {
                                frm.add_custom_button(__('Convert to BNS Internal'), function() {
                                    // Get DN details
                                    frappe.call({
                                        method: 'business_needed_solutions.bns_branch_accounting.utils.get_delivery_note_by_supplier_delivery_note',
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
                                                        method: 'business_needed_solutions.bns_branch_accounting.utils.convert_purchase_receipt_to_bns_internal',
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
                        }
                    });
                }
            });
        }
        
        // Link/Unlink with Delivery Note or Sales Invoice buttons
        if (frm.doc.docstatus == 1) {
            if (frm.doc.bns_inter_company_reference) {
                const ref = frm.doc.bns_inter_company_reference;
                frappe.db.exists('Sales Invoice', ref).then(function(is_si) {
                    const label = is_si ? __('Unlink Sales Invoice') : __('Unlink Delivery Note');
                    const confirm_msg = is_si
                        ? __('Are you sure you want to unlink this Purchase Receipt from Sales Invoice {0}?', ref)
                        : __('Are you sure you want to unlink this Purchase Receipt from Delivery Note {0}?', ref);
                    const method = is_si
                        ? 'business_needed_solutions.bns_branch_accounting.utils.unlink_si_pr'
                        : 'business_needed_solutions.bns_branch_accounting.utils.unlink_dn_pr';
                    const args = is_si
                        ? { sales_invoice: ref, purchase_receipt: frm.doc.name }
                        : { purchase_receipt: frm.doc.name };
                    frm.add_custom_button(label, function() {
                        frappe.confirm(confirm_msg, function() {
                            frappe.call({
                                method: method,
                                args: args,
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
                        });
                    }, __('Actions'));
                });
            } else {
                // Show Link buttons if not linked
                // Link Delivery Note: for same GSTIN (DN->PR flow)
                frm.add_custom_button(__('Link Delivery Note'), function() {
                    const fields = [
                        {
                            label: __('Delivery Note'),
                            fieldname: 'delivery_note',
                            fieldtype: 'Link',
                            options: 'Delivery Note',
                            reqd: 1,
                            default: frm.doc.supplier_delivery_note || null,
                            get_filters: function() {
                                const filters = {
                                    'docstatus': 1
                                };
                                // Filter by company match
                                if (frm.doc.company) {
                                    filters['company'] = frm.doc.company;
                                }
                                // Filter by date: DN posting_date should be <= PR posting_date
                                if (frm.doc.posting_date) {
                                    filters['posting_date'] = ['<=', frm.doc.posting_date];
                                }
                                // If supplier_delivery_note exists, also filter by it (but don't require it)
                                if (frm.doc.supplier_delivery_note) {
                                    filters['name'] = frm.doc.supplier_delivery_note;
                                }
                                return filters;
                            },
                            description: frm.doc.supplier_delivery_note ? 
                                __('Delivery Note linked via supplier_delivery_note') : 
                                __('Select Delivery Note to link')
                        }
                    ];
                    
                    const d = new frappe.ui.Dialog({
                        title: __('Link Delivery Note'),
                        fields: fields,
                        primary_action_label: __('Link'),
                        primary_action(values) {
                            if (!values.delivery_note) {
                                frappe.msgprint({
                                    title: __('Validation Error'),
                                    message: __('Delivery Note is required'),
                                    indicator: 'red'
                                });
                                return;
                            }
                            
                            frappe.call({
                                method: 'business_needed_solutions.bns_branch_accounting.utils.link_dn_pr',
                                args: {
                                    delivery_note: values.delivery_note,
                                    purchase_receipt: frm.doc.name
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

                // Link Sales Invoice: for different GSTIN (SI->PR flow)
                const companyGstin = frm.doc.company_gstin || '';
                const supplierGstin = frm.doc.supplier_gstin || '';
                const hasDifferentGstin = companyGstin && supplierGstin && companyGstin !== supplierGstin;
                if (hasDifferentGstin) {
                    frm.add_custom_button(__('Link Sales Invoice'), function() {
                        const fields = [
                            {
                                label: __('Sales Invoice'),
                                fieldname: 'sales_invoice',
                                fieldtype: 'Link',
                                options: 'Sales Invoice',
                                reqd: 1,
                                default: frm.doc.supplier_delivery_note && frappe.db.exists('Sales Invoice', frm.doc.supplier_delivery_note) ? frm.doc.supplier_delivery_note : null,
                                get_filters: function() {
                                    const filters = { docstatus: 1 };
                                    if (frm.doc.company) {
                                        filters['company'] = ['!=', frm.doc.company];
                                    }
                                    return filters;
                                },
                                description: __('Select Sales Invoice to link (different GSTIN flow)')
                            }
                        ];
                        const d2 = new frappe.ui.Dialog({
                            title: __('Link Sales Invoice'),
                            fields: fields,
                            primary_action_label: __('Link'),
                            primary_action(values) {
                                if (!values.sales_invoice) {
                                    frappe.msgprint({ title: __('Validation Error'), message: __('Sales Invoice is required'), indicator: 'red' });
                                    return;
                                }
                                frappe.call({
                                    method: 'business_needed_solutions.bns_branch_accounting.utils.link_si_pr',
                                    args: { sales_invoice: values.sales_invoice, purchase_receipt: frm.doc.name },
                                    freeze: true,
                                    freeze_message: __('Linking...'),
                                    callback: function(r) {
                                        if (!r.exc) {
                                            frappe.show_alert({ message: r.message.message || __('Linked successfully'), indicator: 'green' });
                                            frm.reload_doc();
                                            d2.hide();
                                        }
                                    }
                                });
                            }
                        });
                        d2.show();
                    }, __('Actions'));
                }
            }
        }
    }
});


