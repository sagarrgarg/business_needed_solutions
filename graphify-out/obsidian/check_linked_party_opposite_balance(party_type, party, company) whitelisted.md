---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L330-L349"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# check_linked_party_opposite_balance(party_type, party, company) [whitelisted]

## Connections
- [[_find_crossed_pair_for_party(party_type, party, company)]] - `calls` [EXTRACTED]
- [[bns_check_linked_party_crossed_balance(frm) client]] - `calls` [EXTRACTED]
- [[test_warning_helper_gated_by_setting]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off