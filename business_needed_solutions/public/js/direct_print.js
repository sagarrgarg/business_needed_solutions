/**
 * Business Needed Solutions - Direct Print System
 * 
 * This module provides direct printing functionality for various document types
 * with configurable print formats and enhanced user experience.
 */

frappe.provide('business_needed_solutions');

/**
 * DirectPrint Class
 * 
 * Handles direct printing functionality for supported document types
 * with configurable print formats from BNS Settings.
 */
business_needed_solutions.DirectPrint = class DirectPrint {
    /**
     * Initialize the DirectPrint system
     */
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
        this.bns_configured_formats = {};
        this.initialized = false;
        this.initialize();
    }

    /**
     * Initialize the direct print system
     */
    async initialize() {
        try {
            await this.load_settings();
            this.setup_handlers();
            this.initialized = true;
            console.log('DirectPrint system initialized successfully');
        } catch (error) {
            console.error('Error initializing DirectPrint system:', error);
        }
    }

    /**
     * Load print format settings from BNS Settings
     */
    async load_settings() {
        try {
            const doc = await frappe.db.get_doc('BNS Settings');
            this._process_bns_settings(doc);
            this._setup_fallback_formats();
        } catch (error) {
            console.error('Error loading BNS Settings:', error);
            this._setup_default_formats();
        }
    }

    /**
     * Process BNS Settings configuration
     * 
     * @param {Object} doc - BNS Settings document
     */
    _process_bns_settings(doc) {
        if (doc && doc.print_format) {
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
    }

    /**
     * Setup fallback formats for unconfigured doctypes
     */
    _setup_fallback_formats() {
        this.supported_doctypes.forEach(doctype => {
            if (!this.print_formats[doctype] || this.print_formats[doctype].length === 0) {
                console.warn(`No print format configured for ${doctype}, using defaults`);
                this._set_default_format(doctype);
            }
        });
    }

    /**
     * Set default print format for a doctype
     * 
     * @param {string} doctype - The document type
     */
    _set_default_format(doctype) {
        const default_formats = {
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
        
        this.print_formats[doctype] = default_formats[doctype] || [];
    }

    /**
     * Setup default formats when BNS Settings cannot be loaded
     */
    _setup_default_formats() {
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

    /**
     * Setup event handlers for supported doctypes
     */
    setup_handlers() {
        this.supported_doctypes.forEach(doctype => {
            frappe.ui.form.on(doctype, {
                refresh: frm => this.setup_print_button(frm)
            });
        });
    }

    /**
     * Setup print button for a form
     * 
     * @param {Object} frm - The form object
     */
    setup_print_button(frm) {
        const $printButton = frm.page.wrapper.find('button[data-original-title="Print"]');
        if (!$printButton.length) return;
        
        // Remove existing click handlers
        $printButton.off('click');
        
        // Setup based on doctype
        if (this._is_sales_invoice_with_copy(frm)) {
            this._setup_sales_invoice_print(frm, $printButton);
        } else {
            this._setup_simple_print(frm, $printButton);
        }
        
        // Setup keyboard shortcut
        this.setup_keyboard_shortcut(frm);
    }

    /**
     * Check if form is Sales Invoice with invoice_copy field
     * 
     * @param {Object} frm - The form object
     * @returns {boolean} True if Sales Invoice with invoice_copy
     */
    _is_sales_invoice_with_copy(frm) {
        return frm.doctype === 'Sales Invoice' && frm.fields_dict.invoice_copy;
    }

    /**
     * Setup Sales Invoice print with dropdown
     * 
     * @param {Object} frm - The form object
     * @param {jQuery} $printButton - The print button element
     */
    _setup_sales_invoice_print(frm, $printButton) {
        $printButton.addClass('dropdown-toggle');
        $printButton.attr('data-toggle', 'dropdown');
        this.create_dropdown_menu(frm, $printButton);
    }

    /**
     * Setup simple print functionality
     * 
     * @param {Object} frm - The form object
     * @param {jQuery} $printButton - The print button element
     */
    _setup_simple_print(frm, $printButton) {
        $printButton.on('click', () => {
            this.generate_pdf(frm);
        });
    }

    /**
     * Create dropdown menu for Sales Invoice print options
     * 
     * @param {Object} frm - The form object
     * @param {jQuery} $printButton - The print button element
     */
    create_dropdown_menu(frm, $printButton) {
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

    /**
     * Setup keyboard shortcut for printing
     * 
     * @param {Object} frm - The form object
     */
    setup_keyboard_shortcut(frm) {
        // Remove existing handler if any
        $(document).off('keydown.directPrint');
        
        // Add new handler
        $(document).on('keydown.directPrint', (e) => {
            if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'P')) {
                e.preventDefault();
                e.stopPropagation();
                
                if (this._is_sales_invoice_with_copy(frm)) {
                    const defaultOption = frm.fields_dict.invoice_copy.df.options.split('\n')[0];
                    this.print_with_option(frm, defaultOption);
                } else {
                    this.generate_pdf(frm);
                }
            }
        });
    }

    /**
     * Print with specific option (for Sales Invoice)
     * 
     * @param {Object} frm - The form object
     * @param {string} option - The print option
     */
    print_with_option(frm, option) {
        // Generate PDF with the selected option without updating the document
        this.generate_pdf(frm, option);
    }

    /**
     * Generate PDF for printing
     * 
     * @param {Object} frm - The form object
     */
    generate_pdf(frm, selectedOption = null) {
        // Validate configuration
        if (!this._is_doctype_configured(frm.doc.doctype)) {
            this._show_configuration_error(frm.doc.doctype);
            return;
        }
        
        // Get print format
        const formats = this.print_formats[frm.doc.doctype];
        if (!formats || formats.length === 0) {
            this._show_configuration_error(frm.doc.doctype);
            return;
        }
        
        // Generate PDF URL
        const pdf_url = this._build_pdf_url(frm, formats[0], selectedOption);
        
        // Open print window
        this._open_print_window(pdf_url);
    }

    /**
     * Check if doctype is configured in BNS Settings
     * 
     * @param {string} doctype - The document type
     * @returns {boolean} True if configured
     */
    _is_doctype_configured(doctype) {
        return this.bns_configured_formats[doctype];
    }

    /**
     * Show configuration error message
     * 
     * @param {string} doctype - The document type
     */
    _show_configuration_error(doctype) {
        frappe.msgprint({
            title: __('Print Format Not Available'),
            indicator: 'red',
            message: __(`Print Format not set for ${doctype}. Please ask your administrator to configure it in BNS Settings.`)
        });
    }

    /**
     * Build PDF URL for printing
     * 
     * @param {Object} frm - The form object
     * @param {string} print_format - The print format to use
     * @returns {string} The PDF URL
     */
    _build_pdf_url(frm, print_format, selectedOption = null) {
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

        // Add invoice_copy parameter for Sales Invoice
        if (frm.doc.doctype === 'Sales Invoice') {
            const copyMap = {
                "Original for Recipient": "1",
                "Duplicate for Transporter": "2",
                "Duplicate for Supplier": "3",
                "Triplicate for Supplier": "4"
            };
            
            // Use selectedOption if provided, otherwise use the document's invoice_copy value or default to "1"
            let copyValue;
            if (selectedOption) {
                copyValue = copyMap[selectedOption];
            } else if (frm.doc.invoice_copy) {
                copyValue = copyMap[frm.doc.invoice_copy] || "1";
            } else {
                copyValue = "1";
            }
            
            // Ensure invoice_copy is added to both params and as a direct query parameter
            params.append('invoice_copy', copyValue);
            
            // Build the base URL with invoice_copy parameter
            const baseUrl = `/api/method/frappe.utils.print_format.download_pdf?${params.toString()}`;
            
            // Add invoice_copy parameter directly to ensure it's not lost
            return frappe.urllib.get_full_url(`${baseUrl}&invoice_copy=${copyValue}`);
        }
        
        return frappe.urllib.get_full_url(
            `/api/method/frappe.utils.print_format.download_pdf?${params.toString()}`
        );
    }

    /**
     * Open print window with PDF
     * 
     * @param {string} pdf_url - The PDF URL
     */
    _open_print_window(pdf_url) {
        const printWindow = window.open(pdf_url);
        if (printWindow) {
            printWindow.addEventListener('load', () => printWindow.print());
        } else {
            this._show_popup_blocked_error();
        }
    }

    /**
     * Show popup blocked error message
     */
    _show_popup_blocked_error() {
        frappe.msgprint({
            title: __('Pop-up Blocked'),
            indicator: 'red',
            message: __('Please allow pop-ups to print the document.')
        });
    }
};

// Initialize the direct print handler
frappe.provide('business_needed_solutions.direct_print');
$(document).ready(function() {
    business_needed_solutions.direct_print = new business_needed_solutions.DirectPrint();
});