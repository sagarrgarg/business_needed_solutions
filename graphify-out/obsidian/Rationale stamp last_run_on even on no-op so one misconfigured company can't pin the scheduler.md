---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "document"
community: "Common Party GL Square-Off"
location: "L355-L357"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# Rationale: stamp last_run_on even on no-op so one misconfigured company can't pin the scheduler

## Connections
- [[scheduled_squareoff_run]] - `rationale_for` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Common_Party_GL_Square-Off