// Copyright (c) 2026, Business Needed Solutions
// POD Dashboard — Proof of Delivery tracking for Sales Invoices

frappe.pages["pod-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("POD Dashboard"),
		single_column: true,
	});

	// ── Refresh button ───────────────────────────────────────────────
	page.add_inner_button(__("Refresh"), function () {
		if (page.pod_dashboard) page.pod_dashboard.refresh();
	});

	page.pod_dashboard = new PODDashboard(page);
	window.pod_dashboard = page.pod_dashboard;
};

frappe.pages["pod-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.page && wrapper.page.pod_dashboard) {
		wrapper.page.pod_dashboard.refresh();
	}
};

// ════════════════════════════════════════════════════════════════════
// PODDashboard Class
// ════════════════════════════════════════════════════════════════════

class PODDashboard {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);
		this.data = [];
		this.filters = {};
		this.init();
	}

	init() {
		this.render_layout();
		this.attach_styles();
		this.setup_filters();
		this.refresh();
	}

	get_filter_value(fieldname) {
		return this.filters && this.filters[fieldname] ? this.filters[fieldname].get_value() : null;
	}

	get_company() {
		return this.get_filter_value("company") || frappe.defaults.get_user_default("Company") || frappe.defaults.get_global_default("company");
	}

	get_from_date() {
		return this.get_filter_value("from_date");
	}

	get_to_date() {
		return this.get_filter_value("to_date");
	}

	get_customer() {
		return this.get_filter_value("customer");
	}

	get_gst_category() {
		return this.get_filter_value("gst_category");
	}

	get_pod_status() {
		return this.get_filter_value("pod_status");
	}

	// ── Layout ───────────────────────────────────────────────────────

	render_layout() {
		this.wrapper.html(`
			<div class="pod-dashboard-container">

				<!-- Summary Cards Row -->
				<div class="pod-summary-row" id="pod-summary-row">
					<div class="pod-metric-card" id="pod-pending-card">
						<div class="pod-metric-value" id="pod-pending-count">--</div>
						<div class="pod-metric-label">${__("Total Pending")}</div>
					</div>
					<div class="pod-metric-card" id="pod-status-card">
						<div class="pod-metric-value" id="pod-missing-status-count">--</div>
						<div class="pod-metric-label">${__("Missing Status")}</div>
					</div>
					<div class="pod-metric-card" id="pod-date-card">
						<div class="pod-metric-value" id="pod-missing-date-count">--</div>
						<div class="pod-metric-label">${__("Missing Date")}</div>
					</div>
					<div class="pod-metric-card" id="pod-attach-card">
						<div class="pod-metric-value" id="pod-missing-attach-count">--</div>
						<div class="pod-metric-label">${__("Missing Attachment")}</div>
					</div>
				</div>

				<!-- Filters Section Card -->
				<div class="pod-filters-card">
					<div class="pod-filters-header">
						<i class="fa fa-filter text-primary"></i>
						<span>${__("Filters")}</span>
					</div>
					<div class="row pod-filters-row" id="pod-filters-row">
						<!-- Loaded dynamically by setup_filters -->
					</div>
				</div>

				<!-- Main POD Table Section -->
				<div class="pod-section">
					<div class="pod-section-header">
						<i class="fa fa-truck text-primary"></i>
						<span>${__("Sales Invoices — Pending POD")}</span>
						<span class="pod-hint">${__("Fill POD details inline. Row disappears once all 3 fields are saved.")}</span>
					</div>
					<div id="pod-table-container">
						<div class="pod-loading">
							<span class="spinner-border spinner-border-sm"></span>
							${__("Loading…")}
						</div>
					</div>
				</div>

			</div>
		`);
	}

	// ── Setup Filters Panel ──────────────────────────────────────────

	setup_filters() {
		const self = this;
		this.filters = {};

		const filter_fields = [
			{
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				default: frappe.defaults.get_user_default("Company") || frappe.defaults.get_global_default("company")
			},
			{
				fieldname: "customer",
				label: __("Customer"),
				fieldtype: "Link",
				options: "Customer"
			},
			{
				fieldname: "gst_category",
				label: __("GST Category"),
				fieldtype: "Select",
				options: "\nRegistered Regular\nRegistered Composition\nUnregistered\nSEZ\nOverseas\nDeemed Export\nUIN Holders\nTax Deductor\nTax Collector\nInput Service Distributor"
			},
			{
				fieldname: "pod_status",
				label: __("POD Status"),
				fieldtype: "Select",
				options: "\nMissing\nDelivered\nIn-Transit\nIssue"
			},
			{
				fieldname: "from_date",
				label: __("From Date"),
				fieldtype: "Date",
				default: frappe.datetime.add_months(frappe.datetime.get_today(), -3)
			},
			{
				fieldname: "to_date",
				label: __("To Date"),
				fieldtype: "Date",
				default: frappe.datetime.get_today()
			}
		];

		const parent = this.wrapper.find("#pod-filters-row");
		parent.empty();

		filter_fields.forEach(df => {
			const col = $(`<div class="col-sm-2 pod-filter-col"></div>`).appendTo(parent);
			
			const control = frappe.ui.form.make_control({
				df: {
					fieldname: df.fieldname,
					label: df.label,
					fieldtype: df.fieldtype,
					options: df.options,
					render_input: true
				},
				parent: col,
				render_input: true
			});
			
			if (df.default) {
				control.set_value(df.default);
			}
			
			control.df.change = function() {
				self.refresh();
			};
			
			self.filters[df.fieldname] = control;
		});
	}

	// ── Refresh / Data Load ──────────────────────────────────────────

	refresh() {
		const self = this;
		const container = this.wrapper.find("#pod-table-container");
		container.html(`
			<div class="pod-loading">
				<span class="spinner-border spinner-border-sm"></span>
				${__("Loading…")}
			</div>
		`);

		frappe.call({
			method: "business_needed_solutions.business_needed_solutions.page.pod_dashboard.pod_dashboard.get_pending_pod_invoices",
			args: {
				company: this.get_company(),
				from_date: this.get_from_date(),
				to_date: this.get_to_date(),
				customer: this.get_customer(),
				gst_category: this.get_gst_category(),
				pod_status: this.get_pod_status(),
			},
			callback: function (r) {
				if (r && r.message) {
					self.data = r.message.invoices || [];
					self.render_summary();
					self.render_table(self.data, container);
				} else {
					container.html(`<div class="pod-empty">${__("No data returned.")}</div>`);
				}
			},
			error: function () {
				container.html(`<div class="pod-empty text-danger">${__("Error loading data. Check permissions.")}</div>`);
			},
		});
	}

	// ── Summary ──────────────────────────────────────────────────────

	render_summary() {
		const total = this.data.length;
		const missing_status = this.data.filter(d => !d.bns_pod_status).length;
		const missing_date = this.data.filter(d => !d.bns_pod_date).length;
		const missing_attach = this.data.filter(d => !d.bns_pod_attachment).length;

		this.wrapper.find("#pod-pending-count").text(total);
		this.wrapper.find("#pod-missing-status-count").text(missing_status);
		this.wrapper.find("#pod-missing-date-count").text(missing_date);
		this.wrapper.find("#pod-missing-attach-count").text(missing_attach);

		this.update_card_style(this.wrapper.find("#pod-pending-card"), total);
		this.update_card_style(this.wrapper.find("#pod-status-card"), missing_status);
		this.update_card_style(this.wrapper.find("#pod-date-card"), missing_date);
		this.update_card_style(this.wrapper.find("#pod-attach-card"), missing_attach);
	}

	update_card_style(card, count) {
		card.removeClass("pod-card-ok pod-card-warning pod-card-danger");
		if (count === 0) {
			card.addClass("pod-card-ok");
		} else if (count <= 20) {
			card.addClass("pod-card-warning");
		} else {
			card.addClass("pod-card-danger");
		}
	}

	// ── Table ────────────────────────────────────────────────────────

	render_table(invoices, container) {
		if (!invoices || invoices.length === 0) {
			container.html(`
				<div class="pod-empty">
					<i class="fa fa-check-circle text-success" style="font-size:2rem;"></i>
					<p>${__("All Sales Invoices have complete POD details. Great job!")}</p>
				</div>
			`);
			return;
		}

		let html = `
			<div class="pod-table-wrapper">
				<table class="table pod-table">
					<thead>
						<tr>
							<th style="width:140px">${__("Sales Invoice")}</th>
							<th>${__("Customer")}</th>
							<th style="width:150px">${__("GST Category")}</th>
							<th style="width:110px">${__("Date")}</th>
							<th style="width:115px">${__("Grand Total")}</th>
							<th style="width:150px">${__("POD Status")}</th>
							<th style="width:140px">${__("POD Date")}</th>
							<th style="width:220px">${__("POD Attachment")}</th>
							<th style="width:85px">${__("Action")}</th>
						</tr>
					</thead>
					<tbody id="pod-table-body">
		`;

		invoices.forEach((inv) => {
			const hasStatus = !!inv.bns_pod_status;
			const hasDate = !!inv.bns_pod_date;
			const hasAttachment = !!inv.bns_pod_attachment;

			const rowClass = "pod-row-pending";

			// GST Category Badge
			let gstBadge = "";
			if (inv.gst_category) {
				const isUnregistered = inv.gst_category === "Unregistered";
				gstBadge = `<span class="pod-gst-badge ${isUnregistered ? 'gst-unregistered' : 'gst-registered'}">${frappe.utils.escape_html(inv.gst_category)}</span>`;
			} else {
				gstBadge = `<span class="text-muted" style="font-size:0.75rem;">—</span>`;
			}

			const escName = frappe.utils.escape_html(inv.name);
			const escCustomer = frappe.utils.escape_html(inv.customer || "");
			const escDate = frappe.utils.escape_html(inv.posting_date || "");
			const grandTotal = format_currency(inv.grand_total, inv.currency);
			const currentAttach = frappe.utils.escape_html(inv.bns_pod_attachment || "");
			const currentStatus = frappe.utils.escape_html(inv.bns_pod_status || "");
			const currentDate = frappe.utils.escape_html(inv.bns_pod_date || "");

			html += `
				<tr class="${rowClass}" data-name="${escName}">
					<td>
						<a href="/app/sales-invoice/${escName}" target="_blank" class="pod-si-link">
							${escName}
						</a>
					</td>
					<td>
						<div class="pod-customer-cell">
							<span class="customer-name">${escCustomer}</span>
						</div>
					</td>
					<td>${gstBadge}</td>
					<td><span class="text-muted">${escDate}</span></td>
					<td><span class="pod-total-amount">${grandTotal}</span></td>
					<td>
						<div class="pod-field-wrap">
							<select class="form-control form-control-sm pod-status-input ${hasStatus ? 'pod-input-filled' : 'pod-input-missing'}" data-name="${escName}">
								<option value="">— ${__("Select")} —</option>
								<option value="Delivered" ${currentStatus === "Delivered" ? "selected" : ""}>${__("Delivered")}</option>
								<option value="In-Transit" ${currentStatus === "In-Transit" ? "selected" : ""}>${__("In-Transit")}</option>
								<option value="Issue" ${currentStatus === "Issue" ? "selected" : ""}>${__("Issue")}</option>
							</select>
						</div>
					</td>
					<td>
						<div class="pod-field-wrap">
							<input type="date" class="form-control form-control-sm pod-date-input ${hasDate ? 'pod-input-filled' : 'pod-input-missing'}"
								data-name="${escName}"
								value="${currentDate}">
						</div>
					</td>
					<td>
						<div class="pod-field-wrap">
							<div class="pod-attach-wrap" data-name="${escName}">
								<input type="text" class="form-control form-control-sm pod-attach-input ${hasAttachment ? 'pod-input-filled' : 'pod-input-missing'}"
									data-name="${escName}"
									value="${currentAttach}"
									placeholder="${__("Attachment URL")}">
								<button class="btn btn-default btn-xs pod-attach-btn" data-name="${escName}"
									title="${__("Upload File")}">
									<i class="fa fa-upload"></i>
								</button>
							</div>
						</div>
					</td>
					<td>
						<button class="btn btn-primary btn-xs btn-pod-save" data-name="${escName}">
							${__("Save")}
						</button>
					</td>
				</tr>
			`;
		});

		html += `</tbody></table></div>`;
		container.html(html);

		this.bind_events(container);
	}

	// ── Event Binding with delegation ────────────────────────────────

	bind_events(container) {
		const self = this;

		// File Upload Button
		container.off("click", ".pod-attach-btn").on("click", ".pod-attach-btn", function () {
			const siName = $(this).data("name");
			const row = container.find(`tr[data-name="${siName}"]`);
			const input = row.find(".pod-attach-input");

			new frappe.ui.FileUploader({
				doctype: "Sales Invoice",
				docname: siName,
				frm: null,
				on_success: function (file_doc) {
					const url = file_doc.file_url;
					input.val(url);
					self.toggle_input_style(input, true);
					frappe.show_alert({
						message: __("File uploaded: {0}", [file_doc.file_name]),
						indicator: "blue",
					});
				},
			});
		});

		// Save Button
		container.off("click", ".btn-pod-save").on("click", ".btn-pod-save", function () {
			const siName = $(this).data("name");
			self.save_pod_row(siName, container, $(this));
		});

		// Update style on input changes
		container.off("change", ".pod-status-input").on("change", ".pod-status-input", function () {
			self.toggle_input_style($(this), !!$(this).val());
		});

		container.off("change", ".pod-date-input").on("change", ".pod-date-input", function () {
			self.toggle_input_style($(this), !!$(this).val());
		});

		container.off("input change", ".pod-attach-input").on("input change", ".pod-attach-input", function () {
			self.toggle_input_style($(this), !!$(this).val().trim());
		});
	}

	// ── Save Row ─────────────────────────────────────────────────────

	save_pod_row(siName, container, btn) {
		const self = this;
		const row = container.find(`tr[data-name="${siName}"]`);

		const pod_status = row.find(".pod-status-input").val();
		const pod_date = row.find(".pod-date-input").val();
		const pod_attachment = row.find(".pod-attach-input").val().trim();

		// Client-side validation — all 3 must be filled to save
		if (!pod_status && !pod_date && !pod_attachment) {
			frappe.show_alert({
				message: __("Please fill at least one POD field before saving."),
				indicator: "orange",
			});
			return;
		}

		btn.prop("disabled", true).html(`<span class="spinner-border spinner-border-sm"></span>`);

		frappe.call({
			method: "business_needed_solutions.business_needed_solutions.page.pod_dashboard.pod_dashboard.save_pod_details",
			args: {
				sales_invoice: siName,
				pod_status: pod_status,
				pod_date: pod_date,
				pod_attachment: pod_attachment,
			},
			callback: function (r) {
				btn.prop("disabled", false).html(__("Save"));
				if (r && r.message && r.message.success) {
					if (r.message.all_filled) {
						// All 3 fields filled — remove row with animation
						frappe.show_alert({
							message: __("POD details saved. Invoice removed from pending list."),
							indicator: "green",
						});
						
						// Remove item from local data array
						self.data = self.data.filter(d => d.name !== siName);

						row.css("transition", "all 0.5s").css("opacity", "0").css("background-color", "#d4edda");
						setTimeout(function () {
							row.remove();
							self.render_summary();
							if (self.data.length === 0) {
								self.render_table([], container);
							}
						}, 500);
					} else {
						// Partial save — update inputs and classes
						frappe.show_alert({
							message: __("POD details saved. Fill remaining fields to complete."),
							indicator: "blue",
						});
						
						// Update local data
						const item = self.data.find(d => d.name === siName);
						if (item) {
							item.bns_pod_status = pod_status;
							item.bns_pod_date = pod_date;
							item.bns_pod_attachment = pod_attachment;
						}

						self.refresh_row_inputs(row, pod_status, pod_date, pod_attachment);
						self.render_summary();
					}
				} else {
					frappe.show_alert({
						message: __("Failed to save. Please try again."),
						indicator: "red",
					});
				}
			},
			error: function () {
				btn.prop("disabled", false).html(__("Save"));
				frappe.show_alert({
					message: __("Error saving POD details. Check your permissions."),
					indicator: "red",
				});
			},
		});
	}

	// ── Update inputs in place after partial save ────────────────────

	refresh_row_inputs(row, pod_status, pod_date, pod_attachment) {
		const statusInput = row.find(".pod-status-input");
		const dateInput = row.find(".pod-date-input");
		const attachInput = row.find(".pod-attach-input");

		statusInput.val(pod_status || "");
		dateInput.val(pod_date || "");
		attachInput.val(pod_attachment || "");

		this.toggle_input_style(statusInput, !!pod_status);
		this.toggle_input_style(dateInput, !!pod_date);
		this.toggle_input_style(attachInput, !!pod_attachment);
	}

	toggle_input_style(input, is_filled) {
		if (is_filled) {
			input.removeClass("pod-input-missing").addClass("pod-input-filled");
		} else {
			input.removeClass("pod-input-filled").addClass("pod-input-missing");
		}
	}

	// ── CSS Styles ───────────────────────────────────────────────────

	attach_styles() {
		if ($("#pod-dashboard-styles").length) return;

		$("head").append(`
			<style id="pod-dashboard-styles">

			/* ─── Container ─────────────────────────────────────────── */
			.pod-dashboard-container {
				padding: 20px 24px;
				font-family: var(--font-stack, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif);
				background-color: #f8fafc;
				min-height: 100vh;
			}

			/* ─── Summary Cards ─────────────────────────────────────── */
			.pod-summary-row {
				display: grid;
				grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
				gap: 20px;
				margin-bottom: 24px;
			}
			.pod-metric-card {
				background: #ffffff;
				border: 1px solid #e2e8f0;
				border-radius: 12px;
				padding: 20px 24px;
				text-align: center;
				box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
				transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
				border-left: 6px solid #e2e8f0;
			}
			.pod-metric-card:hover {
				transform: translateY(-2px);
				box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
			}
			.pod-metric-card.pod-card-ok      { border-left-color: #10b981; }
			.pod-metric-card.pod-card-warning { border-left-color: #f59e0b; }
			.pod-metric-card.pod-card-danger  { border-left-color: #ef4444; }
			
			.pod-metric-value {
				font-size: 2.25rem;
				font-weight: 800;
				color: #1e293b;
				line-height: 1.2;
			}
			.pod-metric-label {
				font-size: 0.875rem;
				color: #64748b;
				margin-top: 6px;
				font-weight: 600;
			}

			/* ─── Filters Section ───────────────────────────────────── */
			.pod-filters-card {
				background: #ffffff;
				border: 1px solid #e2e8f0;
				border-radius: 12px;
				padding: 20px 24px;
				margin-bottom: 24px;
				box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
			}
			.pod-filters-header {
				font-size: 1rem;
				font-weight: 700;
				color: #1e293b;
				margin-bottom: 16px;
				display: flex;
				align-items: center;
				gap: 8px;
			}
			.pod-filters-row {
				margin-left: -8px;
				margin-right: -8px;
			}
			.pod-filter-col {
				padding-left: 8px;
				padding-right: 8px;
				margin-bottom: 12px;
			}
			.pod-filter-col .frappe-control {
				margin-bottom: 0px !important;
			}
			.pod-filter-col label {
				font-size: 0.75rem !important;
				font-weight: 600 !important;
				color: #475569 !important;
				margin-bottom: 4px !important;
			}

			/* ─── Main Section ──────────────────────────────────────── */
			.pod-section {
				background: #ffffff;
				border: 1px solid #e2e8f0;
				border-radius: 12px;
				box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
				overflow: hidden;
			}
			.pod-section-header {
				background: #f8fafc;
				padding: 16px 24px;
				font-weight: 700;
				font-size: 1.05rem;
				color: #1e293b;
				border-bottom: 1px solid #e2e8f0;
				display: flex;
				align-items: center;
				gap: 8px;
			}
			.pod-hint {
				font-weight: 500;
				font-size: 0.8rem;
				color: #94a3b8;
				margin-left: auto;
			}

			/* ─── Table ─────────────────────────────────────────────── */
			.pod-table-wrapper {
				max-height: calc(100vh - 360px);
				overflow-y: auto;
			}
			.pod-table {
				margin: 0;
				font-size: 0.875rem;
				border-collapse: separate;
				border-spacing: 0;
				width: 100%;
			}
			.pod-table thead th {
				background: #f8fafc;
				font-weight: 700;
				font-size: 0.75rem;
				color: #475569;
				text-transform: uppercase;
				letter-spacing: 0.05em;
				white-space: nowrap;
				padding: 12px 16px;
				border-bottom: 2px solid #e2e8f0;
				position: sticky;
				top: 0;
				z-index: 10;
				box-shadow: inset 0 -1px 0 #e2e8f0;
			}
			.pod-table td {
				vertical-align: middle;
				padding: 12px 16px;
				border-bottom: 1px solid #f1f5f9;
				background-color: #ffffff;
			}
			.pod-row-pending:hover td {
				background-color: #f8fafc;
			}

			/* ─── SI Link ───────────────────────────────────────────── */
			.pod-si-link {
				font-weight: 700;
				color: var(--primary-color, #1f6bff);
				text-decoration: none;
			}
			.pod-si-link:hover {
				text-decoration: underline;
			}

			/* ─── GST Badge ─────────────────────────────────────────── */
			.pod-gst-badge {
				display: inline-block;
				padding: 2px 8px;
				border-radius: 9999px;
				font-size: 0.75rem;
				font-weight: 600;
			}
			.gst-registered {
				background-color: #dcfce7;
				color: #166534;
			}
			.gst-unregistered {
				background-color: #f1f5f9;
				color: #475569;
			}

			/* ─── Inputs ────────────────────────────────────────────── */
			.pod-field-wrap {
				display: flex;
				flex-direction: column;
				gap: 4px;
			}
			.pod-status-input,
			.pod-date-input,
			.pod-attach-input {
				height: 32px !important;
				font-size: 0.8125rem !important;
				border-radius: 6px !important;
				transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
			}
			.pod-input-missing {
				border: 1px solid #fecdd3 !important;
				background-color: #fff1f2 !important;
			}
			.pod-input-filled {
				border: 1px solid #cbd5e1 !important;
				background-color: #ffffff !important;
			}
			.pod-input-missing:focus,
			.pod-input-filled:focus {
				border-color: #a5b4fc !important;
				box-shadow: 0 0 0 2px rgba(165, 180, 252, 0.2) !important;
				outline: 0;
			}
			.pod-attach-wrap {
				display: flex;
				gap: 6px;
				align-items: center;
			}
			.pod-attach-wrap .pod-attach-input {
				flex: 1;
				min-width: 0;
			}
			.pod-attach-btn {
				flex-shrink: 0;
				height: 32px;
				width: 32px;
				padding: 0 !important;
				display: flex;
				align-items: center;
				justify-content: center;
				border-radius: 6px !important;
				background-color: #f1f5f9;
				border: 1px solid #cbd5e1;
				color: #475569;
			}
			.pod-attach-btn:hover {
				background-color: #e2e8f0;
				color: #0f172a;
			}
			
			.btn-pod-save {
				height: 32px;
				padding: 0 12px !important;
				font-weight: 600;
				border-radius: 6px !important;
			}

			/* ─── Empty / Loading ───────────────────────────────────── */
			.pod-loading, .pod-empty {
				text-align: center;
				color: #64748b;
				padding: 48px 24px;
				font-size: 0.95rem;
				font-weight: 500;
			}
			.pod-empty i {
				display: block;
				margin-bottom: 12px;
			}

			</style>
		`);
	}
}
