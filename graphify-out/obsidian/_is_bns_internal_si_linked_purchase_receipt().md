---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L777"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# _is_bns_internal_si_linked_purchase_receipt()

## Connections
- [[Check PR is in scoped SI-PR transfer flow (different GSTIN style).     Cutoff c]] - `rationale_for` [EXTRACTED]
- [[_force_rebuild_bns_gl_for_voucher()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_pr_gl_entries()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_accounting_correction()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_correction()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine