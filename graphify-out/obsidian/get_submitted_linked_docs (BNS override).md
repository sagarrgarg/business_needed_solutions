---
source_file: "business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py"
type: "code"
community: "AccountsReceivablePayableSummary"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/AccountsReceivablePayableSummary
---

# get_submitted_linked_docs (BNS override)

## Connections
- [[BNS one-way cancellation policy (PRPI not cascading to DNSI)]] - `implements` [INFERRED]
- [[Delivery Note]] - `references` [EXTRACTED]
- [[Purchase Invoice]] - `references` [EXTRACTED]
- [[Purchase Receipt]] - `references` [EXTRACTED]
- [[Sales Invoice]] - `references` [EXTRACTED]
- [[_as_list]] - `calls` [EXTRACTED]
- [[frappe get_submitted_linked_docs]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/AccountsReceivablePayableSummary