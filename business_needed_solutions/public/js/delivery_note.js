frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        // BNS asset-transfer picker: scope the item-row transferred-asset field to
        // units eligible to dispatch (right item + company, transferable status,
        // not already in transit).
        frm.set_query('bns_transferred_asset', 'items', function(doc, cdt, cdn) {
            const row = locals[cdt][cdn];
            return {
                query: 'business_needed_solutions.bns_branch_accounting.utils.bns_transferable_asset_query',
                filters: { item_code: row.item_code, company: doc.company }
            };
        });

        // Show button to convert to BNS Internal if customer is BNS internal but DN is not marked
        // OR if DN is marked but status is not "BNS Internally Transferred"
        // Only for same GSTIN transfers
        if (frm.doc.docstatus == 1) {
            frappe.db.get_value("Customer", frm.doc.customer, "is_bns_internal_customer", (r) => {
                if (r && r.is_bns_internal_customer) {
                    // Check if DN needs conversion: either flag not set OR flag set but status not updated
                    const needs_conversion = !frm.doc.is_bns_internal_customer || 
                                           (frm.doc.is_bns_internal_customer && frm.doc.status !== "BNS Internally Transferred");
                    
                    if (needs_conversion) {
                        // Check GSTIN match (same GSTIN only)
                        const billing_gstin = frm.doc.billing_address_gstin;
                        const company_gstin = frm.doc.company_gstin;
                        
                        if (billing_gstin && company_gstin && billing_gstin === company_gstin) {
                        frm.add_custom_button(__('Convert to BNS Internal'), function() {
                            // Check if PR exists with supplier_delivery_note matching DN name
                            frappe.call({
                                method: 'business_needed_solutions.bns_branch_accounting.utils.get_purchase_receipt_by_supplier_delivery_note',
                                args: {
                                    delivery_note: frm.doc.name
                                },
                                callback: function(pr_result) {
                                    let pr_details = null;
                                    let default_pr = null;
                                    
                                    if (pr_result.message && pr_result.message.found) {
                                        pr_details = pr_result.message;
                                        default_pr = pr_details.name;
                                    }
                                    
                                    const fields = [
                                        {
                                            label: __('Purchase Receipt'),
                                            fieldname: 'purchase_receipt',
                                            fieldtype: 'Link',
                                            options: 'Purchase Receipt',
                                            reqd: 0,
                                            default: default_pr,
                                            description: __('Optional: Link existing Purchase Receipt')
                                        }
                                    ];
                                    
                                    // Add details section if PR found
                                    if (pr_details) {
                                        fields.push({
                                            fieldtype: 'Section Break',
                                            label: __('Purchase Receipt Details')
                                        });
                                        fields.push({
                                            fieldtype: 'HTML',
                                            options: `
                                                <div style="padding: 10px; background: #f0f0f0; border-radius: 4px;">
                                                    <strong>${__('Found Purchase Receipt')}:</strong> ${pr_details.name}<br>
                                                    <strong>${__('Supplier')}:</strong> ${pr_details.supplier || '-'}<br>
                                                    <strong>${__('Posting Date')}:</strong> ${pr_details.posting_date || '-'}<br>
                                                    <strong>${__('Grand Total')}:</strong> ${frappe.format(pr_details.grand_total || 0, {fieldtype: 'Currency'})}<br>
                                                    <strong>${__('Status')}:</strong> ${pr_details.status || '-'}
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
                                                method: 'business_needed_solutions.bns_branch_accounting.utils.convert_delivery_note_to_bns_internal',
                                                args: {
                                                    delivery_note: frm.doc.name,
                                                    purchase_receipt: values.purchase_receipt || null
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
        
        // Only show the button if delivery note is submitted, doesn't have BNS inter-company reference,
        // and the user has permissions to create Purchase Receipt
        if (
            frm.doc.docstatus == 1 &&
            !frm.doc.bns_inter_company_reference &&
            frappe.model.can_create("Purchase Receipt")
        ) {
            // Check if this is a BNS internal customer
            let is_bns_internal = frm.doc.is_bns_internal_customer;
            if (is_bns_internal) {
                frm.add_custom_button(
                    __("BNS Internal Purchase Receipt"),
                    function() {
                        frappe.model.open_mapped_doc({
                            method: "business_needed_solutions.bns_branch_accounting.utils.make_bns_internal_purchase_receipt",
                            frm: frm,
                        });
                    },
                    __("Create")
                );
                frm.page.set_inner_btn_group_as_primary(__("Create"));
            }
        }
        
        // Link/Unlink with Purchase Receipt buttons
        // Always show for submitted documents, regardless of BNS internal status
        if (frm.doc.docstatus == 1) {
            if (!frm.doc.bns_inter_company_reference) {
                // Show Link button if not linked (regardless of supplier_delivery_note)
                frm.add_custom_button(__('Link Purchase Receipt'), function() {
                    const fields = [
                        {
                            label: __('Purchase Receipt'),
                            fieldname: 'purchase_receipt',
                            fieldtype: 'Link',
                            options: 'Purchase Receipt',
                            reqd: 1,
                            get_filters: function() {
                                const filters = {
                                    'docstatus': 1
                                };
                                // Filter by company match
                                if (frm.doc.company) {
                                    filters['company'] = frm.doc.company;
                                }
                                // Filter by date: PR posting_date should be >= DN posting_date
                                if (frm.doc.posting_date) {
                                    filters['posting_date'] = ['>=', frm.doc.posting_date];
                                }
                                // If supplier_delivery_note exists, also filter by it (but don't require it)
                                if (frm.doc.supplier_delivery_note) {
                                    filters['name'] = frm.doc.supplier_delivery_note;
                                }
                                return filters;
                            },
                            description: __('Select Purchase Receipt to link')
                        }
                    ];
                    
                    const d = new frappe.ui.Dialog({
                        title: __('Link Purchase Receipt'),
                        fields: fields,
                        primary_action_label: __('Link'),
                        primary_action(values) {
                            if (!values.purchase_receipt) {
                                frappe.msgprint({
                                    title: __('Validation Error'),
                                    message: __('Purchase Receipt is required'),
                                    indicator: 'red'
                                });
                                return;
                            }
                            
                            frappe.call({
                                method: 'business_needed_solutions.bns_branch_accounting.utils.link_dn_pr',
                                args: {
                                    delivery_note: frm.doc.name,
                                    purchase_receipt: values.purchase_receipt
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
    }
});


// Diff-GSTIN DN -> PR opt-in: draft-only button that stamps the per-document
// flag and submits the Delivery Note through the same-GSTIN internal transfer
// pipeline. Two-gate visibility: org-level setting must be ON, and the DN
// itself must be a draft, internal-customer, diff-GSTIN delivery challan.
frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        if (frm.doc.docstatus !== 0) {
            return;
        }
        if (!frm.doc.customer) {
            return;
        }
        const billing_gstin = (frm.doc.billing_address_gstin || '').trim();
        const company_gstin = (frm.doc.company_gstin || '').trim();
        if (!billing_gstin || !company_gstin || billing_gstin === company_gstin) {
            return;
        }
        // Skip when DN already opted in — re-stamping is a no-op.
        if (frm.doc.bns_allow_diff_gstin_dn_pr) {
            return;
        }

        frappe.db.get_value('Customer', frm.doc.customer, 'is_bns_internal_customer')
            .then((cust_res) => {
                if (!cust_res || !cust_res.message || !cust_res.message.is_bns_internal_customer) {
                    return;
                }
                frappe.db.get_single_value('BNS Branch Accounting Settings', 'allow_different_gstin_dn_to_pr')
                    .then((global_on) => {
                        if (!global_on) {
                            return;
                        }
                        frm.add_custom_button(__('Submit as Diff GSTIN Internal Transfer'), function() {
                            frappe.warn(
                                __('Submit as Diff GSTIN Internal Transfer?'),
                                __(
                                    'This will flag the Delivery Note for direct DN → PR conversion ' +
                                    'even though Company GSTIN ({0}) and Billing GSTIN ({1}) differ, ' +
                                    'then submit it. The DN will route through the same-GSTIN GL ' +
                                    'rewrite pattern (Internal Branch Debtor / Sales Transfer + Stock ' +
                                    'in Transit / Stock). This is for inter-state stock transfers on ' +
                                    'a delivery challan basis only (e.g. own-use, job work). The opt-in ' +
                                    'flag and your user/timestamp are recorded permanently on the DN.',
                                    [company_gstin, billing_gstin]
                                ),
                                () => {
                                    frappe.call({
                                        method: 'business_needed_solutions.bns_branch_accounting.utils.submit_diff_gstin_dn_for_internal_transfer',
                                        args: { delivery_note: frm.doc.name },
                                        freeze: true,
                                        freeze_message: __('Submitting as Diff GSTIN Internal Transfer...'),
                                        callback: function(r) {
                                            if (!r.exc && r.message && r.message.success) {
                                                frappe.show_alert({
                                                    message: r.message.message || __('Submitted'),
                                                    indicator: 'green',
                                                });
                                                frm.reload_doc();
                                            }
                                        },
                                    });
                                },
                                __('Submit'),
                                true,
                            );
                        }, __('Actions'));
                    });
            });
    },
});


// Diff-GSTIN DN -> PR opt-in: SUBMITTED-DN counterpart of the draft button above.
// Switches an already-submitted diff-GSTIN, internal-customer Delivery Note to
// "BNS Internally Transferred" (stamping the per-doc flag + rewriting DN GL via
// the same on_submit path) without re-submitting. Same two-gate visibility.
frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        if (frm.doc.docstatus !== 1) {
            return;
        }
        if (!frm.doc.customer) {
            return;
        }
        // Already switched -> nothing to do.
        if (frm.doc.status === 'BNS Internally Transferred') {
            return;
        }
        const billing_gstin = (frm.doc.billing_address_gstin || '').trim();
        const company_gstin = (frm.doc.company_gstin || '').trim();
        if (!billing_gstin || !company_gstin || billing_gstin === company_gstin) {
            return;
        }

        frappe.db.get_value('Customer', frm.doc.customer, 'is_bns_internal_customer')
            .then((cust_res) => {
                if (!cust_res || !cust_res.message || !cust_res.message.is_bns_internal_customer) {
                    return;
                }
                frappe.db.get_single_value('BNS Branch Accounting Settings', 'allow_different_gstin_dn_to_pr')
                    .then((global_on) => {
                        if (!global_on) {
                            return;
                        }
                        frm.add_custom_button(__('Switch to Diff GSTIN Internal Transfer'), function() {
                            frappe.warn(
                                __('Switch to Diff GSTIN Internal Transfer?'),
                                __(
                                    'This submitted Delivery Note will be switched to ' +
                                    '"BNS Internally Transferred" even though Company GSTIN ({0}) and ' +
                                    'Billing GSTIN ({1}) differ, and its GL will be rewritten to the ' +
                                    'same-GSTIN internal pattern (Internal Branch Debtor / Sales Transfer ' +
                                    '+ Stock in Transit / Stock) — provided the posting date is past the ' +
                                    'Accounting Rewrite cutoff. This is for inter-state stock transfers on ' +
                                    'a delivery challan basis only (e.g. own-use, job work). The opt-in ' +
                                    'flag and your user/timestamp are recorded permanently on the DN.',
                                    [company_gstin, billing_gstin]
                                ),
                                () => {
                                    frappe.call({
                                        method: 'business_needed_solutions.bns_branch_accounting.utils.apply_diff_gstin_to_submitted_dn',
                                        args: { delivery_note: frm.doc.name },
                                        freeze: true,
                                        freeze_message: __('Switching to Diff GSTIN Internal Transfer...'),
                                        callback: function(r) {
                                            if (!r.exc && r.message && r.message.success) {
                                                frappe.show_alert({
                                                    message: r.message.message || __('Switched'),
                                                    indicator: r.message.gl_rewritten === false ? 'orange' : 'green',
                                                });
                                                frm.reload_doc();
                                            }
                                        },
                                    });
                                },
                                __('Switch'),
                                true,
                            );
                        }, __('Actions'));
                    });
            });
    },
});
