---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "document"
community: "Common Party GL Square-Off"
location: "L299-L301"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# Rationale: _list_companies_for_schedule is an indirection so tests can patch it without mocking frappe.get_all

## Connections
- [[_list_companies_for_schedule]] - `rationale_for` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Common_Party_GL_Square-Off