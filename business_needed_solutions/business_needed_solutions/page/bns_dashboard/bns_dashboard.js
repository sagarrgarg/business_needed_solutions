frappe.pages["bns-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("BNS Health Check"),
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
		this.tds_categories = [];
		this.is_system_manager = frappe.user.has_role("System Manager");
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

	// =====================================================================
	// Layout
	// =====================================================================

	render_layout() {
		this.wrapper.html(`
			<div class="bns-dashboard-container">

				<!-- ======= BNS HEALTH INDICATORS ======= -->
				<div class="bns-section">
					<div class="bns-section-title">
						<i class="fa fa-heartbeat"></i> ${__("Data Health Indicators")}
					</div>
					<div class="row" id="health-indicator-cards">
						<div class="col-lg-3 col-md-6 col-6 mb-3">
							<div class="metric-card" id="health-missing-expense">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Items Missing Expense A/c")}</div>
							</div>
						</div>
						<div class="col-lg-3 col-md-6 col-6 mb-3">
							<div class="metric-card" id="health-pi-fixable">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("PI Expense Fixable")}</div>
							</div>
						</div>
						<div class="col-lg-3 col-md-6 col-6 mb-3">
							<div class="metric-card" id="health-unlinked-pan">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Unlinked by PAN")}</div>
							</div>
						</div>
						<div class="col-lg-3 col-md-6 col-6 mb-3">
							<div class="metric-card" id="health-transfer-mismatch">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Transfer Mismatches")}</div>
							</div>
						</div>
					</div>
				</div>

				<!-- ======= BRANCH ACCOUNTING HEALTH ======= -->
				<div class="bns-section">
					<div class="bns-section-title">
						<i class="fa fa-exchange"></i> ${__("Branch Accounting Health")}
					</div>
					<div class="row" id="branch-accounting-cards">
						<div class="col-lg-2 col-md-4 col-6 mb-3">
							<div class="metric-card mini" id="branch-dn-pending">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("DN → PR Pending")}<br><small class="text-muted">${__("Same GSTIN")}</small></div>
							</div>
						</div>
						<div class="col-lg-2 col-md-4 col-6 mb-3">
							<div class="metric-card mini" id="branch-si-pending">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("SI → PI Pending")}<br><small class="text-muted">${__("Diff GSTIN")}</small></div>
							</div>
						</div>
						<div class="col-lg-2 col-md-4 col-6 mb-3">
							<div class="metric-card mini" id="branch-total-dn">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Same GSTIN DNs")}</div>
							</div>
						</div>
						<div class="col-lg-2 col-md-4 col-6 mb-3">
							<div class="metric-card mini" id="branch-total-si">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Diff GSTIN SIs")}</div>
							</div>
						</div>
						<div class="col-lg-2 col-md-4 col-6 mb-3">
							<div class="metric-card mini" id="branch-pending-repost">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Repost Queued")}</div>
							</div>
						</div>
						<div class="col-lg-2 col-md-4 col-6 mb-3">
							<div class="metric-card mini" id="branch-repost-tracking">
								<div class="metric-value">--</div>
								<div class="metric-label">${__("Repost Tracked")}</div>
							</div>
						</div>
					</div>
					<div class="row">
						<div class="col-lg-6 col-md-12 mb-3">
							<div class="progress-card">
								<div class="d-flex justify-content-between mb-1">
									<span class="progress-card-label">${__("DN → PR Completion (Same GSTIN)")}</span>
									<span class="progress-card-pct" id="branch-dn-pct">--</span>
								</div>
								<div class="progress" style="height: 8px;">
									<div class="progress-bar bg-success" id="branch-dn-bar" role="progressbar" style="width: 0%"></div>
								</div>
							</div>
						</div>
						<div class="col-lg-6 col-md-12 mb-3">
							<div class="progress-card">
								<div class="d-flex justify-content-between mb-1">
									<span class="progress-card-label">${__("SI → PI Completion (Diff GSTIN)")}</span>
									<span class="progress-card-pct" id="branch-si-pct">--</span>
								</div>
								<div class="progress" style="height: 8px;">
									<div class="progress-bar bg-success" id="branch-si-bar" role="progressbar" style="width: 0%"></div>
								</div>
							</div>
						</div>
					</div>
				</div>

				<!-- ======= STOCK & COMPLIANCE ======= -->
				<div class="bns-section">
					<div class="row">
						<div class="col-lg-6">
							<div class="bns-section-title">
								<i class="fa fa-cubes"></i> ${__("Stock Health")}
							</div>
							<div class="row" id="stock-health-cards">
								<div class="col-6 mb-3">
									<div class="metric-card mini" id="stock-neg-items">
										<div class="metric-value">--</div>
										<div class="metric-label">${__("Negative Stock Items")}</div>
									</div>
								</div>
								<div class="col-6 mb-3">
									<div class="metric-card mini" id="stock-neg-wh">
										<div class="metric-value">--</div>
										<div class="metric-label">${__("Negative Stock WHs")}</div>
									</div>
								</div>
								<div class="col-6 mb-3">
									<div class="metric-card mini" id="stock-guarded">
										<div class="metric-value">--</div>
										<div class="metric-label">${__("Guarded Warehouses")}</div>
									</div>
								</div>
								<div class="col-6 mb-3">
									<div class="metric-card mini" id="stock-draft-recon">
										<div class="metric-value">--</div>
										<div class="metric-label">${__("Draft Reconciliations")}</div>
									</div>
								</div>
							</div>
						</div>
						<div class="col-lg-6">
							<div class="bns-section-title">
								<i class="fa fa-shield"></i> ${__("Compliance Health")}
							</div>
							<div class="row" id="compliance-cards">
								<div class="col-6 mb-3">
									<div class="metric-card mini" id="compliance-pr-attach">
										<div class="metric-value">--</div>
										<div class="metric-label">${__("PR Missing Invoice Attachment")}</div>
									</div>
								</div>
								<div class="col-6 mb-3">
									<div class="metric-card mini" id="compliance-pi-attach">
										<div class="metric-value">--</div>
										<div class="metric-label">${__("PI Missing Invoice Attachment")}</div>
									</div>
								</div>
							</div>
							<div class="row">
								<div class="col-6 mb-3">
									<div class="progress-card">
										<div class="d-flex justify-content-between mb-1">
											<span class="progress-card-label">${__("PR Attachment %")}</span>
											<span class="progress-card-pct" id="compliance-pr-pct">--</span>
										</div>
										<div class="progress" style="height: 8px;">
											<div class="progress-bar bg-info" id="compliance-pr-bar" role="progressbar" style="width: 0%"></div>
										</div>
									</div>
								</div>
								<div class="col-6 mb-3">
									<div class="progress-card">
										<div class="d-flex justify-content-between mb-1">
											<span class="progress-card-label">${__("PI Attachment %")}</span>
											<span class="progress-card-pct" id="compliance-pi-pct">--</span>
										</div>
										<div class="progress" style="height: 8px;">
											<div class="progress-bar bg-info" id="compliance-pi-bar" role="progressbar" style="width: 0%"></div>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>

				<!-- ======= QUICK LINKS ======= -->
				<div class="bns-section">
					<div class="bns-section-title">
						<i class="fa fa-link"></i> ${__("Quick Links")}
					</div>
					<div class="row">
						<div class="col-lg-3 col-md-6 mb-3">
							<div class="quick-link-card">
								<div class="quick-link-heading">${__("Accounting Reports")}</div>
								<a href="/app/query-report/Party GL" class="quick-link">${__("Party GL")}</a>
								<a href="/app/query-report/Bank GL" class="quick-link">${__("Bank GL")}</a>
								<a href="/app/query-report/Pure Accounts Receivable Summary" class="quick-link">${__("AR Summary")}</a>
								<a href="/app/query-report/Pure Accounts Payable Summary" class="quick-link">${__("AP Summary")}</a>
							</div>
						</div>
						<div class="col-lg-3 col-md-6 mb-3">
							<div class="quick-link-card">
								<div class="quick-link-heading">${__("Branch Accounting")}</div>
								<a href="/app/query-report/Internal Transfer Accounting Audit" class="quick-link">${__("Transfer Audit")}</a>
								<a href="/app/query-report/Internal Transfer Receive Mismatch" class="quick-link">${__("Receive Mismatch")}</a>
								<a href="/app/bns-branch-accounting-settings" class="quick-link">${__("Branch Settings")}</a>
							</div>
						</div>
						<div class="col-lg-3 col-md-6 mb-3">
							<div class="quick-link-card">
								<div class="quick-link-heading">${__("Stock Reports")}</div>
								<a href="/app/query-report/Outgoing Stock Audit - 1 BNS" class="quick-link">${__("Outgoing Stock Audit")}</a>
								<a href="/app/query-report/Stock Ledger Negative Episodes" class="quick-link">${__("Negative Episodes")}</a>
								<a href="/app/query-report/Negative Stock Resolution Report" class="quick-link">${__("Negative Resolution")}</a>
							</div>
						</div>
						<div class="col-lg-3 col-md-6 mb-3">
							<div class="quick-link-card">
								<div class="quick-link-heading">${__("Settings")}</div>
								<a href="/app/bns-settings" class="quick-link">${__("BNS Settings")}</a>
								<a href="/app/bns-branch-accounting-settings" class="quick-link">${__("Branch Accounting Settings")}</a>
								<a href="/app/query-report/Unlinked Customer-Supplier by PAN" class="quick-link">${__("Unlinked PAN Report")}</a>
							</div>
						</div>
					</div>
				</div>

				<!-- ======= DETAIL SECTIONS (collapsible) ======= -->
				<div class="row">
					<!-- Left Column - Expense Item Fixables -->
					<div class="col-lg-6">
						<div class="frappe-card" id="section-expense-fixables">
							<div class="card-header d-flex justify-content-between align-items-center section-header"
								 style="cursor: pointer; padding: 12px 15px; background: var(--subtle-bg);"
								 data-section="expense-fixables">
								<h5 class="mb-0">
									<i class="fa fa-chevron-down section-toggle collapsed" id="toggle-expense-fixables"></i>
									${__("Expense Item Fixables")}
								</h5>
							</div>
							<div class="card-body section-content" id="content-expense-fixables" style="display: none;">
								<div class="row mb-3" id="summary-cards">
									<div class="col-6">
										<div class="number-card" id="card-items-missing">
											<span class="text-muted">${__("Loading...")}</span>
										</div>
									</div>
									<div class="col-6">
										<div class="number-card" id="card-pi-fixable">
											<span class="text-muted">${__("Loading...")}</span>
										</div>
									</div>
								</div>
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
									<i class="fa fa-chevron-down section-toggle collapsed" id="toggle-party-link"></i>
									${__("Party & Transfer Fixables")}
								</h5>
							</div>
							<div class="card-body section-content" id="content-party-link" style="display: none;">
								<div class="row mb-3">
									<div class="col-6">
										<div class="number-card" id="card-unlinked-pan">
											<span class="text-muted">${__("Loading...")}</span>
										</div>
									</div>
									<div class="col-6">
										<div class="number-card" id="card-transfer-mismatch">
											<span class="text-muted">${__("Loading...")}</span>
										</div>
									</div>
								</div>
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
								<div class="sub-section mb-3" id="subsection-party-squareoff">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="party-squareoff">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-party-squareoff"></i>
											${__("Linked Party Square-Off")}
											<span class="badge badge-warning ml-2" id="badge-party-squareoff">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-party-squareoff" style="display: none; padding-top: 10px;">
										<p class="text-muted small mb-2">
											${__("Linked Customer/Supplier pairs whose party accounts carry opposite-signed balances. Post a balanced contra Journal Entry to net them on the GL — fixes Balance Sheet, Trial Balance, and General Ledger.")}
										</p>
										<div class="d-flex flex-wrap align-items-center mb-2" style="gap: 8px;">
											<label class="small mb-0">${__("As of")}</label>
											<input type="date" class="form-control form-control-sm" id="bns-squareoff-asof" style="max-width: 160px;">
											<button class="btn btn-primary btn-xs" id="btn-squareoff-preview">
												<i class="fa fa-search"></i> ${__("Preview Crossed Pairs")}
											</button>
											<button class="btn btn-success btn-xs" id="btn-squareoff-post" disabled>
												<i class="fa fa-check"></i> ${__("Post Contra Entries")}
											</button>
										</div>
										<div id="table-party-squareoff">
											<p class="text-muted">${__("Click Preview to load.")}</p>
										</div>
										<hr>
										<div class="mt-3">
											<strong class="text-danger small">${__("Historical Backfill")}</strong>
											<p class="text-muted small mb-2">
												${__("One-time pass for existing imbalances. JVs are posted dated the cutoff, so existing period reports reconcile retroactively.")}
											</p>
											<div class="d-flex flex-wrap align-items-center mb-2" style="gap: 8px;">
												<label class="small mb-0">${__("Cutoff date")}</label>
												<input type="date" class="form-control form-control-sm" id="bns-squareoff-cutoff" style="max-width: 160px;">
												<button class="btn btn-warning btn-xs" id="btn-backfill-preview">
													<i class="fa fa-history"></i> ${__("Preview Backfill")}
												</button>
												<button class="btn btn-danger btn-xs" id="btn-backfill-post" disabled>
													<i class="fa fa-bolt"></i> ${__("Post Backfill JVs")}
												</button>
											</div>
											<div id="table-party-backfill">
												<p class="text-muted">${__("Click Preview Backfill to load.")}</p>
											</div>
										</div>
									</div>
								</div>
								<div class="sub-section mb-3" id="subsection-payment-reconciliation">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="payment-reconciliation">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-payment-reconciliation"></i>
											${__("Payment Reconciliation (FIFO)")}
											<span class="badge badge-info ml-2" id="badge-payment-reconciliation">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-payment-reconciliation" style="display: none; padding-top: 10px;">
										<p class="text-muted small mb-2">
											${__("Auto-match open Sales/Purchase Invoices against their Payment Entries and the square-off contra JV using ERPNext's Payment Reconciliation tool (FIFO). Wrapped by BNS Settings \u2192 Auto Payment Reconciliation.")}
										</p>
										<div class="d-flex flex-wrap align-items-center mb-2" style="gap: 8px;">
											<button class="btn btn-primary btn-xs" id="btn-reconcile-preview">
												<i class="fa fa-search"></i> ${__("Preview Unreconciled Parties")}
											</button>
											<button class="btn btn-success btn-xs" id="btn-reconcile-run" disabled>
												<i class="fa fa-refresh"></i> ${__("Run Reconciliation Now")}
											</button>
											<button class="btn btn-warning btn-xs" id="btn-full-pipeline-run">
												<i class="fa fa-bolt"></i> ${__("Run Pre \u2192 Square-Off \u2192 Post")}
											</button>
											<span class="text-muted small" id="reconcile-meta"></span>
										</div>
										<div id="table-payment-reconciliation">
											<p class="text-muted">${__("Click Preview to load.")}</p>
										</div>
									</div>
								</div>
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
											${__("DN/SI with missing or mismatched PR/PI. Data comes from the last prepared report.")}
										</p>
										<div class="mb-2 d-flex align-items-center" style="gap: 8px;">
											<button class="btn btn-primary btn-xs" id="btn-prepare-mismatch-report">
												<i class="fa fa-refresh"></i> ${__("Prepare New Report")}
											</button>
											<a href="/app/query-report/Internal%20Transfer%20Receive%20Mismatch" target="_blank" class="btn btn-secondary btn-xs">
												<i class="fa fa-external-link"></i> ${__("Open Full Report")}
											</a>
											<span class="text-muted small" id="mismatch-report-status"></span>
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

				${this._tds_fixables_html()}

				<!-- Food Company Addresses -->
				<div class="row mt-0" id="row-food-addresses" style="display: none;">
					<div class="col-lg-6">
						<div class="frappe-card" id="section-food-addresses">
							<div class="card-header d-flex justify-content-between align-items-center section-header"
								 style="cursor: pointer; padding: 12px 15px; background: var(--subtle-bg);"
								 data-section="food-addresses">
								<h5 class="mb-0">
									<i class="fa fa-chevron-down section-toggle collapsed" id="toggle-food-addresses"></i>
									<i class="fa fa-map-marker text-muted mr-2"></i>
									${__("Company Addresses & FSSAI")}
									<span class="badge badge-secondary ml-2" id="badge-food-addresses">0</span>
								</h5>
							</div>
							<div class="card-body section-content" id="content-food-addresses" style="display: none;">
								<p class="text-muted small mb-2" id="food-addresses-hint">
									${__("Only shown when Company is marked as a Food Company.")}
								</p>
								<div id="table-food-addresses" class="food-addresses-table-wrap">
									<p class="text-muted">${__("Loading...")}</p>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- SRBNB Reconciliation -->
				<div class="row mt-3">
					<div class="col-12">
						<div class="frappe-card" id="section-srbnb-reconciliation">
							<div class="card-header d-flex justify-content-between align-items-center section-header"
								 style="cursor: pointer; padding: 12px 15px; background: var(--subtle-bg);"
								 data-section="srbnb-reconciliation">
								<h5 class="mb-0">
									<i class="fa fa-chevron-down section-toggle collapsed" id="toggle-srbnb-reconciliation"></i>
									<i class="fa fa-warehouse text-muted mr-2"></i>
									${__("SRBNB Reconciliation")}
								</h5>
							</div>
							<div class="card-body section-content" id="content-srbnb-reconciliation" style="display: none;">
								<p class="text-muted small mb-3">
									${__("Stock Received But Not Billed — categorises every GL entry on the SRBNB account into 4 actionable buckets.")}
								</p>

								<!-- Summary cards row -->
								<div class="row mb-3" id="srbnb-summary-cards">
									<div class="col mb-2">
										<div class="card text-center p-2" style="cursor:pointer;" data-bucket="internal-prs">
											<small class="text-muted">${__("BNS Internal PRs")}</small>
											<div class="font-weight-bold text-info" id="srbnb-total-internal-prs">${__("Loading...")}</div>
											<small class="text-muted" id="srbnb-count-internal-prs"></small>
										</div>
									</div>
									<div class="col mb-2">
										<div class="card text-center p-2" style="cursor:pointer;" data-bucket="open-prs">
											<small class="text-muted">${__("Open PRs (Liability)")}</small>
											<div class="font-weight-bold" id="srbnb-total-open-prs">${__("Loading...")}</div>
											<small class="text-muted" id="srbnb-count-open-prs"></small>
										</div>
									</div>
									<div class="col mb-2">
										<div class="card text-center p-2" style="cursor:pointer;" data-bucket="orphan-pi">
											<small class="text-muted">${__("Orphan PI Debits")}</small>
											<div class="font-weight-bold" id="srbnb-total-orphan-pi">${__("Loading...")}</div>
											<small class="text-muted" id="srbnb-count-orphan-pi"></small>
										</div>
									</div>
									<div class="col mb-2">
										<div class="card text-center p-2" style="cursor:pointer;" data-bucket="stock-entries">
											<small class="text-muted">${__("Stock Entries")}</small>
											<div class="font-weight-bold" id="srbnb-total-stock-entries">${__("Loading...")}</div>
											<small class="text-muted" id="srbnb-count-stock-entries"></small>
										</div>
									</div>
									<div class="col mb-2">
										<div class="card text-center p-2" style="cursor:pointer;" data-bucket="journal-entries">
											<small class="text-muted">${__("Journal Entries")}</small>
											<div class="font-weight-bold" id="srbnb-total-journal-entries">${__("Loading...")}</div>
											<small class="text-muted" id="srbnb-count-journal-entries"></small>
										</div>
									</div>
								</div>

								<!-- Net balance -->
								<div class="mb-3 d-flex align-items-center" style="gap: 12px;">
									<span class="text-muted small">${__("SRBNB Net Balance:")}</span>
									<span class="font-weight-bold" id="srbnb-net-balance">—</span>
									<span class="text-muted small" id="srbnb-account-name"></span>
									<span class="text-muted small" id="srbnb-excluded-info"></span>
								</div>

								<!-- BNS Internal PRs bucket -->
								<div class="sub-section mb-3" id="subsection-srbnb-internal-prs">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="srbnb-internal-prs">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-srbnb-internal-prs"></i>
											${__("BNS Internal PRs (Clear SRBNB → COGS)")}
											<span class="badge badge-info ml-2" id="badge-srbnb-internal-prs">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-srbnb-internal-prs" style="display: none; padding-top: 10px;">
										<p class="text-muted small mb-2">
											${__("Internal transfers between own warehouses. SRBNB liability can be cleared via a Journal Entry: Dr SRBNB / Cr Clearing Account (configurable in BNS Settings, default COGS).")}
										</p>
										<div class="d-flex flex-wrap align-items-center mb-2" style="gap: 8px;">
											<label class="small mb-0">${__("JE Posting Date:")}</label>
											<input type="date" class="form-control form-control-sm" id="srbnb-internal-je-date" style="max-width: 160px;">
											<button class="btn btn-warning btn-xs" id="btn-srbnb-clear-internal" disabled>
												<i class="fa fa-bolt"></i> ${__("Post Clearing JE (Draft)")}
											</button>
										</div>
										<div id="table-srbnb-internal-prs"><p class="text-muted">${__("Loading...")}</p></div>
									</div>
								</div>

								<!-- Open PRs bucket -->
								<div class="sub-section mb-3" id="subsection-srbnb-open-prs">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="srbnb-open-prs">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-srbnb-open-prs"></i>
											${__("Open Purchase Receipts (Real Liability)")}
											<span class="badge badge-danger ml-2" id="badge-srbnb-open-prs">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-srbnb-open-prs" style="display: none; padding-top: 10px;">
										<div id="table-srbnb-open-prs"><p class="text-muted">${__("Loading...")}</p></div>
									</div>
								</div>

								<!-- Orphan PI Debits bucket -->
								<div class="sub-section mb-3" id="subsection-srbnb-orphan-pi">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="srbnb-orphan-pi">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-srbnb-orphan-pi"></i>
											${__("Orphan PI Debits (No PR Link)")}
											<span class="badge badge-warning ml-2" id="badge-srbnb-orphan-pi">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-srbnb-orphan-pi" style="display: none; padding-top: 10px;">
										<div id="table-srbnb-orphan-pi"><p class="text-muted">${__("Loading...")}</p></div>
									</div>
								</div>

								<!-- Stock Entries bucket -->
								<div class="sub-section mb-3" id="subsection-srbnb-stock-entries">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="srbnb-stock-entries">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-srbnb-stock-entries"></i>
											${__("Stock Entries (Intra-state Transfers)")}
											<span class="badge badge-info ml-2" id="badge-srbnb-stock-entries">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-srbnb-stock-entries" style="display: none; padding-top: 10px;">
										<div id="table-srbnb-stock-entries"><p class="text-muted">${__("Loading...")}</p></div>
									</div>
								</div>

								<!-- Journal Entries bucket -->
								<div class="sub-section mb-3" id="subsection-srbnb-journal-entries">
									<div class="sub-section-header d-flex justify-content-between align-items-center"
										 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
										 data-subsection="srbnb-journal-entries">
										<strong>
											<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-srbnb-journal-entries"></i>
											${__("Journal Entries (Manual Adjustments)")}
											<span class="badge badge-secondary ml-2" id="badge-srbnb-journal-entries">0</span>
										</strong>
									</div>
									<div class="sub-section-content" id="subcontent-srbnb-journal-entries" style="display: none; padding-top: 10px;">
										<div id="table-srbnb-journal-entries"><p class="text-muted">${__("Loading...")}</p></div>
									</div>
								</div>

							</div>
						</div>
					</div>
				</div>

			${this.get_styles()}
		`);

		this.bind_events();
	}

	// =====================================================================
	// TDS Category Fixables (System Manager only)
	// =====================================================================

	_tds_fixables_html() {
		if (!this.is_system_manager) return "";
		return `
			<!-- TDS Category Fixables (System Manager only) -->
			<div class="row mt-0" id="row-tds-fixables">
				<div class="col-lg-12">
					<div class="frappe-card" id="section-tds-fixables">
						<div class="card-header d-flex justify-content-between align-items-center section-header"
							 style="cursor: pointer; padding: 12px 15px; background: var(--subtle-bg);"
							 data-section="tds-fixables">
							<h5 class="mb-0">
								<i class="fa fa-chevron-down section-toggle collapsed" id="toggle-tds-fixables"></i>
								<i class="fa fa-percent text-muted mr-2"></i>
								${__("TDS Category Fixables")}
								<span class="badge badge-danger ml-2">${__("System Manager")}</span>
							</h5>
						</div>
						<div class="card-body section-content" id="content-tds-fixables" style="display: none;">
							<p class="text-muted small mb-3">
								${__("Fill missing Tax Withholding (TDS) Categories on suppliers, and correct the TDS Category on this fiscal year's Purchase Invoices where it disagrees with the supplier. Correcting a PI here updates the category field only — it does not recompute TDS amounts.")}
							</p>

							<div class="sub-section mb-3" id="subsection-suppliers-missing-tds">
								<div class="sub-section-header d-flex justify-content-between align-items-center"
									 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
									 data-subsection="suppliers-missing-tds">
									<strong>
										<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-suppliers-missing-tds"></i>
										${__("Suppliers Missing TDS Category")}
										<span class="badge badge-secondary ml-2" id="badge-suppliers-missing-tds">0</span>
									</strong>
								</div>
								<div class="sub-section-content" id="subcontent-suppliers-missing-tds" style="display: none; padding-top: 10px;">
									<div id="table-suppliers-missing-tds">
										<p class="text-muted">${__("Loading...")}</p>
									</div>
								</div>
							</div>

							<div class="sub-section mb-3" id="subsection-pi-wrong-tds">
								<div class="sub-section-header d-flex justify-content-between align-items-center"
									 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
									 data-subsection="pi-wrong-tds">
									<strong>
										<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-pi-wrong-tds"></i>
										${__("Purchase Invoices with Wrong TDS Category (Current FY)")}
										<span class="badge badge-warning ml-2" id="badge-pi-wrong-tds">0</span>
									</strong>
								</div>
								<div class="sub-section-content" id="subcontent-pi-wrong-tds" style="display: none; padding-top: 10px;">
									<div class="mb-2">
										<button class="btn btn-primary btn-xs" id="btn-bulk-fix-tds" disabled>
											<i class="fa fa-wrench"></i> ${__("Bulk Fix Selected")}
										</button>
										<button class="btn btn-secondary btn-xs ml-2" id="btn-select-all-tds">
											${__("Select All")}
										</button>
									</div>
									<div id="table-pi-wrong-tds">
										<p class="text-muted">${__("Loading...")}</p>
									</div>
								</div>
							</div>

							<div class="sub-section" id="subsection-all-suppliers-tds">
								<div class="sub-section-header d-flex justify-content-between align-items-center"
									 style="cursor: pointer; padding: 8px 10px; background: var(--control-bg); border-radius: 4px;"
									 data-subsection="all-suppliers-tds">
									<strong>
										<i class="fa fa-chevron-right subsection-toggle collapsed" id="subtoggle-all-suppliers-tds"></i>
										${__("All Suppliers with TDS Category")}
										<span class="badge badge-info ml-2" id="badge-all-suppliers-tds">0</span>
									</strong>
								</div>
								<div class="sub-section-content" id="subcontent-all-suppliers-tds" style="display: none; padding-top: 10px;">
									<div id="table-all-suppliers-tds">
										<p class="text-muted">${__("Loading...")}</p>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		`;
	}

	async load_tds_fixables() {
		if (!this.is_system_manager) return;
		await this.load_tax_withholding_categories();
		await Promise.all([
			this.load_suppliers_missing_tds(),
			this.load_pi_wrong_tds(),
			this.load_all_suppliers_tds(),
		]);
	}

	async load_tax_withholding_categories() {
		if (!this.is_system_manager) return;
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_tax_withholding_categories",
			});
			this.tds_categories = result.message || [];
		} catch (e) {
			console.error("Failed to load TDS categories:", e);
		}
	}

	_tds_category_options(selected) {
		let opts = '<option value="">' + __("Select...") + "</option>";
		this.tds_categories.forEach(function (c) {
			const sel = selected && selected === c.name ? " selected" : "";
			opts += '<option value="' + frappe.utils.escape_html(c.name) + '"' + sel + ">" + frappe.utils.escape_html(c.name) + "</option>";
		});
		return opts;
	}

	async load_suppliers_missing_tds() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_suppliers_missing_tds_category",
			});
			const data = result.message || {};
			this.wrapper.find("#badge-suppliers-missing-tds").text(data.count || 0);
			this.render_suppliers_missing_tds_table(data.suppliers || []);
		} catch (e) {
			console.error("Failed to load suppliers missing TDS:", e);
			this.wrapper.find("#table-suppliers-missing-tds").html('<p class="text-danger">' + __("Failed to load data") + "</p>");
		}
	}

	render_suppliers_missing_tds_table(suppliers) {
		const container = this.wrapper.find("#table-suppliers-missing-tds");
		if (!suppliers || suppliers.length === 0) {
			container.html('<p class="text-success mb-0">' + __("All suppliers have a TDS Category set!") + "</p>");
			return;
		}
		const self = this;
		let html = '<table class="table table-sm"><thead><tr>';
		html += "<th>" + __("Supplier") + "</th><th>" + __("TDS Category") + '</th><th style="width: 60px;"></th></tr></thead><tbody>';
		suppliers.forEach(function (s) {
			html += '<tr data-supplier="' + frappe.utils.escape_html(s.supplier) + '">';
			html += '<td><a href="/app/supplier/' + encodeURIComponent(s.supplier) + '" target="_blank">' + frappe.utils.escape_html(s.supplier_name || s.supplier) + "</a>";
			if (s.pan) html += '<br><small class="text-muted">PAN: ' + frappe.utils.escape_html(s.pan) + "</small>";
			html += "</td>";
			html += '<td><select class="form-control tds-category-select" data-supplier="' + frappe.utils.escape_html(s.supplier) + '">' + self._tds_category_options() + "</select></td>";
			html += '<td><button class="btn btn-primary btn-xs btn-set-tds" data-supplier="' + frappe.utils.escape_html(s.supplier) + '">' + __("Set") + "</button></td>";
			html += "</tr>";
		});
		html += "</tbody></table>";
		container.html(html);

		container.find(".btn-set-tds").on("click", function () {
			const supplier = $(this).data("supplier");
			const category = container.find('.tds-category-select[data-supplier="' + supplier + '"]').val();
			self.set_supplier_tds_category(supplier, category, $(this));
		});
	}

	async set_supplier_tds_category(supplier, category, btn) {
		if (!category) {
			frappe.msgprint(__("Please select a TDS Category"));
			return;
		}
		btn.prop("disabled", true).text(__("..."));
		try {
			await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.set_supplier_tds_category",
				args: { supplier: supplier, tax_withholding_category: category },
			});
			frappe.show_alert({ message: __("Set for {0}", [supplier]), indicator: "green" });
			btn.closest("tr").fadeOut(300, function () { $(this).remove(); });
			this.load_all_suppliers_tds();
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
			btn.prop("disabled", false).text(__("Set"));
		}
	}

	async load_all_suppliers_tds() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_all_suppliers_with_tds_category",
			});
			const data = result.message || {};
			this.wrapper.find("#badge-all-suppliers-tds").text(data.count || 0);
			this.render_all_suppliers_tds_table(data.suppliers || []);
		} catch (e) {
			console.error("Failed to load all suppliers TDS:", e);
			this.wrapper.find("#table-all-suppliers-tds").html('<p class="text-danger">' + __("Failed to load data") + "</p>");
		}
	}

	render_all_suppliers_tds_table(suppliers) {
		const container = this.wrapper.find("#table-all-suppliers-tds");
		if (!suppliers || suppliers.length === 0) {
			container.html('<p class="text-muted mb-0">' + __("No suppliers found.") + "</p>");
			return;
		}
		const self = this;
		let html = '<table class="table table-sm"><thead><tr>';
		html += "<th>" + __("Supplier") + "</th><th>" + __("Group") + "</th><th>" + __("TDS Category") + '</th><th style="width: 60px;"></th></tr></thead><tbody>';
		suppliers.forEach(function (s) {
			html += "<tr>";
			html += '<td><a href="/app/supplier/' + encodeURIComponent(s.supplier) + '" target="_blank">' + frappe.utils.escape_html(s.supplier_name || s.supplier) + "</a></td>";
			html += "<td><small>" + frappe.utils.escape_html(s.supplier_group || "-") + "</small></td>";
			html += '<td><select class="form-control tds-category-select-all" data-supplier="' + frappe.utils.escape_html(s.supplier) + '">' + self._tds_category_options(s.tax_withholding_category) + "</select></td>";
			html += '<td><button class="btn btn-secondary btn-xs btn-set-tds-all" data-supplier="' + frappe.utils.escape_html(s.supplier) + '">' + __("Set") + "</button></td>";
			html += "</tr>";
		});
		html += "</tbody></table>";
		container.html(html);

		container.find(".btn-set-tds-all").on("click", function () {
			const supplier = $(this).data("supplier");
			const category = container.find('.tds-category-select-all[data-supplier="' + supplier + '"]').val();
			self.set_supplier_tds_category(supplier, category, $(this));
		});
	}

	async load_pi_wrong_tds() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_pis_with_wrong_tds_category",
				args: { company: this.get_company() },
			});
			const data = result.message || {};
			this.wrapper.find("#badge-pi-wrong-tds").text(data.count || 0);
			this.render_pi_wrong_tds_table(data.items || []);
		} catch (e) {
			console.error("Failed to load PI wrong TDS:", e);
			this.wrapper.find("#table-pi-wrong-tds").html('<p class="text-danger">' + __("Failed to load data") + "</p>");
		}
	}

	render_pi_wrong_tds_table(items) {
		const container = this.wrapper.find("#table-pi-wrong-tds");
		if (!items || items.length === 0) {
			container.html('<p class="text-success mb-0">' + __("All current-FY Purchase Invoices match their supplier's TDS Category!") + "</p>");
			this.wrapper.find("#btn-bulk-fix-tds").prop("disabled", true);
			return;
		}
		const self = this;
		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th style="width: 30px;"><input type="checkbox" id="check-all-pi-tds"></th>';
		html += "<th>" + __("PI / Supplier") + "</th><th>" + __("PI Category") + "</th><th>" + __("Correct (Supplier)") + "</th><th>" + __("Apply TDS") + "</th></tr></thead><tbody>";
		items.forEach(function (it) {
			html += '<tr class="row-tds-fixable">';
			html += '<td><input type="checkbox" class="pi-tds-checkbox" data-pi="' + frappe.utils.escape_html(it.purchase_invoice) + '" data-correct-category="' + frappe.utils.escape_html(it.supplier_category) + '"></td>';
			html += '<td><a href="/app/purchase-invoice/' + encodeURIComponent(it.purchase_invoice) + '" target="_blank">' + frappe.utils.escape_html(it.purchase_invoice) + "</a>";
			html += '<br><small class="text-muted">' + frappe.utils.escape_html(it.supplier_name || it.supplier) + " · " + frappe.utils.escape_html(String(it.posting_date || "")) + "</small></td>";
			html += '<td><small class="text-danger">' + frappe.utils.escape_html(it.pi_category || "—") + "</small></td>";
			html += '<td><small class="text-success">' + frappe.utils.escape_html(it.supplier_category) + "</small></td>";
			html += "<td>" + (parseInt(it.apply_tds) ? '<span class="badge badge-success">' + __("Yes") + "</span>" : '<span class="badge badge-secondary">' + __("No") + "</span>") + "</td>";
			html += "</tr>";
		});
		html += "</tbody></table>";
		container.html(html);

		container.find(".pi-tds-checkbox").on("change", function () { self.update_tds_bulk_button(); });
		container.find("#check-all-pi-tds").on("change", function () {
			container.find(".pi-tds-checkbox:not(:disabled)").prop("checked", $(this).is(":checked"));
			self.update_tds_bulk_button();
		});
		this.update_tds_bulk_button();
	}

	update_tds_bulk_button() {
		const checked = this.wrapper.find(".pi-tds-checkbox:checked").length;
		const btn = this.wrapper.find("#btn-bulk-fix-tds");
		btn.prop("disabled", checked === 0);
		btn.html('<i class="fa fa-wrench"></i> ' + (checked > 0 ? __("Fix ({0})", [checked]) : __("Bulk Fix Selected")));
	}

	async bulk_fix_tds_selected() {
		const selected = [];
		this.wrapper.find(".pi-tds-checkbox:checked").each(function () {
			selected.push({ purchase_invoice: $(this).data("pi"), correct_category: $(this).data("correct-category") });
		});
		if (selected.length === 0) {
			frappe.msgprint(__("No invoices selected"));
			return;
		}
		const self = this;
		frappe.confirm(
			__("Correct the TDS Category on {0} Purchase Invoices to match their suppliers? This updates the category field only (no TDS recompute) and runs in the background.", [selected.length]),
			async function () {
				const btn = self.wrapper.find("#btn-bulk-fix-tds");
				btn.prop("disabled", true).html('<i class="fa fa-spinner fa-spin"></i> ' + __("Queuing..."));
				try {
					const result = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.bulk_fix_pi_tds_category",
						args: { items: selected },
					});
					const data = result.message;
					if (data.status === "error") {
						frappe.msgprint({ title: __("Validation failed"), message: __("No fixable invoices found."), indicator: "red" });
						btn.prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix Selected"));
						return;
					}
					self.show_tds_fix_progress(data.total_invoices);
				} catch (e) {
					let msg = "";
					try {
						if (e && e._server_messages) {
							const arr = JSON.parse(e._server_messages);
							if (arr && arr.length) { const first = JSON.parse(arr[0]); msg = first.message || arr[0]; }
						}
					} catch (_) { /* fall through */ }
					if (!msg) msg = (e && (e.message || e.statusText)) || "";
					if (msg) frappe.show_alert({ message: __("Bulk fix failed: {0}", [frappe.utils.escape_html(String(msg))]), indicator: "red" }, 8);
					btn.prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix Selected"));
				}
			}
		);
	}

	show_tds_fix_progress(total) {
		const btn = this.wrapper.find("#btn-bulk-fix-tds");
		btn.prop("disabled", true).html('<i class="fa fa-spinner fa-spin"></i> ' + __("Processing..."));
		this.wrapper.find("#btn-select-all-tds").prop("disabled", true);

		const container = this.wrapper.find("#table-pi-wrong-tds");
		container.before(`
			<div id="tds-fix-progress" class="mb-3" style="padding: 10px; background: var(--control-bg); border-radius: 6px;">
				<div class="d-flex justify-content-between align-items-center mb-1">
					<span class="text-muted" style="font-size: 0.85rem;" id="tds-fix-status">
						<i class="fa fa-spinner fa-spin"></i> ${__("Processing 0 / {0} invoices...", [total])}
					</span>
					<span class="text-muted" style="font-size: 0.8rem;" id="tds-fix-pct">0%</span>
				</div>
				<div class="progress" style="height: 8px;">
					<div class="progress-bar bg-primary progress-bar-striped progress-bar-animated"
						 id="tds-fix-bar" role="progressbar" style="width: 0%; transition: width 0.4s ease;"></div>
				</div>
			</div>
		`);

		const self = this;
		this._onTdsFixProgress = function (data) {
			const pct = Math.round((data.done / data.total) * 100);
			self.wrapper.find("#tds-fix-bar").css("width", pct + "%");
			self.wrapper.find("#tds-fix-pct").text(pct + "%");
			self.wrapper.find("#tds-fix-status").html('<i class="fa fa-spinner fa-spin"></i> ' + __("Processing {0} / {1} invoices... ({2} fixed)", [data.done, data.total, data.success_count]));
		};
		this._onTdsFixComplete = function (data) {
			self.hide_tds_fix_progress();
			if (data.success_count > 0) {
				frappe.show_alert({ message: __("Corrected TDS Category on {0} invoices", [data.success_count]), indicator: "green" });
			}
			if (data.error_count > 0) {
				let errorMsg = "";
				(data.errors || []).forEach(function (e) { errorMsg += (e.purchase_invoice || "?") + ": " + e.error + "<br>"; });
				frappe.msgprint({ title: __("{0} invoices failed", [data.error_count]), message: errorMsg, indicator: "orange" });
			}
			self.load_tds_fixables();
		};
		frappe.realtime.on("bns_tds_fix_progress", this._onTdsFixProgress);
		frappe.realtime.on("bns_tds_fix_complete", this._onTdsFixComplete);
	}

	hide_tds_fix_progress() {
		this.wrapper.find("#tds-fix-progress").remove();
		this.wrapper.find("#btn-bulk-fix-tds").prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix Selected"));
		this.wrapper.find("#btn-select-all-tds").prop("disabled", false);
		if (this._onTdsFixProgress) { frappe.realtime.off("bns_tds_fix_progress", this._onTdsFixProgress); this._onTdsFixProgress = null; }
		if (this._onTdsFixComplete) { frappe.realtime.off("bns_tds_fix_complete", this._onTdsFixComplete); this._onTdsFixComplete = null; }
	}

	get_styles() {
		return `<style>
			.bns-dashboard-container {
				padding: 15px;
				max-width: 1400px;
				margin: 0 auto;
			}

			/* Section titles */
			.bns-section {
				margin-bottom: 20px;
			}
			.bns-section-title {
				font-size: 1rem;
				font-weight: 700;
				color: var(--heading-color);
				margin-bottom: 12px;
				padding-bottom: 6px;
				border-bottom: 2px solid var(--primary);
				display: inline-block;
			}
			.bns-section-title i {
				margin-right: 6px;
				color: var(--primary);
			}

			/* Metric cards (top-level health numbers) */
			.metric-card {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 16px;
				text-align: center;
				transition: box-shadow 0.2s, border-color 0.2s;
				height: 100%;
			}
			.metric-card:hover {
				box-shadow: 0 2px 8px rgba(0,0,0,0.08);
				border-color: var(--primary);
			}
			.metric-card.mini {
				padding: 10px;
			}
			.metric-card .metric-value {
				font-size: 1.6rem;
				font-weight: 700;
				line-height: 1.2;
			}
			.metric-card.mini .metric-value {
				font-size: 1.3rem;
			}
			.metric-card .metric-label {
				font-size: 0.75rem;
				color: var(--text-muted);
				margin-top: 4px;
				text-transform: uppercase;
				letter-spacing: 0.3px;
			}
			.metric-card .metric-sub {
				font-size: 0.7rem;
				color: var(--text-light);
				margin-top: 2px;
			}
			.metric-card.ok .metric-value { color: var(--green-500); }
			.metric-card.warn .metric-value { color: var(--orange-500); }
			.metric-card.danger .metric-value { color: var(--red-500); }
			.metric-card.info .metric-value { color: var(--blue-500); }

			/* Chart wrapper */
			.chart-wrapper {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 16px;
				min-height: 80px;
			}

			/* Progress cards */
			.progress-card {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 12px 16px;
			}
			.progress-card-label {
				font-size: 0.8rem;
				font-weight: 600;
				color: var(--text-color);
			}
			.progress-card-pct {
				font-size: 0.8rem;
				font-weight: 700;
				color: var(--primary);
			}

			/* Quick links */
			.quick-link-card {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 14px;
				height: 100%;
			}
			.quick-link-heading {
				font-size: 0.8rem;
				font-weight: 700;
				text-transform: uppercase;
				letter-spacing: 0.5px;
				color: var(--text-muted);
				margin-bottom: 8px;
				padding-bottom: 6px;
				border-bottom: 1px solid var(--border-color);
			}
			.quick-link {
				display: block;
				font-size: 0.85rem;
				padding: 3px 0;
				color: var(--text-color);
				text-decoration: none;
			}
			.quick-link:hover {
				color: var(--primary);
			}

			/* Legacy number cards (detail sections) */
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
			.bns-dashboard-container .row-fssai-ok {
				background: rgba(34, 197, 94, 0.12);
				border-left: 3px solid var(--green-500, #22c55e);
			}
			.bns-dashboard-container .row-fssai-missing {
				background: rgba(239, 68, 68, 0.1);
				border-left: 3px solid var(--red-500, #ef4444);
			}
			.bns-dashboard-container .food-address-name {
				font-weight: 600;
				color: var(--text-color);
			}
			.bns-dashboard-container .food-address-full {
				font-size: 0.8rem;
				color: var(--text-muted);
				line-height: 1.4;
				white-space: pre-line;
			}
			.bns-dashboard-container .fssai-badge {
				font-family: var(--font-family-mono, monospace);
				font-size: 0.8rem;
				padding: 2px 6px;
				border-radius: 4px;
			}
			.bns-dashboard-container .food-addresses-table-wrap {
				max-height: 400px;
				overflow-y: auto;
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
		</style>`;
	}

	bind_events() {
		const self = this;

		this.wrapper.find(".section-header").on("click", function () {
			const section = $(this).data("section");
			self.toggle_section(section);
		});

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

		// TDS Category Fixables (System Manager only; elements absent otherwise)
		this.wrapper.find("#btn-bulk-fix-tds").on("click", function () {
			self.bulk_fix_tds_selected();
		});
		this.wrapper.find("#btn-select-all-tds").on("click", function () {
			self.wrapper.find(".pi-tds-checkbox:not(:disabled)").prop("checked", true);
			self.update_tds_bulk_button();
		});

		this.wrapper.find("#btn-prepare-mismatch-report").on("click", function () {
			self.prepare_mismatch_report();
		});

		this.wrapper.find("#btn-squareoff-preview").on("click", function () {
			self.preview_common_party_squareoff();
		});
		this.wrapper.find("#btn-squareoff-post").on("click", function () {
			self.post_common_party_squareoff();
		});
		this.wrapper.find("#btn-backfill-preview").on("click", function () {
			self.preview_historical_backfill();
		});
		this.wrapper.find("#btn-backfill-post").on("click", function () {
			self.post_historical_backfill();
		});

		// SRBNB clear internal PRs button
		this.wrapper.find("#btn-srbnb-clear-internal").on("click", function () {
			self.clear_internal_srbnb();
		});

		// SRBNB summary card → expand matching sub-section
		this.wrapper.find("#srbnb-summary-cards [data-bucket]").on("click", function () {
			const bucket = $(this).data("bucket");
			const map = {
				"internal-prs": "srbnb-internal-prs",
				"open-prs": "srbnb-open-prs",
				"orphan-pi": "srbnb-orphan-pi",
				"stock-entries": "srbnb-stock-entries",
				"journal-entries": "srbnb-journal-entries",
			};
			const sub = map[bucket];
			if (sub) {
				// Ensure parent section is open
				const content = self.wrapper.find("#content-srbnb-reconciliation");
				if (!content.is(":visible")) self.toggle_section("srbnb-reconciliation");
				// Open the sub-section
				const subContent = self.wrapper.find("#subcontent-" + sub);
				if (!subContent.is(":visible")) self.toggle_subsection(sub);
			}
		});

		this.wrapper.find("#btn-reconcile-preview").on("click", function () {
			self.preview_payment_reconciliation();
		});
		this.wrapper.find("#btn-reconcile-run").on("click", function () {
			self.run_payment_reconciliation();
		});
		this.wrapper.find("#btn-full-pipeline-run").on("click", function () {
			self.run_full_squareoff_pipeline();
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

	// =====================================================================
	// Data Loading
	// =====================================================================

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
		await Promise.all([
			this.load_expense_accounts(),
			this.load_health_overview(),
			this.load_summary(),
			this.load_items_missing_expense_account(),
			this.load_pi_wrong_expense_account(),
			this.load_all_expense_items(),
			this.load_food_company_addresses(),
			this.load_unlinked_pan(),
			this.load_transfer_mismatches(),
			this.load_srbnb_reconciliation(),
			this.load_tds_fixables(),
		]);
	}

	// =====================================================================
	// Health Overview (single API, populates all top sections)
	// =====================================================================

	async load_health_overview() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_health_check_overview",
				args: { company: this.get_company() },
			});
			this.render_health_overview(result.message);
		} catch (e) {
			console.error("Health overview load failed:", e);
		}
	}

	render_health_overview(data) {
		if (!data) return;

		// --- Branch Accounting cards ---
		const ba = data.branch_accounting || {};
		this._set_metric("branch-dn-pending", ba.dns_without_pr, null,
			ba.dns_without_pr > 0 ? "warn" : "ok");
		this._set_metric("branch-si-pending", ba.sis_without_pi, null,
			ba.sis_without_pi > 0 ? "warn" : "ok");
		this._set_metric("branch-total-dn", ba.total_internal_dns, null, "info");
		this._set_metric("branch-total-si", ba.total_internal_sis, null, "info");
		this._set_metric("branch-pending-repost", ba.pending_repost, null,
			ba.pending_repost > 0 ? "danger" : "ok");
		this._set_metric("branch-repost-tracking", ba.repost_tracking, null, "info");

		const dnPct = ba.total_internal_dns > 0
			? Math.round(((ba.total_internal_dns - ba.dns_without_pr) / ba.total_internal_dns) * 100)
			: 100;
		const siPct = ba.total_internal_sis > 0
			? Math.round(((ba.total_internal_sis - ba.sis_without_pi) / ba.total_internal_sis) * 100)
			: 100;
		this._set_progress("branch-dn", dnPct);
		this._set_progress("branch-si", siPct);

		// --- Stock Health cards ---
		const st = data.stock || {};
		this._set_metric("stock-neg-items", st.negative_stock_items, null,
			st.negative_stock_items > 0 ? "danger" : "ok");
		this._set_metric("stock-neg-wh", st.negative_stock_warehouses, null,
			st.negative_stock_warehouses > 0 ? "danger" : "ok");
		this._set_metric("stock-guarded", st.guarded_warehouses,
			st.total_warehouses ? __("of {0}", [st.total_warehouses]) : null, "info");
		this._set_metric("stock-draft-recon", st.draft_reconciliations, null,
			st.draft_reconciliations > 0 ? "warn" : "ok");

		// --- Compliance cards ---
		const comp = data.compliance || {};
		this._set_metric("compliance-pr-attach", comp.pr_without_attachment,
			comp.total_prs ? __("of {0} PRs", [comp.total_prs]) : null,
			comp.pr_without_attachment > 0 ? "warn" : "ok");
		this._set_metric("compliance-pi-attach", comp.pi_without_attachment,
			comp.total_pis ? __("of {0} PIs", [comp.total_pis]) : null,
			comp.pi_without_attachment > 0 ? "warn" : "ok");

		const prPct = comp.total_prs > 0
			? Math.round(((comp.total_prs - comp.pr_without_attachment) / comp.total_prs) * 100)
			: 100;
		const piPct = comp.total_pis > 0
			? Math.round(((comp.total_pis - comp.pi_without_attachment) / comp.total_pis) * 100)
			: 100;
		this._set_progress("compliance-pr", prPct);
		this._set_progress("compliance-pi", piPct);
	}

	_set_metric(id, value, subText, colorClass) {
		const card = this.wrapper.find("#" + id);
		card.removeClass("ok warn danger info").addClass(colorClass || "");
		card.find(".metric-value").text(value);
		if (subText) {
			if (card.find(".metric-sub").length === 0) {
				card.find(".metric-label").after('<div class="metric-sub"></div>');
			}
			card.find(".metric-sub").text(subText);
		}
	}

	_set_progress(prefix, pct) {
		this.wrapper.find("#" + prefix + "-pct").text(pct + "%");
		const bar = this.wrapper.find("#" + prefix + "-bar");
		bar.css("width", pct + "%");
		bar.removeClass("bg-success bg-warning bg-danger");
		if (pct >= 90) bar.addClass("bg-success");
		else if (pct >= 60) bar.addClass("bg-warning");
		else bar.addClass("bg-danger");
	}

	// =====================================================================
	// Existing Summary (detail section badges)
	// =====================================================================

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

			const mismatchCount = data.transfer_mismatch_count || 0;
			const mismatchStatus = data.transfer_mismatch_status || "Not Prepared";
			let mismatchLabel = __("Transfer Mismatches");
			if (mismatchStatus === "Completed" && data.transfer_mismatch_prepared_at) {
				mismatchLabel = __("Mismatches") + '<br><small class="text-muted">' + frappe.datetime.prettyDate(data.transfer_mismatch_prepared_at) + '</small>';
			} else if (mismatchStatus === "Queued" || mismatchStatus === "Started") {
				mismatchLabel = __("Mismatches") + '<br><small class="text-muted">' + __("Preparing...") + '</small>';
			} else {
				mismatchLabel = __("Mismatches") + '<br><small class="text-muted">' + __("Not prepared yet") + '</small>';
			}

			const mismatchCard = this.wrapper.find("#card-transfer-mismatch");
			const mismatchColorClass = mismatchCount > 0 ? "danger" : "";
			mismatchCard.removeClass("warning danger").addClass(mismatchColorClass);
			mismatchCard.html('<div class="number">' + mismatchCount + '</div><div class="label">' + mismatchLabel + '</div>');

			this.wrapper.find("#badge-items-missing").text(data.items_missing_expense_account);
			this.wrapper.find("#badge-pi-fixable").text(data.pi_items_fixable);
			this.wrapper.find("#badge-unlinked-pan").text(data.unlinked_pan_count || 0);
			this.wrapper.find("#badge-transfer-mismatch").text(mismatchCount);

			// Also update health indicator cards from summary data
			this._set_metric("health-missing-expense", data.items_missing_expense_account, null,
				data.items_missing_expense_account > 0 ? "warn" : "ok");
			this._set_metric("health-pi-fixable", data.pi_items_fixable, null,
				data.pi_items_fixable > 0 ? "danger" : "ok");
			this._set_metric("health-unlinked-pan", data.unlinked_pan_count || 0, null,
				(data.unlinked_pan_count || 0) > 0 ? "warn" : "ok");
			this._set_metric("health-transfer-mismatch", mismatchCount, null,
				mismatchCount > 0 ? "danger" : "ok");
		} catch (e) {
			console.error("Failed to load summary:", e);
		}
	}

	render_number_card(id, number, label, colorClass) {
		const card = this.wrapper.find("#" + id);
		card.removeClass("warning danger").addClass(colorClass || "");
		card.html('<div class="number">' + number + '</div><div class="label">' + label + '</div>');
	}

	// =====================================================================
	// Items Missing Expense Account
	// =====================================================================

	async load_items_missing_expense_account() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_items_missing_expense_account",
				args: { company: this.get_company() },
			});
			this.render_items_missing_table(result.message.items);
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

	// =====================================================================
	// PI Wrong Expense Account
	// =====================================================================

	async load_pi_wrong_expense_account() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_purchase_invoices_with_wrong_expense_account",
				args: { company: this.get_company() },
			});
			this.render_pi_wrong_table(result.message);
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
			__("Fix expense accounts for {0} PI items? This will run in the background.", [selected.length]),
			async function () {
				const btn = self.wrapper.find("#btn-bulk-fix");
				btn.prop("disabled", true).html('<i class="fa fa-spinner fa-spin"></i> ' + __("Queuing..."));

				try {
					const result = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.bulk_fix_pi_expense_accounts",
						args: { items: selected },
					});

					const data = result.message;

					if (data.status === "error") {
						let errorMsg = "";
						(data.validation_errors || []).forEach(function (e) {
							errorMsg += (e.pi_item_name || "?") + ": " + e.error + "<br>";
						});
						frappe.msgprint({
							title: __("Validation failed"),
							message: errorMsg || __("No fixable items found."),
							indicator: "red",
						});
						btn.prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix"));
						return;
					}

					if (data.validation_errors && data.validation_errors.length > 0) {
						let errorMsg = "";
						data.validation_errors.forEach(function (e) {
							errorMsg += (e.pi_item_name || "?") + ": " + e.error + "<br>";
						});
						frappe.msgprint({
							title: __("Some items skipped"),
							message: errorMsg,
							indicator: "orange",
						});
					}

					self.show_fix_progress(data.total_invoices);
				} catch (e) {
					// Frappe's global handler already shows the server's real
					// error message (e.g. PermissionError). Pull a readable
					// string out of the call's _server_messages / exc fields so
					// we never surface "[object Object]" to the user.
					let msg = "";
					try {
						if (e && e._server_messages) {
							const arr = JSON.parse(e._server_messages);
							if (arr && arr.length) {
								const first = JSON.parse(arr[0]);
								msg = first.message || arr[0];
							}
						}
					} catch (_) { /* fall through */ }
					if (!msg) msg = (e && (e.message || e.statusText)) || "";
					// show_alert renders message as HTML; escape the server-derived
					// string so any markup in it can't inject into the toast.
					if (msg) frappe.show_alert({ message: __("Bulk fix failed: {0}", [frappe.utils.escape_html(String(msg))]), indicator: "red" }, 8);
					btn.prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix"));
				}
			}
		);
	}

	// ── Realtime progress for background PI fix ──────────────────────

	show_fix_progress(total) {
		this.fix_in_progress = true;

		const btn = this.wrapper.find("#btn-bulk-fix");
		btn.prop("disabled", true).html('<i class="fa fa-spinner fa-spin"></i> ' + __("Processing..."));
		this.wrapper.find("#btn-select-all-fixable").prop("disabled", true);

		const container = this.wrapper.find("#table-pi-wrong");
		container.before(`
			<div id="pi-fix-progress" class="mb-3" style="padding: 10px; background: var(--control-bg); border-radius: 6px;">
				<div class="d-flex justify-content-between align-items-center mb-1">
					<span class="text-muted" style="font-size: 0.85rem;" id="pi-fix-status">
						<i class="fa fa-spinner fa-spin"></i> ${__("Processing 0 / {0} invoices...", [total])}
					</span>
					<span class="text-muted" style="font-size: 0.8rem;" id="pi-fix-pct">0%</span>
				</div>
				<div class="progress" style="height: 8px;">
					<div class="progress-bar bg-primary progress-bar-striped progress-bar-animated"
						 id="pi-fix-bar" role="progressbar" style="width: 0%; transition: width 0.4s ease;"></div>
				</div>
			</div>
		`);

		const self = this;

		this._onFixProgress = function (data) {
			const pct = Math.round((data.done / data.total) * 100);
			self.wrapper.find("#pi-fix-bar").css("width", pct + "%");
			self.wrapper.find("#pi-fix-pct").text(pct + "%");
			self.wrapper.find("#pi-fix-status").html(
				'<i class="fa fa-spinner fa-spin"></i> ' +
				__("Processing {0} / {1} invoices... ({2} items fixed)", [data.done, data.total, data.success_count])
			);
		};

		this._onFixComplete = function (data) {
			self.hide_fix_progress();

			if (data.success_count > 0) {
				frappe.show_alert({
					message: __("Fixed {0} items across background batch", [data.success_count]),
					indicator: "green",
				});
			}

			if (data.error_count > 0) {
				let errorMsg = "";
				(data.errors || []).forEach(function (e) {
					errorMsg += (e.pi_item_name || "?") + ": " + e.error + "<br>";
				});
				frappe.msgprint({
					title: __("{0} items failed", [data.error_count]),
					message: errorMsg,
					indicator: "orange",
				});
			}

			self.refresh();
		};

		frappe.realtime.on("bns_pi_fix_progress", this._onFixProgress);
		frappe.realtime.on("bns_pi_fix_complete", this._onFixComplete);
	}

	hide_fix_progress() {
		this.fix_in_progress = false;

		this.wrapper.find("#pi-fix-progress").remove();

		const btn = this.wrapper.find("#btn-bulk-fix");
		btn.prop("disabled", false).html('<i class="fa fa-wrench"></i> ' + __("Bulk Fix"));
		this.wrapper.find("#btn-select-all-fixable").prop("disabled", false);

		if (this._onFixProgress) {
			frappe.realtime.off("bns_pi_fix_progress", this._onFixProgress);
			this._onFixProgress = null;
		}
		if (this._onFixComplete) {
			frappe.realtime.off("bns_pi_fix_complete", this._onFixComplete);
			this._onFixComplete = null;
		}
	}

	// =====================================================================
	// All Expense Items
	// =====================================================================

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

			this.load_summary();
			this.load_items_missing_expense_account();
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
			btn.prop("disabled", false).text(__("Update"));
		}
	}

	// =====================================================================
	// Food Company Addresses & FSSAI
	// =====================================================================

	async load_food_company_addresses() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_food_company_addresses",
				args: { company: this.get_company() },
			});

			const data = result.message;

			const row = this.wrapper.find("#row-food-addresses");
			const content = this.wrapper.find("#content-food-addresses");
			const toggle = this.wrapper.find("#toggle-food-addresses");
			const hint = this.wrapper.find("#food-addresses-hint");

			if (!data.is_food_company) {
				row.hide();
				return;
			}

			row.show();
			hint.text(__("Addresses linked to this company. Green = FSSAI present, Red = missing."));
			this.wrapper.find("#badge-food-addresses").text(data.addresses ? data.addresses.length : 0);
			this.render_food_addresses_table(data.addresses || []);
			content.hide();
			toggle.addClass("collapsed");
		} catch (e) {
			this.wrapper.find("#row-food-addresses").hide();
		}
	}

	render_food_addresses_table(addresses) {
		const container = this.wrapper.find("#table-food-addresses");

		if (!addresses || addresses.length === 0) {
			container.html(
				'<p class="text-muted mb-0">' +
				'<i class="fa fa-map-marker"></i> ' +
				__("No company addresses linked yet. Add an Address and link it to this Company.") +
				"</p>"
			);
			return;
		}

		const self = this;
		let html = '<table class="table table-sm"><thead><tr>';
		html += '<th>' + __("Address") + '</th>';
		html += '<th style="width: 100px;">' + __("Status") + '</th>';
		html += '<th style="width: 200px;">' + __("FSSAI") + '</th>';
		html += '</tr></thead><tbody>';

		addresses.forEach(function (addr) {
			const rowClass = addr.has_fssai ? "row-fssai-ok" : "row-fssai-missing";
			const displayName = addr.address_title || addr.name;
			const typeLabel = addr.address_type ? " <span class=\"badge badge-light\">" + addr.address_type + "</span>" : "";
			const escName = frappe.utils.escape_html(addr.name);
			const escFssai = frappe.utils.escape_html(addr.fssai_license_no || "");
			html += '<tr class="' + rowClass + '" data-address="' + escName + '">';
			html += '<td>';
			html += '<a href="/app/address/' + encodeURIComponent(addr.name) + '" target="_blank" class="food-address-name">' + frappe.utils.escape_html(displayName) + '</a>' + typeLabel;
			html += '<div class="food-address-full mt-1">' + (addr.full_address || "-") + '</div>';
			html += "</td>";
			html += '<td>';
			if (addr.has_fssai) {
				html += '<span class="badge badge-success fssai-badge"><i class="fa fa-check"></i> ' + __("Present") + "</span>";
			} else {
				html += '<span class="badge badge-danger fssai-badge"><i class="fa fa-times"></i> ' + __("Missing") + "</span>";
			}
			html += "</td>";
			html += '<td>';
			html += '<div class="d-flex align-items-center" style="gap: 6px;">';
			html += '<input type="text" class="form-control form-control-sm fssai-input" ';
			html += 'value="' + escFssai + '" ';
			html += 'placeholder="' + __("FSSAI No.") + '" style="min-width: 100px; font-size: 0.8rem;">';
			html += '<button class="btn btn-primary btn-xs btn-set-fssai">' + __("Set") + '</button>';
			html += '</div>';
			html += '</td>';
			html += "</tr>";
		});

		html += "</tbody></table>";
		container.html(html);

		container.find(".btn-set-fssai").on("click", function () {
			const row = $(this).closest("tr");
			const addressName = row.data("address");
			const value = row.find(".fssai-input").val() ? row.find(".fssai-input").val().trim() : "";
			self.set_address_fssai(addressName, value, $(this));
		});
	}

	async set_address_fssai(addressName, fssaiValue, btn) {
		btn.prop("disabled", true).text(__("..."));

		try {
			await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.set_address_fssai",
				args: {
					address_name: addressName,
					fssai_license_no: fssaiValue,
				},
			});

			frappe.show_alert({ message: __("FSSAI updated"), indicator: "green" });
			this.load_food_company_addresses();
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
		} finally {
			btn.prop("disabled", false).text(__("Set"));
		}
	}

	// =====================================================================
	// Unlinked Customer/Supplier by PAN
	// =====================================================================

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

	// =====================================================================
	// Internal Transfer Mismatches
	// =====================================================================

	async load_transfer_mismatches() {
		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_internal_transfer_mismatches",
				args: { company: this.get_company() },
			});

			const data = result.message;
			this.wrapper.find("#badge-transfer-mismatch").text(data.count);

			const statusEl = this.wrapper.find("#mismatch-report-status");
			if (data.status === "Completed" && data.prepared_at) {
				statusEl.html(
					'<i class="fa fa-check text-success"></i> ' +
					__("Last prepared") + ": " + frappe.datetime.prettyDate(data.prepared_at)
				);
			} else if (data.status === "Queued" || data.status === "Started") {
				statusEl.html(
					'<i class="fa fa-spinner fa-spin"></i> ' + __("Report is being prepared...")
				);
				if (data.prepared_report_name) {
					this._poll_prepared_report(data.prepared_report_name);
				}
			} else {
				statusEl.html(
					'<i class="fa fa-info-circle text-muted"></i> ' +
					__("No prepared report found. Click 'Prepare New Report' to generate.")
				);
			}

			this.render_transfer_mismatch_table(data.records, data.status);
		} catch (e) {
			console.error("Failed to load transfer mismatch data:", e);
			this.wrapper.find("#table-transfer-mismatch").html(
				'<p class="text-danger">' + __("Failed to load data") + '</p>'
			);
		}
	}

	async prepare_mismatch_report() {
		const btn = this.wrapper.find("#btn-prepare-mismatch-report");
		btn.prop("disabled", true).html('<i class="fa fa-spinner fa-spin"></i> ' + __("Preparing..."));

		try {
			const result = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.trigger_mismatch_report_preparation",
				args: { company: this.get_company() },
			});

			const data = result.message;
			frappe.show_alert({ message: data.message, indicator: "blue" });

			this.wrapper.find("#mismatch-report-status").html(
				'<i class="fa fa-spinner fa-spin"></i> ' + __("Report is being prepared...")
			);

			if (data.prepared_report_name) {
				this._poll_prepared_report(data.prepared_report_name);
			}
		} catch (e) {
			frappe.msgprint(__("Failed to trigger report preparation: {0}", [e.message || e]));
		} finally {
			btn.prop("disabled", false).html('<i class="fa fa-refresh"></i> ' + __("Prepare New Report"));
		}
	}

	_poll_prepared_report(prepared_report_name, attempt = 0) {
		const self = this;
		const maxAttempts = 30;
		const delay = Math.min(3000 + attempt * 2000, 15000);

		setTimeout(async function () {
			try {
				const result = await frappe.call({
					method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_prepared_report_status",
					args: { prepared_report_name: prepared_report_name },
				});

				const data = result.message;

				if (data.status === "Completed") {
					frappe.show_alert({ message: __("Transfer mismatch report is ready!"), indicator: "green" });
					self.load_transfer_mismatches();
					self.load_summary();
				} else if (data.status === "Error") {
					self.wrapper.find("#mismatch-report-status").html(
						'<i class="fa fa-exclamation-circle text-danger"></i> ' +
						__("Report preparation failed. Try again.")
					);
					frappe.show_alert({ message: __("Report preparation failed"), indicator: "red" });
				} else if (attempt < maxAttempts) {
					self._poll_prepared_report(prepared_report_name, attempt + 1);
				} else {
					self.wrapper.find("#mismatch-report-status").html(
						'<i class="fa fa-clock-o text-warning"></i> ' +
						__("Still preparing. Refresh page to check.")
					);
				}
			} catch (e) {
				console.error("Poll error:", e);
			}
		}, delay);
	}

	render_transfer_mismatch_table(records, status) {
		const container = this.wrapper.find("#table-transfer-mismatch");

		if (!records || records.length === 0) {
			if (status !== "Completed") {
				container.html(
					'<p class="text-danger mb-0">' +
					'<i class="fa fa-exclamation-circle"></i> ' +
					__("No prepared report available. Click 'Prepare New Report' above to generate.") +
					'</p>'
				);
			} else {
				container.html('<p class="text-success mb-0">' + __("No internal transfer mismatches found!") + '</p>');
			}
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

	// =====================================================================
	// Linked Party Square-Off (Common Party GL reconciliation)
	// =====================================================================

	_render_squareoff_table(containerId, pairs, checkboxClass) {
		const container = this.wrapper.find("#" + containerId);
		if (!pairs || pairs.length === 0) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No linked parties with crossed or consolidatable balances found.") + '</p>');
			return 0;
		}
		let html = '<table class="table table-sm table-bordered"><thead><tr>';
		html += '<th style="width:30px;"><input type="checkbox" class="' + checkboxClass + '-all"></th>';
		html += '<th><small>' + __("Kind") + '</small></th>';
		html += '<th><small>' + __("Primary Party") + '</small></th>';
		html += '<th><small>' + __("Secondary Party") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Primary Balance") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Secondary Balance") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Square-Off") + '</small></th>';
		html += '</tr></thead><tbody>';
		pairs.forEach(function (p) {
			const isConsolidate = p.kind === "consolidate";
			const kindLabel = isConsolidate ? __("Consolidate") : __("Net");
			const kindBadge = isConsolidate ? "badge-info" : "badge-warning";
			const kindTitle = isConsolidate
				? __("Same-sign pair: the secondary's balance is moved to the primary side (no netting, just consolidation).")
				: __("Crossed pair: the matching amount is cancelled from both sides.");
			html += '<tr>';
			html += '<td><input type="checkbox" class="' + checkboxClass + '" data-pair-key="' + frappe.utils.escape_html(p.pair_key) + '" checked></td>';
			html += '<td><span class="badge ' + kindBadge + '" title="' + frappe.utils.escape_html(kindTitle) + '">' + kindLabel + '</span></td>';
			html += '<td><small>' + frappe.utils.escape_html(p.primary_party_type) + ' <b>' + frappe.utils.escape_html(p.primary_party) + '</b><br>' + frappe.utils.escape_html(p.primary_account || '') + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(p.secondary_party_type) + ' <b>' + frappe.utils.escape_html(p.secondary_party) + '</b><br>' + frappe.utils.escape_html(p.secondary_account || '') + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(p.primary_balance) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(p.secondary_balance) + '</small></td>';
			html += '<td class="text-right"><small><b>' + format_currency(p.square_off_amount) + '</b></small></td>';
			html += '</tr>';
		});
		html += '</tbody></table>';
		container.html(html);

		const self = this;
		container.find("." + checkboxClass + "-all").on("change", function () {
			container.find("." + checkboxClass).prop("checked", $(this).is(":checked"));
		});
		return pairs.length;
	}

	_collect_pair_keys(containerId, checkboxClass) {
		const keys = [];
		this.wrapper.find("#" + containerId + " ." + checkboxClass + ":checked").each(function () {
			keys.push($(this).data("pair-key"));
		});
		return keys;
	}

	async preview_common_party_squareoff() {
		const company = this.get_company();
		if (!company) {
			frappe.msgprint(__("Select a company first."));
			return;
		}
		const as_of_date = this.wrapper.find("#bns-squareoff-asof").val() || frappe.datetime.get_today();
		try {
			const r = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.preview_common_party_squareoff",
				args: { company: company, as_of_date: as_of_date },
				freeze: true,
				freeze_message: __("Scanning linked parties..."),
			});
			const data = r.message || { pairs: [], count: 0 };
			this.wrapper.find("#badge-party-squareoff").text(data.count || 0);
			const n = this._render_squareoff_table("table-party-squareoff", data.pairs, "bns-squareoff-chk");
			this.wrapper.find("#btn-squareoff-post").prop("disabled", n === 0);
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
		}
	}

	async post_common_party_squareoff() {
		const company = this.get_company();
		if (!company) return;
		const as_of_date = this.wrapper.find("#bns-squareoff-asof").val() || frappe.datetime.get_today();
		const pair_keys = this._collect_pair_keys("table-party-squareoff", "bns-squareoff-chk");
		if (pair_keys.length === 0) {
			frappe.msgprint(__("Select at least one pair."));
			return;
		}
		frappe.confirm(
			__("Post {0} contra Journal Entries? This writes to the GL.", [pair_keys.length]),
			async () => {
				try {
					const r = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.execute_common_party_squareoff",
						args: {
							company: company,
							as_of_date: as_of_date,
							pair_keys: pair_keys,
							posting_date: as_of_date,
						},
						freeze: true,
						freeze_message: __("Posting contra entries..."),
					});
					const res = r.message || {};
					const posted = (res.posted || []).length;
					const errors = (res.errors || []).length;
					let msg = __("Posted {0} contra Journal Entries.", [posted]);
					if (errors > 0) msg += "<br>" + __("{0} error(s) — check Error Log.", [errors]);
					if (res.posted && res.posted.length) {
						msg += '<br><ul style="margin-top:8px;">';
						res.posted.forEach(function (p) {
							msg += '<li><a href="/app/journal-entry/' + p.journal_entry + '" target="_blank">' + p.journal_entry + '</a> — ' + format_currency(p.amount) + '</li>';
						});
						msg += "</ul>";
					}
					frappe.msgprint({ title: __("Square-Off Complete"), message: msg, indicator: errors ? "orange" : "green" });
					this.preview_common_party_squareoff();
				} catch (e) {
					frappe.msgprint(__("Failed: {0}", [e.message || e]));
				}
			}
		);
	}

	async preview_historical_backfill() {
		const company = this.get_company();
		if (!company) return;
		const cutoff = this.wrapper.find("#bns-squareoff-cutoff").val();
		if (!cutoff) {
			frappe.msgprint(__("Pick a cutoff date."));
			return;
		}
		try {
			const r = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.preview_historical_backfill",
				args: { company: company, cutoff_date: cutoff },
				freeze: true,
				freeze_message: __("Scanning historical linked balances..."),
			});
			const data = r.message || { pairs: [], count: 0 };
			const n = this._render_squareoff_table("table-party-backfill", data.pairs, "bns-backfill-chk");
			this.wrapper.find("#btn-backfill-post").prop("disabled", n === 0);
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
		}
	}

	async post_historical_backfill() {
		const company = this.get_company();
		const cutoff = this.wrapper.find("#bns-squareoff-cutoff").val();
		if (!company || !cutoff) return;
		const pair_keys = this._collect_pair_keys("table-party-backfill", "bns-backfill-chk");
		if (pair_keys.length === 0) {
			frappe.msgprint(__("Select at least one pair."));
			return;
		}
		frappe.confirm(
			__("Post {0} backfill Journal Entries dated {1}? This touches past periods.", [pair_keys.length, cutoff]),
			async () => {
				try {
					const r = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.execute_historical_backfill",
						args: { company: company, cutoff_date: cutoff, pair_keys: pair_keys },
						freeze: true,
						freeze_message: __("Posting backfill entries..."),
					});
					const res = r.message || {};
					const posted = (res.posted || []).length;
					const errors = (res.errors || []).length;
					let msg = __("Posted {0} backfill Journal Entries.", [posted]);
					if (errors > 0) msg += "<br>" + __("{0} error(s) — check Error Log.", [errors]);
					frappe.msgprint({ title: __("Backfill Complete"), message: msg, indicator: errors ? "orange" : "green" });
					this.preview_historical_backfill();
				} catch (e) {
					frappe.msgprint(__("Failed: {0}", [e.message || e]));
				}
			}
		);
	}

	// =====================================================================
	// Payment Reconciliation (FIFO) — preview/run/full-pipeline
	// =====================================================================

	_render_reconcile_table(candidates, totals) {
		const container = this.wrapper.find("#table-payment-reconciliation");
		if (!candidates || candidates.length === 0) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No parties with reconcilable open items \u2014 everything is clean.") + '</p>');
			return 0;
		}
		const chkClass = "bns-reconcile-chk";
		let html = '<div class="table-responsive"><table class="table table-sm table-bordered" style="font-size:11px;"><thead><tr>';
		html += '<th style="width:26px;"><input type="checkbox" class="' + chkClass + '-all" checked></th>';
		html += '<th><small>' + __("Party") + '</small></th>';
		html += '<th class="text-center"><small>' + __("Open Inv") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Inv Outstanding") + '</small></th>';
		html += '<th class="text-center"><small>' + __("Open PE") + '</small></th>';
		html += '<th class="text-right"><small>' + __("PE Unallocated") + '</small></th>';
		html += '<th class="text-right"><small><b>' + __("Reconcilable") + '</b></small></th>';
		html += '<th class="text-right"><small>' + __("Residual \u2192 Link") + '</small></th>';
		html += '<th><small>' + __("Primary Link") + '</small></th>';
		html += '</tr></thead><tbody>';
		candidates.forEach(function (c) {
			const key = (c.party_type || '') + '|' + (c.party || '');
			const residualInv = c.residual_invoice_side || 0;
			const residualPay = c.residual_payment_side || 0;
			const residual = residualInv + residualPay;
			const primary = c.primary_link_party
				? frappe.utils.escape_html(c.primary_link_party_type + ' ' + c.primary_link_party)
				: '<span class="text-muted">&mdash;</span>';
			html += '<tr>';
			html += '<td><input type="checkbox" class="' + chkClass + '" data-party-key="' + frappe.utils.escape_html(key) + '" checked></td>';
			html += '<td><small>' + frappe.utils.escape_html(c.party_type) + ' <b>' + frappe.utils.escape_html(c.party) + '</b>';
			if (c.account) html += '<br><span class="text-muted">' + frappe.utils.escape_html(c.account) + '</span>';
			html += '</small></td>';
			html += '<td class="text-center"><small>' + (c.open_invoice_count || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(c.open_invoice_outstanding || 0) + '</small></td>';
			html += '<td class="text-center"><small>' + (c.open_payment_count || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(c.open_payment_unallocated || 0) + '</small></td>';
			html += '<td class="text-right"><small><b>' + format_currency(c.reconcilable_amount || 0) + '</b></small></td>';
			html += '<td class="text-right"><small>' + format_currency(residual) + '</small></td>';
			html += '<td><small>' + primary + '</small></td>';
			html += '</tr>';
		});
		if (totals) {
			html += '<tr style="background:var(--subtle-bg); font-weight:bold;">';
			html += '<td></td><td><small>' + __("TOTAL") + '</small></td>';
			html += '<td class="text-center"><small>' + (totals.open_invoice_count || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(totals.open_invoice_outstanding || 0) + '</small></td>';
			html += '<td class="text-center"><small>' + (totals.open_payment_count || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(totals.open_payment_unallocated || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(totals.reconcilable_amount || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency((totals.residual_invoice_side || 0) + (totals.residual_payment_side || 0)) + '</small></td>';
			html += '<td></td>';
			html += '</tr>';
		}
		html += '</tbody></table></div>';
		container.html(html);
		container.find("." + chkClass + "-all").on("change", function () {
			container.find("." + chkClass).prop("checked", $(this).is(":checked"));
		});
		return candidates.length;
	}

	_collect_reconcile_keys() {
		const keys = [];
		this.wrapper.find("#table-payment-reconciliation .bns-reconcile-chk:checked").each(function () {
			keys.push($(this).data("party-key"));
		});
		return keys;
	}

	async preview_payment_reconciliation() {
		const company = this.get_company();
		if (!company) {
			frappe.msgprint(__("Select a company first."));
			return;
		}
		try {
			const r = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.preview_payment_reconciliation",
				args: { company: company },
				freeze: true,
				freeze_message: __("Scanning unreconciled parties..."),
			});
			const data = r.message || { candidates: [], count: 0, totals: {} };
			this.wrapper.find("#badge-payment-reconciliation").text(data.count || 0);
			const meta = [];
			if (data.scope) meta.push(__("Scope: {0}", [data.scope]));
			if (data.window) meta.push(__("Window: {0}", [data.window]));
			if (data.totals && data.totals.reconcilable_amount) {
				meta.push(__("Reconcilable: {0}", [format_currency(data.totals.reconcilable_amount)]));
			}
			if (data.last_run_on) meta.push(__("Last run: {0}", [data.last_run_on]));
			this.wrapper.find("#reconcile-meta").text(meta.join(" · "));
			const n = this._render_reconcile_table(data.candidates || [], data.totals || {});
			this.wrapper.find("#btn-reconcile-run").prop("disabled", n === 0);
		} catch (e) {
			frappe.msgprint(__("Failed: {0}", [e.message || e]));
		}
	}

	async run_payment_reconciliation() {
		const company = this.get_company();
		if (!company) return;
		const party_keys = this._collect_reconcile_keys();
		if (party_keys.length === 0) {
			frappe.msgprint(__("Select at least one party from the preview table."));
			return;
		}
		frappe.confirm(
			__("Run FIFO Payment Reconciliation for {0} selected parties? This modifies Payment Entry references, rewrites the Payment Ledger, and may post exchange gain/loss JVs.", [party_keys.length]),
			async () => {
				try {
					const r = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.execute_payment_reconciliation",
						args: { company: company, party_keys: party_keys },
						freeze: true,
						freeze_message: __("Reconciling (FIFO)..."),
					});
					const res = r.message || {};
					if (res.enqueued) {
						frappe.msgprint({
							title: __("Queued"),
							message: res.message || __("Background job enqueued."),
							indicator: "blue",
						});
						return;
					}
					const parties = (res.reconciled_parties || []).length;
					const errors = (res.errors || []).length;
					const allocations = res.total_allocations || 0;
					let msg = __("Reconciled {0} parties, {1} allocations.", [parties, allocations]);
					if (errors > 0) msg += "<br>" + __("{0} error(s) — check Error Log.", [errors]);
					frappe.msgprint({ title: __("Reconciliation Complete"), message: msg, indicator: errors ? "orange" : "green" });
					this.preview_payment_reconciliation();
				} catch (e) {
					frappe.msgprint(__("Failed: {0}", [e.message || e]));
				}
			}
		);
	}

	async run_full_squareoff_pipeline() {
		const company = this.get_company();
		if (!company) return;
		frappe.confirm(
			__("Run the full pipeline for <b>{0}</b>?<br><br>1. Pre-reconcile every customer + supplier<br>2. Post contra JVs for crossed linked pairs<br>3. Post-reconcile to FIFO-allocate the JVs against invoices<br><br>This touches the GL. Proceed?", [company]),
			async () => {
				try {
					const r = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.execute_full_squareoff_pipeline",
						args: { company: company },
						freeze: true,
						freeze_message: __("Running full pipeline..."),
					});
					const res = r.message || {};
					const pre = res.pre_reconcile || {};
					const sq = res.squareoff || {};
					const post = res.post_reconcile || {};
					const msg = `
						<b>${__("Pre-reconcile")}:</b> ${pre.reconciled_parties || 0} parties, ${pre.total_allocations || 0} allocations, ${pre.errors || 0} errors<br>
						<b>${__("Square-off")}:</b> ${sq.posted || 0} posted, ${sq.skipped || 0} skipped, ${sq.errors || 0} errors<br>
						<b>${__("Post-reconcile")}:</b> ${post.reconciled_parties || 0} parties, ${post.total_allocations || 0} allocations, ${post.errors || 0} errors
					`;
					frappe.msgprint({
						title: __("Full Pipeline Complete"),
						message: msg,
						indicator: (pre.errors || sq.errors || post.errors) ? "orange" : "green",
					});
					this.preview_payment_reconciliation();
					this.preview_common_party_squareoff();
				} catch (e) {
					frappe.msgprint(__("Failed: {0}", [e.message || e]));
				}
			}
		);
	}

	// =====================================================================
	// SRBNB Reconciliation (Stock Received But Not Billed)
	// =====================================================================

	async load_srbnb_reconciliation() {
		try {
			const r = await frappe.call({
				method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.get_srbnb_reconciliation",
				args: { company: this.get_company() },
			});
			const data = r.message || {};
			if (data.error) {
				this.wrapper.find("#srbnb-net-balance").text(data.error);
				return;
			}
			this._render_srbnb_data(data);
		} catch (e) {
			console.error("SRBNB load failed:", e);
			this.wrapper.find("#srbnb-net-balance").text(__("Load failed"));
		}
	}

	_render_srbnb_data(data) {
		const b = data.buckets || {};
		const internalPrs = b.internal_prs || {};
		const openPrs = b.open_prs || {};
		const orphanPi = b.orphan_pi_debits || {};
		const stockEnt = b.stock_entries || {};
		const journalEnt = b.journal_entries || {};

		// Summary cards
		this.wrapper.find("#srbnb-total-internal-prs").html(format_currency(internalPrs.total || 0));
		this.wrapper.find("#srbnb-count-internal-prs").text(__("{0} entries", [internalPrs.count || 0]));
		this.wrapper.find("#srbnb-total-open-prs").html(format_currency(openPrs.total || 0));
		this.wrapper.find("#srbnb-count-open-prs").text(__("{0} entries", [openPrs.count || 0]));
		this.wrapper.find("#srbnb-total-orphan-pi").html(format_currency(orphanPi.total || 0));
		this.wrapper.find("#srbnb-count-orphan-pi").text(__("{0} entries", [orphanPi.count || 0]));
		this.wrapper.find("#srbnb-total-stock-entries").html(format_currency(stockEnt.total || 0));
		this.wrapper.find("#srbnb-count-stock-entries").text(__("{0} entries", [stockEnt.count || 0]));
		this.wrapper.find("#srbnb-total-journal-entries").html(format_currency(journalEnt.total || 0));
		this.wrapper.find("#srbnb-count-journal-entries").text(__("{0} entries", [journalEnt.count || 0]));

		// Badges
		this.wrapper.find("#badge-srbnb-internal-prs").text(internalPrs.count || 0);
		this.wrapper.find("#badge-srbnb-open-prs").text(openPrs.count || 0);
		this.wrapper.find("#badge-srbnb-orphan-pi").text(orphanPi.count || 0);
		this.wrapper.find("#badge-srbnb-stock-entries").text(stockEnt.count || 0);
		this.wrapper.find("#badge-srbnb-journal-entries").text(journalEnt.count || 0);

		// Net balance + account info
		this.wrapper.find("#srbnb-net-balance").text(format_currency(data.net_balance || 0));
		this.wrapper.find("#srbnb-account-name").text(data.account || "");
		this.wrapper.find("#srbnb-excluded-info").text(
			__("{0} GL entries total, {1} paired PRs excluded", [data.total_gl_entries || 0, data.paired_prs_excluded || 0])
		);

		// Drilldown tables
		this._render_srbnb_internal_prs(internalPrs.rows || []);
		this._render_srbnb_open_prs(openPrs.rows || []);
		this._render_srbnb_orphan_pi(orphanPi.rows || []);
		this._render_srbnb_stock_entries(stockEnt.rows || []);
		this._render_srbnb_journal_entries(journalEnt.rows || []);
	}

	_render_srbnb_internal_prs(rows) {
		const container = this.wrapper.find("#table-srbnb-internal-prs");
		if (!rows.length) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No BNS internal PRs on SRBNB.") + '</p>');
			this.wrapper.find("#btn-srbnb-clear-internal").prop("disabled", true);
			return;
		}
		const chkClass = "srbnb-internal-chk";
		let html = '<div class="table-responsive"><table class="table table-sm table-bordered" style="font-size:11px;"><thead><tr>';
		html += '<th style="width:26px;"><input type="checkbox" class="' + chkClass + '-all" checked></th>';
		html += '<th><small>' + __("PR") + '</small></th>';
		html += '<th><small>' + __("Linked DN") + '</small></th>';
		html += '<th><small>' + __("Supplier") + '</small></th>';
		html += '<th><small>' + __("Date") + '</small></th>';
		html += '<th class="text-right"><small>' + __("SRBNB Amount") + '</small></th>';
		html += '<th class="text-center"><small>' + __("Age") + '</small></th>';
		html += '</tr></thead><tbody>';
		rows.forEach(function (r) {
			const ageClass = r.age_color === "red" ? "indicator-pill red" : (r.age_color === "amber" ? "indicator-pill orange" : "");
			html += '<tr>';
			html += '<td><input type="checkbox" class="' + chkClass + '" data-pr="' + frappe.utils.escape_html(r.voucher_no) + '" checked></td>';
			html += '<td><small><a href="/app/purchase-receipt/' + frappe.utils.escape_html(r.voucher_no) + '" target="_blank">' + frappe.utils.escape_html(r.voucher_no) + '</a></small></td>';
			const dn = r.linked_dn || '';
			html += '<td><small>' + (dn ? '<a href="/app/delivery-note/' + frappe.utils.escape_html(dn) + '" target="_blank">' + frappe.utils.escape_html(dn) + '</a>' : '<span class="text-muted">&mdash;</span>') + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.supplier || '') + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.posting_date || '') + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(r.amount) + '</small></td>';
			html += '<td class="text-center"><small><span class="' + ageClass + '">' + (r.age_days || 0) + 'd</span></small></td>';
			html += '</tr>';
		});
		html += '</tbody></table></div>';
		container.html(html);
		container.find("." + chkClass + "-all").on("change", function () {
			container.find("." + chkClass).prop("checked", $(this).is(":checked"));
		});
		this.wrapper.find("#btn-srbnb-clear-internal").prop("disabled", false);
	}

	async clear_internal_srbnb() {
		const company = this.get_company();
		if (!company) return;
		const pr_names = [];
		this.wrapper.find("#table-srbnb-internal-prs .srbnb-internal-chk:checked").each(function () {
			pr_names.push($(this).data("pr"));
		});
		if (!pr_names.length) {
			frappe.msgprint(__("Select at least one internal PR."));
			return;
		}
		const posting_date = this.wrapper.find("#srbnb-internal-je-date").val() || frappe.datetime.get_today();
		frappe.confirm(
			__("Create a draft Journal Entry to clear SRBNB for {0} internal PRs dated {1}?<br><br>Dr SRBNB / Cr Clearing Account (from BNS Settings). The JE will be saved as Draft — review and submit manually.", [pr_names.length, posting_date]),
			async () => {
				try {
					const r = await frappe.call({
						method: "business_needed_solutions.business_needed_solutions.page.bns_dashboard.bns_dashboard.clear_internal_srbnb",
						args: { company: company, pr_names: pr_names, posting_date: posting_date },
						freeze: true,
						freeze_message: __("Creating clearing JE..."),
					});
					const res = r.message || {};
					if (res.error) {
						frappe.msgprint({ title: __("Error"), message: res.error, indicator: "red" });
						return;
					}
					frappe.msgprint({
						title: __("Clearing JE Created (Draft)"),
						message: __("Journal Entry <a href='/app/journal-entry/{0}' target='_blank'><b>{0}</b></a> created for {1} — Dr SRBNB / Cr {2}. Review and submit manually.",
							[res.journal_entry, format_currency(res.amount), res.clearing_account]),
						indicator: "green",
					});
					this.load_srbnb_reconciliation();
				} catch (e) {
					frappe.msgprint(__("Failed: {0}", [e.message || e]));
				}
			}
		);
	}

	_render_srbnb_open_prs(rows) {
		const container = this.wrapper.find("#table-srbnb-open-prs");
		if (!rows.length) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No open Purchase Receipts — all paired with submitted PIs.") + '</p>');
			return;
		}
		let html = '<div class="table-responsive"><table class="table table-sm table-bordered" style="font-size:11px;"><thead><tr>';
		html += '<th><small>' + __("PR") + '</small></th>';
		html += '<th><small>' + __("Supplier") + '</small></th>';
		html += '<th><small>' + __("Date") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Amount") + '</small></th>';
		html += '<th class="text-center"><small>' + __("Age") + '</small></th>';
		html += '<th><small>' + __("Action") + '</small></th>';
		html += '</tr></thead><tbody>';
		rows.forEach(function (r) {
			const ageClass = r.age_color === "red" ? "indicator-pill red" : (r.age_color === "amber" ? "indicator-pill orange" : "");
			html += '<tr>';
			html += '<td><small><a href="/app/purchase-receipt/' + frappe.utils.escape_html(r.voucher_no) + '" target="_blank">' + frappe.utils.escape_html(r.voucher_no) + '</a></small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.supplier || '') + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.posting_date || '') + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(r.amount) + '</small></td>';
			html += '<td class="text-center"><small><span class="' + ageClass + '">' + (r.age_days || 0) + 'd</span></small></td>';
			html += '<td><small><a href="/app/purchase-invoice/new?supplier=' + encodeURIComponent(r.supplier || '') + '&items=%5B%7B%22purchase_receipt%22%3A%22' + encodeURIComponent(r.voucher_no) + '%22%7D%5D" target="_blank" class="btn btn-xs btn-primary">' + __("Create PI") + '</a></small></td>';
			html += '</tr>';
		});
		html += '</tbody></table></div>';
		container.html(html);
	}

	_render_srbnb_orphan_pi(rows) {
		const container = this.wrapper.find("#table-srbnb-orphan-pi");
		if (!rows.length) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No orphan PI debits.") + '</p>');
			return;
		}
		let html = '<div class="table-responsive"><table class="table table-sm table-bordered" style="font-size:11px;"><thead><tr>';
		html += '<th><small>' + __("PI") + '</small></th>';
		html += '<th><small>' + __("Supplier") + '</small></th>';
		html += '<th><small>' + __("Date") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Amount") + '</small></th>';
		html += '</tr></thead><tbody>';
		rows.forEach(function (r) {
			html += '<tr>';
			html += '<td><small><a href="/app/purchase-invoice/' + frappe.utils.escape_html(r.voucher_no) + '" target="_blank">' + frappe.utils.escape_html(r.voucher_no) + '</a></small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.supplier || '') + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.posting_date || '') + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(r.amount) + '</small></td>';
			html += '</tr>';
		});
		html += '</tbody></table></div>';
		container.html(html);
	}

	_render_srbnb_stock_entries(rows) {
		const container = this.wrapper.find("#table-srbnb-stock-entries");
		if (!rows.length) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No Stock Entry hits on SRBNB.") + '</p>');
			return;
		}
		let html = '<div class="table-responsive"><table class="table table-sm table-bordered" style="font-size:11px;"><thead><tr>';
		html += '<th><small>' + __("SE") + '</small></th>';
		html += '<th><small>' + __("Type") + '</small></th>';
		html += '<th><small>' + __("Date") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Amount") + '</small></th>';
		html += '<th><small>' + __("From WH → To WH") + '</small></th>';
		html += '<th class="text-center"><small>' + __("Same GSTIN?") + '</small></th>';
		html += '</tr></thead><tbody>';
		rows.forEach(function (r) {
			html += '<tr>';
			html += '<td><small><a href="/app/stock-entry/' + frappe.utils.escape_html(r.voucher_no) + '" target="_blank">' + frappe.utils.escape_html(r.voucher_no) + '</a></small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.stock_entry_type || '') + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.posting_date || '') + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(r.amount) + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.from_warehouse || '') + ' → ' + frappe.utils.escape_html(r.to_warehouse || '') + '</small></td>';
			html += '<td class="text-center"><small>' + (r.is_same_gstin ? '<span class="indicator-pill green">' + __("Yes") + '</span>' : '<span class="indicator-pill red">' + __("No") + '</span>') + '</small></td>';
			html += '</tr>';
		});
		html += '</tbody></table></div>';
		container.html(html);
	}

	_render_srbnb_journal_entries(rows) {
		const container = this.wrapper.find("#table-srbnb-journal-entries");
		if (!rows.length) {
			container.html('<p class="text-success small"><i class="fa fa-check"></i> ' + __("No Journal Entry hits on SRBNB.") + '</p>');
			return;
		}
		let html = '<div class="table-responsive"><table class="table table-sm table-bordered" style="font-size:11px;"><thead><tr>';
		html += '<th><small>' + __("JE") + '</small></th>';
		html += '<th><small>' + __("Date") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Dr") + '</small></th>';
		html += '<th class="text-right"><small>' + __("Cr") + '</small></th>';
		html += '<th><small>' + __("Remark") + '</small></th>';
		html += '<th class="text-center"><small>' + __("Review?") + '</small></th>';
		html += '</tr></thead><tbody>';
		rows.forEach(function (r) {
			const trClass = r.needs_review ? ' style="background: #fff3cd;"' : '';
			html += '<tr' + trClass + '>';
			html += '<td><small><a href="/app/journal-entry/' + frappe.utils.escape_html(r.voucher_no) + '" target="_blank">' + frappe.utils.escape_html(r.voucher_no) + '</a></small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.posting_date || '') + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(r.debit || 0) + '</small></td>';
			html += '<td class="text-right"><small>' + format_currency(r.credit || 0) + '</small></td>';
			html += '<td><small>' + frappe.utils.escape_html(r.remark || '') + '</small></td>';
			html += '<td class="text-center"><small>' + (r.needs_review ? '<span class="indicator-pill red">' + __("Review") + '</span>' : '<span class="indicator-pill green">' + __("OK") + '</span>') + '</small></td>';
			html += '</tr>';
		});
		html += '</tbody></table></div>';
		container.html(html);
	}
}
