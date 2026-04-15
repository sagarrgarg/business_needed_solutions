---
source_file: "business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py"
type: "code"
community: "Transfer Receive Mismatch"
location: "L899"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Transfer_Receive_Mismatch
---

# get_sales_invoice_mismatches()

## Connections
- [[Get Sales Invoices that are missing Purchase Invoices or Purchase Receipts or ha]] - `rationale_for` [EXTRACTED]
- [[_check_si_pr_chain_mismatch()]] - `calls` [EXTRACTED]
- [[_get_si_pi_amount_tolerance()]] - `calls` [EXTRACTED]
- [[check_si_pi_mismatch()]] - `calls` [EXTRACTED]
- [[get_data()]] - `calls` [EXTRACTED]
- [[internal_transfer_receive_mismatch.js]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Transfer_Receive_Mismatch