# Graph Report - .  (2026-04-16)

## Corpus Check
- 140 files · ~129,076 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1563 nodes · 2478 edges · 114 communities detected
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 13 edges (avg confidence: 0.84)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `BNSDashboard` - 58 edges
2. `_bns_require_accounts_read()` - 25 edges
3. `is_after_internal_transfer_cutoff()` - 24 edges
4. `is_after_accounting_rewrite_cutoff()` - 22 edges
5. `_resolve_source_posting_date()` - 20 edges
6. `TestCommonPartySquareOff` - 20 edges
7. `BNSValidationError` - 19 edges
8. `_run_bns_gl_repost_correction()` - 18 edges
9. `_run_bns_gl_repost_accounting_correction()` - 18 edges
10. `BNSSettings` - 18 edges

## Surprising Connections (you probably didn't know these)
- `Common Party Square-Off Module` --semantically_similar_to--> `Common Party Reconciliation Module`  [INFERRED] [semantically similar]
  business_needed_solutions/bns_branch_accounting/common_party_squareoff.py → business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- `BNS Dashboard (JS)` --calls--> `BNS Dashboard API`  [EXTRACTED]
  business_needed_solutions/page/bns_dashboard/bns_dashboard.js → business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- `Cancellation Philosophy` --rationale_for--> `Internal Transfers System`  [EXTRACTED]
  business_needed_solutions/psychological_handbook.md → business_needed_solutions/docs/TECHNICAL_HANDBOOK.md
- `Transfer Rate Authority` --rationale_for--> `Internal Transfers System`  [EXTRACTED]
  business_needed_solutions/psychological_handbook.md → business_needed_solutions/docs/TECHNICAL_HANDBOOK.md
- `PI GL Rewrite Parity` --rationale_for--> `Internal Transfers System`  [EXTRACTED]
  business_needed_solutions/psychological_handbook.md → business_needed_solutions/docs/TECHNICAL_HANDBOOK.md

## Hyperedges (group relationships)
- **Internal Transfer Document Lifecycle** — utils_branch_accounting, fn_make_bns_internal_purchase_receipt, fn_make_bns_internal_purchase_invoice, fn_verify_and_repost, hooks_app_config [EXTRACTED 0.95]
- **AR/AP Netting and Square-Off System** — pure_accounts_receivable_summary, pure_accounts_payable_summary, common_party_squareoff_module, common_party_reconciliation_module, bns_dashboard_py [INFERRED 0.85]
- **GST Compliance Suite** — gst_itc_health_check_py, pan_gstin_mismatch_banner, attachment_validation [INFERRED 0.75]
- **Transfer Rate Valuation Chain** — handbook_transfer_rate_authority, handbook_chain_completion_invariant, handbook_pi_gl_rewrite_parity, handbook_si_pi_parity_invariant [EXTRACTED 0.95]
- **Repost Execution Framework** — handbook_repost_lock_hardening, bns_repost_tracking [EXTRACTED 0.90]
- **BNS Settings Configuration Hub** — tech_bns_settings, tech_triple_discount, tech_submission_restriction, tech_negative_stock_control, tech_pan_validation [EXTRACTED 0.95]
- **Unified Submission Restriction Suite** — hooks_doc_events, submission_restriction_override, bns_settings_doctype, test_submission_restriction [EXTRACTED 0.90]
- **he:nsr-resolution-pipeline** — func:nsr.analyze_episode, func:nsr.analyze_bom_availability, func:nsr.find_alternative_warehouse [INFERRED 0.85]
- **he:osa-voucher-fetchers** — func:osa.get_sales_invoice_items, func:osa.get_purchase_invoice_items, func:osa.get_delivery_note_items [INFERRED 0.90]
- **Warning dialog pipeline (PE + JE)** — file:linked_party_warning.js, jshandler:pe_party_handlers, jshandler:jea_party_handlers, jshandler:je_company_handler, jsfn:bns_call_and_warn, fn:check_linked_party_opposite_balance, fn:_find_crossed_pair_for_party, doctype:Party Link [EXTRACTED 0.95]

## Communities

### Community 0 - "Internal Transfer Engine"
Cohesion: 0.01
Nodes (339): _apply_bns_internal_gl_rewrite_patch(), _apply_bns_repost_accounting_ledger_patch(), _apply_bns_repost_gl_failsafe_patch(), apply_bns_runtime_patches(), _apply_bns_transfer_rate_stock_ledger_patch(), apply_internal_pi_transfer_rates_from_si(), _audit_unlink_action(), backfill_item_references() (+331 more)

