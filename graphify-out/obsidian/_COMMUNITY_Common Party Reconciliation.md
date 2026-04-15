---
type: community
cohesion: 0.11
members: 24
---

# Common Party Reconciliation

**Cohesion:** 0.11 - loosely connected
**Members:** 24 nodes

## Members
- [[Batch runner. Iterate parties per scope; call reconcile_single_party.  	If `part]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Cheap pre-filter signed balance on party account. Non-zero - candidate.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Indirection so tests can monkey-patch without mocking frappe.get_all.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Map BNS Settings 'common_party_reconcile_window' to (from_date, to_date).  	- 'A]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Per-party reconciliation status report for the BNS Dashboard.  	For every party]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Return {(party_type, party) (primary_role, primary_party)} — the 	'where does r]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Return {(party_type, party) {count, outstanding}} from SI + PI tables. 	outstan]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Return {(party_type, party) {count, unallocated}} from Payment Entry.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Run ERPNext's Payment Reconciliation tool for exactly one party.  	Returns a sum]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Update the read-only stamp on BNS Settings.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Yield (party_type, party) tuples according to the reconciliation scope.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_fetch_linked_primary_map()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_fetch_open_invoice_map()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_fetch_unallocated_payment_map()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_fiscal_years_back()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_iter_parties_for_scope()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_list_companies_for_reconcile()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_party_account_has_balance()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_resolve_window()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[common_party_reconciliation.py]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[get_reconciliation_candidates()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[reconcile_all_parties()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[reconcile_single_party()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[stamp_reconcile_last_run()]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Common_Party_Reconciliation
SORT file.name ASC
```
