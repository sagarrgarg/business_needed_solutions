---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py"
type: "code"
community: "Common Party Payment Reconciliation (FIFO)"
location: "L116-211"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Payment_Reconciliation_(FIFO)
---

# reconcile_single_party()

## Connections
- [[Auto Payment Reconciliation (FIFO)]] - `implements` [INFERRED]
- [[Per-party savepoint isolation]] - `implements` [EXTRACTED]
- [[TestCommonPartyReconciliation_1]] - `references` [EXTRACTED]
- [[_party_account_has_balance()_1]] - `calls` [EXTRACTED]
- [[_resolve_window()_1]] - `calls` [EXTRACTED]
- [[common_party_reconciliation.py_1]] - `references` [EXTRACTED]
- [[reconcile_all_parties()_1]] - `calls` [EXTRACTED]
- [[test_reconcile_single_party_noop_when_only_one_side]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Payment_Reconciliation_(FIFO)