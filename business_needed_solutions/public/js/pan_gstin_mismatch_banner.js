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

// GSTIN lookups are cached per page; the banner itself is drawn on every
// refresh, because each form render clears all headline messages.
var _bns_gstin_cache = {};

function _bns_get_gstin(doctype, name) {
	var key = doctype + "::" + name;
	if (!_bns_gstin_cache[key]) {
		_bns_gstin_cache[key] = frappe.db
			.get_value(doctype, name, "gstin")
			.then(function (r) {
				return (r && r.message && r.message.gstin) || "";
			});
	}
	return _bns_gstin_cache[key];
}

function _bns_check_pan_gstin_mismatch(frm) {
	if (frm.doc.is_return) return;
	if (!frm.doc.customer) return;
	if (frm.doc.docstatus === 2) return;

	var doc_name = frm.doc.name;
	var shipping_addr = frm.doc.shipping_address_name || "";

	Promise.all([
		_bns_get_gstin("Customer", frm.doc.customer),
		shipping_addr ? _bns_get_gstin("Address", shipping_addr) : Promise.resolve(""),
	]).then(function (values) {
		if (frm.doc.name !== doc_name) return; // user moved to another document
		var customer_gstin = values[0];
		var shipping_gstin = values[1];
		if (!customer_gstin) return;

		var customer_pan =
			(frm.doc.tax_id || "").toUpperCase() ||
			_bns_pan_from_gstin(customer_gstin);
		if (!customer_pan) return;

		var messages = [];
		var color = null;

		// RED: billing address PAN mismatch
		var billing_pan = _bns_pan_from_gstin(frm.doc.billing_address_gstin || "");
		if (billing_pan && billing_pan !== customer_pan) {
			messages.push(
				__(
					"Customer PAN ({0}) does not match Billing Address GSTIN PAN ({1}). This invoice may be billed to wrong party.",
					[customer_pan, billing_pan]
				)
			);
			color = "red";
		}

		// YELLOW: shipping address PAN mismatch
		var shipping_pan = _bns_pan_from_gstin(shipping_gstin);
		if (shipping_pan && shipping_pan !== customer_pan) {
			messages.push(
				__(
					"Customer PAN ({0}) does not match Shipping Address GSTIN PAN ({1}). Verify shipping destination.",
					[customer_pan, shipping_pan]
				)
			);
			color = color || "yellow";
		}

		if (messages.length) {
			frm.dashboard.set_headline_alert(messages.join("<br>"), color);
		}
	});
}
