---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party Square-Off"
location: "L457"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_Square-Off
---

# scheduled_squareoff_run()

## Connections
- [[Daily scheduler tick. Runs auto square-off across every company when the 	config]] - `rationale_for` [EXTRACTED]
- [[_list_companies_for_schedule()]] - `calls` [EXTRACTED]
- [[_run_reconcile()]] - `calls` [EXTRACTED]
- [[_schedule_is_due()]] - `calls` [EXTRACTED]
- [[common_party_squareoff.py]] - `contains` [EXTRACTED]
- [[compute_linked_party_net_positions()]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_Square-Off