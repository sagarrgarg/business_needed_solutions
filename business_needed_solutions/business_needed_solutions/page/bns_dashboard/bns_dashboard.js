frappe.pages["bns-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("BNS Dashboard"),
		single_column: true,
	});

	page.company_field = page.add_field({
		fieldname: "company",
		label: __("Company"),
		fieldtype: "Link",
		options: "Company",
		default: frappe.defaults.get_user_default("Company"),
		change: function () {
			page.dashboard.refresh();
		},
	});

	page.dashboard = new BNSDashboard(page);
	window.bns_dashboard = page.dashboard;
};

frappe.pages["bns-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.page && wrapper.page.dashboard) {
		wrapper.page.dashboard.refresh();
	}
};

class BNSDashboard {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);
		this.expense_accounts = [];
		this.init();
	}

	init() {
		this.render_layout();
		this.load_expense_accounts();
		this.refresh();
	}

	get_company() {
		return this.page.company_field.get_value() || frappe.defaults.get_user_default("Company");
	}

	render_layout() {
		this.wrapper.html(`
			<div class="bns-dashboard-container" style="padding: 15px;">
				<div class="row">
					<!-- Left Column - Expense Item Fixables -->
					<div class="col-lg-6">
						<div class="frappe-card" id="section-expense-fixables">
							<div class="card-header d-flex justify-content-between align-items-center section-header" 
								 style="cursor: pointer; padding: 12px 15px; background: var(--subtle-bg);"
								 data-section="expense-fixables">
								<h5 class="mb-0">
									<i class="fa fa-chevron-down section-toggle" id="toggle-expense-fixables"></i>
									${__("Expense Item Fixables")}
								</h5>
							</div>
							<div class="card-body section-content" id="content-expense-fixables">
								<!-- Summary Cards -->
								<div class="row mb-3" id="summary-cards">
									<div class="col-6">
										<div class="number-card" id="card-items-missing">
											<div class="number-card-loading">
												<span class="text-muted">${__("Loading...")}</span>
											</div>
										</div>
									</div>
									<div class="col-6">
										<div class="number-card" id="card-pi-fixable">
											<div class="number-card-loading">
												<span class="text-muted">${__("Loading...")}</span>
											</div>
										</div>
									</div>
								</div>

								<!-- Sub-section 1: Items Missing Expense Account -->
								<div class="sub-section mb-3" id="subsection-items-missing">
									<div class="sub-section-header d-flex justify-content-between align-items-center" 
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="items-missing">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-items-missing"></i>
											${__("Items Missing Default Expense Account")}
											<span class="badge badge-secondary ml-2" id="badge-items-missing">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-items-missing" style="display: none; padding-top: 10px;">
										<div id="table-items-missing">
											<p class="text-muted">${__("Loading...")}</p>
										</div>
									</div>
								</div>

								<!-- Sub-section 2: PI Items with Wrong Expense Account -->
								<div class="sub-section mb-3" id="subsection-pi-wrong">
									<div class="sub-section-header d-flex justify-content-between align-items-center" 
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="pi-wrong">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-pi-wrong"></i>
											${__("Purchase Invoices with Wrong Expense Account")}
											<span class="badge badge-warning ml-2" id="badge-pi-fixable">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-pi-wrong" style="display: none; padding-top: 10px;">
										<div class="mb-2">
											<button class="btn btn-primary btn-xs" id="btn-bulk-fix" disabled>
												<i class="fa fa-wrench"></i> ${__("Bulk Fix Selected")}
											</button>
											<button class="btn btn-secondary btn-xs ml-2" id="btn-select-all-fixable">
												${__("Select All Fixable")}
											</button>
										</div>
										<div id="table-pi-wrong">
											<p class="text-muted">${__("Loading...")}</p>
										</div>
									</div>
								</div>

								<!-- Sub-section 3: All Expense Items -->
								<div class="sub-section" id="subsection-all-items">
									<div class="sub-section-header d-flex justify-content-between align-items-center" 
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="all-items">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-all-items"></i>
											${__("All Expense Items")}
											<span class="badge badge-info ml-2" id="badge-all-items">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-all-items" style="display: none; padding-top: 10px;">
										<div id="table-all-items">
											<p class="text-muted">${__("Loading...")}</p>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Right Column - Party Link & Transfer Fixables -->
					<div class="col-lg-6">
						<div class="frappe-card" id="section-party-link">
							<div class="card-header d-flex justify-content-between align-items-center section-header" 
								 style="cursor: pointer; padding: 12px 15px; background: var(--subtle-bg);"
								 data-section="party-link">
								<h5 class="mb-0">
									<i class="fa fa-chevron-down section-toggle" id="toggle-party-link"></i>
									${__("Party & Transfer Fixables")}
								</h5>
							</div>
							<div class="card-body section-content" id="content-party-link">
								<!-- Summary Cards -->
								<div class="row mb-3">
									<div class="col-6">
										<div class="number-card" id="card-unlinked-pan">
											<div class="number-card-loading">
												<span class="text-muted">${__("Loading...")}</span>
											</div>
										</div>
									</div>
									<div class="col-6">
										<div class="number-card" id="card-transfer-mismatch">
											<div class="number-card-loading">
												<span class="text-muted">${__("Loading...")}</span>
											</div>
										</div>
									</div>
								</div>

								<!-- Sub-section: Unlinked Customer/Supplier by PAN -->
								<div class="sub-section mb-3" id="subsection-unlinked-pan">
									<div class="sub-section-header d-flex justify-content-between align-items-center" 
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="unlinked-pan">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-unlinked-pan"></i>
											${__("Unlinked Customer/Supplier by PAN")}
											<span class="badge badge-warning ml-2" id="badge-unlinked-pan">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-unlinked-pan" style="display: none; padding-top: 10px;">
										<p class="text-muted small mb-2">
											${__("Customers and Suppliers with same PAN but no Party Link. Link them for proper internal transfer handling.")}
										</p>
										<div id="table-unlinked-pan">
											<p class="text-muted">${__("Loading...")}</p>
										</div>
									</div>
								</div>

								<!-- Sub-section: Internal Transfer Mismatches -->
								<div class="sub-section" id="subsection-transfer-mismatch">
									<div class="sub-section-header d-flex justify-content-between align-items-center" 
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="transfer-mismatch">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-transfer-mismatch"></i>
											${__("Internal Transfer Mismatches")}
											<span class="badge badge-danger ml-2" id="badge-transfer-mismatch">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-transfer-mismatch" style="display: none; padding-top: 10px;">
										<p class="text-muted small mb-2">
											${__("DN/SI with missing or mismatched PR/PI. Click document to view details.")}
										</p>
										<div class="mb-2">
											<a href="/app/query-report/Internal%20Transfer%20Receive%20Mismatch" target="_blank" class="btn btn-secondary btn-xs">
												<i class="fa fa-external-link"></i> ${__("Open Full Report")}
											</a>
										</div>
										<div id="table-transfer-mismatch">
											<p class="text-muted">${__("Loading...")}</p>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<style>
				.bns-dashboard-container .number-card {
					background: var(--card-bg);
					border: 1px solid var(--border-color);
					border-radius: 6px;
					padding: 12px;
					text-align: center;
				}
				.bns-dashboard-container .number-card .number {
					font-size: 1.8rem;
					font-weight: bold;
					color: var(--primary);
				}
				.bns-dashboard-container .number-card .label {
					color: var(--text-muted);
					font-size: 0.8rem;
				}
				.bns-dashboard-container .number-card.warning .number {
					color: var(--orange-500);
				}
				.bns-dashboard-container .number-card.danger .number {
					color: var(--red-500);
				}
				.bns-dashboard-container .frappe-card {
					background: var(--card-bg);
					border: 1px solid var(--border-color);
					border-radius: 8px;
					margin-bottom: 15px;
				}
				.bns-dashboard-container .card-body {
					padding: 15px;
				}
				.bns-dashboard-container .section-toggle,
				.bns-dashboard-container .subsection-toggle {
					transition: transform 0.2s;
					margin-right: 8px;
					width: 12px;
				}
				.bns-dashboard-container .section-toggle.collapsed,
				.bns-dashboard-container .subsection-toggle.collapsed {
					transform: rotate(-90deg);
				}
				.bns-dashboard-container .sub-section {
					border: 1px solid var(--border-color);
					border-radius: 4px;
					padding: 0;
				}
				.bns-dashboard-container .sub-section-content {
					padding: 10px;
					max-height: 400px;
					overflow-y: auto;
				}
				.bns-dashboard-container table {
					width: 100%;
					font-size: 0.85rem;
				}
				.bns-dashboard-container table th,
				.bns-dashboard-container table td {
					padding: 6px 8px;
					border-bottom: 1px solid var(--border-color);
				}
				.bns-dashboard-container table th {
					background: var(--card-bg, #fff);
					font-weight: 600;
					position: sticky;
					top: 0;
					z-index: 1;
					box-shadow: 0 1px 0 var(--border-color);
				}
				.bns-dashboard-container .row-fixable {
					background: var(--subtle-accent);
				}
				.bns-dashboard-container .row-not-fixable {
					opacity: 0.7;
				}
				.bns-dashboard-container .expense-account-select {
					min-width: 150px;
					font-size: 0.8rem;
					padding: 2px 6px;
				}
				.bns-dashboard-container .btn-xs {
					font-size: 0.75rem;
					padding: 2px 8px;
				}
			</style>
		`);

		this.bind_events();
	}

	bind_events() {
		const self = this;

		// Main section toggle
		this.wrapper.find(".section-header").on("click", function () {
			const section = $(this).data("section");
			self.toggle_section(section);
		});

		// Sub-section toggles
		this.wrapper.find(".sub-section-header").on("click", function () {
			const subsection = $(this).data("subsection");
			self.toggle_subsection(subsection);
		});

		this.wrapper.find("#btn-bulk-fix").on("click", function () {
			self.bulk_fix_selected();
		});

		this.wrapper.find("#btn-select-all-fixable").on("click", function () {
			self.wrapper.find(".pi-fix-checkbox:not(:disabled)").prop("checked", true);
			self.update_bulk_fix_button();
		});
	}

	toggle_section(section) {
		const content = this.wrapper.find("#content-" + section);
		const toggle = this.wrapper.find("#toggle-" + section);

		if (content.is(":visible")) {
			content.slideUp(200);
			toggle.addClass("collapsed");
		} else {
			content.slideDown(200);
			toggle.removeClass("collapsed");
		}
	}

	toggle_subsection(subsection) {
		const content = this.wrapper.find("#subcontent-" + subsection);
		const toggle = this.wrapper.find("#subtoggle-" + subsection);

		if (content.is(":visible")) {
			content.slideUp(200);
			toggle.addClass("collapsed");
		} else {
			content.slideDown(200);
			toggle.removeClass("collapsed");
		}
	}

	async load_expense_accounts() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_expense_accounts",
				args: { company: this.get_company() },
			});
			this.expense_accounts = result.message || [];
		} catch (e) {
			console.error("Failed to load expense accounts:", e);
		}
	}

	async refresh() {
		await this.load_expense_accounts();
		await Promise.all([
			this.load_summary(),
			this.load_items_missing_expense_account(),
			this.load_pi_wrong_expense_account(),
			this.load_all_expense_items(),
			this.load_unlinked_pan(),
			this.load_transfer_mismatches(),
		]);
	}

	async load_summary() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_dashboard_summary",
				args: { company: this.get_company() },
			});

			const data = result.message;

			this.render_number_card(
				"card-items-missing",
				data.items_missing_expense_account,
				__("Missing Account"),
				data.items_missing_expense_account > 0 ? "warning" : ""
			);

			this.render_number_card(
				"card-pi-fixable",
				data.pi_items_fixable,
				__("PI Fixable"),
				data.pi_items_fixable > 0 ? "danger" : ""
			);

			this.render_number_card(
				"card-unlinked-pan",
				data.unlinked_pan_count || 0,
				__("Unlinked by PAN"),
				(data.unlinked_pan_count || 0) > 0 ? "warning" : ""
			);

			this.render_number_card(
				"card-transfer-mismatch",
				data.transfer_mismatch_count || 0,
				__("Transfer Mismatches"),
				(data.transfer_mismatch_count || 0) > 0 ? "danger" : ""
			);

			this.wrapper.find("#badge-items-missing").text(data.items_missing_expense_account);
			this.wrapper.find("#badge-pi-fixable").text(data.pi_items_fixable);
			this.wrapper.find("#badge-unlinked-pan").text(data.unlinked_pan_count || 0);
			this.wrapper.find("#badge-transfer-mismatch").text(data.transfer_mismatch_count || 0);
		} catch (e) {
			console.error("Failed to load summary:", e);
		}
	}

	render_number_card(id, number, label, colorClass) {
		const card = this.wrapper.find("#" + id);
		card.removeClass("warning danger").addClass(colorClass || "");
		card.html('<div class="number">' + number + '</div><div class="label">' + label + '</div>');
	}

	async load_items_missing_expense_account() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_items_missing_expense_account",
				args: { company: this.get_company() },
			});

			const data = result.message;
			this.render_items_missing_table(data.items);
		} catch (e) {
			console.error("Failed to load items:", e);
			this.wrapper.find("#table-items-missing").html(
				'<p class="text-danger">' + __("Failed to load data") + '</p>'
			);
		}
	}

	render_items_missing_table(items) {
		const container = this.wrapper.find("#table-items-missing");

		if (!items || items.length === 0) {
			container.html('<p class="text-success mb-0">' + __("All items have expense accounts set!") + '</p>');
			return;
		}

		const self = this;
		let accountOptions = '<option value="">' + __("Select...") + '</option>';
		this.expense_accounts.forEach(function (a) {
			accountOptions += '<option value="' + a.name + '">' + a.name + '</option>';
		});

		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th>' + __("Item") + '</th>';
		html += '<th>' + __("Expense Account") + '</th>';
		html += '<th style="width: 60px;"></th>';
		html += '</tr></thead><tbody>';

		items.forEach(function (item) {
			html += '<tr data-item="' + item.item_code + '">';
			html += '<td><a href="/app/item/' + item.item_code + '" target="_blank">' + item.item_code + '</a>';
			if (item.item_name) {
				html += '<br><small class="text-muted">' + item.item_name + '</small>';
			}
			html += '</td>';
			html += '<td><select class="form-control expense-account-select" data-item="' + item.item_code + '">';
			html += accountOptions + '</select></td>';
			html += '<td><button class="btn btn-primary btn-xs btn-set-expense" data-item="' + item.item_code + '">' + __("Set") + '</button></td>';
			html += '</tr>';
		});

		html += '</tbody></table>';
		container.html(html);

		container.find(".btn-set-expense").on("click", function () {
			const itemCode = $(this).data("item");
			const account = container.find('.expense-account-select[data-item="' + itemCode + '"]').val();
			self.set_item_expense_account(itemCode, account, $(this));
		});
	}

	async set_item_expense_account(itemCode, account, btn) {
		if (!account) {
			frappe.msgprint(__("Please select an expense account"));
			return;
		}

		btn.prop("disabled", true).text(__("..."));

		try {
			await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.set_item_expense_account",
				args: {
					item_code: itemCode,
					expense_account: account,
					company: this.get_company(),
				},
			});

			frappe.show_alert({ message: __("Set for {0}", [itemCode]), indicator: "green" });

			btn.closest("tr").fadeOut(300, function () {
				$(this).remove();
			});

			this.load_summary();
			this.load_all_expense_items();
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
			btn.prop("disabled", false).text(__("Set"));
		}
	}

	async load_pi_wrong_expense_account() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_purchase_invoices_with_wrong_expense_account",
				args: { company: this.get_company() },
			});

			const data = result.message;
			this.render_pi_wrong_table(data);
		} catch (e) {
			console.error("Failed to load PI data:", e);
			this.wrapper.find("#table-pi-wrong").html(
				'<p class="text-danger">' + __("Failed to load data") + '</p>'
			);
		}
	}

	render_pi_wrong_table(data) {
		const container = this.wrapper.find("#table-pi-wrong");
		const fixableItems = data.items_with_wrong_account || [];
		const unfixableItems = data.items_without_default || [];

		if (fixableItems.length === 0 && unfixableItems.length === 0) {
			container.html('<p class="text-success mb-0">' + __("All PI expense accounts are correct!") + '</p>');
			this.wrapper.find("#btn-bulk-fix").prop("disabled", true);
			return;
		}

		const self = this;

		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th style="width: 30px;"><input type="checkbox" id="check-all-pi"></th>';
		html += '<th>' + __("PI / Item") + '</th>';
		html += '<th>' + __("PI Account") + '</th>';
		html += '<th>' + __("Correct") + '</th>';
		html += '<th>' + __("Status") + '</th>';
		html += '</tr></thead><tbody>';

		fixableItems.forEach(function (item) {
			html += '<tr class="row-fixable">';
			html += '<td><input type="checkbox" class="pi-fix-checkbox" data-pi-item="' + item.pi_item_name + '" data-correct-account="' + item.item_default_expense_account + '"></td>';
			html += '<td><a href="/app/purchase-invoice/' + item.purchase_invoice + '" target="_blank">' + item.purchase_invoice + '</a>';
			html += '<br><small>' + item.item_code + '</small></td>';
			html += '<td><small class="text-danger">' + (item.pi_expense_account || "-") + '</small></td>';
			html += '<td><small class="text-success">' + item.item_default_expense_account + '</small></td>';
			html += '<td><span class="badge badge-success">' + __("Fixable") + '</span></td>';
			html += '</tr>';
		});

		unfixableItems.forEach(function (item) {
			html += '<tr class="row-not-fixable">';
			html += '<td><input type="checkbox" disabled></td>';
			html += '<td><a href="/app/purchase-invoice/' + item.purchase_invoice + '" target="_blank">' + item.purchase_invoice + '</a>';
			html += '<br><small>' + item.item_code + '</small></td>';
			html += '<td><small>' + (item.pi_expense_account || "-") + '</small></td>';
			html += '<td><small class="text-muted">' + __("Not set") + '</small></td>';
			html += '<td><span class="badge badge-secondary">' + __("Set First") + '</span></td>';
			html += '</tr>';
		});

		html += '</tbody></table>';
		container.html(html);

		container.find(".pi-fix-checkbox").on("change", function () {
			self.update_bulk_fix_button();
		});

		container.find("#check-all-pi").on("change", function () {
			container.find(".pi-fix-checkbox:not(:disabled)").prop("checked", $(this).is(":checked"));
			self.update_bulk_fix_button();
		});

		this.update_bulk_fix_button();
	}

	update_bulk_fix_button() {
		const checkedCount = this.wrapper.find(".pi-fix-checkbox:checked").length;
		const btn = this.wrapper.find("#btn-bulk-fix");
		btn.prop("disabled", checkedCount === 0);
		if (checkedCount > 0) {
			btn.html('<i class="fa fa-wrench"></i> ' + __("Fix ({0})", [checkedCount]));
		} else {
			btn.html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix"));
		}
	}

	async bulk_fix_selected() {
		const selected = [];
		this.wrapper.find(".pi-fix-checkbox:checked").each(function () {
			selected.push({
				pi_item_name: $(this).data("pi-item"),
				correct_expense_account: $(this).data("correct-account"),
			});
		});

		if (selected.length === 0) {
			frappe.msgprint(__("No items selected"));
			return;
		}

		const self = this;

		frappe.confirm(
			__("Fix expense accounts for {0} PI items?", [selected.length]),
			async function () {
				const btn = self.wrapper.find("#btn-bulk-fix");
				btn.prop("disabled", true).html('<i class="fa fa-spinner fa-spin"></i>');

				try {
					const result = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.bulk_fix_pi_expense_accounts",
						args: { items: selected },
					});

					const data = result.message;

					if (data.success_count > 0) {
						frappe.show_alert({
							message: __("Fixed {0} items", [data.success_count]),
							indicator: "green",
						});
					}

					if (data.error_count > 0) {
						let errorMsg = "";
						data.errors.forEach(function (e) {
							errorMsg += e.pi_item_name + ": " + e.error + "<br>";
						});
						frappe.msgprint({
							title: __("Some failed"),
							message: errorMsg,
							indicator: "orange",
						});
					}

					self.refresh();
				} catch (e) {
					frappe.msgprint(__("Failed: {0}", [e.message || e]));
				} finally {
					btn.prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix"));
				}
			}
		);
	}

	async load_all_expense_items() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_all_expense_items",
				args: { company: this.get_company() },
			});

			const data = result.message;
			this.wrapper.find("#badge-all-items").text(data.count);
			this.render_all_items_table(data.items);
		} catch (e) {
			console.error("Failed to load all items:", e);
			this.wrapper.find("#table-all-items").html(
				'<p class="text-danger">' + __("Failed to load data") + '</p>'
			);
		}
	}

	render_all_items_table(items) {
		const container = this.wrapper.find("#table-all-items");

		if (!items || items.length === 0) {
			container.html('<p class="text-muted mb-0">' + __("No expense items found.") + '</p>');
			return;
		}

		const self = this;
		let accountOptions = '<option value="">' + __("Select...") + '</option>';
		this.expense_accounts.forEach(function (a) {
			accountOptions += '<option value="' + a.name + '">' + a.name + '</option>';
		});

		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th>' + __("Item") + '</th>';
		html += '<th>' + __("Current Expense Account") + '</th>';
		html += '<th style="width: 60px;"></th>';
		html += '</tr></thead><tbody>';

		items.forEach(function (item) {
			html += '<tr data-item="' + item.item_code + '">';
			html += '<td><a href="/app/item/' + item.item_code + '" target="_blank">' + item.item_code + '</a>';
			if (item.item_name) {
				html += '<br><small class="text-muted">' + item.item_name + '</small>';
			}
			html += '</td>';
			html += '<td>';
			html += '<select class="form-control expense-account-select-all" data-item="' + item.item_code + '">';
			html += '<option value="">' + __("Select...") + '</option>';
			self.expense_accounts.forEach(function (a) {
				const selected = (a.name === item.expense_account) ? ' selected' : '';
				html += '<option value="' + a.name + '"' + selected + '>' + a.name + '</option>';
			});
			html += '</select>';
			html += '</td>';
			html += '<td><button class="btn btn-secondary btn-xs btn-update-expense" data-item="' + item.item_code + '">' + __("Update") + '</button></td>';
			html += '</tr>';
		});

		html += '</tbody></table>';
		container.html(html);

		container.find(".btn-update-expense").on("click", function () {
			const itemCode = $(this).data("item");
			const account = container.find('.expense-account-select-all[data-item="' + itemCode + '"]').val();
			self.update_item_expense_account(itemCode, account, $(this));
		});
	}

	async update_item_expense_account(itemCode, account, btn) {
		if (!account) {
			frappe.msgprint(__("Please select an expense account"));
			return;
		}

		btn.prop("disabled", true).text(__("..."));

		try {
			await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.set_item_expense_account",
				args: {
					item_code: itemCode,
					expense_account: account,
					company: this.get_company(),
				},
			});

			frappe.show_alert({ message: __("Updated {0}", [itemCode]), indicator: "green" });
			btn.prop("disabled", false).text(__("Update"));
			
			// Refresh summary and missing items
			this.load_summary();
			this.load_items_missing_expense_account();
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
			btn.prop("disabled", false).text(__("Update"));
		}
	}

	// ========== Unlinked Customer/Supplier by PAN ==========

	async load_unlinked_pan() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_unlinked_customer_supplier_by_pan",
			});

			const data = result.message;
			this.wrapper.find("#badge-unlinked-pan").text(data.count);
			this.render_unlinked_pan_table(data.records);
		} catch (e) {
			console.error("Failed to load unlinked PAN data:", e);
			this.wrapper.find("#table-unlinked-pan").html(
				'<p class="text-danger">' + __("Failed to load data") + '</p>'
			);
		}
	}

	render_unlinked_pan_table(records) {
		const container = this.wrapper.find("#table-unlinked-pan");

		if (!records || records.length === 0) {
			container.html('<p class="text-success mb-0">' + __("All matching Customer/Supplier pairs are linked!") + '</p>');
			return;
		}

		const self = this;

		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th>' + __("Customer") + '</th>';
		html += '<th>' + __("Supplier") + '</th>';
		html += '<th>' + __("PAN") + '</th>';
		html += '<th>' + __("Link As") + '</th>';
		html += '</tr></thead><tbody>';

		records.forEach(function (record) {
			html += '<tr data-customer="' + record.customer + '" data-supplier="' + record.supplier + '">';
			html += '<td><a href="/app/customer/' + record.customer + '" target="_blank">' + record.customer + '</a>';
			if (record.customer_name && record.customer_name !== record.customer) {
				html += '<br><small class="text-muted">' + record.customer_name + '</small>';
			}
			html += '</td>';
			html += '<td><a href="/app/supplier/' + record.supplier + '" target="_blank">' + record.supplier + '</a>';
			if (record.supplier_name && record.supplier_name !== record.supplier) {
				html += '<br><small class="text-muted">' + record.supplier_name + '</small>';
			}
			html += '</td>';
			html += '<td><code>' + record.pan + '</code></td>';
			html += '<td>';
			html += '<button class="btn btn-success btn-xs btn-link-c2s mr-1" data-customer="' + record.customer + '" data-supplier="' + record.supplier + '" title="' + __("Customer as Primary") + '">';
			html += '<i class="fa fa-arrow-right"></i> ' + __("C→S");
			html += '</button>';
			html += '<button class="btn btn-primary btn-xs btn-link-s2c" data-customer="' + record.customer + '" data-supplier="' + record.supplier + '" title="' + __("Supplier as Primary") + '">';
			html += '<i class="fa fa-arrow-left"></i> ' + __("S→C");
			html += '</button>';
			html += '</td>';
			html += '</tr>';
		});

		html += '</tbody></table>';
		container.html(html);

		// Bind click events
		container.find(".btn-link-c2s").on("click", function () {
			const customer = $(this).data("customer");
			const supplier = $(this).data("supplier");
			self.create_party_link(customer, supplier, "Customer", "Supplier", $(this));
		});

		container.find(".btn-link-s2c").on("click", function () {
			const customer = $(this).data("customer");
			const supplier = $(this).data("supplier");
			self.create_party_link(supplier, customer, "Supplier", "Customer", $(this));
		});
	}

	async create_party_link(primary, secondary, primaryRole, secondaryRole, btn) {
		btn.prop("disabled", true);
		const row = btn.closest("tr");

		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.create_party_link",
				args: {
					primary_party: primary,
					secondary_party: secondary,
					primary_role: primaryRole,
					secondary_role: secondaryRole,
				},
			});

			const data = result.message;

			if (data.success) {
				frappe.show_alert({ message: data.message, indicator: "green" });
				row.fadeOut(300, function () {
					$(this).remove();
				});
				this.load_summary();
			} else {
				frappe.msgprint(data.message);
				btn.prop("disabled", false);
			}
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
			btn.prop("disabled", false);
		}
	}

	// ========== Internal Transfer Mismatches ==========

	async load_transfer_mismatches() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_internal_transfer_mismatches",
				args: { company: this.get_company() },
			});

			const data = result.message;
			this.wrapper.find("#badge-transfer-mismatch").text(data.count);
			this.render_transfer_mismatch_table(data.records);
		} catch (e) {
			console.error("Failed to load transfer mismatch data:", e);
			this.wrapper.find("#table-transfer-mismatch").html(
				'<p class="text-danger">' + __("Failed to load data") + '</p>'
			);
		}
	}

	render_transfer_mismatch_table(records) {
		const container = this.wrapper.find("#table-transfer-mismatch");

		if (!records || records.length === 0) {
			container.html('<p class="text-success mb-0">' + __("No internal transfer mismatches found!") + '</p>');
			return;
		}

		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th>' + __("Date") + '</th>';
		html += '<th>' + __("Document") + '</th>';
		html += '<th>' + __("Customer") + '</th>';
		html += '<th>' + __("Amount") + '</th>';
		html += '<th>' + __("Issue") + '</th>';
		html += '<th>' + __("Linked") + '</th>';
		html += '</tr></thead><tbody>';

		records.forEach(function (record) {
			const docType = record.document_type;
			const docName = record.document_name;
			const route = docType === "Delivery Note" ? "delivery-note" : "sales-invoice";
			const linkedRoute = record.linked_document 
				? (docType === "Delivery Note" ? "purchase-receipt" : "purchase-invoice")
				: null;

			const mismatchBadgeClass = record.mismatch_type === "Missing PR" || record.mismatch_type === "Missing PI" 
				? "badge-danger" 
				: "badge-warning";

			html += '<tr>';
			html += '<td><small>' + (record.posting_date || '-') + '</small></td>';
			html += '<td><a href="/app/' + route + '/' + docName + '" target="_blank">';
			html += '<small>' + (docType === "Delivery Note" ? "DN" : "SI") + '</small> ';
			html += docName + '</a></td>';
			html += '<td><small>' + (record.customer || '-') + '</small></td>';
			html += '<td><small>' + format_currency(record.grand_total || 0) + '</small></td>';
			html += '<td><span class="badge ' + mismatchBadgeClass + '">' + record.mismatch_type + '</span>';
			if (record.mismatch_reason) {
				html += '<br><small class="text-muted">' + record.mismatch_reason + '</small>';
			}
			html += '</td>';
			html += '<td>';
			if (record.linked_document && linkedRoute) {
				html += '<a href="/app/' + linkedRoute + '/' + record.linked_document + '" target="_blank">';
				html += '<small>' + record.linked_document + '</small></a>';
			} else {
				html += '<span class="text-muted">-</span>';
			}
			html += '</td>';
			html += '</tr>';
		});

		html += '</tbody></table>';
		container.html(html);
	}
}
