---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L422"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# check_linked_party_opposite_balance

## Connections
- [[Linked Party Warning Dialog (JS)]] - `calls` [EXTRACTED]
- [[Payment Entry (doctype)]] - `references` [EXTRACTED]
- [[Rationale check_linked_party_opposite_balance gated by BNS Settings flag AND Payment Entry+party read perms because it leaks outstanding balances]] - `rationale_for` [EXTRACTED]
- [[_find_crossed_pair_for_party]] - `calls` [EXTRACTED]
- [[bns_call_and_warn]] - `calls` [EXTRACTED]
- [[common_party_squareoff.py_1]] - `implements` [EXTRACTED]
- [[square_off_linked_party]] - `conceptually_related_to` [INFERRED]
- [[test_warning_helper_gated_by_setting]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off