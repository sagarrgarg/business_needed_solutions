---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py"
type: "code"
community: "Common Party Payment Reconciliation (FIFO)"
location: "L72-97"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Payment_Reconciliation_(FIFO)
---

# _resolve_window()

## Connections
- [[Reconciliation Window labels (All time  Last 2 FY  Since Cutoff)]] - `implements` [EXTRACTED]
- [[_fiscal_years_back()_1]] - `calls` [EXTRACTED]
- [[_get_accounting_rewrite_cutoff_date()_1]] - `calls` [EXTRACTED]
- [[common_party_reconciliation.py_1]] - `references` [EXTRACTED]
- [[reconcile_single_party()_1]] - `calls` [EXTRACTED]
- [[test_resolve_window_all_time]] - `references` [EXTRACTED]
- [[test_resolve_window_last_2_fy]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Payment_Reconciliation_(FIFO)