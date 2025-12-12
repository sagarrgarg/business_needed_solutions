frappe.ui.form.on('Warehouse', {
	refresh: function(frm) {
		// Check Stock Settings and BNS Settings and show/hide the field accordingly
		_check_and_toggle_negative_stock_field(frm);
	},
	
	// Also check when Stock Settings might change (though this is less common)
	onload: function(frm) {
		_check_and_toggle_negative_stock_field(frm);
	}
});

function _check_and_toggle_negative_stock_field(frm) {
	// Get both Stock Settings and BNS Settings values
	Promise.all([
		frappe.db.get_single_value('Stock Settings', 'allow_negative_stock'),
		frappe.db.get_single_value('BNS Settings', 'enable_per_warehouse_negative_stock_disallow')
	]).then(function(values) {
		var allow_negative_stock = values[0];
		var bns_feature_enabled = values[1];
		
		// Show field only if both conditions are met:
		// 1. Stock Settings allows negative stock globally
		// 2. BNS Settings has per-warehouse feature enabled
		if (allow_negative_stock && bns_feature_enabled) {
			// Show the field if both settings are enabled
			frm.set_df_property('bns_disallow_negative_stock', 'hidden', 0);
		} else {
			// Hide the field if either setting is disabled
			frm.set_df_property('bns_disallow_negative_stock', 'hidden', 1);
			// Also unset the value when hiding
			if (frm.doc.bns_disallow_negative_stock) {
				frm.set_value('bns_disallow_negative_stock', 0);
			}
		}
	});
}
