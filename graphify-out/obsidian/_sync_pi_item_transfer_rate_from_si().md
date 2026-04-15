---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L5297"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# _sync_pi_item_transfer_rate_from_si()

## Connections
- [[Sync Purchase Invoice Item.bns_transfer_rate from Sales Invoice Item.incoming_ra]] - `rationale_for` [EXTRACTED]
- [[_build_si_rate_maps_for_pi()]] - `calls` [EXTRACTED]
- [[_get_submitted_pis_for_si()]] - `calls` [EXTRACTED]
- [[_resolve_pi_item_transfer_rate_extras()]] - `calls` [EXTRACTED]
- [[_sync_pi_sle_from_transfer_rate()]] - `calls` [EXTRACTED]
- [[refresh_si_transfer_rate_after_repost()]] - `calls` [EXTRACTED]
- [[update_purchase_invoice_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine