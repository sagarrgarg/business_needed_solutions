/**
 * BNS Internal Customer: when on, turn off and hide standard Is Internal Customer.
 */
frappe.ui.form.on("Customer", {
	refresh: function (frm) {
		_sync_standard_internal_visibility(frm);
	},
	is_bns_internal_customer: function (frm) {
		if (frm.doc.is_bns_internal_customer) {
			frm.set_value("is_internal_customer", 0);
		}
		_sync_standard_internal_visibility(frm);
	},
});

function _sync_standard_internal_visibility(frm) {
	// When BNS internal is on, hide standard internal and keep it off
	if (frm.doc.is_bns_internal_customer) {
		frm.set_value("is_internal_customer", 0);
		frm.set_df_property("is_internal_customer", "hidden", 1);
	} else {
		frm.set_df_property("is_internal_customer", "hidden", 0);
	}
}
