---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L757"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# _is_bns_internal_same_gstin_purchase_receipt()

## Connections
- [[Check PR is in scoped BNS internal same-GSTIN DN-PR flow.     Cutoff check is t]] - `rationale_for` [EXTRACTED]
- [[_force_rebuild_bns_gl_for_voucher()]] - `calls` [EXTRACTED]
- [[_get_linked_delivery_note_for_pr()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_pr_gl_entries()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_accounting_correction()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_correction()]] - `calls` [EXTRACTED]
- [[bns_debug_internal_gl_scope()]] - `calls` [EXTRACTED]
- [[is_bns_internal_supplier()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine