frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
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
                            method: "business_needed_solutions.business_needed_solutions.utils.make_bns_internal_purchase_receipt",
                            frm: frm,
                        });
                    },
                    __("Create")
                );
                frm.page.set_inner_btn_group_as_primary(__("Create"));
            }
        }
    }
}); 