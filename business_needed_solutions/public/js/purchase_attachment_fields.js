/**
 * Controls visibility and mandatory status of BNS purchase attachment fields on
 * Purchase Receipt and Purchase Invoice:
 *
 *   bns_supplier_invoice_attachment   (Attach)
 *   bns_ewaybill_attachment           (Attach, paired with bns_ewaybill_date)
 *   bns_ewaybill_date                 (Date)
 *   bns_mode_of_transport             (Select: By Hand / By Lorry / By e-Waybill)
 *   bns_builty_attachment             (Attach, always optional)
 *
 * Rules:
 *   - BNS internal supplier  → entire section hidden, nothing required.
 *   - PI with linked PR rows → per-field hide based on whether each linked PR
 *     has that field filled; nothing required (server-side bypass applies).
 *   - Otherwise               → section visible. Mode = "By Hand" / "By Lorry"
 *     skips the e-Waybill threshold check entirely. Mode = "By e-Waybill" or
 *     blank → server-side threshold call decides whether e-Waybill attach+date
 *     are required.
 *
 * Supplier-level toggle bns_skip_supplier_invoice_details inverts the bill_no /
 * bill_date requirement for that supplier (default OFF → fields required).
 */

function setupPurchaseAttachmentFields(frm) {
  if (!frm.fields_dict.bns_supplier_invoice_attachment) return;

  _resolveBnsInternalSupplier(frm, function (internal) {
    if (internal) {
      _hideAttachmentSection(frm);
      _toggleBillFieldsReqd(frm, false);
      return;
    }

    if (_isLinkedToPR(frm)) {
      _showAttachmentSection(frm);
      _applyLinkedPRHides(frm);
      _resolveSupplierSkipFlag(frm, function (skip) {
        _toggleBillFieldsReqd(frm, !skip);
      });
      return;
    }

    _showAttachmentSection(frm);
    _refreshEwaybillVisibility(frm);
    _resolveSupplierSkipFlag(frm, function (skip) {
      _toggleBillFieldsReqd(frm, !skip);
    });
  });
}

function _resolveBnsInternalSupplier(frm, callback) {
  if (!frm.doc.supplier) {
    callback(false);
    return;
  }
  if (cint(frm.doc.is_bns_internal_supplier)) {
    callback(true);
    return;
  }
  frappe.db.get_value(
    'Supplier',
    frm.doc.supplier,
    'is_bns_internal_supplier',
    function (r) {
      callback(r && cint(r.is_bns_internal_supplier));
    }
  );
}

function _resolveSupplierSkipFlag(frm, callback) {
  if (!frm.doc.supplier) {
    callback(false);
    return;
  }
  frappe.db.get_value(
    'Supplier',
    frm.doc.supplier,
    'bns_skip_supplier_invoice_details',
    function (r) {
      callback(r && cint(r.bns_skip_supplier_invoice_details));
    }
  );
}

function _isLinkedToPR(frm) {
  if (frm.doc.doctype !== 'Purchase Invoice') return false;
  return (frm.doc.items || []).some(function (d) { return d.purchase_receipt; });
}

function _linkedPRNames(frm) {
  var seen = {};
  var out = [];
  (frm.doc.items || []).forEach(function (d) {
    if (d.purchase_receipt && !seen[d.purchase_receipt]) {
      seen[d.purchase_receipt] = true;
      out.push(d.purchase_receipt);
    }
  });
  return out;
}

function _hideAttachmentSection(frm) {
  frm.toggle_display('bns_purchase_attachments_section', false);
  frm.toggle_display('bns_supplier_invoice_attachment', false);
  frm.toggle_display('bns_ewaybill_attachment', false);
  frm.toggle_display('bns_ewaybill_date', false);
  frm.toggle_display('bns_mode_of_transport', false);
  frm.toggle_display('bns_builty_attachment', false);
  frm.toggle_reqd('bns_supplier_invoice_attachment', false);
  frm.toggle_reqd('bns_ewaybill_attachment', false);
  frm.toggle_reqd('bns_ewaybill_date', false);
}

function _showAttachmentSection(frm) {
  frm.toggle_display('bns_purchase_attachments_section', true);
  frm.toggle_display('bns_supplier_invoice_attachment', true);
  frm.toggle_display('bns_mode_of_transport', true);
  frm.toggle_display('bns_builty_attachment', true);
}

