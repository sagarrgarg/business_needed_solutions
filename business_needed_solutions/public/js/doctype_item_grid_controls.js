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

// BNS Settings are read once per form refresh and shared by the row events.
function get_bns_grid_settings(frm, reload) {
    if (reload || !frm.__bns_grid_settings) {
        frm.__bns_grid_settings = frappe.db.get_doc('BNS Settings');
    }
    return frm.__bns_grid_settings;
}

// Setup handlers for all supported doctypes
Object.entries(SUPPORTED_DOCTYPES).forEach(([doctype, child_doctype]) => {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            get_bns_grid_settings(frm, true).then(settings => {
                if (settings.enable_uom_restriction) {
                    setup_uom_restriction(frm);
                }
                frm.__bns_conversion_tags = !!settings.enable_conversion_tags;
                if (frm.__bns_conversion_tags) {
                    add_conversion_styles();
                    watch_items_grid(frm);
                    apply_conversion_overlays(frm);
                }
            });
        }
    });

    // Setup handlers for child doctypes
    const reapply_row = function(frm, cdt, cdn) {
        get_bns_grid_settings(frm).then(settings => {
            if (settings.enable_conversion_tags) {
                setTimeout(() => apply_single_overlay(frm, cdt, cdn), 200);
            }
        });
    };
    frappe.ui.form.on(child_doctype, {
        item_code: reapply_row,
        uom: reapply_row,
        conversion_factor: reapply_row
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

function get_items_grid(frm) {
    const field = frm.fields_dict && frm.fields_dict.items;
    return field && field.grid && field.grid.wrapper ? field.grid : null;
}

// ERPNext v16 rebuilds every grid row on refresh (grid.reset_grid() from
// erpnext.toggle_serial_batch_fields when serial/batch fields are hidden), which
// drops the tags drawn moments earlier. Watch the items grid and draw the tags
// again whenever rows or columns are rebuilt. Only grid-row / grid-static-col
// insertions count, so drawing a tag never wakes the watcher again.
function watch_items_grid(frm) {
    const grid = get_items_grid(frm);
    const el = grid && grid.wrapper.get(0);
    if (!el || el.__bns_conversion_observer) return;

    let pending = null;
    const observer = new MutationObserver(mutations => {
        const rebuilt = mutations.some(m => Array.from(m.addedNodes).some(n =>
            n.nodeType === 1 && (n.classList.contains('grid-row') || n.classList.contains('grid-static-col'))
        ));
        if (!rebuilt || !frm.__bns_conversion_tags) return;
        clearTimeout(pending);
        pending = setTimeout(() => apply_conversion_overlays(frm), 50);
    });
    observer.observe(el, { childList: true, subtree: true });
    el.__bns_conversion_observer = observer;
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
    let row = locals[cdt] && locals[cdt][cdn];
    if (!row) return;

    const grid = get_items_grid(frm);
    if (!grid) return;

    // Find the qty cell of this row in this form's items grid only
    let qty_field = grid.wrapper.find(
        `.grid-body .grid-row[data-name="${cdn}"] .grid-static-col[data-fieldname="qty"]`
    );

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
                    ${frappe.utils.escape_html(String(row.conversion_factor))} ${frappe.utils.escape_html(row.stock_uom)}
                    <span>per ${frappe.utils.escape_html(row.uom)}</span>
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
