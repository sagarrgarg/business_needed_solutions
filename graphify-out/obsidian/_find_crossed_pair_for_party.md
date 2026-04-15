---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L369"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# _find_crossed_pair_for_party

## Connections
- [[Party Link (doctype)]] - `references` [EXTRACTED]
- [[_get_party_signed_balance]] - `calls` [EXTRACTED]
- [[check_linked_party_opposite_balance]] - `calls` [EXTRACTED]
- [[compute_linked_party_net_positions]] - `semantically_similar_to` [INFERRED]
- [[erpnext.accounts.party.get_party_account]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off