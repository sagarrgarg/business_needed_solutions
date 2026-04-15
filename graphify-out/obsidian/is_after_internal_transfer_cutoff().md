---
source_file: "business_needed_solutions/bns_branch_accounting/utils.py"
type: "code"
community: "Internal Transfer Engine"
location: "L529"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Internal_Transfer_Engine
---

# is_after_internal_transfer_cutoff()

## Connections
- [[True when posting_date = Internal Transfer cutoff FY start.     Returns False w]] - `rationale_for` [EXTRACTED]
- [[_get_internal_transfer_cutoff_date()]] - `calls` [EXTRACTED]
- [[_rewrite_bns_internal_pi_gl_entries()]] - `calls` [EXTRACTED]
- [[apply_internal_pi_transfer_rates_from_si()]] - `calls` [EXTRACTED]
- [[convert_purchase_invoice_to_bns_internal()]] - `calls` [EXTRACTED]
- [[convert_purchase_receipt_to_bns_internal()]] - `calls` [EXTRACTED]
- [[is_after_accounting_rewrite_cutoff()]] - `calls` [EXTRACTED]
- [[is_after_internal_validation_cutoff()]] - `calls` [EXTRACTED]
- [[link_dn_pr()]] - `calls` [EXTRACTED]
- [[link_si_pi()]] - `calls` [EXTRACTED]
- [[link_si_pr()]] - `calls` [EXTRACTED]
- [[make_bns_internal_purchase_invoice()]] - `calls` [EXTRACTED]
- [[make_bns_internal_purchase_receipt()]] - `calls` [EXTRACTED]
- [[make_bns_internal_purchase_receipt_from_si()]] - `calls` [EXTRACTED]
- [[update_delivery_note_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[update_purchase_invoice_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[update_purchase_receipt_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[update_sales_invoice_status_for_bns_internal()]] - `calls` [EXTRACTED]
- [[utils.py]] - `contains` [EXTRACTED]
- [[validate_internal_purchase_invoice_linkage()]] - `calls` [EXTRACTED]
- [[validate_internal_purchase_invoice_si_parity()]] - `calls` [EXTRACTED]
- [[validate_internal_purchase_invoice_transfer_rate()]] - `calls` [EXTRACTED]
- [[validate_internal_purchase_receipt_linkage()]] - `calls` [EXTRACTED]
- [[validate_internal_sales_invoice_linkage()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Internal_Transfer_Engine