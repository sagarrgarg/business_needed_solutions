frappe.ui.form.on('BNS Branch Accounting Settings', {
  refresh: function(frm) {
    frm.add_custom_button(__('Bulk Convert to BNS Internal'), function() {
      let previewData = null;

      const fields = [
        {
          label: __('From Date'),
          fieldname: 'from_date',
          fieldtype: 'Date',
          reqd: 1,
          default: frappe.datetime.add_months(frappe.datetime.get_today(), -1)
        },
        {
          fieldtype: 'Column Break'
        },
        {
          label: __('Force Update'),
          fieldname: 'force',
          fieldtype: 'Check',
          default: 0,
          description: __('Update even if is_bns_internal_customer/supplier is already ticked')
        },
        {
          fieldtype: 'Section Break',
          label: __('Preview')
        },
        {
          fieldtype: 'HTML',
          fieldname: 'preview_html',
          options: '<div id="preview-content" style="padding: 10px; background: #f0f0f0; border-radius: 4px; min-height: 100px;">' +
                   '<p style="text-align: center; color: #666;">Click "Preview" to see counts</p></div>'
        }
      ];

      const updatePreview = function(dialog) {
        const values = dialog.get_values();
        if (!values.from_date) {
          return;
        }

        frappe.call({
          method: 'business_needed_solutions.bns_branch_accounting.utils.get_bulk_conversion_preview',
          args: {
            from_date: values.from_date,
            force: values.force ? 1 : 0
          },
          freeze: true,
          freeze_message: __('Getting preview...'),
          callback: function(r) {
            if (!r.exc && r.message) {
              previewData = r.message;
              const preview = r.message;
              const previewHtml = `
                <div style="padding: 15px; background: #fff; border-radius: 4px;">
                  <h4 style="margin-top: 0;">${__('Documents to be converted:')}</h4>
                  <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Sales Invoice')}:</strong></td>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">${preview.sales_invoice_count || 0}</td>
                    </tr>
                    <tr>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Purchase Invoice')}:</strong></td>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">${preview.purchase_invoice_count || 0}</td>
                    </tr>
                    <tr>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Delivery Note')}:</strong></td>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">${preview.delivery_note_count || 0}</td>
                    </tr>
                    <tr>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Purchase Receipt')}:</strong></td>
                      <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">${preview.purchase_receipt_count || 0}</td>
                    </tr>
                    <tr style="background: #f9f9f9;">
                      <td style="padding: 8px;"><strong>${__('Total')}:</strong></td>
                      <td style="padding: 8px; text-align: right;"><strong>${preview.total_count || 0}</strong></td>
                    </tr>
                  </table>
                </div>
              `;

              dialog.fields_dict.preview_html.$wrapper.html(previewHtml);

              if (preview.total_count === 0) {
                frappe.show_alert({
                  message: __('No documents found to convert'),
                  indicator: 'orange'
                });
              } else {
                frappe.show_alert({
                  message: __('Preview updated. Found {0} document(s) to convert', preview.total_count),
                  indicator: 'blue'
                });
              }
            }
          }
        });
      };

      const d = new frappe.ui.Dialog({
        title: __('Bulk Convert to BNS Internal'),
        fields: fields,
        primary_action_label: __('Convert'),
        primary_action(values) {
          if (!values.from_date) {
            frappe.msgprint({
              title: __('Validation Error'),
              message: __('From Date is required'),
              indicator: 'red'
            });
            return;
          }

          if (!previewData || !previewData.total_count || previewData.total_count === 0) {
            frappe.msgprint({
              title: __('No Documents'),
              message: __('Please preview first. No documents found to convert.'),
              indicator: 'orange'
            });
            return;
          }

          const totalCount = previewData.total_count || 0;

          frappe.confirm(
            __('Are you sure you want to convert {0} document(s) to BNS Internally Transferred?', totalCount),
            function() {
              frappe.call({
                method: 'business_needed_solutions.bns_branch_accounting.utils.bulk_convert_to_bns_internal',
                args: {
                  from_date: values.from_date,
                  force: values.force ? 1 : 0
                },
                freeze: true,
                freeze_message: __('Converting documents...'),
                callback: function(r) {
                  if (!r.exc) {
                    frappe.show_alert({
                      message: r.message.message || __('Conversion completed successfully'),
                      indicator: 'green'
                    });
                    d.hide();
                  }
                }
              });
            }
          );
        },
        secondary_action_label: __('Preview'),
        secondary_action(values) {
          updatePreview(d);
        }
      });

      d.onhide = function() {
        previewData = null;
      };

      d.show();

      setTimeout(function() {
        if (d.fields_dict.from_date) {
          d.fields_dict.from_date.$input.on('change', function() {
            if (d.fields_dict.from_date.get_value()) {
              updatePreview(d);
            }
          });
        }

        if (d.fields_dict.force) {
          d.fields_dict.force.$input.on('change', function() {
            if (d.fields_dict.from_date && d.fields_dict.from_date.get_value()) {
              updatePreview(d);
            }
          });
        }
      }, 100);
    }, __('Actions'));
  }
});
