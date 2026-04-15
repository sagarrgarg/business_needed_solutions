---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L1434"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# validate_internal_purchase_invoice_transfer_rate()

## Connections
- [[Require PI item transfer-rate for internal SI-linked update-stock PI rows.]] - `rationale_for` [EXTRACTED]
- [[_build_si_rate_maps_for_pi()]] - `calls` [EXTRACTED]
- [[_resolve_si_name_for_internal_pi()]] - `calls` [EXTRACTED]
- [[_resolve_source_posting_date()]] - `calls` [EXTRACTED]
- [[apply_internal_pi_transfer_rates_from_si()]] - `calls` [EXTRACTED]
- [[is_after_internal_transfer_cutoff()]] - `calls` [EXTRACTED]
- [[is_bns_internal_supplier()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine