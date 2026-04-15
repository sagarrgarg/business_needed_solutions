---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "rationale"
community: "Common Party Square-Off"
location: "L430"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Common_Party_Square-Off
---

# Indirection so tests can patch it without mocking the whole frappe.get_all.

## Connections
- [[_list_companies_for_schedule()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Common_Party_Square-Off