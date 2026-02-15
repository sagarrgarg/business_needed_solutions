// Copyright (c) 2025, Business Needed Solutions and contributors
// For license information, please see license.txt

/* eslint-disable camelcase */
/* global frappe */

const BNS_SETTINGS_METHOD = 'business_needed_solutions.business_needed_solutions.doctype.bns_settings.bns_settings';

frappe.ui.form.on('BNS Settings', {
	refresh: function (frm) {
		addAddressTools(frm);
		addLocationTools(frm);
		addActionTools(frm);
	}
});

// --- Address tools ---
function addAddressTools(frm) {
	frm.add_custom_button(__('Clear Preferred Flags from All Addresses'), function () {
		frappe.confirm(
			__('This will set is_primary_address and is_shipping_address to 0 on ALL Address records. Use this to clean past data when suppressing preferred billing/shipping. Continue?'),
			function () {
				frappe.call({
					method: BNS_SETTINGS_METHOD + '.clear_preferred_flags_from_all_addresses',
					freeze: true,
					freeze_message: __('Clearing preferred flags...'),
					callback: function (r) {
						if (!r.exc && r.message) {
							frappe.msgprint({ title: __('Done'), message: r.message.message, indicator: 'green' });
						}
					}
				});
			}
		);
	}, __('Address'));
}

// --- Location tools ---
function addLocationTools(frm) {
	frm.add_custom_button(__('Backfill Billing & Dispatch Location'), function () {
		frappe.call({
			method: BNS_SETTINGS_METHOD + '.backfill_billing_and_dispatch_location',
			args: { dry_run: 1 },
			freeze: true,
			freeze_message: __('Preview...'),
			callback: function (r) {
				if (r.exc) return;
				const data = r.message;
				if (!data.success) {
					frappe.msgprint({ title: __('Error'), message: data.message, indicator: 'red' });
					return;
				}
				const total = data.total || 0;
				if (total === 0) {
					frappe.msgprint({ title: __('Preview'), message: data.message, indicator: 'blue' });
					return;
				}
				frappe.confirm(data.message + '<br><br>' + __('Apply these updates?'), function () {
					frappe.call({
						method: BNS_SETTINGS_METHOD + '.backfill_billing_and_dispatch_location',
						args: { dry_run: 0 },
						freeze: true,
						freeze_message: __('Updating...'),
						callback: function (r2) {
							if (!r2.exc && r2.message && r2.message.success) {
								frappe.msgprint({ title: __('Done'), message: r2.message.message, indicator: 'green' });
							}
						}
					});
				});
			}
		});
	}, __('Location'));
}

// --- Action tools ---
function addActionTools(frm) {
	frm.add_custom_button(__('Apply List View Settings'), function () {
		frm.call({
			doc: frm.doc,
			method: 'apply_settings',
			freeze: true,
			freeze_message: __('Applying Settings...'),
			callback: function (r) {
				if (r.message) {
					frappe.show_alert({ message: __('Settings Applied Successfully'), indicator: 'green' });
				}
			}
		});
	}, __('Actions'));

	frm.add_custom_button(__('Run FIFO Reconciliation'), function () {
		showFifoReconciliationDialog(frm);
	}, __('Actions'));
}

