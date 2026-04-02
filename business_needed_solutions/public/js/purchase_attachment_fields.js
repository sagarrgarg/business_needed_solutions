/**
 * Controls visibility and mandatory status of BNS purchase attachment fields
 * (bns_supplier_invoice_attachment, bns_ewaybill_attachment, bns_builty_attachment)
 * on Purchase Receipt and Purchase Invoice.
 *
 * e-Waybill field is hidden when the document doesn't meet GST threshold criteria.
 * When visible, it becomes mandatory on submit.
 * Builty / LR Copy is always optional.
 * When PI is linked to a PR, the entire section is hidden with an info note.
 */

function setupPurchaseAttachmentFields(frm) {
  if (!frm.fields_dict.bns_supplier_invoice_attachment) return;

  if (_isLinkedToPR(frm)) {
    _hideAttachmentSection(frm);
    return;
  }

  _showAttachmentSection(frm);
  _refreshEwaybillVisibility(frm);
}

function _isLinkedToPR(frm) {
  if (frm.doc.doctype !== 'Purchase Invoice') return false;
  return (frm.doc.items || []).some(function(d) { return d.purchase_receipt; });
}

function _hideAttachmentSection(frm) {
  frm.toggle_display('bns_purchase_attachments_section', false);
  frm.toggle_display('bns_supplier_invoice_attachment', false);
  frm.toggle_display('bns_ewaybill_attachment', false);
  frm.toggle_display('bns_builty_attachment', false);
  frm.toggle_reqd('bns_supplier_invoice_attachment', false);
  frm.toggle_reqd('bns_ewaybill_attachment', false);
}

function _showAttachmentSection(frm) {
  frm.toggle_display('bns_purchase_attachments_section', true);
  frm.toggle_display('bns_supplier_invoice_attachment', true);
  frm.toggle_display('bns_builty_attachment', true);
}

function _refreshEwaybillVisibility(frm) {
  frappe.call({
    method: 'business_needed_solutions.business_needed_solutions.overrides.attachment_validation.check_ewaybill_applicability',
    args: {
      doctype: frm.doc.doctype,
      base_grand_total: frm.doc.base_grand_total || 0,
      update_stock: frm.doc.update_stock || 0,
      items_json: JSON.stringify((frm.doc.items || []).map(function(d) { return {item_code: d.item_code}; }))
    },
    callback: function(r) {
      if (!r || !r.message) return;

      var ewaybillRequired = r.message.required;
      frm.toggle_display('bns_ewaybill_attachment', ewaybillRequired);
      frm.toggle_reqd('bns_ewaybill_attachment', ewaybillRequired && frm.doc.docstatus === 0);

      if (ewaybillRequired && frm.doc.docstatus === 0 && frm.fields_dict.bns_ewaybill_attachment) {
        frm.fields_dict.bns_ewaybill_attachment.set_description(
          __('Required: Net total exceeds e-Waybill threshold of {0}',
            [frappe.format(r.message.threshold, {fieldtype: 'Currency'})])
        );
      }
    }
  });
}

frappe.ui.form.on('Purchase Receipt', {
  refresh: function(frm) { setupPurchaseAttachmentFields(frm); },
  base_grand_total: function(frm) { _refreshEwaybillVisibility(frm); },
  items_remove: function(frm) { _refreshEwaybillVisibility(frm); }
});

frappe.ui.form.on('Purchase Receipt Item', {
  item_code: function(frm) { _refreshEwaybillVisibility(frm); }
});

frappe.ui.form.on('Purchase Invoice', {
  refresh: function(frm) { setupPurchaseAttachmentFields(frm); },
  base_grand_total: function(frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  update_stock: function(frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  items_remove: function(frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  }
});

frappe.ui.form.on('Purchase Invoice Item', {
  item_code: function(frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  }
});
