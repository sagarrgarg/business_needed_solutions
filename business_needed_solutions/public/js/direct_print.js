// File: apps/business_needed_solutions/business_needed_solutions/public/js/direct_print.js

// File: apps/business_needed_solutions/business_needed_solutions/public/js/direct_print.js

frappe.provide('business_needed_solutions');

business_needed_solutions.DirectPrint = class DirectPrint {
    constructor() {
        this.settings = {};
        this.supported_doctypes = [
            'Sales Invoice', 
            'Sales Order', 
            'Delivery Note', 
            'Quotation',
            'Purchase Order',
            'Purchase Receipt',
            'Purchase Invoice',
            'Supplier Quotation',
            'POS Invoice'
        ];
        this.print_formats = {};
        this.initialized = false;
        this.initialize();
    }

    async initialize() {
        await this.load_settings();
        this.setup_handlers();
    }

    async load_settings() {
        try {
            this.bns_configured_formats = {};
            const doc = await frappe.db.get_doc('BNS Settings');
            if (doc && doc.print_format) {
                // Create a mapping of doctype to print format
                doc.print_format.forEach(row => {
                    if (!this.print_formats[row.doctype_map]) {
                        this.print_formats[row.doctype_map] = [];
                    }
                    this.print_formats[row.doctype_map].push(row.print_format);
                    // Track which doctypes are configured in BNS Settings
                    if (!this.bns_configured_formats[row.doctype_map]) {
                        this.bns_configured_formats[row.doctype_map] = true;
                    }
                });
            }
            
            // Fallback for doctypes that might not be configured
            this.supported_doctypes.forEach(doctype => {
                if (!this.print_formats[doctype] || this.print_formats[doctype].length === 0) {
                    console.warn(`No print format configured for ${doctype}, using defaults`);
                    // Set default mapping for backward compatibility
                    switch(doctype) {
                        case 'Sales Invoice':
                            this.print_formats[doctype] = ['BNS SI - V1'];
                            break;
                        case 'Quotation':
                            this.print_formats[doctype] = ['BNS Q - V1'];
                            break;
                        case 'Sales Order':
                            this.print_formats[doctype] = ['BNS SO - V1'];
                            break;
                        case 'Delivery Note':
                            this.print_formats[doctype] = ['BNS DN - V1'];
                            break;
                        case 'Purchase Order':
                            this.print_formats[doctype] = ['BNS PO - V1'];
                            break;
                        case 'Purchase Receipt':
                            this.print_formats[doctype] = ['BNS PR - V1'];
                            break;
                        case 'Purchase Invoice':
                            this.print_formats[doctype] = ['BNS PI - V1'];
                            break;
                        case 'Supplier Quotation':
                            this.print_formats[doctype] = ['BNS SQ - V1'];
                            break;
                        case 'POS Invoice':
                            this.print_formats[doctype] = ['BNS POS - V1'];
                            break;
                        default:
                            this.print_formats[doctype] = [];
                    }
                }
            });
        } catch (error) {
            console.error('Error loading BNS Settings:', error);
            // Set default mappings for backward compatibility
            this.print_formats = {
                'Sales Invoice': ['BNS SI - V1'],
                'Quotation': ['BNS Q - V1'],
                'Sales Order': ['BNS SO - V1'],
                'Delivery Note': ['BNS DN - V1'],
                'Purchase Order': ['BNS PO - V1'],
                'Purchase Receipt': ['BNS PR - V1'],
                'Purchase Invoice': ['BNS PI - V1'],
                'Supplier Quotation': ['BNS SQ - V1'],
                'POS Invoice': ['BNS POS - V1']
            };
        }
    }

    setup_handlers() {
        this.supported_doctypes.forEach(doctype => {
            frappe.ui.form.on(doctype, {
                refresh: frm => this.setup_print_button(frm)
            });
        });
    }

    setup_print_button(frm) {
        // Remove dependency on invoice_copy field
        
        // Find the print button
        const $printButton = frm.page.wrapper.find('button[data-original-title="Print"]');
        if (!$printButton.length) return;
        
        // Remove existing click handlers
        $printButton.off('click');
        
        // Special handling for Sales Invoice which has invoice_copy
        if (frm.doctype === 'Sales Invoice' && frm.fields_dict.invoice_copy) {
            // Add dropdown functionality
            $printButton.addClass('dropdown-toggle');
            $printButton.attr('data-toggle', 'dropdown');
            
            // Create dropdown menu if it doesn't exist
            this.create_dropdown_menu(frm, $printButton);
        } else {
            // For other doctypes, simple click handler
            $printButton.on('click', () => {
                this.generate_pdf(frm);
            });
        }
        
        // Setup keyboard shortcut
        this.setup_keyboard_shortcut(frm);
    }

    create_dropdown_menu(frm, $printButton) {
        // Only for Sales Invoice with invoice_copy
        // Remove existing dropdown menu if any
        $printButton.next('.dropdown-menu').remove();
        
        // Create new dropdown menu
        const $dropdownMenu = $('<div class="dropdown-menu"></div>');
        
        // Get print options from the form
        const options = frm.fields_dict.invoice_copy.df.options.split('\n');
        
        // Add options to dropdown
        options.forEach(option => {
            if (option) {
                $dropdownMenu.append(
                    `<a class="dropdown-item" href="#" data-print-option="${option}">${option}</a>`
                );
            }
        });
        
        // Insert dropdown menu after print button
        $printButton.after($dropdownMenu);
        
        // Handle print option selection
        $dropdownMenu.on('click', '.dropdown-item', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const printOption = $(e.currentTarget).data('print-option');
            this.print_with_option(frm, printOption);
        });
    }

    setup_keyboard_shortcut(frm) {
        // Remove existing handler if any
        $(document).off('keydown.directPrint');
        
        // Add new handler - works for all doctypes
        $(document).on('keydown.directPrint', (e) => {
            if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'P')) {
                e.preventDefault();
                e.stopPropagation();
                
                if (frm.doctype === 'Sales Invoice' && frm.fields_dict.invoice_copy) {
                    const defaultOption = frm.fields_dict.invoice_copy.df.options.split('\n')[0];
                    this.print_with_option(frm, defaultOption);
                } else {
                    this.generate_pdf(frm);
                }
            }
        });
    }

    print_with_option(frm, option) {
        // Only for Sales Invoice
        frappe.call({
            method: "frappe.client.set_value",
            args: {
                doctype: frm.doc.doctype,
                name: frm.doc.name,
                fieldname: "invoice_copy",
                value: option
            },
            callback: (response) => {
                if (!response.exc) {
                    this.generate_pdf(frm);
                }
            }
        });
    }

    generate_pdf(frm) {
        // Check if this doctype is explicitly configured in BNS Settings
        if (!this.bns_configured_formats[frm.doc.doctype]) {
            frappe.msgprint({
                title: __('Print Format Not Available'),
                indicator: 'red',
                message: __(`Print Format not set for ${frm.doc.doctype}. Please ask your administrator to configure it in BNS Settings.`)
            });
            return;
        }
        // Get the configured print format for this doctype
        const formats = this.print_formats[frm.doc.doctype];
        
        if (!formats || formats.length === 0) {
            frappe.msgprint({
                title: __('Print Format Not Available'),
                indicator: 'red',
                message: __(`Print Format not set for ${frm.doc.doctype}. Please ask your administrator to configure it in BNS Settings.`)
            });
            return;
        }
        
        // Use the first print format by default
        const print_format = formats[0];
        const letterhead = frm.doc.letter_head || '';
        const no_letterhead = letterhead === '' ? 1 : 0;
        
        // Use URLSearchParams for cleaner URL construction
        const params = new URLSearchParams({
            doctype: frm.doc.doctype,
            name: frm.doc.name,
            format: print_format,
            no_letterhead: no_letterhead
        });
        
        if (letterhead) {
            params.append('letterhead', letterhead);
        }
        
        const pdf_url = frappe.urllib.get_full_url(
            `/api/method/frappe.utils.print_format.download_pdf?${params.toString()}`
        );
        
        const printWindow = window.open(pdf_url);
        if (printWindow) {
            printWindow.addEventListener('load', () => printWindow.print());
        } else {
            frappe.msgprint({
                title: __('Pop-up Blocked'),
                indicator: 'red',
                message: __('Please allow pop-ups to print the document.')
            });
        }
    }
}

// Initialize the direct print handler
frappe.provide('business_needed_solutions.direct_print');
$(document).ready(function() {
    business_needed_solutions.direct_print = new business_needed_solutions.DirectPrint();
});