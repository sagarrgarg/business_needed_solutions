---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py"
type: "rationale"
community: "Common Party Reconciliation"
location: "L42"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Common_Party_Reconciliation
---

# Indirection so tests can monkey-patch without mocking frappe.get_all.

## Connections
- [[_list_companies_for_reconcile()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Common_Party_Reconciliation