---
source_file: "business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py"
type: "code"
community: "Common Party Payment Reconciliation (FIFO)"
location: "L1353-1397"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Payment_Reconciliation_(FIFO)
---

# execute_payment_reconciliation()

## Connections
- [[Rationale sync up to SQUAREOFF_SYNC_BATCH_CAP (20), else enqueue long job]] - `rationale_for` [EXTRACTED]
- [[_get_reconcile_settings()_1]] - `calls` [EXTRACTED]
- [[_require_accounts_manager()_1]] - `calls` [EXTRACTED]
- [[_run_reconcile_batch() RQ job]] - `references` [EXTRACTED]
- [[get_reconciliation_candidates()_1]] - `calls` [EXTRACTED]
- [[reconcile_all_parties()_1]] - `calls` [EXTRACTED]
- [[run_payment_reconciliation() JS]] - `calls` [EXTRACTED]
- [[stamp_reconcile_last_run()_1]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Payment_Reconciliation_(FIFO)