function _applyLinkedPRHides(frm) {
  // PI-from-PR: PR is the source of truth. Hide any field on the PI that's
  // already populated on at least one linked PR. Nothing is reqd in this
  // branch — server-side _has_linked_purchase_receipt bypass covers it.
  frm.toggle_reqd('bns_supplier_invoice_attachment', false);
  frm.toggle_reqd('bns_ewaybill_attachment', false);
  frm.toggle_reqd('bns_ewaybill_date', false);

  var prNames = _linkedPRNames(frm);
  if (!prNames.length) return;

  frappe.call({
    method: 'frappe.client.get_list',
    args: {
      doctype: 'Purchase Receipt',
      filters: [['name', 'in', prNames]],
      fields: [
        'name',
        'bns_mode_of_transport',
        'bns_ewaybill_attachment',
        'bns_supplier_invoice_attachment'
      ],
      limit_page_length: 0
    },
    callback: function (r) {
      var rows = (r && r.message) || [];
      var anyMode = rows.some(function (x) { return x.bns_mode_of_transport; });
      var anyEwb = rows.some(function (x) { return x.bns_ewaybill_attachment; });
      var anySupInv = rows.some(function (x) { return x.bns_supplier_invoice_attachment; });

      if (anyMode) frm.toggle_display('bns_mode_of_transport', false);
      if (anyEwb) {
        frm.toggle_display('bns_ewaybill_attachment', false);
        frm.toggle_display('bns_ewaybill_date', false);
      } else {
        // PR doesn't have e-Waybill — keep PI fields hidden until threshold
        // call says otherwise (and server is exempting anyway, so reqd stays
        // off; this just keeps the form tidy).
        frm.toggle_display('bns_ewaybill_attachment', false);
        frm.toggle_display('bns_ewaybill_date', false);
      }
      if (anySupInv) frm.toggle_display('bns_supplier_invoice_attachment', false);
    }
  });
}

function _refreshEwaybillVisibility(frm) {
  _resolveBnsInternalSupplier(frm, function (internal) {
    if (internal) {
      frm.toggle_display('bns_ewaybill_attachment', false);
      frm.toggle_display('bns_ewaybill_date', false);
      frm.toggle_reqd('bns_ewaybill_attachment', false);
      frm.toggle_reqd('bns_ewaybill_date', false);
      return;
    }
    frappe.call({
      method: 'business_needed_solutions.business_needed_solutions.overrides.attachment_validation.check_ewaybill_applicability',
      args: {
        doctype: frm.doc.doctype,
        base_grand_total: frm.doc.base_grand_total || 0,
        update_stock: frm.doc.update_stock || 0,
        items_json: JSON.stringify((frm.doc.items || []).map(function (d) { return { item_code: d.item_code }; })),
        is_bns_internal_supplier: cint(frm.doc.is_bns_internal_supplier),
        supplier: frm.doc.supplier || '',
        gst_category: frm.doc.gst_category || '',
        posting_date: frm.doc.posting_date || '',
        mode_of_transport: frm.doc.bns_mode_of_transport || ''
      },
      callback: function (r) {
        if (!r || !r.message) return;

        var ewaybillRequired = r.message.required;
        var inDraft = frm.doc.docstatus === 0;
        frm.toggle_display('bns_ewaybill_attachment', ewaybillRequired);
        frm.toggle_display('bns_ewaybill_date', ewaybillRequired);
        frm.toggle_reqd('bns_ewaybill_attachment', ewaybillRequired && inDraft);
        frm.toggle_reqd('bns_ewaybill_date', ewaybillRequired && inDraft);

        if (ewaybillRequired && inDraft && frm.fields_dict.bns_ewaybill_attachment) {
          frm.fields_dict.bns_ewaybill_attachment.set_description(
            __('Required: Net total exceeds e-Waybill threshold of {0}',
              [frappe.format(r.message.threshold, { fieldtype: 'Currency' })])
          );
        }
      }
    });
  });
}

function _toggleBillFieldsReqd(frm, required) {
  // Only PI has bill_no/bill_date as standard fields; PR doesn't. Guard so
  // calling on PR is a no-op.
  if (!frm.fields_dict.bill_no || !frm.fields_dict.bill_date) return;
  var inDraft = frm.doc.docstatus === 0;
  frm.toggle_reqd('bill_no', required && inDraft);
  frm.toggle_reqd('bill_date', required && inDraft);
}

frappe.ui.form.on('Purchase Receipt', {
  refresh: function (frm) { setupPurchaseAttachmentFields(frm); },
  supplier: function (frm) { setupPurchaseAttachmentFields(frm); },
  is_bns_internal_supplier: function (frm) { setupPurchaseAttachmentFields(frm); },
  bns_mode_of_transport: function (frm) { _refreshEwaybillVisibility(frm); },
  gst_category: function (frm) { _refreshEwaybillVisibility(frm); },
  base_grand_total: function (frm) { _refreshEwaybillVisibility(frm); },
  items_remove: function (frm) { _refreshEwaybillVisibility(frm); }
});

frappe.ui.form.on('Purchase Receipt Item', {
  item_code: function (frm) { _refreshEwaybillVisibility(frm); }
});

frappe.ui.form.on('Purchase Invoice', {
  refresh: function (frm) { setupPurchaseAttachmentFields(frm); },
  supplier: function (frm) { setupPurchaseAttachmentFields(frm); },
  is_bns_internal_supplier: function (frm) { setupPurchaseAttachmentFields(frm); },
  bns_mode_of_transport: function (frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  gst_category: function (frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  base_grand_total: function (frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  update_stock: function (frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  items_remove: function (frm) { setupPurchaseAttachmentFields(frm); }
});

frappe.ui.form.on('Purchase Invoice Item', {
  item_code: function (frm) {
    if (!_isLinkedToPR(frm)) _refreshEwaybillVisibility(frm);
  },
  purchase_receipt: function (frm) { setupPurchaseAttachmentFields(frm); }
});
