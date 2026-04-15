---
source_file: "business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py"
type: "code"
community: "Transfer Receive Mismatch"
location: "L1141"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Transfer_Receive_Mismatch
---

# check_si_pi_mismatch()

## Connections
- [[Check if Sales Invoice has matching Purchase Invoice. 	Compares quantities, taxa]] - `rationale_for` [EXTRACTED]
- [[_amounts_within_tolerance()]] - `calls` [EXTRACTED]
- [[_qtys_equal()]] - `calls` [EXTRACTED]
- [[get_sales_invoice_mismatches()]] - `calls` [EXTRACTED]
- [[internal_transfer_receive_mismatch.js]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Transfer_Receive_Mismatch