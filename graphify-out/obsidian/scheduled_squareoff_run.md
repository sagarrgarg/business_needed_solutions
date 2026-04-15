---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L304"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# scheduled_squareoff_run

## Connections
- [[(REMOVED) maybe_auto_squareoff_on_payment_entry per-PE auto-hook]] - `semantically_similar_to` [INFERRED]
- [[Rationale native Balance Sheet  TB  GL reports are Party-Link-unaware and inflate Debtors+Creditors for common parties]] - `conceptually_related_to` [INFERRED]
- [[Rationale per-Payment-Entry hook was too invasive (every PE, invisible side-effects, hard to audit); scheduled cadence is predictable and auditable]] - `rationale_for` [EXTRACTED]
- [[Rationale scheduled_squareoff_run never raises so the scheduler keeps ticking; errors go to Error Log]] - `rationale_for` [EXTRACTED]
- [[Rationale stamp last_run_on even on no-op so one misconfigured company can't pin the scheduler]] - `rationale_for` [EXTRACTED]
- [[_list_companies_for_schedule]] - `calls` [EXTRACTED]
- [[_run_scheduler_scoped (isolation harness)]] - `calls` [EXTRACTED]
- [[_schedule_is_due]] - `calls` [EXTRACTED]
- [[common_party_squareoff.py_1]] - `implements` [EXTRACTED]
- [[compute_linked_party_net_positions]] - `calls` [EXTRACTED]
- [[hooks.scheduler_events.daily - scheduled_squareoff_run]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off