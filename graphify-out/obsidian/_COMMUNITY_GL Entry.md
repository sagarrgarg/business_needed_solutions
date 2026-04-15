---
type: community
cohesion: 0.07
members: 35
---

# GL Entry

**Cohesion:** 0.07 - loosely connected
**Members:** 35 nodes

## Members
- [[(RENAMED) payment_entry_linked_party_warning.js]] - document - business_needed_solutions/public/js/linked_party_warning.js
- [[BNS Dashboard - Linked Party Square-Off manual action]] - document - business_needed_solutions/public/js/linked_party_warning.js
- [[Bank GL Report]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[ERPNext General Ledger report (parent)]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[GL Entry]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[Journal Entry]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[Journal Entry Account (child)]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[Journal Entry Account partyparty_type handlers]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[Journal Entry company handler (recheck rows)]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[Linked Party Warning Dialog (JS)]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[Party GL Report (linked)]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[Payment Entry (doctype)]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[Payment Entry partyparty_typecompany handlers]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[Pure Accounts Payable Summary]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[Pure Accounts Receivable Summary (linked)]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.js
- [[Rationale Payment Entry has header party; Journal Entry has party per accounts child row - dialog covers both shapes]] - document - business_needed_solutions/public/js/linked_party_warning.js
- [[Rationale daily tick is cheap because scheduled_squareoff_run short-circuits on schedulelast_run; lets operators change cadence without restart]] - document - business_needed_solutions/hooks.py
- [[Rationale warning dialog is purely a nudge, never blocks savesubmit]] - document - business_needed_solutions/public/js/linked_party_warning.js
- [[bank_gl.execute]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[bank_gl.get_accountwise_gle]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[bank_gl.get_columns]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[bank_gl.get_conditions]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[bank_gl.get_gl_entries]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[bank_gl.js filters]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.js
- [[bns_call_and_warn]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[bns_check_header_crossed]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[bns_check_row_crossed]] - code - business_needed_solutions/public/js/linked_party_warning.js
- [[check_linked_party_opposite_balance()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[doctype_js'Journal Entry' - linked_party_warning.js]] - code - business_needed_solutions/hooks.py
- [[doctype_js'Payment Entry' - linked_party_warning.js]] - code - business_needed_solutions/hooks.py
- [[get_party_details_from_against]] - code - business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py
- [[hooks.py_1]] - code - business_needed_solutions/hooks.py
- [[hooks.scheduler_events.daily - scheduled_squareoff_run]] - code - business_needed_solutions/hooks.py
- [[pure_accounts_payable_summary.js_1]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.js
- [[test_warning_helper_gated_by_setting]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/GL_Entry
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Common Party Payment Reconciliation (FIFO)]]

## Top bridge nodes
- [[hooks.scheduler_events.daily - scheduled_squareoff_run]] - degree 3, connects to 1 community
- [[test_warning_helper_gated_by_setting]] - degree 2, connects to 1 community