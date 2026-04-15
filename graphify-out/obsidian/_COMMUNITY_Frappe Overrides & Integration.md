---
type: community
cohesion: 0.06
members: 44
---

# Frappe Overrides & Integration

**Cohesion:** 0.06 - loosely connected
**Members:** 44 nodes

## Members
- [[BNS Branch Accounting Settings (DocType controller)]] - code - business_needed_solutions/bns_branch_accounting/doctype/bns_branch_accounting_settings/bns_branch_accounting_settings.py
- [[BNS GL Repost Correction pattern]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[BNS Internal Transfer Flow (DN-PR, SI-PI)]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[BNS Repost Tracking DocType]] - code - business_needed_solutions/bns_branch_accounting/doctype/bns_repost_tracking/bns_repost_tracking.js
- [[Business Needed Solutions - Negative Stock Cutoff  Prerequisite ERPNext Stock S]] - rationale - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[Business Needed Solutions App (hooks.py)]] - code - business_needed_solutions/hooks.py
- [[Collect outgoing stock movements from the document, grouped by 	(item_code, ware]] - rationale - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[Ensure warehouse-level negative stock monkey-patches are applied before stock do]] - rationale - business_needed_solutions/business_needed_solutions/overrides/ensure_stock_patches.py
- [[Fiscal Year Cutoff (internal_transfer  accounting_rewrite)]] - code - business_needed_solutions/bns_branch_accounting/doctype/bns_branch_accounting_settings/bns_branch_accounting_settings.py
- [[GST Settings (India Compliance)]] - code - external/india_compliance
- [[Internal Transfer Accounting Audit report]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Internal Transfer Receive Mismatch report]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Return a set of item_code values from the document that are stock items. 	Single]] - rationale - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[Returns True when BNS should block negative stock for this 	posting_date and cur]] - rationale - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[Roles allowed to submit negative stock on or before the cutoff date.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[_collect_outgoing()]] - code - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[_get_override_roles()]] - code - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[_get_stock_item_set()]] - code - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[_global_runtime_patches (before_requestbefore_job)]] - code - business_needed_solutions/hooks.py
- [[address_preferred_flags.enforce_suppress_preferred_address]] - code - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py
- [[after_migrate hook]] - code - business_needed_solutions/hooks.py
- [[attachment_validation.validate_purchase_attachments]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[before_submit hook on stock documents.  	Checks every outgoing stock movement in]] - rationale - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[before_submit()]] - code - business_needed_solutions/business_needed_solutions/overrides/ensure_stock_patches.py
- [[billing_location.set_customer_address_from_billing_location]] - code - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[bns_branch_accounting.gst_integration (e-Waybill)]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[bns_branch_accounting.migration]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[bns_branch_accounting.utils (core internal-transfer engine)]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[cancel_dialog.get_submitted_linked_docs override]] - code - business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py
- [[doc_events hook registry]] - code - business_needed_solutions/hooks.py
- [[ensure_stock_patches.py]] - code - business_needed_solutions/business_needed_solutions/overrides/ensure_stock_patches.py
- [[get_value_filters_fix.get_value]] - code - business_needed_solutions/business_needed_solutions/overrides/get_value_filters_fix.py
- [[gst_compliance.validate_purchase_invoice_same_gstin]] - code - business_needed_solutions/business_needed_solutions/overrides/gst_compliance.py
- [[india_compliance.gst_india.utils.e_waybill._generate_e_waybill]] - code - external/india_compliance
- [[internal_party.enforce_bns_over_standard_internal_(customersupplier)]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[item_validation.validate_expense_account_for_non_stock_items]] - code - business_needed_solutions/business_needed_solutions/overrides/item_validation.py
- [[negative_stock_override.py]] - code - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[override_whitelisted_methods]] - code - business_needed_solutions/hooks.py
- [[pan_validation.validate_pan_uniqueness]] - code - business_needed_solutions/business_needed_solutions/overrides/pan_validation.py
- [[should_restrict()]] - code - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[stock_update_validation.validate_stock_update_or_reference]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[update_vehicle_or_transporter whitelisted API]] - code - business_needed_solutions/update_vehicle.py
- [[validate_negative_stock()]] - code - business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py
- [[warehouse_negative_stock.validate_sle_warehouse_negative_stock]] - code - business_needed_solutions/business_needed_solutions/overrides/warehouse_negative_stock.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Frappe_Overrides_&_Integration
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Submission & Stock Validation]]

## Top bridge nodes
- [[doc_events hook registry]] - degree 16, connects to 1 community