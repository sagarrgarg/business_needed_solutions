---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py"
type: "code"
community: "Common Party Payment Reconciliation (FIFO)"
location: "L358-369"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Payment_Reconciliation_(FIFO)
---

# stamp_reconcile_last_run()

## Connections
- [[_run_reconcile_batch() RQ job]] - `calls` [EXTRACTED]
- [[common_party_reconciliation.py_1]] - `references` [EXTRACTED]
- [[execute_full_squareoff_pipeline()_1]] - `calls` [EXTRACTED]
- [[execute_payment_reconciliation()_1]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Payment_Reconciliation_(FIFO)