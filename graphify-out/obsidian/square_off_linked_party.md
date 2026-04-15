---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L147"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# square_off_linked_party

## Connections
- [[Journal Entry (doctype)]] - `references` [EXTRACTED]
- [[Rationale post contra JV per linked pair so raw GL reflects netted reality, downstream reports self-correct without overrides]] - `rationale_for` [EXTRACTED]
- [[_build_leg]] - `calls` [EXTRACTED]
- [[_default_cost_center]] - `calls` [EXTRACTED]
- [[check_linked_party_opposite_balance]] - `conceptually_related_to` [INFERRED]
- [[common_party_squareoff.py_1]] - `implements` [EXTRACTED]
- [[erpnext.get_company_currency]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off