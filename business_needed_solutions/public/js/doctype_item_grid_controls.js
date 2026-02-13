// Define supported doctypes and their item child tables
const SUPPORTED_DOCTYPES = {
    // Stock Transactions
    'Stock Entry': 'Stock Entry Detail',
    
    // Sales Documents
    'Sales Invoice': 'Sales Invoice Item',
    'Sales Order': 'Sales Order Item',
    'Delivery Note': 'Delivery Note Item',
    
    // Purchase Documents
    'Purchase Invoice': 'Purchase Invoice Item',
    'Purchase Order': 'Purchase Order Item',
    'Purchase Receipt': 'Purchase Receipt Item'
};

// Setup handlers for all supported doctypes
Object.entries(SUPPORTED_DOCTYPES).forEach(([doctype, child_doctype]) => {
    frappe.ui.form.on(doctype, {
        after_grid_render(frm) {
            // Apply overlays after grid is rendered
            frappe.db.get_doc('BNS Settings').then(settings => {
                if (settings.enable_conversion_tags) {
                    apply_conversion_overlays(frm);
                }
            });
        },

        refresh(frm) {
            // Load BNS Settings
            frappe.db.get_doc('BNS Settings').then(settings => {
                if (settings.enable_uom_restriction) {
                    setup_uom_restriction(frm);
                }
                if (settings.enable_conversion_tags) {
                    // Apply to all existing rows
                    apply_conversion_overlays(frm);
                }
            });
        },

        onload: function(frm) {
            // Add custom CSS for conversion tags
            frappe.db.get_doc('BNS Settings').then(settings => {
                if (settings.enable_conversion_tags) {
                    add_conversion_styles();
                    // Apply to all existing rows
                    apply_conversion_overlays(frm);
                }
            });
        }
    });

    // Setup handlers for child doctypes
    frappe.ui.form.on(child_doctype, {
        item_code: function(frm, cdt, cdn) {
            frappe.db.get_doc('BNS Settings').then(settings => {
                if (settings.enable_conversion_tags) {
                    setTimeout(() => apply_single_overlay(frm, cdt, cdn), 200);
                }
            });
        },
        
        uom: function(frm, cdt, cdn) {
            frappe.db.get_doc('BNS Settings').then(settings => {
                if (settings.enable_conversion_tags) {
                    setTimeout(() => apply_single_overlay(frm, cdt, cdn), 200);
                }
            });
        },
        
        conversion_factor: function(frm, cdt, cdn) {
            frappe.db.get_doc('BNS Settings').then(settings => {
                if (settings.enable_conversion_tags) {
                    setTimeout(() => apply_single_overlay(frm, cdt, cdn), 200);
                }
            });
        }
    });
});

// UOM Restriction Functions
function setup_uom_restriction(frm) {
    frm.set_query('uom', 'items', function(doc, cdt, cdn) {
        const d = locals[cdt][cdn];
        let allowed_uoms = [];

        if (!d.item_code) return {};

        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Item',
                name: d.item_code
            },
            async: false,
            callback: function(r) {
                const item = r.message;
                allowed_uoms = [item.stock_uom];

                if (item.uoms && Array.isArray(item.uoms)) {
                    item.uoms.forEach(entry => {
                        if (entry.uom && !allowed_uoms.includes(entry.uom)) {
                            allowed_uoms.push(entry.uom);
                        }
                    });
                }

                console.log("Allowed UOMs for", d.item_code, ":", allowed_uoms);
            }
        });

        return {
            filters: {
                name: ["in", allowed_uoms]
            }
        };
    });
}

