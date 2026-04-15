---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "document"
community: "Common Party GL Square-Off"
location: "L304-L307"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# Rationale: scheduled_squareoff_run never raises so the scheduler keeps ticking; errors go to Error Log

## Connections
- [[scheduled_squareoff_run]] - `rationale_for` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Common_Party_GL_Square-Off