### Community 1 - "Dashboard API"
Cohesion: 0.04
Nodes (81): bulk_fix_pi_expense_accounts(), clear_internal_srbnb(), create_party_link(), _default_company(), execute_common_party_squareoff(), execute_full_squareoff_pipeline(), execute_historical_backfill(), execute_payment_reconciliation() (+73 more)

### Community 2 - "Transfer Accounting Audit"
Cohesion: 0.05
Nodes (74): _actual_gl_account_sides(), _apply_cutoff_filters(), _audit_cross_document_consistency(), _audit_delivery_notes(), _audit_purchase_invoices(), _audit_purchase_receipts(), _audit_sales_invoices(), _build_date_conditions() (+66 more)

### Community 3 - "Dashboard Frontend"
Cohesion: 0.09
Nodes (1): BNSDashboard

### Community 4 - "Branch Accounting Settings"
Cohesion: 0.06
Nodes (30): BNSBranchAccountingSettings, BNS Branch Accounting Settings - Account mapping for internal transfers., One-time migration: copy old Date field into new FY Link fields., Accounting Rewrite requires Internal Transfer to be set first, 		and its FY star, BNSRepostTracking, Tracks repost lock and processing status for idempotent BNS repost flows., apply_settings(), BNSSettings (+22 more)

### Community 5 - "Stock Update Validation"
Cohesion: 0.06
Nodes (49): Exception, _get_non_referenced_stock_items(), _has_sales_invoice_dn_links(), _is_sales_invoice_rate_adjustment_debit_note(), _is_stock_item(), _is_stock_update_validation_enabled(), _raise_purchase_invoice_reference_error(), _raise_sales_invoice_reference_error() (+41 more)

### Community 6 - "Party GL Report"
Cohesion: 0.07
Nodes (45): calculate_ageing_from_gl(), collect_voucher_nos_by_type(), downloadStatementPDF(), execute(), get_account_type_map(), get_accounts_with_children(), get_accountwise_gle(), get_balance() (+37 more)

### Community 7 - "Square-Off Tests"
Cohesion: 0.12
Nodes (15): _ensure_current_fiscal_year(), _ensure_customer(), _ensure_party_link(), _ensure_supplier(), _get_test_company(), _pick_balancing_account(), _post_journal(), Pick a non-party, non-group expense/income account to balance fixture JVs. (+7 more)

### Community 8 - "Transfer Receive Mismatch"
Cohesion: 0.09
Nodes (33): _amounts_equal(), _amounts_within_tolerance(), _apply_cutoff_filters(), check_si_pi_mismatch(), _check_si_pr_chain_mismatch(), company_address_query(), execute(), get_asymmetric_reference_mismatches() (+25 more)

### Community 9 - "Stock Entry BOM Variance"
Cohesion: 0.09
Nodes (16): BNSStockEntry, Business Needed Solutions - Stock Entry Component Quantity Variance  This module, Get expected BOM component item codes for component matching.          Returns:, Validate component quantities against BOM with variance tolerance.          If B, Check if BNS variance feature is enabled in BNS Settings.                  Retur, Extended Stock Entry class with BNS manufacturing controls.          Features:, Get default variance percentage from BNS Settings.                  Returns:, Validate component quantities with variance tolerance.                  Computes (+8 more)

### Community 10 - "Dashboard Orchestration"
Cohesion: 0.09
Nodes (25): BNS Dashboard (JS), BNS Dashboard API, Common Party Reconciliation Module, Common Party Square-Off Module, BNS Branch Accounting Settings, execute_full_squareoff_pipeline(), BNS Hooks Configuration, build_internal_srbnb_clearing_je() (+17 more)

### Community 11 - "Common Party Square-Off"
Cohesion: 0.13
Nodes (27): _active_party_links(), _build_leg(), check_linked_party_opposite_balance(), _classify_pair(), compute_linked_party_net_positions(), _default_cost_center(), _find_crossed_pair_for_party(), _get_party_signed_balance() (+19 more)

### Community 12 - "DN-PR Link Fixup"
Cohesion: 0.09
Nodes (26): _check_dn_pr_fixable(), _detect_chain_type(), _fix_dn_pr_link(), _format_item_issues(), _get_sis_from_dn(), _qtys_equal_bulk(), Verify all internal transfer chains after a cutoff date and optionally repost fu, Compare quantities with no tolerance; round to 6 decimals. (+18 more)

### Community 13 - "Pure AR/AP Reports"
Cohesion: 0.13
Nodes (14): redistribute_negative_ageing_buckets(), AccountsReceivablePayableSummary, execute(), get_customer_invoice_and_paid_amounts(), get_fiscal_year_dates(), get_gl_balance(), get_supplier_invoice_and_received_amounts(), Get customer invoice amounts (Sales Invoices including Credit Notes) for custome (+6 more)

