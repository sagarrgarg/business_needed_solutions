---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "document"
community: "Common Party GL Square-Off"
location: "L284-L288"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# Rationale: per-Payment-Entry hook was too invasive (every PE, invisible side-effects, hard to audit); scheduled cadence is predictable and auditable

## Connections
- [[(REMOVED) maybe_auto_squareoff_on_payment_entry per-PE auto-hook]] - `rationale_for` [INFERRED]
- [[scheduled_squareoff_run]] - `rationale_for` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Common_Party_GL_Square-Off