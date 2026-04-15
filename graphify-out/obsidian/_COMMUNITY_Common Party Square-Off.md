---
type: community
cohesion: 0.13
members: 28
---

# Common Party Square-Off

**Cohesion:** 0.13 - loosely connected
**Members:** 28 nodes

## Members
- [[Batch runner. Returns a summary dict with postedskippederrors.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Daily scheduler tick. Runs auto square-off across every company when the 	config]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Decide what kind of square-off this pair needs.  	Returns (kind, amount, source)]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Indirection so tests can patch it without mocking the whole frappe.get_all.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Is this balance on the natural side for its account type  	  - Customer (Debt]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Lazy-import wrapper so common_party_reconciliation can safely import us 	back (f]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Post one balanced contra JV between the primary and secondary party.  	Handles b]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Re-read live GL balances for a pair and re-classify.  	Returns a fresh pair dict]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Return the list of linked pairs that need a contra JV.  	Two kinds of pairs are]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Signed GL balance (debit - credit) for party on its party account.]] - rationale - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_active_party_links()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_build_leg()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_classify_pair()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_default_cost_center()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_find_crossed_pair_for_party()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_get_party_signed_balance()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_is_normal_balance()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_list_companies_for_schedule()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_pair_key()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_refresh_pair_balances()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_run_reconcile()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_schedule_is_due()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[check_linked_party_opposite_balance()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[common_party_squareoff.py]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[compute_linked_party_net_positions()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[scheduled_squareoff_run()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[square_off_all_common_parties()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[square_off_linked_party()]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Common_Party_Square-Off
SORT file.name ASC
```
