---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py"
type: "rationale"
community: "Common Party Reconciliation"
location: "L101"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Common_Party_Reconciliation
---

# Cheap pre-filter: signed balance on party account. Non-zero -> candidate.

## Connections
- [[_party_account_has_balance()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Common_Party_Reconciliation