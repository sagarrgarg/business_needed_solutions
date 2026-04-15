---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L278-L327"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# _find_crossed_pair_for_party(party_type, party, company)

## Connections
- [[Party Link]] - `references` [EXTRACTED]
- [[_get_party_signed_balance(party_type, party, account, company, as_of_date)]] - `calls` [EXTRACTED]
- [[check_linked_party_opposite_balance(party_type, party, company) whitelisted]] - `calls` [EXTRACTED]
- [[maybe_auto_squareoff_on_payment_entry(doc, method)]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off