// --- FIFO Reconciliation dialog ---
function showFifoReconciliationDialog(frm) {
	let previewData = null;

	const fields = [
		{ label: __('Company'), fieldname: 'company', fieldtype: 'Link', options: 'Company', reqd: 1, default: frappe.defaults.get_user_default('Company') },
		{ label: __('Include Future Payments'), fieldname: 'include_future_payments', fieldtype: 'Check', default: frm.doc.include_future_payments_in_reconciliation || 1, description: __('Include payments dated after today when reconciling') },
		{ fieldtype: 'Column Break' },
		{ label: __('Party Type'), fieldname: 'party_type', fieldtype: 'Select', options: '\nCustomer\nSupplier', description: __('Leave blank to process all party types') },
		{ label: __('Party'), fieldname: 'party', fieldtype: 'Dynamic Link', options: 'party_type', depends_on: 'party_type', description: __('Leave blank to process all parties') },
		{ fieldtype: 'Section Break', label: __('Batch Control') },
		{ label: __('Batch Size'), fieldname: 'batch_size', fieldtype: 'Int', default: frm.doc.reconciliation_batch_size || 100, description: __('Maximum allocations per run (0 = unlimited). Lower values reduce system load.') },
		{ fieldtype: 'Section Break', label: __('Preview') },
		{ fieldtype: 'HTML', fieldname: 'preview_html', options: '<div id="reconcile-preview" style="padding: 10px; background: #f5f5f5; border-radius: 4px; min-height: 100px;"><p style="text-align: center; color: #666;">Click "Preview" to see what would be reconciled</p></div>' }
	];

	function updatePreview(dialog) {
		const values = dialog.get_values();
		if (!values.company) {
			frappe.msgprint(__('Please select a Company'));
			return;
		}
		let party_types = ['Customer', 'Supplier'];
		let specific_party = null;
		let specific_party_type = null;
		if (values.party_type) {
			party_types = [values.party_type];
			specific_party_type = values.party_type;
			if (values.party) specific_party = values.party;
		}
		frappe.call({
			method: 'business_needed_solutions.business_needed_solutions.auto_payment_reconcile.reconcile_all_parties',
			args: {
				company: values.company,
				include_future_payments: values.include_future_payments ? 1 : 0,
				dry_run: 1,
				party_types,
				specific_party,
				specific_party_type,
				batch_size: values.batch_size || 0
			},
			freeze: true,
			freeze_message: __('Analyzing reconciliation...'),
			callback: function (r) {
				if (r.exc) return;
				if (r.message) {
					previewData = r.message;
					const summary = r.message.summary;
					const hasMore = summary.has_more ? `<span style="color: #856404; background: #fff3cd; padding: 2px 6px; border-radius: 3px; font-size: 11px;">${__('More pending')}</span>` : '';
					const html = `
						<div style="padding: 15px; background: #fff; border-radius: 4px;">
							<h4 style="margin-top: 0;">${__('Reconciliation Preview:')} ${hasMore}</h4>
							<table style="width: 100%; border-collapse: collapse;">
								<tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Parties Processed')}:</strong></td><td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">${summary.total_parties || 0}</td></tr>
								<tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Parties with Matches')}:</strong></td><td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right; color: green;">${summary.reconciled || 0}</td></tr>
								<tr style="background: #f0f8ff;"><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Total Allocations')}:</strong></td><td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right; font-weight: bold; color: #0066cc;">${summary.total_allocations || 0}</td></tr>
								<tr><td style="padding: 8px; border-bottom: 1px solid #ddd;"><strong>${__('Skipped (no matches)')}:</strong></td><td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right; color: orange;">${summary.skipped || 0}</td></tr>
								<tr><td style="padding: 8px;"><strong>${__('Errors')}:</strong></td><td style="padding: 8px; text-align: right; color: red;">${summary.errors || 0}</td></tr>
							</table>
							${summary.has_more ? '<p style="margin: 10px 0 0; color: #856404; font-size: 12px;"><i class="fa fa-info-circle"></i> ' + __('Batch limit reached. Run again to process more.') + '</p>' : ''}
						</div>
					`;
					dialog.fields_dict.preview_html.$wrapper.html(html);
					frappe.show_alert({
						message: summary.total_allocations === 0 ? __('No allocations to make') : __('Found {0} allocations across {1} parties', [summary.total_allocations, summary.reconciled]),
						indicator: summary.total_allocations === 0 ? 'orange' : 'blue'
					});
				}
			}
		});
	}

	const d = new frappe.ui.Dialog({
		title: __('Run FIFO Payment Reconciliation'),
		fields,
		size: 'large',
		primary_action_label: __('Reconcile'),
		primary_action: function (values) {
			if (!values.company) {
				frappe.msgprint(__('Please select a Company'));
				return;
			}
			if (!previewData || !previewData.summary || previewData.summary.total_allocations === 0) {
				frappe.msgprint({ title: __('No Allocations'), message: __('Please preview first. No allocations found to make.'), indicator: 'orange' });
				return;
			}
			let party_types = ['Customer', 'Supplier'];
			let specific_party = null;
			let specific_party_type = null;
			if (values.party_type) {
				party_types = [values.party_type];
				specific_party_type = values.party_type;
				if (values.party) specific_party = values.party;
			}
			const confirmMsg = __('Are you sure you want to make {0} allocations across {1} parties? This will match payments to invoices using FIFO logic.', [previewData.summary.total_allocations, previewData.summary.reconciled]);
			frappe.confirm(confirmMsg, function () {
				frappe.call({
					method: 'business_needed_solutions.business_needed_solutions.auto_payment_reconcile.reconcile_all_parties',
					args: {
						company: values.company,
						include_future_payments: values.include_future_payments ? 1 : 0,
						dry_run: 0,
						party_types,
						specific_party,
						specific_party_type,
						batch_size: values.batch_size || 0
					},
					freeze: true,
					freeze_message: __('Reconciling payments...'),
					callback: function (r) {
						if (!r.exc && r.message) {
							const summary = r.message.summary;
							let msg = __('Allocations: {0}<br>Parties: {1}<br>Errors: {2}', [summary.total_allocations, summary.reconciled, summary.errors]);
							if (summary.has_more) msg += '<br><br><em>' + __('More entries pending. Run again to continue.') + '</em>';
							frappe.msgprint({ title: __('Reconciliation Complete'), message: msg, indicator: summary.errors > 0 ? 'orange' : 'green' });
							frm.reload_doc();
							d.hide();
						}
					},
					error: function () {
						frappe.msgprint({ title: __('Error'), message: __('Reconciliation failed. Check browser console.'), indicator: 'red' });
					}
				});
			});
		},
		secondary_action_label: __('Preview'),
		secondary_action: function (values) { updatePreview(d); }
	});

	d.show();
	setTimeout(function () {
		if (d.fields_dict.company && d.fields_dict.company.get_value()) updatePreview(d);
	}, 500);
}
