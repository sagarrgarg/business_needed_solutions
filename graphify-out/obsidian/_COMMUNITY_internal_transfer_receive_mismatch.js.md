---
type: community
cohesion: 0.09
members: 32
---

# internal_transfer_receive_mismatch.js

**Cohesion:** 0.09 - loosely connected
**Members:** 32 nodes

## Members
- [[Apply cutoff as default from_date when user has not provided one.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Check SI-PR chain for item mismatches.  	Args 		si_name Sales Invoice name]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Check if Sales Invoice has matching Purchase Invoice. 	Compares quantities, taxa]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Compare amounts allowing a configurable tolerance (absolute value).]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Compare amounts with no tolerance; round to 2 decimals.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Compare quantities with no tolerance; round to 6 decimals._1]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Define report columns.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Execute the report and return columns and data. 	 	Args 		filters Dictionary o]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Find submitted internal PRPI rows violating PRPI linkage rules.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Get Delivery Notes that are missing Purchase Receipts or have quantity mismatche]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Get Sales Invoices that are missing Purchase Invoices or Purchase Receipts or ha]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Get report data by checking for missing or mismatched Purchase ReceiptsPurchase]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Load the SI-PI amount tolerance from BNS Branch Accounting Settings.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Query to fetch only company addresses for the report filter.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[Return link flags for DNSI from given reference values.]] - rationale - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_amounts_equal()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_amounts_within_tolerance()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_apply_cutoff_filters()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_check_si_pr_chain_mismatch()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_get_si_pi_amount_tolerance()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_link_flags_from_refs()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_qtys_equal()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[_resolve_scope()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[check_si_pi_mismatch()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[company_address_query()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[execute()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[get_columns()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[get_data()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[get_delivery_note_mismatches()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[get_internal_purchase_doc_linkage_mismatches()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[get_sales_invoice_mismatches()]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[internal_transfer_receive_mismatch.js]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.js

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/internal_transfer_receive_mismatch.js
SORT file.name ASC
```
