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

    frm.add_custom_button(__('Verify & Repost Internal Transfers'), function() {
      const cutoffDate = frm.doc.internal_validation_cutoff_date;
      let lastVerifyData = null;

      const escapeCsvField = function(val) {
        if (val == null) return '';
        const str = String(val);
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
          return '"' + str.replace(/"/g, '""') + '"';
        }
        return str;
      };

      const downloadReport = function() {
        if (!lastVerifyData) {
          frappe.msgprint(__('No verification data available. Run Verify first.'));
          return;
        }
        const rows = [];
        rows.push(['Category', 'Chain Type', 'Delivery Note', 'Sales Invoice',
          'Purchase Receipt', 'Purchase Invoice', 'Issues / Reason'].join(','));

        for (const c of (lastVerifyData.partially_linked || [])) {
          rows.push([
            escapeCsvField('Partially Linked'),
            escapeCsvField(c.chain_type),
            escapeCsvField(c.docs.dn || ''),
            escapeCsvField(c.docs.si || ''),
            escapeCsvField(c.docs.pr || ''),
            escapeCsvField(c.docs.pi || ''),
            escapeCsvField((c.issues || []).join('; '))
          ].join(','));
        }

        for (const c of (lastVerifyData.unlinked || [])) {
          rows.push([
            escapeCsvField('Unlinked'),
            escapeCsvField(c.chain_type),
            escapeCsvField(c.docs.dn || ''),
            escapeCsvField(c.docs.si || ''),
            escapeCsvField(c.docs.pr || ''),
            escapeCsvField(c.docs.pi || ''),
            escapeCsvField((c.issues || []).join('; '))
          ].join(','));
        }

        for (const f of (lastVerifyData.fix_results || [])) {
          let category = 'Fix: ' + (f.action || 'unknown');
          if (f.action === 'fixed') category = 'DN→PR Fixed';
          else if (f.action === 'skipped') category = 'DN→PR Skipped';
          else if (f.action === 'error') category = 'DN→PR Error';
          rows.push([
            escapeCsvField(category),
            escapeCsvField('DN->PR'),
            escapeCsvField(f.dn || ''),
            escapeCsvField(''),
            escapeCsvField(f.pr || ''),
            escapeCsvField(''),
            escapeCsvField(f.reason || '')
          ].join(','));
        }

        const csvContent = '\uFEFF' + rows.join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const cutoff = (lastVerifyData.summary && lastVerifyData.summary.cutoff_date) || 'report';
        a.href = url;
        a.download = 'internal_transfer_verify_' + cutoff + '.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      };

      const fields = [
        {
          label: __('Cutoff Date'),
          fieldname: 'cutoff_date',
          fieldtype: 'Date',
          reqd: 1,
          default: cutoffDate || frappe.datetime.add_months(frappe.datetime.get_today(), -3),
          description: __('Verify and repost all internal transfers on or after this date')
        },
        {
          fieldtype: 'Column Break'
        },
        {
          label: __('Repost Fully Linked'),
          fieldname: 'repost',
          fieldtype: 'Check',
          default: 1,
          description: __('Create Repost Item Valuation entries for all fully-linked chains')
        },
        {
          fieldtype: 'Section Break',
          label: __('Fix Options')
        },
        {
          label: __('Fix Partial DN→PR'),
          fieldname: 'fix_partial_dn_pr',
          fieldtype: 'Check',
          default: 0,
          description: __('Attempt to fix partially linked DN→PR chains. Skips if item, rate, taxable amount, or warehouse mismatch is detected.')
        },
        {
          fieldtype: 'Section Break',
          label: __('Results')
        },
        {
          fieldtype: 'HTML',
          fieldname: 'results_html',
          options: '<div id="verify-results" style="padding: 10px; background: #f0f0f0; border-radius: 4px; min-height: 80px;">' +
                   '<p style="text-align: center; color: #666;">' + __('Click "Verify" to check linkage or "Run" to verify and repost') + '</p></div>'
        }
      ];

      const renderResults = function(dialog, data) {
        if (!data || !data.summary) return;
        lastVerifyData = data;
        const s = data.summary;
        let chainRows = '';
        for (const [chainType, counts] of Object.entries(s.chains_by_type || {})) {
          chainRows += `<tr>
            <td style="padding: 6px; border-bottom: 1px solid #ddd;">${chainType}</td>
            <td style="padding: 6px; border-bottom: 1px solid #ddd; text-align: right; color: green;">${counts.fully_linked || 0}</td>
            <td style="padding: 6px; border-bottom: 1px solid #ddd; text-align: right; color: orange;">${counts.partially_linked || 0}</td>
            <td style="padding: 6px; border-bottom: 1px solid #ddd; text-align: right; color: red;">${counts.unlinked || 0}</td>
          </tr>`;
        }

        let issuesList = '';
        if (data.partially_linked && data.partially_linked.length) {
          issuesList = '<h5 style="margin-top: 12px;">' + __('Partially Linked (needs attention):') + '</h5><ul style="max-height: 200px; overflow-y: auto;">';
          for (const c of data.partially_linked.slice(0, 20)) {
            const docLinks = Object.entries(c.docs).map(([k, v]) => `${k.toUpperCase()}: ${v}`).join(', ');
            const issueText = (c.issues || []).slice(0, 2).join('; ');
            issuesList += `<li><strong>${c.chain_type}</strong> (${docLinks}): ${issueText}</li>`;
          }
          if (data.partially_linked.length > 20) {
            issuesList += `<li>... and ${data.partially_linked.length - 20} more</li>`;
          }
          issuesList += '</ul>';
        }

        let fixSection = '';
        if (s.fix_partial_dn_pr && data.fix_results && data.fix_results.length) {
          const fixed = data.fix_results.filter(f => f.action === 'fixed');
          const skipped = data.fix_results.filter(f => f.action === 'skipped');
          const errored = data.fix_results.filter(f => f.action === 'error');

          fixSection = `<h5 style="margin-top: 12px;">${__('DN→PR Fix Results')}:
            <span style="color: green;">${fixed.length} ${__('fixed')}</span>,
            <span style="color: orange;">${skipped.length} ${__('skipped')}</span>,
            <span style="color: red;">${errored.length} ${__('errors')}</span>
          </h5>`;

          if (skipped.length) {
            fixSection += `<details style="margin-bottom: 8px;"><summary style="cursor: pointer; color: orange;">${__('Skipped')} (${skipped.length})</summary>`;
            fixSection += '<ul style="max-height: 200px; overflow-y: auto;">';
            for (const f of skipped.slice(0, 30)) {
              fixSection += `<li>DN: ${f.dn}, PR: ${f.pr} — ${f.reason}</li>`;
            }
            if (skipped.length > 30) {
              fixSection += `<li>... and ${skipped.length - 30} more</li>`;
            }
            fixSection += '</ul></details>';
          }

          if (fixed.length) {
            fixSection += `<details style="margin-bottom: 8px;"><summary style="cursor: pointer; color: green;">${__('Fixed')} (${fixed.length})</summary>`;
            fixSection += '<ul style="max-height: 150px; overflow-y: auto;">';
            for (const f of fixed.slice(0, 30)) {
              fixSection += `<li>DN: ${f.dn} ↔ PR: ${f.pr}</li>`;
            }
            if (fixed.length > 30) {
              fixSection += `<li>... and ${fixed.length - 30} more</li>`;
            }
            fixSection += '</ul></details>';
          }

          if (errored.length) {
            fixSection += `<details style="margin-bottom: 8px;"><summary style="cursor: pointer; color: red;">${__('Errors')} (${errored.length})</summary>`;
            fixSection += '<ul style="max-height: 150px; overflow-y: auto;">';
            for (const f of errored.slice(0, 20)) {
              fixSection += `<li>DN: ${f.dn}, PR: ${f.pr} — ${f.reason}</li>`;
            }
            fixSection += '</ul></details>';
          }
        }

        const html = `
          <div style="padding: 10px; background: #fff; border-radius: 4px;">
            <h4 style="margin-top: 0;">${__('Verification Summary')} (${__('Cutoff')}: ${s.cutoff_date})</h4>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 10px;">
              <thead><tr>
                <th style="padding: 6px; border-bottom: 2px solid #ddd; text-align: left;">${__('Chain Type')}</th>
                <th style="padding: 6px; border-bottom: 2px solid #ddd; text-align: right;">${__('Linked')}</th>
                <th style="padding: 6px; border-bottom: 2px solid #ddd; text-align: right;">${__('Partial')}</th>
                <th style="padding: 6px; border-bottom: 2px solid #ddd; text-align: right;">${__('Unlinked')}</th>
              </tr></thead>
              <tbody>${chainRows}</tbody>
              <tfoot><tr style="background: #f9f9f9; font-weight: bold;">
                <td style="padding: 6px;">${__('Total')}</td>
                <td style="padding: 6px; text-align: right; color: green;">${s.fully_linked}</td>
                <td style="padding: 6px; text-align: right; color: orange;">${s.partially_linked}</td>
                <td style="padding: 6px; text-align: right; color: red;">${s.unlinked}</td>
              </tr></tfoot>
            </table>
            ${s.repost_enabled ? '<p><strong>' + __('Reposted') + ':</strong> ' + s.reposted_count + ' ' + __('documents') +
              (s.repost_error_count ? ' (' + s.repost_error_count + ' ' + __('errors') + ')' : '') + '</p>' : ''}
            ${(s.partially_linked || s.unlinked || (data.fix_results && data.fix_results.length))
              ? '<div style="margin: 10px 0;"><button class="btn btn-xs btn-default btn-download-report">' +
                '<svg style="width:14px;height:14px;margin-right:4px;vertical-align:text-bottom;" viewBox="0 0 24 24"><path fill="currentColor" d="M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9Z"/></svg>' +
                __('Download Report') + '</button></div>'
              : ''}
            ${fixSection}
            ${issuesList}
          </div>`;
        dialog.fields_dict.results_html.$wrapper.html(html);
        dialog.fields_dict.results_html.$wrapper.find('.btn-download-report').on('click', function() {
          downloadReport();
        });
      };

      const d = new frappe.ui.Dialog({
        title: __('Verify & Repost Internal Transfers'),
        fields: fields,
        size: 'large',
        primary_action_label: __('Run'),
        primary_action(values) {
          if (!values.cutoff_date) {
            frappe.msgprint(__('Cutoff Date is required'));
            return;
          }
          const actionParts = [values.cutoff_date];
          const actionDescs = [];
          if (values.repost) actionDescs.push(__('repost fully-linked ones'));
          if (values.fix_partial_dn_pr) actionDescs.push(__('fix partial DN→PR'));
          if (!actionDescs.length) actionDescs.push(__('report only'));

          frappe.confirm(
            __('This will verify all internal transfer chains from {0} and {1}. Continue?',
              [values.cutoff_date, actionDescs.join(', ')]),
            function() {
              frappe.call({
                method: 'business_needed_solutions.bns_branch_accounting.utils.enqueue_verify_and_repost_internal_transfers',
                args: {
                  cutoff_date: values.cutoff_date,
                  repost: values.repost ? 1 : 0,
                  fix_partial_dn_pr: values.fix_partial_dn_pr ? 1 : 0
                },
                freeze: true,
                freeze_message: __('Enqueuing background job...'),
                callback: function(r) {
                  if (!r.exc && r.message) {
                    frappe.show_alert({
                      message: r.message.message || __('Job enqueued successfully'),
                      indicator: 'green'
                    });
                    d.hide();
                  }
                }
              });
            }
          );
        },
        secondary_action_label: __('Verify'),
        secondary_action() {
          const values = d.get_values(true);
          if (!values || !values.cutoff_date) {
            frappe.msgprint(__('Cutoff Date is required'));
            return;
          }
          frappe.call({
            method: 'business_needed_solutions.bns_branch_accounting.utils.verify_and_repost_internal_transfers',
            args: {
              cutoff_date: values.cutoff_date,
              repost: 0,
              fix_partial_dn_pr: values.fix_partial_dn_pr ? 1 : 0
            },
            freeze: true,
            freeze_message: __('Verifying linkage...'),
            callback: function(r) {
              if (!r.exc && r.message) {
                renderResults(d, r.message);
                frappe.show_alert({
                  message: r.message.message || __('Verification complete'),
                  indicator: 'blue'
                });
              }
            }
          });
        }
      });

      d.show();
    }, __('Actions'));
  }
});
