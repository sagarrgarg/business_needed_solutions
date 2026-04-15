---
source_file: "business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py"
type: "code"
community: "AccountsReceivablePayableSummary"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/AccountsReceivablePayableSummary
---

# pure_accounts_payable_summary.execute

## Connections
- [[APAR netting via Party Link + common-party logic]] - `implements` [INFERRED]
- [[AccountsReceivablePayableSummary_1]] - `calls` [EXTRACTED]
- [[Party Link]] - `references` [EXTRACTED]
- [[Supplier]] - `references` [EXTRACTED]
- [[get_customer_invoice_and_paid_amounts]] - `calls` [EXTRACTED]
- [[get_supplier_invoice_and_received_amounts]] - `calls` [EXTRACTED]
- [[redistribute_negative_ageing_buckets]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/AccountsReceivablePayableSummary