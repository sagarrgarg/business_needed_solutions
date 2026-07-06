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
		this.in_filter_change = false;
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

	get_fiscal_year() {
		return this.get_filter_value("fiscal_year");
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
		this.in_filter_change = false;

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
				options: "\nRegistered Regular\nRegistered Composition\nSEZ\nOverseas\nDeemed Export\nUIN Holders\nTax Deductor\nTax Collector\nInput Service Distributor"
			},
			{
				fieldname: "pod_status",
				label: __("POD Status"),
				fieldtype: "Select",
				options: "\nMissing\nDelivered\nIn-Transit\nIssue"
			},
			{
				fieldname: "fiscal_year",
				label: __("Fiscal Year"),
				fieldtype: "Link",
				options: "Fiscal Year",
				default: frappe.defaults.get_user_default("fiscal_year") || frappe.defaults.get_global_default("fiscal_year")
			},
			{
				fieldname: "from_date",
				label: __("From Date"),
				fieldtype: "Date"
			},
			{
				fieldname: "to_date",
				label: __("To Date"),
				fieldtype: "Date"
			}
		];

		const parent = this.wrapper.find("#pod-filters-row");
		parent.empty();

		// Create all control inputs
		filter_fields.forEach(df => {
			const col = $(`<div class="pod-filter-col"></div>`).appendTo(parent);
			
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
			
			self.filters[df.fieldname] = control;
		});

		// Resolve initial values
		const default_fy = frappe.defaults.get_user_default("fiscal_year") || frappe.defaults.get_global_default("fiscal_year");
		const default_co = frappe.defaults.get_user_default("Company") || frappe.defaults.get_global_default("company");

		if (this.filters.company && default_co) {
			this.filters.company.set_value(default_co);
		}

		if (this.filters.fiscal_year && default_fy) {
			this.filters.fiscal_year.set_value(default_fy);
			
			// Resolve start & end date of default fiscal year asynchronously, then bind change handlers
			frappe.db.get_value("Fiscal Year", default_fy, ["year_start_date", "year_end_date"]).then(r => {
				if (r && r.message) {
					if (self.filters.from_date) {
						self.filters.from_date.set_value(r.message.year_start_date);
					}
					if (self.filters.to_date) {
						self.filters.to_date.set_value(r.message.year_end_date);
					}
				}
				self.bind_filter_events();
			});
		} else {
			this.bind_filter_events();
		}
	}

	// ── Bind Change Handlers to Filters ──────────────────────────────

	bind_filter_events() {
		const self = this;
		Object.entries(this.filters).forEach(([fieldname, control]) => {
			if (fieldname === "fiscal_year") {
				control.df.change = function() {
					const val = control.get_value();
					if (val) {
						self.in_filter_change = true;
						frappe.db.get_value("Fiscal Year", val, ["year_start_date", "year_end_date"]).then(r => {
							if (r && r.message) {
								if (self.filters.from_date) {
									self.filters.from_date.set_value(r.message.year_start_date);
								}
								if (self.filters.to_date) {
									self.filters.to_date.set_value(r.message.year_end_date);
								}
								self.in_filter_change = false;
								self.refresh();
							} else {
								self.in_filter_change = false;
								self.refresh();
							}
						});
					} else {
						self.refresh();
					}
				};
			} else {
				control.df.change = function() {
					if (!self.in_filter_change) {
						self.refresh();
					}
				};
			}
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
				fiscal_year: this.get_fiscal_year(),
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
							<th style="width:130px">${__("Sales Invoice")}</th>
							<th>${__("Customer")}</th>
							<th style="width:130px">${__("GST Category")}</th>
							<th style="width:110px">${__("Date")}</th>
							<th style="width:115px">${__("Grand Total")}</th>
							<th style="width:130px">${__("POD Status")}</th>
							<th style="width:130px">${__("POD Date")}</th>
							<th style="width:180px">${__("POD Attachment")}</th>
							<th style="width:85px">${__("Action")}</th>
						</tr>
						<tr class="pod-search-row">
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="name" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="customer" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="gst_category" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="posting_date" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="grand_total" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="pod_status" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="pod_date" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="pod_attachment" placeholder="${__("Search…")}"></th>
							<th></th>
						</tr>
					</thead>
					<tbody id="pod-table-body">
		`;

		invoices.forEach((inv) => {
			const hasStatus = !!inv.bns_pod_status;
			const hasDate = !!inv.bns_pod_date;
			const hasAttachment = !!inv.bns_pod_attachment;

			const rowClass = "pod-row-pending";

			// GST Category Badge (Note: 'Unregistered' is excluded in the backend query)
			let gstBadge = "";
			if (inv.gst_category) {
				gstBadge = `<span class="pod-gst-badge gst-registered">${frappe.utils.escape_html(inv.gst_category)}</span>`;
			} else {
				gstBadge = `<span class="text-muted" style="font-size:0.75rem;">—</span>`;
			}

			const escName = frappe.utils.escape_html(inv.name);
			const escCustomerName = frappe.utils.escape_html(inv.customer_name || inv.customer || "");
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
							<span class="customer-name" title="${frappe.utils.escape_html(inv.customer || '')}">${escCustomerName}</span>
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

		// Quick Search inputs
		container.off("input", ".pod-search-input").on("input", ".pod-search-input", function () {
			self.apply_search_filters(container);
		});

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

	// ── Apply Client-Side Search Filters ──────────────────────────────

	apply_search_filters(container) {
		const rowFilters = {};
		container.find(".pod-search-input").each(function () {
			const col = $(this).data("col");
			const val = $(this).val().toLowerCase().trim();
			if (val) {
				rowFilters[col] = val;
			}
		});

		const rows = container.find("#pod-table-body tr");
		
		rows.each(function () {
			const row = $(this);
			let matches = true;

			for (const [col, val] of Object.entries(rowFilters)) {
				let cellText = "";
				if (col === "name") {
					cellText = row.find(".pod-si-link").text();
				} else if (col === "customer") {
					cellText = row.find(".customer-name").text();
				} else if (col === "gst_category") {
					cellText = row.find(".pod-gst-badge").text();
				} else if (col === "posting_date") {
					cellText = row.find("td:nth-child(4)").text();
				} else if (col === "grand_total") {
					cellText = row.find(".pod-total-amount").text();
				} else if (col === "pod_status") {
					cellText = row.find(".pod-status-input").val() || "";
				} else if (col === "pod_date") {
					cellText = row.find(".pod-date-input").val() || "";
				} else if (col === "pod_attachment") {
					cellText = row.find(".pod-attach-input").val() || "";
				}

				if (!cellText.toLowerCase().includes(val)) {
					matches = false;
					break;
				}
			}

			if (matches) {
				row.show();
			} else {
				row.hide();
			}
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
				padding: 16px 20px;
				font-family: var(--font-stack, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif);
				background-color: #f8fafc;
				min-height: 100vh;
			}

			/* ─── Summary Cards (Compact Size) ──────────────────────── */
			.pod-summary-row {
				display: grid;
				grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
				gap: 12px;
				margin-bottom: 16px;
			}
			.pod-metric-card {
				background: #ffffff;
				border: 1px solid #e2e8f0;
				border-radius: 8px;
				padding: 10px 16px;
				text-align: center;
				box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px 0 rgba(0, 0, 0, 0.03);
				transition: all 0.2s ease;
				border-left: 4px solid #e2e8f0;
			}
			.pod-metric-card:hover {
				transform: translateY(-1px);
				box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
			}
			.pod-metric-card.pod-card-ok      { border-left-color: #10b981; }
			.pod-metric-card.pod-card-warning { border-left-color: #f59e0b; }
			.pod-metric-card.pod-card-danger  { border-left-color: #ef4444; }
			
			.pod-metric-value {
				font-size: 1.5rem;
				font-weight: 800;
				color: #1e293b;
				line-height: 1.2;
			}
			.pod-metric-label {
				font-size: 0.75rem;
				color: #64748b;
				margin-top: 4px;
				font-weight: 600;
			}

			/* ─── Filters Section (Overflow Visible for Link dropdowns) ─ */
			.pod-filters-card {
				background: #ffffff;
				border: 1px solid #e2e8f0;
				border-radius: 12px;
				padding: 16px 20px;
				margin-bottom: 16px;
				box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
				z-index: 20;
				position: relative;
				overflow: visible !important;
			}
			.pod-filters-header {
				font-size: 0.95rem;
				font-weight: 700;
				color: #1e293b;
				margin-bottom: 12px;
				display: flex;
				align-items: center;
				gap: 8px;
			}
			.pod-filters-row {
				display: flex;
				flex-wrap: wrap;
				gap: 12px;
				overflow: visible !important;
			}
			.pod-filter-col {
				flex: 1 1 160px;
				min-width: 140px;
				overflow: visible !important;
			}
			.pod-filter-col .frappe-control {
				margin-bottom: 0px !important;
				overflow: visible !important;
			}
			.pod-filter-col label {
				font-size: 0.75rem !important;
				font-weight: 600 !important;
				color: #475569 !important;
				margin-bottom: 4px !important;
			}
			
			/* Ensure Awesomplete autocomplete results overlay correctly */
			.awesomplete {
				overflow: visible !important;
			}
			.awesomplete > ul {
				z-index: 9999 !important;
				position: absolute !important;
				background: #ffffff !important;
				border: 1px solid #e2e8f0 !important;
				border-radius: 6px !important;
				box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05) !important;
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
				padding: 14px 20px;
				font-weight: 700;
				font-size: 0.95rem;
				color: #1e293b;
				border-bottom: 1px solid #e2e8f0;
				display: flex;
				align-items: center;
				gap: 8px;
			}
			.pod-hint {
				font-weight: 500;
				font-size: 0.75rem;
				color: #94a3b8;
				margin-left: auto;
			}

			/* ─── Table ─────────────────────────────────────────────── */
			.pod-table-wrapper {
				max-height: calc(100vh - 300px);
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
				padding: 10px 14px;
				border-bottom: 2px solid #e2e8f0;
				position: sticky;
				top: 0;
				z-index: 10;
				box-shadow: inset 0 -1px 0 #e2e8f0;
			}
			
			/* Search Row styling */
			.pod-search-row th {
				padding: 4px 10px !important;
				background: #f1f5f9 !important;
				border-bottom: 2px solid #cbd5e1 !important;
				position: sticky;
				top: 38px; /* Offset for main sticky header */
				z-index: 9;
				box-shadow: inset 0 -1px 0 #cbd5e1;
			}
			.pod-search-input {
				height: 26px !important;
				padding: 2px 6px !important;
				font-size: 0.75rem !important;
				border: 1px solid #cbd5e1 !important;
				border-radius: 4px !important;
				background-color: #ffffff !important;
				width: 100%;
			}
			.pod-search-input::placeholder {
				color: #94a3b8;
				opacity: 0.8;
			}

			.pod-table td {
				vertical-align: middle;
				padding: 10px 14px;
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

			/* ─── Inputs ────────────────────────────────────────────── */
			.pod-field-wrap {
				display: flex;
				flex-direction: column;
				gap: 4px;
			}
			.pod-status-input,
			.pod-date-input,
			.pod-attach-input {
				height: 28px !important;
				font-size: 0.78rem !important;
				border-radius: 5px !important;
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
				gap: 4px;
				align-items: center;
			}
			.pod-attach-wrap .pod-attach-input {
				flex: 1;
				min-width: 0;
			}
			.pod-attach-btn {
				flex-shrink: 0;
				height: 28px;
				width: 28px;
				padding: 0 !important;
				display: flex;
				align-items: center;
				justify-content: center;
				border-radius: 5px !important;
				background-color: #f1f5f9;
				border: 1px solid #cbd5e1;
				color: #475569;
			}
			.pod-attach-btn:hover {
				background-color: #e2e8f0;
				color: #0f172a;
			}
			
			.btn-pod-save {
				height: 28px;
				padding: 0 10px !important;
				font-weight: 600;
				border-radius: 5px !important;
				font-size: 0.78rem !important;
			}

			/* ─── Empty / Loading ───────────────────────────────────── */
			.pod-loading, .pod-empty {
				text-align: center;
				color: #64748b;
				padding: 40px 20px;
				font-size: 0.9rem;
				font-weight: 500;
			}
			.pod-empty i {
				display: block;
				margin-bottom: 10px;
			}

			</style>
		`);
	}
}