### Community 14 - "ERPNext Stock Concepts"
Cohesion: 0.08
Nodes (26): negative-stock voucher detection (qty_after_transaction<0), sale-below-valuation detection (net_rate vs SLE valuation_rate), BOM, Bin, Delivery Note, Item, Purchase Invoice, Purchase Receipt (+18 more)

### Community 15 - "Attachment Validation"
Cohesion: 0.11
Nodes (24): check_ewaybill_applicability(), _get_ewaybill_threshold(), _has_linked_purchase_receipt(), _has_stock_items(), _is_attachment_validation_enabled(), _is_before_attachment_cutoff(), _is_bns_internal_supplier_scope(), _is_ewaybill_required() (+16 more)

### Community 16 - "Common Party Reconciliation"
Cohesion: 0.11
Nodes (23): _fetch_linked_primary_map(), _fetch_open_invoice_map(), _fetch_unallocated_payment_map(), _fiscal_years_back(), get_reconciliation_candidates(), _iter_parties_for_scope(), _list_companies_for_reconcile(), _party_account_has_balance() (+15 more)

### Community 17 - "GL and Payment Entries"
Cohesion: 0.09
Nodes (24): GL Entry, Journal Entry, Journal Entry Account (child), Payment Entry (doctype), ERPNext General Ledger report (parent), Linked Party Warning Dialog (JS), bank_gl.execute, bank_gl.get_accountwise_gle (+16 more)

### Community 18 - "Submission Restriction"
Cohesion: 0.13
Nodes (22): submission_restriction overrides module, _get_bns_settings(), Business Needed Solutions - Submission Restriction Test Suite  This module provi, Test permission checking functionality.          Returns:         bool: True if, Test that old restriction fields have been cleaned up.          Returns:, Custom exception for submission restriction test errors., Get BNS Settings document for testing.          Returns:         The BNS Setting, Test that the new 'restrict_submission' setting exists.          Args:         b (+14 more)

### Community 19 - "BNS Settings Tests"
Cohesion: 0.12
Nodes (12): FrappeTestCase, Verify BNS Settings can be loaded without error., TestBNSSettings, _balancing_account(), _ensure_current_fiscal_year(), _ensure_customer(), _ensure_supplier(), _get_test_company() (+4 more)

### Community 20 - "Bank GL Report"
Cohesion: 0.18
Nodes (21): execute(), get_account_type_map(), get_accounts_with_children(), get_accountwise_gle(), get_balance(), get_columns(), get_conditions(), get_data_with_opening_closing() (+13 more)

### Community 21 - "Direct Print System"
Cohesion: 0.16
Nodes (20): _build_pdf_url(), constructor(), create_dropdown_menu(), generate_pdf(), initialize(), _is_doctype_configured(), _is_sales_invoice_with_copy(), load_settings() (+12 more)

### Community 22 - "Outgoing Stock Audit"
Cohesion: 0.14
Nodes (20): build_report_data(), execute(), get_columns(), get_delivery_note_items(), get_items(), get_purchase_invoice_items(), get_purchase_receipt_items(), get_sales_invoice_items() (+12 more)

### Community 23 - "Migration Handler"
Cohesion: 0.14
Nodes (19): add_bns_internal_transfer_links(), add_bns_status_option(), after_migrate(), disable_pi_update_stock_mandatory_script(), ensure_pr_item_sales_invoice_item_field(), ensure_si_pr_reference_field(), initialize_bns_repost_tracking_state(), migrate_split_internal_transfer_accounts() (+11 more)

### Community 24 - "Update Items Override"
Cohesion: 0.21
Nodes (17): applyItemDetailsToDialogRow(), asFloat(), buildDialogFields(), buildItemDetailsArgs(), computeRate(), findDialogRow(), getAllowedUoms(), getBnsSettings() (+9 more)

### Community 25 - "Negative Stock Episodes"
Cohesion: 0.16
Nodes (16): execute(), export_fix_plan(), find_episodes_for_group(), find_negative_episodes(), get_columns(), get_conditions(), get_stock_ledger_data(), prepare_report_data() (+8 more)

### Community 26 - "Warehouse Negative Stock"
Cohesion: 0.18
Nodes (17): apply_patches(), _is_per_warehouse_negative_stock_enabled(), is_warehouse_negative_stock_disallowed(), Business Needed Solutions - Warehouse-Level Negative Stock Restriction  This mod, Validate negative stock for a single batch_no., Extract batch numbers from a Serial and Batch Bundle and validate 	each batch in, Check if a warehouse disallows negative stock. 	 	Args: 		warehouse (str): Wareh, Apply monkey patches to ERPNext stock ledger functions to add warehouse-level ne (+9 more)

