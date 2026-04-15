---
source_file: "business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py"
type: "code"
community: "Common Party Payment Reconciliation (FIFO)"
location: "L363"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Payment_Reconciliation_(FIFO)
---

# _run_scheduler_scoped (isolation harness)

## Connections
- [[Rationale test isolation patches _list_companies_for_schedule AND _active_party_links so scheduler never sees production Party Link data on shared dev site]] - `rationale_for` [EXTRACTED]
- [[TestCommonPartySquareOff_1]] - `implements` [EXTRACTED]
- [[_list_companies_for_schedule()_1]] - `references` [EXTRACTED]
- [[scheduled_squareoff_run()_1]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Payment_Reconciliation_(FIFO)