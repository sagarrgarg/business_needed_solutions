---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L247"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# _refresh_pair_balances

## Connections
- [[Rationale re-read balances inside savepoint to handle concurrent posters and avoid over-squareoff]] - `rationale_for` [EXTRACTED]
- [[_get_party_signed_balance]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off