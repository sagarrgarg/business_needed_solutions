---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L299"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# _list_companies_for_schedule

## Connections
- [[Company (doctype)]] - `references` [EXTRACTED]
- [[Rationale _list_companies_for_schedule is an indirection so tests can patch it without mocking frappe.get_all]] - `rationale_for` [EXTRACTED]
- [[_run_scheduler_scoped (isolation harness)]] - `references` [EXTRACTED]
- [[scheduled_squareoff_run]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off