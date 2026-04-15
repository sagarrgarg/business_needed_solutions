---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L3012"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# _is_bns_repost_voucher_processed()

## Connections
- [[Check DB-backed tracking first (status Processed), fallback to cache.]] - `rationale_for` [EXTRACTED]
- [[_bns_repost_voucher_marker_key()]] - `calls` [EXTRACTED]
- [[_build_bns_repost_tracking_key()]] - `calls` [EXTRACTED]
- [[_is_bns_repost_tracking_available()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_accounting_correction()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_correction()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine