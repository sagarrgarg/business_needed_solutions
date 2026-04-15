---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L641"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# _is_bns_internal_delivery_note()

## Connections
- [[Check DN is in scoped BNS internal flow (samedifferent GSTIN).     Cutoff check]] - `rationale_for` [EXTRACTED]
- [[_force_rebuild_bns_gl_for_voucher()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_dn_gl_entries()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_accounting_correction()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_correction()]] - `calls` [EXTRACTED]
- [[bns_debug_internal_gl_scope()]] - `calls` [EXTRACTED]
- [[is_bns_internal_customer()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine