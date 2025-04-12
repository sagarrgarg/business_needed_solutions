frappe.ui.form.on('Item', {
    validate: function(frm) {
        if (frm.doc.custom_print_uom) {
            const uoms_list = frm.doc.uoms.map(row => row.uom); // Get a list of UOMs from the table
            
            if (!uoms_list.includes(frm.doc.custom_print_uom)) {
                frappe.throw(__('The selected Custom Print UOM "{0}" is not in the UOMs table.', [frm.doc.custom_print_uom]));
            }
        }
    }
}); 