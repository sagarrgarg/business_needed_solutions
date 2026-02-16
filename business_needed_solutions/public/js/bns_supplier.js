/**
 * BNS Internal Supplier: when on, turn off and hide standard Is Internal Supplier.
 */
frappe.ui.form.on("Supplier", {
	refresh: function (frm) {
		_sync_standard_internal_visibility(frm);
	},
	is_bns_internal_supplier: function (frm) {
		if (frm.doc.is_bns_internal_supplier) {
			frm.set_value("is_internal_supplier", 0);
		}
		_sync_standard_internal_visibility(frm);
	},
});

function _sync_standard_internal_visibility(frm) {
	// When BNS internal is on, hide standard internal and keep it off
	if (frm.doc.is_bns_internal_supplier) {
		frm.set_value("is_internal_supplier", 0);
		frm.set_df_property("is_internal_supplier", "hidden", 1);
	} else {
		frm.set_df_property("is_internal_supplier", "hidden", 0);
	}
}
