---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L6509"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# update_purchase_invoice_status_for_bns_internal()

## Connections
- [[Set PI status to 'BNS Internally Transferred' on submit for SI-backed internal P]] - `rationale_for` [EXTRACTED]
- [[_is_bns_internal_purchase_invoice_from_si()]] - `calls` [EXTRACTED]
- [[_mirror_pi_item_valuation_from_transfer_rate()]] - `calls` [EXTRACTED]
- [[_resolve_si_name_for_internal_pi()]] - `calls` [EXTRACTED]
- [[_resolve_source_posting_date()]] - `calls` [EXTRACTED]
- [[_sync_pi_item_transfer_rate_from_si()]] - `calls` [EXTRACTED]
- [[_trigger_bns_internal_gl_repost()]] - `calls` [EXTRACTED]
- [[_trigger_pi_repost_for_transfer_rate()]] - `calls` [EXTRACTED]
- [[is_after_accounting_rewrite_cutoff()]] - `calls` [EXTRACTED]
- [[is_after_internal_transfer_cutoff()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine