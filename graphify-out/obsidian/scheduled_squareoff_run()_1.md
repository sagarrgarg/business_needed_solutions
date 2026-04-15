---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party Payment Reconciliation (FIFO)"
location: "L327-440"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Payment_Reconciliation_(FIFO)
---

# scheduled_squareoff_run()

## Connections
- [[Rationale scheduled cadence over PE hook (auditable, predictable)]] - `rationale_for` [EXTRACTED]
- [[_list_companies_for_schedule()_1]] - `calls` [EXTRACTED]
- [[_run_reconcile() squareoff wrapper]] - `calls` [EXTRACTED]
- [[_run_scheduler_scoped (isolation harness)]] - `calls` [EXTRACTED]
- [[_schedule_is_due()_1]] - `calls` [EXTRACTED]
- [[compute_linked_party_net_positions()_1]] - `calls` [EXTRACTED]
- [[hooks.scheduler_events.daily - scheduled_squareoff_run]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties()_1]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Payment_Reconciliation_(FIFO)