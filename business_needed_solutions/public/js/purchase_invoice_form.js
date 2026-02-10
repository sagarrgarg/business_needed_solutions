(function() {
    var _fetch_link_title = frappe.utils.fetch_link_title;
    frappe.utils.fetch_link_title = function(doctype, name) {
        if (doctype === 'Sales Invoice' && name && cur_frm && cur_frm.doctype === 'Purchase Invoice') {
            return _fetch_link_title.apply(this, arguments).catch(function() {
                frappe.utils.add_link_title(doctype, name, name);
                return name;
            });
        }
        if (doctype === 'Sales Invoice Item' && name && cur_frm && cur_frm.doctype === 'Purchase Invoice') {
            return _fetch_link_title.apply(this, arguments).catch(function() {
                frappe.utils.add_link_title(doctype, name, name);
                return name;
            });
        }
        return _fetch_link_title.apply(this, arguments);
    };
})();

frappe.ui.form.on('Purchase Invoice', {
    onload: function(frm) {
        // Prevent "Sales Invoice X not found" when opening a PI whose linked SI was deleted.
        // Pre-populate link title cache SYNCHRONOUSLY so Link controls never request missing docs.
        if (!frappe._link_titles) frappe._link_titles = {};

        var siRefs = [
            frm.doc.bns_inter_company_reference,
            frm.doc.inter_company_invoice_reference
        ].filter(Boolean);
        siRefs.forEach(function(siName) {
            frappe._link_titles['Sales Invoice::' + siName] = siName;
        });

        // Pre-populate Sales Invoice Item link titles for grid (avoids 404 for deleted SI items)
        if (frm.doc.items && Array.isArray(frm.doc.items)) {
            frm.doc.items.forEach(function(row) {
                var siItem = row.sales_invoice_item;
                if (siItem) {
                    frappe._link_titles['Sales Invoice Item::' + siItem] = siItem;
                }
            });
        }
    },
    refresh: function(frm) {
        // Show button to convert to BNS Internal if supplier is BNS internal but PI is not marked
        // OR if PI is marked but status is not "BNS Internally Transferred"
        if (frm.doc.docstatus == 1) {
            frappe.db.get_value("Supplier", frm.doc.supplier, "is_bns_internal_supplier", (r) => {
                if (r && r.is_bns_internal_supplier) {
                    // Check if PI needs conversion: either flag not set OR flag set but status not updated
                    const needs_conversion = !frm.doc.is_bns_internal_supplier || 
                                           (frm.doc.is_bns_internal_supplier && frm.doc.status !== "BNS Internally Transferred");
                    
                    if (needs_conversion) {
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
                }
            });
        }
        
        // Link/Unlink with Sales Invoice buttons
        if (frm.doc.docstatus == 1) {
            if (frm.doc.bns_inter_company_reference) {
                // Show Unlink button if already linked
                frm.add_custom_button(__('Unlink Sales Invoice'), function() {
                    frappe.confirm(
                        __('Are you sure you want to unlink this Purchase Invoice from Sales Invoice {0}?', [frm.doc.bns_inter_company_reference]),
                        function() {
                            frappe.call({
                                method: 'business_needed_solutions.business_needed_solutions.utils.unlink_si_pi',
                                args: {
                                    purchase_invoice: frm.doc.name
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
            } else if (frm.doc.bill_no) {
                // Only attempt the SI lookup for BNS internal suppliers.
                // For external suppliers bill_no is the vendor's own invoice
                // number (e.g. "KPU1/25-26/4588") which is NOT a Sales
                // Invoice in the system.  Calling frappe.client.get with
                // that name causes a harmless but annoying "not found" error
                // every time the PI is opened.
                frappe.db.get_value("Supplier", frm.doc.supplier, "is_bns_internal_supplier", (supplier_r) => {
                    if (!supplier_r || !supplier_r.is_bns_internal_supplier) {
                        // External supplier — nothing to link
                        return;
                    }

                    // BNS internal supplier — check if bill_no matches a submitted SI
                    frappe.db.get_value("Sales Invoice", frm.doc.bill_no, ["name", "docstatus"], (si_result) => {
                        if (!si_result || !si_result.name || si_result.docstatus != 1) {
                            return;
                        }

                        frm.add_custom_button(__('Link Sales Invoice'), function() {
                            const fields = [
                                {
                                    label: __('Sales Invoice'),
                                    fieldname: 'sales_invoice',
                                    fieldtype: 'Link',
                                    options: 'Sales Invoice',
                                    reqd: 1,
                                    default: frm.doc.bill_no,
                                    get_filters: function() {
                                        const filters = {
                                            'docstatus': 1
                                        };
                                        // Filter by company match
                                        if (frm.doc.company) {
                                            filters['company'] = frm.doc.company;
                                        }
                                        // Filter by date: SI posting_date should be <= PI posting_date
                                        if (frm.doc.posting_date) {
                                            filters['posting_date'] = ['<=', frm.doc.posting_date];
                                        }
                                        // Filter by name matching bill_no
                                        if (frm.doc.bill_no) {
                                            filters['name'] = frm.doc.bill_no;
                                        }
                                        return filters;
                                    },
                                    description: __('Sales Invoice matching supplier invoice number')
                                }
                            ];
                            
                            const d = new frappe.ui.Dialog({
                                title: __('Link Sales Invoice'),
                                fields: fields,
                                primary_action_label: __('Link'),
                                primary_action(values) {
                                    if (!values.sales_invoice) {
                                        frappe.msgprint({
                                            title: __('Validation Error'),
                                            message: __('Sales Invoice is required'),
                                            indicator: 'red'
                                        });
                                        return;
                                    }
                                    
                                    frappe.call({
                                        method: 'business_needed_solutions.business_needed_solutions.utils.link_si_pi',
                                        args: {
                                            sales_invoice: values.sales_invoice,
                                            purchase_invoice: frm.doc.name
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
                    });
                });
            }
        }
    }
});

