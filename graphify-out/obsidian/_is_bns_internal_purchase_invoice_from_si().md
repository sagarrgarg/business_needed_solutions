---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L5750"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# _is_bns_internal_purchase_invoice_from_si()

## Connections
- [[Return True when submitted PI belongs to BNS internal SI-PISI-PR flow.      D]] - `rationale_for` [EXTRACTED]
- [[_force_rebuild_bns_gl_for_voucher()]] - `calls` [EXTRACTED]
- [[_reassert_purchase_invoice_bns_internal_status()]] - `calls` [EXTRACTED]
- [[_resolve_si_name_for_internal_pi()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_pi_gl_entries()]] - `calls` [EXTRACTED]
- [[is_bns_internal_supplier()]] - `calls` [EXTRACTED]
- [[update_purchase_invoice_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine