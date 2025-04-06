// File: apps/business_needed_solutions/business_needed_solutions/public/js/compound_discount.js

frappe.provide('business_needed_solutions');

business_needed_solutions.CompoundDiscount = class CompoundDiscount {
    constructor() {
        this.settings = {
            discount_type: 'Single' // Default fallback
        };
        this.supported_doctypes = ['Sales Invoice', 'Sales Order', 'Delivery Note',"Quotation"];
        this.initialize();
    }

    initialize() {
        // Load settings
        this.load_settings().then(() => {
            this.setup_handlers();
        });
    }

    async load_settings() {
        try {
            this.settings.discount_type = await frappe.db.get_single_value('BNS Settings', 'discount_type');
        } catch (error) {
            console.error('Error loading BNS Settings:', error);
            // Keep using default fallback
        }
    }

    setup_handlers() {
        this.supported_doctypes.forEach(doctype => {
            // Main doctype handlers
            frappe.ui.form.on(doctype, {
                refresh: frm => this.toggle_readonly_fields(frm),
                validate: frm => {
                    frm.doc.items.forEach(item => {
                        this.update_discount(item);
                        this.validate_and_clear_discounts(item);
                    });
                }
            });

            // Item doctype handlers
            frappe.ui.form.on(`${doctype} Item`, {
                custom_d1_: (frm, cdt, cdn) => this.handle_discount_change(frm, cdt, cdn),
                custom_d2_: (frm, cdt, cdn) => this.handle_discount_change(frm, cdt, cdn),
                custom_d3_: (frm, cdt, cdn) => {
                    const item = locals[cdt][cdn];
                    this.update_discount(item);
                    this.toggle_readonly_fields(frm);
                },
                discount_percentage: (frm, cdt, cdn) => {
                    const item = locals[cdt][cdn];
                    this.validate_and_clear_discounts(item);
                },
                items_add: frm => this.toggle_readonly_fields(frm),
                items_remove: frm => this.toggle_readonly_fields(frm)
            });
        });
    }

    handle_discount_change(frm, cdt, cdn) {
        const item = locals[cdt][cdn];
        
        if (this.settings.discount_type !== 'Single') {
            const d1 = item.custom_d1_ || 0;
            const d2 = item.custom_d2_ || 0;

            if (d1 === 0) {
                frappe.model.set_value(cdt, cdn, 'custom_d2_', 0);
                frappe.model.set_value(cdt, cdn, 'custom_d3_', 0);
            } else if (d2 === 0) {
                frappe.model.set_value(cdt, cdn, 'custom_d3_', 0);
            }
        }

        this.update_discount(item);
        this.toggle_readonly_fields(frm);
    }

    validate_and_clear_discounts(item) {
        if (this.settings.discount_type === 'Single') {
            if (!item.discount_percentage || item.discount_percentage == 0) {
                this.clear_discounts(item);
            }
        } else {
            const d1 = item.custom_d1_ || 0;
            const d2 = item.custom_d2_ || 0;
            const d3 = item.custom_d3_ || 0;

            if (d1 === 0 && d2 === 0 && d3 === 0) {
                this.clear_discounts(item);
            }
        }
    }

    clear_discounts(item) {
        frappe.model.set_value(item.doctype, item.name, 'discount_amount', 0);
        frappe.model.set_value(item.doctype, item.name, 'discount_percentage', 0);
        frappe.model.set_value(item.doctype, item.name, 'rate', item.price_list_rate || 0);
    }

    update_discount(item) {
        if (this.settings.discount_type === 'Single') return;
        const { custom_d1_, custom_d2_, custom_d3_, price_list_rate = 0 } = item;

        const d1 = custom_d1_ || 0;
        const d2 = custom_d2_ || 0;
        const d3 = custom_d3_ || 0;

        let rate = price_list_rate * (1 - d1 / 100);
        rate *= (1 - d2 / 100);
        rate *= (1 - d3 / 100);

        const total_discount = price_list_rate
            ? 100 - (rate / price_list_rate * 100)
            : 0;

        frappe.model.set_value(item.doctype, item.name, 'discount_percentage', total_discount);
    }

    toggle_readonly_fields(frm) {
        if (!frm.fields_dict.items?.grid) return;

        frm.fields_dict.items.grid.grid_rows.forEach(row => {
            const item = row.doc;
            const d1_filled = item.custom_d1_ != null && item.custom_d1_ != 0;
            const d2_filled = item.custom_d2_ != null && item.custom_d2_ != 0;

            // Update docfield properties
            frappe.meta.get_docfield(item.doctype, 'custom_d2_', frm.doc.name).read_only = !d1_filled;
            frappe.meta.get_docfield(item.doctype, 'custom_d3_', frm.doc.name).read_only = !(d1_filled && d2_filled);

            // Update grid row editability
            row.toggle_editable('custom_d2_', d1_filled);
            row.toggle_editable('custom_d3_', d1_filled && d2_filled);
        });

        frm.refresh_field('items');
    }
}

// Initialize the compound discount handler
frappe.provide('business_needed_solutions.compound_discount');
$(document).ready(function() {
    business_needed_solutions.compound_discount = new business_needed_solutions.CompoundDiscount();
});