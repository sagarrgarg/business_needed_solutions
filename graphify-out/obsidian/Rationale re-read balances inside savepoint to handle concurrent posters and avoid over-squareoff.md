---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "document"
community: "Common Party GL Square-Off"
location: "L225-L228"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# Rationale: re-read balances inside savepoint to handle concurrent posters and avoid over-squareoff

## Connections
- [[_refresh_pair_balances]] - `rationale_for` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Common_Party_GL_Square-Off