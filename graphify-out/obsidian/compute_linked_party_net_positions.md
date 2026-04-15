---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L58"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# compute_linked_party_net_positions

## Connections
- [[ERPNext process_common_party_accounting]] - `semantically_similar_to` [INFERRED]
- [[Rationale ERPNext process_common_party_accounting only fires on SIPI submit, missing Payment Entries and direct JVs]] - `rationale_for` [EXTRACTED]
- [[_PARTY_ROLES]] - `references` [EXTRACTED]
- [[_active_party_links]] - `calls` [EXTRACTED]
- [[_find_crossed_pair_for_party]] - `semantically_similar_to` [INFERRED]
- [[_get_party_signed_balance]] - `calls` [EXTRACTED]
- [[_pair_key]] - `calls` [EXTRACTED]
- [[common_party_squareoff.py_1]] - `implements` [EXTRACTED]
- [[erpnext.accounts.party.get_party_account]] - `calls` [EXTRACTED]
- [[scheduled_squareoff_run]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off