// Conversion Tag Functions
function add_conversion_styles() {
    if ($('#conversion-styles').length === 0) {
        $('head').append(`
            <style id="conversion-styles">
                .qty-conversion-container {
                    position: relative !important;
                }
                
                .conversion-badge {
                    position: absolute;
                    top: -6px;
                    right: -3px;
                    background: linear-gradient(135deg, #ff4757, #ff3838);
                    color: white;
                    padding: 1px 4px;
                    border-radius: 4px;
                    font-size: 8px;
                    font-weight: bold;
                    z-index: 1000;
                    white-space: nowrap;
                    box-shadow: 0 1px 3px rgba(255, 71, 87, 0.3);
                }
                
                .conversion-badge.high-conversion {
                    background: linear-gradient(135deg, #ff9500, #ff8c00);
                    box-shadow: 0 1px 3px rgba(255, 149, 0, 0.3);
                }
                
                .conversion-badge.medium-conversion {
                    background: linear-gradient(135deg, #3498db, #2980b9);
                    box-shadow: 0 1px 3px rgba(52, 152, 219, 0.3);
                }
                
                .conversion-badge.low-conversion {
                    background: linear-gradient(135deg, #2ecc71, #27ae60);
                    box-shadow: 0 1px 3px rgba(46, 204, 113, 0.3);
                }
                
                .conversion-badge span {
                    opacity: 0.9;
                    font-size: 7px;
                }
            </style>
        `);
    }
}

function apply_conversion_overlays(frm) {
    // Get the child table name based on the doctype
    const child_doctype = SUPPORTED_DOCTYPES[frm.doc.doctype];
    if (!child_doctype) return;

    // Apply overlay to each row
    (frm.doc.items || []).forEach(row => {
        apply_single_overlay(frm, child_doctype, row.name);
    });
}

function apply_single_overlay(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    if (!row) return;
    
    // Find the qty field first
    let qty_field = $(`.grid-row[data-idx="${row.idx}"] .grid-static-col[data-fieldname="qty"]`);
    
    if (qty_field.length > 0) {
        // ALWAYS remove existing overlay and class first
        qty_field.find('.conversion-badge').remove();
        qty_field.removeClass('qty-conversion-container');
        
        // Only add overlay if we have data AND UOM is different from Stock UOM
        if (row.uom && row.stock_uom && row.conversion_factor && row.uom !== row.stock_uom) {
            // Add container class
            qty_field.addClass('qty-conversion-container');
            
            // Determine badge class based on conversion factor
            let badgeClass = 'conversion-badge';
            if (row.conversion_factor >= 40) {
                badgeClass += ' high-conversion';
            } else if (row.conversion_factor >= 20) {
                badgeClass += ' medium-conversion';
            } else if (row.conversion_factor >= 10) {
                badgeClass += ' low-conversion';
            }
            
            // Create badge HTML
            let badgeHtml = `
                <div class="${badgeClass}">
                    ${row.conversion_factor} ${row.stock_uom}
                    <span>per ${row.uom}</span>
                </div>
            `;
            
            // Append badge
            qty_field.append(badgeHtml);
        }
    }
}


// ============================================================
// Stock Entry: BOM Enforcement — red-highlight mandatory fields
// ============================================================
// Dynamically sets bom_no and from_bom as required when
// BNS Settings.enforce_bom_for_manufacture is on and purpose is Manufacture.
// This triggers Frappe's built-in mandatory field highlighting (red border + scroll).

frappe.ui.form.on('Stock Entry', {
    refresh(frm) {
        _toggle_bom_mandatory(frm);
    },
    purpose(frm) {
        _toggle_bom_mandatory(frm);
    },
    stock_entry_type(frm) {
        _toggle_bom_mandatory(frm);
    }
});

function _toggle_bom_mandatory(frm) {
    if (frm.doc.purpose !== 'Manufacture') {
        frm.toggle_reqd('bom_no', false);
        frm.toggle_reqd('from_bom', false);
        return;
    }

    frappe.db.get_single_value('BNS Settings', 'enforce_bom_for_manufacture').then(val => {
        const enforce = cint(val);
        frm.toggle_reqd('bom_no', enforce);
        frm.toggle_reqd('from_bom', enforce);
    });
}
