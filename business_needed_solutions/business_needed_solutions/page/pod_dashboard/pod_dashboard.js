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

		// Pagination State
		this.start = 0;
		this.page_length = 500;
		this.total = 0;

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
						<div class="pod-metric-label">${__("Total Pending (1+ Missing)")}</div>
					</div>
					<div class="pod-metric-card" id="pod-done-card">
						<div class="pod-metric-value" id="pod-done-count">--</div>
						<div class="pod-metric-label">${__("Total Done POD")}</div>
					</div>
					<div class="pod-metric-card" id="pod-all-missing-card">
						<div class="pod-metric-value" id="pod-all-missing-count">--</div>
						<div class="pod-metric-label">${__("Total Pending POD (3 Missing)")}</div>
					</div>
					<div class="pod-metric-card" id="pod-partial-card">
						<div class="pod-metric-value" id="pod-partial-count">--</div>
						<div class="pod-metric-label">${__("Total Partial POD")}</div>
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
				fieldname: "pod_status",
				label: __("POD Status"),
				fieldtype: "Select",
				options: "\nDelivered\nPartially Delivered\nNot Delivered"
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
								self.start = 0; // Reset pagination
								self.refresh();
							} else {
								self.in_filter_change = false;
								self.start = 0; // Reset pagination
								self.refresh();
							}
						});
					} else {
						self.start = 0; // Reset pagination
						self.refresh();
					}
				};
			} else {
				control.df.change = function() {
					if (!self.in_filter_change) {
						self.start = 0; // Reset pagination
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

		// Show loading spinner but preserve existing table structure to avoid UI jump if possible
		const hasTable = container.find("table").length > 0;
		if (!hasTable) {
			container.html(`
				<div class="pod-loading">
					<span class="spinner-border spinner-border-sm"></span>
					${__("Loading…")}
				</div>
			`);
		}

		// Read quick column search inputs
		const search_args = {};
		container.find(".pod-search-input").each(function () {
			const col = $(this).data("col");
			const val = $(this).val().trim();
			if (val) {
				search_args[`search_${col}`] = val;
			}
		});

		frappe.call({
			method: "business_needed_solutions.business_needed_solutions.page.pod_dashboard.pod_dashboard.get_pending_pod_invoices",
			args: {
				company: this.get_company(),
				fiscal_year: this.get_fiscal_year(),
				from_date: this.get_from_date(),
				to_date: this.get_to_date(),
				customer: this.get_customer(),
				pod_status: this.get_pod_status(),
				start: this.start,
				page_length: this.page_length,
				...search_args
			},
			callback: function (r) {
				if (r && r.message) {
					self.data = r.message.invoices || [];
					self.total = r.message.total || 0;

					self.render_summary(
						r.message.total,
						r.message.total_done,
						r.message.total_pending_all_missing,
						r.message.total_partial
					);
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

	render_summary(total, total_done, total_pending_all_missing, total_partial) {
		this.wrapper.find("#pod-pending-count").text(total || 0);
		this.wrapper.find("#pod-done-count").text(total_done || 0);
		this.wrapper.find("#pod-all-missing-count").text(total_pending_all_missing || 0);
		this.wrapper.find("#pod-partial-count").text(total_partial || 0);

		this.update_card_style(this.wrapper.find("#pod-pending-card"), total || 0);
		this.wrapper.find("#pod-done-card").removeClass("pod-card-ok pod-card-warning pod-card-danger");
		this.wrapper.find("#pod-done-card").addClass("pod-card-ok");

		this.update_card_style(this.wrapper.find("#pod-all-missing-card"), total_pending_all_missing || 0);
		this.update_card_style(this.wrapper.find("#pod-partial-card"), total_partial || 0);
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
		const self = this;

		// Save current search input values and focus state
		const search_vals = {};
		container.find(".pod-search-input").each(function () {
			const col = $(this).data("col");
			search_vals[col] = $(this).val();
		});

		const active_input = document.activeElement;
		let active_col = null;
		let selection_start = null;
		let selection_end = null;
		if (active_input && $(active_input).hasClass("pod-search-input")) {
			active_col = $(active_input).data("col");
			selection_start = active_input.selectionStart;
			selection_end = active_input.selectionEnd;
		}

		if (!invoices || invoices.length === 0) {
			let emptyHtml = `
				<div class="pod-empty">
					<i class="fa fa-check-circle text-success" style="font-size:2rem;"></i>
					<p>${__("No pending Sales Invoices match your filters. Great job!")}</p>
				</div>
			`;
			
			// Keep headers if search values were typed
			const hasSearchActive = Object.values(search_vals).some(val => !!val);
			if (hasSearchActive) {
				emptyHtml = `
					<div class="pod-table-wrapper">
						<table class="table pod-table">
							<thead>
								<tr>
									<th style="width:220px">${__("Sales Invoice")}</th>
									<th>${__("Customer")}</th>
									<th style="width:110px">${__("Date")}</th>
									<th style="width:160px">${__("POD Status")}</th>
									<th style="width:140px">${__("POD Date")}</th>
									<th style="width:200px">${__("POD Attachment")}</th>
									<th style="width:85px">${__("Action")}</th>
								</tr>
								<tr class="pod-search-row">
									<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="name" placeholder="${__("Search…")}"></th>
									<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="customer" placeholder="${__("Search…")}"></th>
									<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="posting_date" placeholder="${__("Search…")}"></th>
									<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="pod_status" placeholder="${__("Search…")}"></th>
									<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="pod_date" placeholder="${__("Search…")}"></th>
									<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="pod_attachment" placeholder="${__("Search…")}"></th>
									<th></th>
								</tr>
							</thead>
							<tbody>
								<tr>
									<td colspan="7" class="text-center text-muted">${__("No matching records found")}</td>
								</tr>
							</tbody>
						</table>
					</div>
				`;
			}
			
			container.html(emptyHtml);

			// Restore search values & focus
			Object.entries(search_vals).forEach(([col, val]) => {
				if (val) container.find(`.pod-search-input[data-col="${col}"]`).val(val);
			});
			if (active_col) {
				const input = container.find(`.pod-search-input[data-col="${active_col}"]`);
				if (input.length) {
					input.focus();
					try { input[0].setSelectionRange(selection_start, selection_end); } catch(e) {}
				}
			}

			this.bind_events(container);
			return;
		}

		let html = `
			<div class="pod-table-wrapper">
				<table class="table pod-table">
					<thead>
						<tr>
							<th style="width:220px">${__("Sales Invoice")}</th>
							<th>${__("Customer")}</th>
							<th style="width:110px">${__("Date")}</th>
							<th style="width:160px">${__("POD Status")}</th>
							<th style="width:140px">${__("POD Date")}</th>
							<th style="width:200px">${__("POD Attachment")}</th>
							<th style="width:85px">${__("Action")}</th>
						</tr>
						<tr class="pod-search-row">
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="name" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="customer" placeholder="${__("Search…")}"></th>
							<th><input type="text" class="form-control form-control-sm pod-search-input" data-col="posting_date" placeholder="${__("Search…")}"></th>
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

			const escName = frappe.utils.escape_html(inv.name);
			const escCustomerName = frappe.utils.escape_html(inv.customer_name || inv.customer || "");
			const escDate = frappe.utils.escape_html(inv.posting_date || "");
			const currentAttach = frappe.utils.escape_html(inv.bns_pod_attachment || "");
			const currentStatus = frappe.utils.escape_html(inv.bns_pod_status || "");
			const currentDate = frappe.utils.escape_html(inv.bns_pod_date || "");

			// PO Details below Sales Invoice
			let poDetailsHtml = "";
			if (inv.po_no || inv.po_date) {
				const escPoNo = inv.po_no ? frappe.utils.escape_html(inv.po_no) : "";
				const escPoDate = inv.po_date ? frappe.datetime.str_to_user(inv.po_date) : "";
				poDetailsHtml = `
					<div class="pod-invoice-sub-row">
						<span class="sub-label">PO:</span>
						<span class="sub-val">${escPoNo} ${escPoDate ? `(${escPoDate})` : ""}</span>
					</div>
				`;
			}

			// SO Details below Sales Invoice
			let soDetailsHtml = "";
			if (inv.sales_orders) {
				const escSalesOrders = frappe.utils.escape_html(inv.sales_orders);
				soDetailsHtml = `
					<div class="pod-invoice-sub-row">
						<span class="sub-label">SO:</span>
						<span class="sub-val" title="${escSalesOrders}">${escSalesOrders}</span>
					</div>
				`;
			}

			html += `
				<tr class="${rowClass}" data-name="${escName}">
					<td>
						<a href="/app/sales-invoice/${escName}" target="_blank" class="pod-si-link">
							${escName}
						</a>
						<div class="pod-invoice-sub-info">
							${soDetailsHtml}
							${poDetailsHtml}
						</div>
					</td>
					<td>
						<div class="pod-customer-cell">
							<span class="customer-name" title="${frappe.utils.escape_html(inv.customer || '')}">${escCustomerName}</span>
							${(inv.city || inv.state) ? `
								<div class="pod-customer-address">
									${[inv.city, inv.state].filter(Boolean).map(frappe.utils.escape_html).join(", ")}
								</div>
							` : ""}
						</div>
					</td>
					<td><span class="text-muted">${escDate}</span></td>
					<td>
						<div class="pod-field-wrap">
							<select class="form-control form-control-sm pod-status-select ${hasStatus ? 'pod-input-filled' : 'pod-input-missing'}"
								data-name="${escName}">
								<option value="">${__("Select...")}</option>
								<option value="Delivered" ${currentStatus === "Delivered" ? "selected" : ""}>${__("Delivered")}</option>
								<option value="Partially Delivered" ${currentStatus === "Partially Delivered" ? "selected" : ""}>${__("Partially Delivered")}</option>
								<option value="Not Delivered" ${currentStatus === "Not Delivered" ? "selected" : ""}>${__("Not Delivered")}</option>
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

		// Add Pagination HTML Row
		const startIdx = this.start + 1;
		const endIdx = Math.min(this.start + this.page_length, this.total);
		html += `
			<div class="pod-pagination-row">
				<button class="btn btn-default btn-xs btn-pod-prev" ${this.start === 0 ? "disabled" : ""}>
					<i class="fa fa-chevron-left"></i> ${__("Previous")}
				</button>
				<span class="pod-pagination-text">
					${__("Showing {0} to {1} of {2} records", [startIdx, endIdx, this.total])}
				</span>
				<button class="btn btn-default btn-xs btn-pod-next" ${this.start + this.page_length >= this.total ? "disabled" : ""}>
					${__("Next")} <i class="fa fa-chevron-right"></i>
				</button>
			</div>
		`;

		container.html(html);

		// Restore search input values & focus state
		Object.entries(search_vals).forEach(([col, val]) => {
			if (val) container.find(`.pod-search-input[data-col="${col}"]`).val(val);
		});
		if (active_col) {
			const input = container.find(`.pod-search-input[data-col="${active_col}"]`);
			if (input.length) {
				input.focus();
				try { input[0].setSelectionRange(selection_start, selection_end); } catch(e) {}
			}
		}

		this.bind_events(container);
	}

	// ── Event Binding with delegation ────────────────────────────────

	bind_events(container) {
		const self = this;

		// Quick Search inputs with Server-Side Debounce
		let search_timeout = null;
		container.off("input", ".pod-search-input").on("input", ".pod-search-input", function () {
			clearTimeout(search_timeout);
			search_timeout = setTimeout(function() {
				self.start = 0; // Reset pagination on filter change
				self.refresh();
			}, 450); // 450ms debounce
		});

		// Pagination Buttons
		container.find(".btn-pod-prev").off("click").on("click", function() {
			self.start = Math.max(0, self.start - self.page_length);
			self.refresh();
		});
		container.find(".btn-pod-next").off("click").on("click", function() {
			self.start = self.start + self.page_length;
			self.refresh();
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

		// Update style on status select changes
		container.off("change", ".pod-status-select").on("change", ".pod-status-select", function () {
			self.toggle_input_style($(this), !!$(this).val());
		});

		// Update style on date input changes
		container.off("change", ".pod-date-input").on("change", ".pod-date-input", function () {
			self.toggle_input_style($(this), !!$(this).val());
		});

		// Update style on attachment input changes
		container.off("input change", ".pod-attach-input").on("input change", ".pod-attach-input", function () {
			self.toggle_input_style($(this), !!$(this).val().trim());
		});
	}

	// ── Save Row ─────────────────────────────────────────────────────

	save_pod_row(siName, container, btn) {
		const self = this;
		const row = container.find(`tr[data-name="${siName}"]`);

		const pod_status = row.find(".pod-status-select").val();
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
						
						row.css("transition", "all 0.5s").css("opacity", "0").css("background-color", "#d4edda");
						setTimeout(function () {
							self.refresh(); // Reload current page list to pull new record into pagination view
						}, 500);
					} else {
						// Partial save — update inputs and classes
						frappe.show_alert({
							message: __("POD details saved. Fill remaining fields to complete."),
							indicator: "blue",
						});
						
						self.refresh_row_inputs(row, pod_status, pod_date, pod_attachment);
						self.refresh(); // Reload statistics and lists
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
		const statusSelect = row.find(".pod-status-select");
		const dateInput = row.find(".pod-date-input");
		const attachInput = row.find(".pod-attach-input");

		statusSelect.val(pod_status || "");
		dateInput.val(pod_date || "");
		attachInput.val(pod_attachment || "");

		this.toggle_input_style(statusSelect, !!pod_status);
		this.toggle_input_style(dateInput, !!pod_date);
		this.toggle_input_style(attachInput, !!pod_attachment);
	}

	toggle_input_style(input, is_filled) {
		if (input.is(":checkbox")) {
			const wrap = input.closest(".pod-checkbox-wrap");
			if (is_filled) {
				wrap.removeClass("pod-input-missing").addClass("pod-input-filled");
			} else {
				wrap.removeClass("pod-input-filled").addClass("pod-input-missing");
			}
		} else {
			if (is_filled) {
				input.removeClass("pod-input-missing").addClass("pod-input-filled");
			} else {
				input.removeClass("pod-input-filled").addClass("pod-input-missing");
			}
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
				max-height: calc(100vh - 220px);
				min-height: 500px;
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

			/* ─── SI Link & PO / SO Details ────────────────────────── */
			.pod-si-link {
				font-weight: 700;
				color: var(--primary-color, #1f6bff);
				text-decoration: none;
			}
			.pod-si-link:hover {
				text-decoration: underline;
			}
			.pod-invoice-sub-info {
				display: flex;
				flex-direction: column;
				gap: 2px;
				margin-top: 4px;
			}
			.pod-invoice-sub-row {
				font-size: 0.72rem;
				color: #64748b;
				line-height: 1.2;
				display: flex;
				gap: 4px;
				align-items: center;
			}
			.sub-label {
				font-weight: 700;
				color: #475569;
			}
			.sub-val {
				color: #64748b;
				white-space: nowrap;
				overflow: hidden;
				text-overflow: ellipsis;
				max-width: 180px;
			}
			.pod-customer-address {
				font-size: 0.72rem;
				color: #64748b;
				font-style: italic;
				margin-top: 2px;
			}

			/* ─── Inputs & Status Select ────────────────────────────── */
			.pod-field-wrap {
				display: flex;
				flex-direction: column;
				gap: 4px;
			}
			.pod-status-select {
				height: 28px !important;
				font-size: 0.78rem !important;
				border-radius: 5px !important;
				padding: 2px 6px !important;
				font-weight: 600;
				cursor: pointer;
			}
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
			
			/* Focus styles for status select and inputs */

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

			/* ─── Pagination ────────────────────────────────────────── */
			.pod-pagination-row {
				display: flex;
				align-items: center;
				justify-content: space-between;
				padding: 12px 20px;
				border-top: 1px solid #e2e8f0;
				background-color: #f8fafc;
			}
			.pod-pagination-text {
				font-size: 0.78rem;
				font-weight: 600;
				color: #475569;
			}
			.btn-pod-prev, .btn-pod-next {
				height: 28px;
				padding: 0 12px !important;
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
