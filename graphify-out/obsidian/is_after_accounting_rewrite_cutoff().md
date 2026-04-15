---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L541"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# is_after_accounting_rewrite_cutoff()

## Connections
- [[True when posting_date = Accounting Rewrite cutoff FY start     AND Phase 1 (In]] - `rationale_for` [EXTRACTED]
- [[_get_accounting_rewrite_cutoff_date()]] - `calls` [EXTRACTED]
- [[_get_bns_transfer_rate_for_pi_sle()]] - `calls` [EXTRACTED]
- [[_get_bns_transfer_rate_for_pr_sle()]] - `calls` [EXTRACTED]
- [[_mirror_pi_item_valuation_from_transfer_rate()]] - `calls` [EXTRACTED]
- [[_mirror_pr_item_valuation_from_transfer_rate()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_dn_gl_entries()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_pi_gl_entries()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_pr_gl_entries()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_si_gl_entries()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_accounting_correction()]] - `calls` [EXTRACTED]
- [[_run_bns_gl_repost_correction()]] - `calls` [EXTRACTED]
- [[_sync_pi_sle_from_transfer_rate()]] - `calls` [EXTRACTED]
- [[_sync_pr_sle_from_transfer_rate()]] - `calls` [EXTRACTED]
- [[_sync_si_item_incoming_rate_from_dn()]] - `calls` [EXTRACTED]
- [[_trigger_pi_repost_for_transfer_rate()]] - `calls` [EXTRACTED]
- [[_trigger_pr_repost_for_transfer_rate()]] - `calls` [EXTRACTED]
- [[is_after_internal_transfer_cutoff()]] - `calls` [EXTRACTED]
- [[update_delivery_note_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[update_purchase_invoice_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[update_purchase_receipt_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine