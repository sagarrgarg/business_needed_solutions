// PAN / GSTIN mismatch warning banners for Sales Invoice and Delivery Note.
//
// For GST-registered customers, compares Customer PAN against:
//   RED    - Billing Address GSTIN PAN (wrong legal entity billed)
//   YELLOW - Shipping Address GSTIN PAN (goods going to different entity)
//
// PAN = characters [2:12] of a 15-char Indian GSTIN.
// Skipped for returns and unregistered customers.

frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		_bns_check_pan_gstin_mismatch(frm);
	},
});

frappe.ui.form.on("Delivery Note", {
	refresh: function (frm) {
		_bns_check_pan_gstin_mismatch(frm);
	},
});

function _bns_pan_from_gstin(gstin) {
	if (!gstin || gstin.length < 12) return null;
	return gstin.substring(2, 12).toUpperCase();
}

function _bns_check_pan_gstin_mismatch(frm) {
	if (frm.doc.is_return) return;
	if (!frm.doc.customer) return;
	if (frm.doc.docstatus === 2) return;

	var cache_key = [
		frm.doc.name,
		frm.doc.customer,
		frm.doc.billing_address_gstin || "",
		frm.doc.shipping_address_name || "",
		frm.doc.tax_id || "",
		frm.doc.modified || "",
	].join("|");

	if (frm.__bns_pan_check_key === cache_key) return;
	frm.__bns_pan_check_key = cache_key;

	frappe.db.get_value("Customer", frm.doc.customer, "gstin", function (r) {
		var customer_gstin = (r && r.gstin) || "";
		if (!customer_gstin) return;

		var customer_pan =
			(frm.doc.tax_id || "").toUpperCase() ||
			_bns_pan_from_gstin(customer_gstin);
		if (!customer_pan) return;

		// RED: billing address PAN mismatch
		var billing_gstin = frm.doc.billing_address_gstin || "";
		if (billing_gstin) {
			var billing_pan = _bns_pan_from_gstin(billing_gstin);
			if (billing_pan && billing_pan !== customer_pan) {
				frm.dashboard.set_headline_alert(
					__(
						"Customer PAN ({0}) does not match Billing Address GSTIN PAN ({1}). This invoice may be billed to wrong party.",
						[customer_pan, billing_pan]
					),
					"red"
				);
			}
		}

		// YELLOW: shipping address PAN mismatch
		var shipping_addr = frm.doc.shipping_address_name || "";
		if (!shipping_addr) return;

		frappe.db.get_value("Address", shipping_addr, "gstin", function (addr_r) {
			var shipping_gstin = (addr_r && addr_r.gstin) || "";
			if (!shipping_gstin) return;

			var shipping_pan = _bns_pan_from_gstin(shipping_gstin);
			if (shipping_pan && shipping_pan !== customer_pan) {
				frm.dashboard.set_headline_alert(
					__(
						"Customer PAN ({0}) does not match Shipping Address GSTIN PAN ({1}). Verify shipping destination.",
						[customer_pan, shipping_pan]
					),
					"yellow"
				);
			}
		});
	});
}
