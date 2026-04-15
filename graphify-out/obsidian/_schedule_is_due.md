---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L283"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# _schedule_is_due

## Connections
- [[Rationale interval-based (not calendar-pinned) so first run after enabling fires immediately]] - `rationale_for` [EXTRACTED]
- [[_SCHEDULE_INTERVAL_DAYS]] - `references` [EXTRACTED]
- [[scheduled_squareoff_run]] - `calls` [EXTRACTED]
- [[test_schedule_is_due_logic]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off