### Community 27 - "Vehicle Update"
Cohesion: 0.2
Nodes (15): _load_document(), _prepare_update_data(), Business Needed Solutions - Vehicle Update System  This module provides function, Prepare the data to be updated.          Args:         vehicle_no (Optional[str], Update the document with the provided data.          Args:         doc: The docu, Show a success message after successful update.          Args:         doctype (, Custom exception for vehicle update errors., Update vehicle number and transporter details for a document.      This function (+7 more)

### Community 28 - "Item Transfer Rate Utils"
Cohesion: 0.14
Nodes (16): _clear_item_level_fields(), _clear_item_level_fields_pi(), _duplicate_serial_and_batch_bundle(), _get_dn_item_transfer_rate(), _get_si_item_transfer_rate(), Clone a Serial and Batch Bundle from source item row to target item row.      Ha, Update item details for the purchase receipt item., Get outgoing valuation mirror for a Delivery Note Item. (+8 more)

### Community 29 - "GST E-Waybill Integration"
Cohesion: 0.17
Nodes (15): _are_goods_supplied(), _get_ewaybill_threshold(), _is_inter_state_transfer(), _is_internal_dn_ewaybill_enabled(), maybe_generate_internal_dn_ewaybill(), BNS Branch Accounting - GST integration for internal transfers.  Handles: - Mand, Mandate Vehicle No or GST Transporter ID before submission for internal     cust, Check if internal DN e-Waybill feature is enabled in BNS Branch Accounting Setti (+7 more)

### Community 30 - "Group 30"
Cohesion: 0.23
Nodes (14): analyze_bom_availability(), analyze_episode(), convert_to_stock_qty(), execute(), find_alternative_warehouse(), get_bin_qty(), get_columns(), get_data() (+6 more)

### Community 31 - "Group 31"
Cohesion: 0.16
Nodes (14): _clear_document_level_fields(), _clear_document_level_fields_pi(), get_received_items(), _has_any_positive_received_qty(), Get already received items for a reference document.          Tracks partial rec, Return True if any already-received quantity exists for source item keys., Set missing values for the target Purchase Receipt., Clear warehouse and accounting dimension fields at document level. (+6 more)

### Community 32 - "Group 32"
Cohesion: 0.2
Nodes (13): _check_pan_uniqueness(), _find_existing_pan_document(), _get_doctype_label(), _is_pan_uniqueness_enabled(), _raise_pan_uniqueness_error(), Business Needed Solutions - PAN Validation System  This module provides validati, Find existing document with the same PAN number.          Args:         doctype, Raise a PAN uniqueness error with appropriate message.          Args:         do (+5 more)

### Community 33 - "Group 33"
Cohesion: 0.23
Nodes (11): _collect_outgoing(), _get_override_roles(), _get_stock_item_set(), Business Needed Solutions - Negative Stock Cutoff  Prerequisite: ERPNext Stock S, Roles allowed to submit negative stock on or before the cutoff date., Collect outgoing stock movements from the document, grouped by 	(item_code, ware, Return a set of item_code values from the document that are stock items. 	Single, before_submit hook on stock documents.  	Checks every outgoing stock movement in (+3 more)

### Community 34 - "Group 34"
Cohesion: 0.23
Nodes (11): _has_expense_account_configured(), _is_expense_account_validation_enabled(), _raise_expense_account_error(), Business Needed Solutions - Item Validation System  This module provides validat, Raise an error indicating that expense account is required.          Raises:, Validate that non-stock items have at least one expense account in Item Defaults, Check if expense account validation is enabled in BNS Settings.          Returns, Validate that the item has at least one expense account configured.          Arg (+3 more)

### Community 35 - "Group 35"
Cohesion: 0.21
Nodes (11): _compute_rate_from_price_list(), _get_discount_type(), get_item_details_for_update_items_dialog(), Business Needed Solutions - Custom Update Items for Sales Order / Purchase Order, Compute (rate, computed_discount_percentage) using BNS rules.  	- Single: rate =, Update Sales Order / Purchase Order items after submit using BNS fields.  	Args:, BNS wrapper for get_item_details used by Update Items dialog. 	Ensures correct a, Return BNS discount type (Single / Triple Compounded). (+3 more)

### Community 36 - "Group 36"
Cohesion: 0.31
Nodes (10): execute(), get_columns(), get_conditions(), get_entries(), get_item_details(), get_items(), get_price_list_rates(), group_by_item() (+2 more)

### Community 37 - "Group 37"
Cohesion: 0.36
Nodes (9): classify_invoice(), execute(), fetch_invoices(), fetch_tax_rows(), get_columns(), get_data(), GST ITC Health Check Report  Catches Purchase Invoice GST issues: 1. POS Mismatc, _row() (+1 more)

### Community 38 - "Group 38"
Cohesion: 0.27
Nodes (4): purpose(), refresh(), stock_entry_type(), _toggle_bom_mandatory()

### Community 39 - "Group 39"
Cohesion: 0.31
Nodes (8): clear_discounts(), constructor(), handle_discount_change(), initialize(), load_settings(), toggle_readonly_fields(), update_discount(), validate_and_clear_discounts()

### Community 40 - "Group 40"
Cohesion: 0.25
Nodes (9): Cancellation Philosophy, Chain Completion Invariant, PI GL Rewrite Parity, SI-PI Parity Invariant, Transfer Rate Authority, Master Bug Registry, Flow A: Same GSTIN Transfer, Flow B: Different GSTIN Transfer (+1 more)

### Community 41 - "Group 41"
Cohesion: 0.57
Nodes (6): _hideAttachmentSection(), _isLinkedToPR(), _refreshEwaybillVisibility(), _resolveBnsInternalSupplier(), setupPurchaseAttachmentFields(), _showAttachmentSection()

### Community 42 - "Group 42"
Cohesion: 0.29
Nodes (7): Address, Location, frappe.contacts.doctype.address.get_address_display, india_compliance.get_place_of_supply, bns_branch_accounting.utils.is_bns_internal_customer, _set_place_of_supply_from_address, set_customer_address_from_billing_location

### Community 43 - "Group 43"
Cohesion: 0.33
Nodes (6): Verify batch/serial information is consistent between paired source and target i, Compare batch entries between two Serial and Batch Bundles., Compare serial number entries between two Serial and Batch Bundles., _validate_batch_serial_parity(), _validate_sbb_batch_parity(), _validate_sbb_serial_parity()

### Community 44 - "Group 44"
Cohesion: 0.33
Nodes (6): cancel_linked_purchase_docs_for_sales_invoice(), _cancel_submitted_docs(), Cancel submitted documents safely and return cancelled count., Cancel linked submitted Purchase Receipts when cancelling Delivery Note.      On, Cancel linked submitted PI/PR when cancelling Sales Invoice.      One-way policy, validate_delivery_note_cancellation()

### Community 45 - "Group 45"
Cohesion: 0.4
Nodes (5): _as_list(), get_submitted_linked_docs(), BNS Branch Accounting - cancel dialog overrides.  This module customizes Frappe', Normalize ignore_doctypes_on_cancel_all payload to list., Filter cancel-all popup for BNS one-way cancellation policy.      Policy:     -

### Community 46 - "Group 46"
Cohesion: 0.33
Nodes (5): enforce_bns_over_standard_internal_customer(), enforce_bns_over_standard_internal_supplier(), BNS internal party guard.  When BNS internal flags are enabled, standard ERPNext, If BNS internal customer is on, keep standard internal customer off., If BNS internal supplier is on, keep standard internal supplier off.

### Community 47 - "Group 47"
Cohesion: 0.4
Nodes (5): BNS Branch Accounting - Billing Location → Customer Address  On validate: if bil, Set customer_address and GST fields from billing_location.linked_address on save, Set place_of_supply from address. Uses India Compliance if available, else addre, set_customer_address_from_billing_location(), _set_place_of_supply_from_address()

### Community 48 - "Group 48"
Cohesion: 0.53
Nodes (5): execute(), get_columns(), get_filtered_stock_entries(), _get_item_batch_no(), Resolve batch_no from a Stock Entry Detail row.  	Checks the legacy batch_no fie

### Community 49 - "Group 49"
Cohesion: 0.33
Nodes (5): apply_purchase_register_fix(), get_invoice_tax_map(), Temporary fix for ERPNext Purchase Register tax doubling bug.  Bug: get_invoice_, Patched version — adds `parenttype = 'Purchase Invoice'` filter., Monkey-patch the broken function in ERPNext's purchase_register module.

### Community 50 - "Group 50"
Cohesion: 0.4
Nodes (5): _is_same_gstin_validation_enabled(), Business Needed Solutions - GST Compliance System  This module provides GST comp, Validate that Purchase Invoice is not submitted when Supplier GSTIN     and Comp, Check if same GSTIN validation is enabled in BNS Settings.          Returns:, validate_purchase_invoice_same_gstin()

### Community 51 - "Group 51"
Cohesion: 0.33
Nodes (5): clear_existing_address_flags(), enforce_suppress_preferred_address(), Override Address to suppress is_primary_address and is_shipping_address when BNS, Force is_primary_address and is_shipping_address to 0 on every Address save, Bulk update all Address records to set is_primary_address=0 and is_shipping_addr

### Community 52 - "Group 52"
Cohesion: 0.33
Nodes (6): Negative Stock Cutoff Philosophy, BNS Settings Documentation, GST Compliance and E-Waybill, Per-Warehouse Negative Stock, PAN Validation, Triple Discount System

### Community 53 - "Group 53"
Cohesion: 0.33
Nodes (6): is_bns_internal_customer, is_bns_internal_supplier, is_internal_customer (ERPNext), is_internal_supplier (ERPNext), enforce_bns_over_standard_internal_customer, enforce_bns_over_standard_internal_supplier

### Community 54 - "Group 54"
Cohesion: 0.5
Nodes (4): ignore_parent_cancellation_links_for_bns_internal(), On PR/PI cancel, skip backlink-enforced parent cancellation.      Desired behavi, On PR/PI cancel, only remove BNS links; never cancel parent SI/DN.      Policy:, unlink_references_on_purchase_cancel()

### Community 55 - "Group 55"
Cohesion: 0.5
Nodes (4): _is_bns_internal_dn_pr_scope(), Return True when document is in BNS internal DN/PR scope., Hard gate before DN/PR submit for BNS internal scope.      Blocks submit when re, validate_bns_internal_accounting_settings_for_dn_pr()

### Community 56 - "Group 56"
Cohesion: 0.5
Nodes (3): get_value(), Fix malformed filters sent to frappe.client.get_value by old/cached client code., Drop-in override for frappe.client.get_value.  	Unwraps {"name": <dict>} → <dict

### Community 57 - "Group 57"
Cohesion: 0.83
Nodes (3): bns_call_and_warn(), bns_check_header_crossed(), bns_check_row_crossed()

### Community 58 - "Group 58"
Cohesion: 0.67
Nodes (3): GST ITC Health Check Report, _bns_check_pan_gstin_mismatch(), _bns_pan_from_gstin()

### Community 59 - "Group 59"
Cohesion: 0.83
Nodes (3): bns_toggle_fssai(), is_your_company_address(), refresh()

### Community 60 - "Group 60"
Cohesion: 0.67
Nodes (0): 

### Community 61 - "Group 61"
Cohesion: 0.67
Nodes (1): Set Report "Internal Transfer Receive Mismatch" module to BNS Branch Accounting.

### Community 62 - "Group 62"
Cohesion: 0.67
Nodes (0): 

### Community 63 - "Group 63"
Cohesion: 0.67
Nodes (1): Migrate enable_internal_dn_ewaybill from BNS Settings to BNS Branch Accounting S

### Community 64 - "Group 64"
Cohesion: 0.67
Nodes (1): Remove custom_destination custom field from Purchase Receipt and Purchase Invoic

### Community 65 - "Group 65"
Cohesion: 0.67
Nodes (1): Remove the interim 'BNS Health Check' workspace.  The workspace has been consoli

### Community 66 - "Group 66"
Cohesion: 0.67
Nodes (1): Remove stale workspace records that no longer have a JSON file on disk.

### Community 67 - "Group 67"
Cohesion: 0.67
Nodes (1): Ensure warehouse-level negative stock monkey-patches are applied before stock do

### Community 68 - "Group 68"
Cohesion: 0.67
Nodes (3): BNS Branch Accounting Settings (DocType controller), bns_branch_accounting.gst_integration (e-Waybill), Fiscal Year Cutoff (internal_transfer / accounting_rewrite)

### Community 69 - "Group 69"
Cohesion: 0.67
Nodes (2): Negative Stock Resolution Report, Outgoing Stock Audit - 1 BNS

### Community 70 - "Group 70"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "Group 71"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Group 72"
Cohesion: 1.0
Nodes (0): 

### Community 73 - "Group 73"
Cohesion: 1.0
Nodes (2): Migration Correctness Guarantee, Migration and Post-Install

### Community 74 - "Group 74"
Cohesion: 1.0
Nodes (2): Submission Restriction Docs, Submission Restriction System

### Community 75 - "Group 75"
Cohesion: 1.0
Nodes (2): BNSRepostTracking, BNS Repost Tracking

### Community 76 - "Group 76"
Cohesion: 1.0
Nodes (2): overrides/billing_location.py, overrides/internal_party.py

### Community 77 - "Group 77"
Cohesion: 1.0
Nodes (2): bns_branch_accounting.utils, business_needed_solutions/utils.py (re-export)

### Community 78 - "Group 78"
Cohesion: 1.0
Nodes (1): Pure Accounts Receivable Summary (linked)

### Community 79 - "Init"
Cohesion: 1.0
Nodes (0): 

### Community 80 - "Hooks"
Cohesion: 1.0
Nodes (0): 

### Community 81 - "Bns Settings Rationale 47"
Cohesion: 1.0
Nodes (1): Apply BNS settings to all relevant doctypes.          This method updates field

### Community 82 - "Sales Invoice List"
Cohesion: 1.0
Nodes (0): 

### Community 83 - "Delivery Note List"
Cohesion: 1.0
Nodes (0): 

### Community 84 - "Purchase Receipt List"
Cohesion: 1.0
Nodes (0): 

### Community 85 - "Purchase Invoice Form"
Cohesion: 1.0
Nodes (0): 

### Community 86 - "Supplier List"
Cohesion: 1.0
Nodes (0): 

### Community 87 - "Delivery Note"
Cohesion: 1.0
Nodes (0): 

### Community 88 - "Sales Invoice Form"
Cohesion: 1.0
Nodes (0): 

### Community 89 - "Item"
Cohesion: 1.0
Nodes (0): 

### Community 90 - "Purchase Receipt Form"
Cohesion: 1.0
Nodes (0): 

### Community 91 - "Purchase Invoice List"
Cohesion: 1.0
Nodes (0): 

### Community 92 - "Gst Itc Health Check Js"
Cohesion: 1.0
Nodes (1): GST ITC Health Check (JS)

### Community 93 - "Accounts Receivable Payable Summary Clas"
Cohesion: 1.0
Nodes (1): AccountsReceivablePayableSummary Class

### Community 94 - "Fn Build Internal Srbnb Clearing Je"
Cohesion: 1.0
Nodes (0): 

### Community 95 - "Fn Make Bns Internal Purchase Receipt"
Cohesion: 1.0
Nodes (0): 

### Community 96 - "Fn Make Bns Internal Purchase Invoice"
Cohesion: 1.0
Nodes (0): 

### Community 97 - "Fn Verify And Repost"
Cohesion: 1.0
Nodes (0): 

### Community 98 - "Handbook Architectural Intent"
Cohesion: 1.0
Nodes (1): Architectural Intent

### Community 99 - "Handbook Health Check Dashboard"
Cohesion: 1.0
Nodes (1): Health Check Dashboard Philosophy

### Community 100 - "Technical Handbook"
Cohesion: 1.0
Nodes (1): BNS Technical Handbook

### Community 101 - "Tech Bom Variance"
Cohesion: 1.0
Nodes (1): BOM Component Qty Variance

### Community 102 - "Tech Direct Print"
Cohesion: 1.0
Nodes (1): Direct Print System

### Community 103 - "Warehouse Restriction Doc"
Cohesion: 1.0
Nodes (1): Warehouse Restriction Feature

### Community 104 - "Bns Repost Tracking Doctype"
Cohesion: 1.0
Nodes (1): BNS Repost Tracking DocType

### Community 105 - "Internal Party Override"
Cohesion: 1.0
Nodes (1): internal_party.enforce_bns_over_standard_internal_(customer|supplier)

### Community 106 - "Billing Location Override"
Cohesion: 1.0
Nodes (1): billing_location.set_customer_address_from_billing_location

### Community 107 - "Doctype:Accounts Settings"
Cohesion: 1.0
Nodes (1): Accounts Settings

### Community 108 - "Stock Update Validation Override"
Cohesion: 1.0
Nodes (1): stock_update_validation.validate_stock_update_or_reference

### Community 109 - "Stock Entry Override Bnsstockentry"
Cohesion: 1.0
Nodes (1): BNSStockEntry (stock_entry_component_qty_variance override)

### Community 110 - "Gst Compliance Override"
Cohesion: 1.0
Nodes (1): gst_compliance.validate_purchase_invoice_same_gstin

### Community 111 - "Item Validation Override"
Cohesion: 1.0
Nodes (1): item_validation.validate_expense_account_for_non_stock_items

### Community 112 - "Pan Validation Override"
Cohesion: 1.0
Nodes (1): pan_validation.validate_pan_uniqueness

### Community 113 - "Warehouse Negative Stock Override"
Cohesion: 1.0
Nodes (1): warehouse_negative_stock.validate_sle_warehouse_negative_stock

## Knowledge Gaps
- **627 isolated node(s):** `Business Needed Solutions - Submission Restriction Test Suite  This module provi`, `Custom exception for submission restriction test errors.`, `Test script to verify the unified submission restriction system.          This f`, `Test BNS Settings configuration for new unified system.          Returns:`, `Test document categorization functionality.          Returns:         bool: True` (+622 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Group 70`** (2 nodes): `bns_supplier.js`, `_sync_standard_internal_visibility()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 71`** (2 nodes): `bns_customer.js`, `_sync_standard_internal_visibility()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 72`** (2 nodes): `warehouse.js`, `_check_and_toggle_negative_stock_field()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 73`** (2 nodes): `Migration Correctness Guarantee`, `Migration and Post-Install`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 74`** (2 nodes): `Submission Restriction Docs`, `Submission Restriction System`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 75`** (2 nodes): `BNSRepostTracking`, `BNS Repost Tracking`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 76`** (2 nodes): `overrides/billing_location.py`, `overrides/internal_party.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 77`** (2 nodes): `bns_branch_accounting.utils`, `business_needed_solutions/utils.py (re-export)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Group 78`** (2 nodes): `pure_accounts_payable_summary.js`, `Pure Accounts Receivable Summary (linked)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Hooks`** (1 nodes): `hooks.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bns Settings Rationale 47`** (1 nodes): `Apply BNS settings to all relevant doctypes.          This method updates field`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Sales Invoice List`** (1 nodes): `sales_invoice_list.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Delivery Note List`** (1 nodes): `delivery_note_list.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Purchase Receipt List`** (1 nodes): `purchase_receipt_list.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Purchase Invoice Form`** (1 nodes): `purchase_invoice_form.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Supplier List`** (1 nodes): `supplier_list.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Delivery Note`** (1 nodes): `delivery_note.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Sales Invoice Form`** (1 nodes): `sales_invoice_form.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Item`** (1 nodes): `item.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Purchase Receipt Form`** (1 nodes): `purchase_receipt_form.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Purchase Invoice List`** (1 nodes): `purchase_invoice_list.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Gst Itc Health Check Js`** (1 nodes): `GST ITC Health Check (JS)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Accounts Receivable Payable Summary Clas`** (1 nodes): `AccountsReceivablePayableSummary Class`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Fn Build Internal Srbnb Clearing Je`** (1 nodes): `build_internal_srbnb_clearing_je()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Fn Make Bns Internal Purchase Receipt`** (1 nodes): `make_bns_internal_purchase_receipt()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Fn Make Bns Internal Purchase Invoice`** (1 nodes): `make_bns_internal_purchase_invoice()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Fn Verify And Repost`** (1 nodes): `verify_and_repost_internal_transfers()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Handbook Architectural Intent`** (1 nodes): `Architectural Intent`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Handbook Health Check Dashboard`** (1 nodes): `Health Check Dashboard Philosophy`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Technical Handbook`** (1 nodes): `BNS Technical Handbook`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tech Bom Variance`** (1 nodes): `BOM Component Qty Variance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tech Direct Print`** (1 nodes): `Direct Print System`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Warehouse Restriction Doc`** (1 nodes): `Warehouse Restriction Feature`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bns Repost Tracking Doctype`** (1 nodes): `BNS Repost Tracking DocType`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Internal Party Override`** (1 nodes): `internal_party.enforce_bns_over_standard_internal_(customer|supplier)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Billing Location Override`** (1 nodes): `billing_location.set_customer_address_from_billing_location`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Doctype:Accounts Settings`** (1 nodes): `Accounts Settings`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Stock Update Validation Override`** (1 nodes): `stock_update_validation.validate_stock_update_or_reference`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Stock Entry Override Bnsstockentry`** (1 nodes): `BNSStockEntry (stock_entry_component_qty_variance override)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Gst Compliance Override`** (1 nodes): `gst_compliance.validate_purchase_invoice_same_gstin`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Item Validation Override`** (1 nodes): `item_validation.validate_expense_account_for_non_stock_items`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Pan Validation Override`** (1 nodes): `pan_validation.validate_pan_uniqueness`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Warehouse Negative Stock Override`** (1 nodes): `warehouse_negative_stock.validate_sle_warehouse_negative_stock`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BNSSettingsError` connect `Branch Accounting Settings` to `Stock Update Validation`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Why does `BNSValidationError` connect `Internal Transfer Engine` to `Stock Update Validation`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._
- **What connects `Business Needed Solutions - Submission Restriction Test Suite  This module provi`, `Custom exception for submission restriction test errors.`, `Test script to verify the unified submission restriction system.          This f` to the rest of the system?**
  _627 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Internal Transfer Engine` be split into smaller, more focused modules?**
  _Cohesion score 0.01 - nodes in this community are weakly interconnected._
- **Should `Dashboard API` be split into smaller, more focused modules?**
  _Cohesion score 0.04 - nodes in this community are weakly interconnected._
- **Should `Transfer Accounting Audit` be split into smaller, more focused modules?**
  _Cohesion score 0.05 - nodes in this community are weakly interconnected._
- **Should `Dashboard Frontend` be split into smaller, more focused modules?**
  _Cohesion score 0.09 - nodes in this community are weakly interconnected._