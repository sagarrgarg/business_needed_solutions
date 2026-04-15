---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L36-L51"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# _get_party_signed_balance(party_type, party, account, company, as_of_date)

## Connections
- [[GL Entry]] - `references` [EXTRACTED]
- [[_find_crossed_pair_for_party(party_type, party, company)]] - `calls` [EXTRACTED]
- [[compute_linked_party_net_positions(company, as_of_date)]] - `calls` [EXTRACTED]
- [[test_square_off_partial_leaves_residual]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off