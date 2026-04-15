---
type: community
cohesion: 0.05
members: 77
---

# Internal Transfer Audit Report

**Cohesion:** 0.05 - loosely connected
**Members:** 77 nodes

## Members
- [[Apply cutoff as default from_date when user has not provided one._1]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Audit GL and SLE for BNS internal Purchase Invoices (including debit notes).]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Audit GL and SLE for BNS internal Purchase Receipts.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Audit GL entries for BNS internal Delivery Notes.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Audit GL entries for BNS internal Sales Invoices (including credit notes).]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Background worker create Repost Item Valuation entries for each document.  	Arg]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Background worker force-rebuild GL entries for each document.  	Args 		documen]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Build SQL WHERE fragments for date and company filters.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Build a single report output row.  	Args 		doc_row dict from SQL with name, po]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Build report rows by auditing GL and SLE for each BNS internal document.  	Args]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Classify a Delivery Note into its BNS internal scope.  	Returns 		str or None]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Classify a Purchase Invoice.  	Returns 		str or None 'si_linked'  'si_linked_]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Classify a Purchase Receipt.  	Returns 		str or None 'dn_same_gstin'  'si_lin]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Classify a Sales Invoice.  	Returns 		str or None 'different_gstin'  'differe]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Compare expected vs actual GL account-side sets.  	Ignores ERPNext round-off acc]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Define report columns._1]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Derive set of (account, side) tuples from actual GL entries.  	Returns 		set of]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Detect cross-document issues that per-document audits miss.  	Checks 	1. Orphan]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Enqueue GL rebuild for a batch of audit-flagged documents.  	Uses the existing b]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Enqueue SLE repost for a batch of audit-flagged documents.  	Creates one Repost]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Entry point for the Script Report.  	Args 		filters dict with optional keys co]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Fetch BNS Branch Accounting account names.  	Returns 		dict with account names,]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Fetch actual GL Entry rows for a given voucher.  	Returns 		list of dicts with]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Format a set of (account, side) tuples into a readable string.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Resolve the company round-off account (used by ERPNext for GL residuals).]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Resolve the stock-in-hand account for a document via warehouse account map.  	Re]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return True when document has zero grand total and net total -- no GL expected.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return list of doctypes to audit based on filter.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return set of (account, side) tuples for expected BNS GL on PI debit note (rever]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return set of (account, side) tuples for expected BNS GL on SI credit note (reve]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return set of (account, side) tuples for expected BNS GL pattern on PI.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return set of (account, side) tuples for expected BNS GL pattern on PR.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return set of (account, side) tuples for expected BNS GL pattern on SI.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Return set of (account, side) tuples for expected BNS GL pattern.  	Args 		scop]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Validate SLE incoming_rate against bns_transfer_rate for PI items (update_stock]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Validate SLE incoming_rate against bns_transfer_rate for PR items.  	Returns]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_actual_gl_account_sides()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_apply_cutoff_filters()_1]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_audit_cross_document_consistency()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_audit_delivery_notes()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_audit_purchase_invoices()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_audit_purchase_receipts()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_audit_sales_invoices()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_build_date_conditions()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_build_row()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_check_sle_for_pi()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_check_sle_for_pr()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_classify_dn()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_classify_pi()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_classify_pr()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_classify_si()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_compare_gl()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_expected_gl_for_dn()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_expected_gl_for_pi()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_expected_gl_for_pi_return()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_expected_gl_for_pr()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_expected_gl_for_si()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_expected_gl_for_si_return()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_fetch_gl_entries()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_format_account_set()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_get_bns_accounts()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_get_columns()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_get_data()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_get_doc_types_to_audit()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_get_round_off_account()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_hasGlDeviation()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.js
- [[_hasSleDeviation()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.js
- [[_is_zero_amount_document()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_process_gl_repost_batch()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_process_sle_repost_batch()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_resolve_stock_account_for_doc()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[_triggerBulkRepost()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.js
- [[execute()_1]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[internal_transfer_accounting_audit.py]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[onload()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.js
- [[repost_gl_for_audit_documents()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[repost_sle_for_audit_documents()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Internal_Transfer_Audit_Report
SORT file.name ASC
```
