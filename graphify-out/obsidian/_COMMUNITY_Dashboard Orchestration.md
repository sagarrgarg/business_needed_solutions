---
type: community
cohesion: 0.09
members: 29
---

# Dashboard Orchestration

**Cohesion:** 0.09 - loosely connected
**Members:** 29 nodes

## Members
- [[BNS Branch Accounting Settings]] - code
- [[BNS Branch Accounting Utils]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[BNS Dashboard (JS)]] - code - business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[BNS Dashboard API]] - code - business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[BNS Hooks Configuration]] - code - business_needed_solutions/hooks.py
- [[Build (and optionally submit) a Journal Entry that clears the SRBNB 	liability f]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[Common Party Reconciliation Module]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Common Party Square-Off Module]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Get Stock Entry type and warehouse info for SRBNB categorisation.]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[Get the linked Delivery Note for a BNS internal PR.]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[Return set of PI names that have at least one item with a purchase_receipt link.]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[Return set of PR names that are BNS internal transfers.]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[Return set of PR names that have at least one submitted PI linked.]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[Return the SRBNB reconciliation breakdown for the BNS Dashboard.  	Buckets 	  1]] - rationale - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_empty_result()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_bns_internal_prs()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_paired_prs()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_pi_supplier()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_pis_with_pr_link()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_pr_linked_dn()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_pr_supplier()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[_get_stock_entry_info()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[apply_bns_runtime_patches()_1]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[apply_purchase_register_fix()_1]] - code - business_needed_solutions/overrides/purchase_register_fix.py
- [[build_internal_srbnb_clearing_je()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[execute_full_squareoff_pipeline()_1]] - code - business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[get_srbnb_reconciliation()]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[srbnb_reconciliation.py]] - code - business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py
- [[validate_purchase_attachments()_1]] - code - business_needed_solutions/overrides/attachment_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Dashboard_Orchestration
SORT file.name ASC
```
