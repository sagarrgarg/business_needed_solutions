---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L147-L201"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# square_off_linked_party(pair, posting_date, cost_center, remark, submit)

## Connections
- [[GL Entry]] - `shares_data_with` [INFERRED]
- [[Journal Entry]] - `references` [EXTRACTED]
- [[_build_leg(account, party_type, party, debit, credit, cost_center)]] - `calls` [EXTRACTED]
- [[_default_cost_center(company)]] - `calls` [EXTRACTED]
- [[maybe_auto_squareoff_on_payment_entry(doc, method)]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties(company, as_of_date, pairs, dry_run, ...)]] - `calls` [EXTRACTED]
- [[test_square_off_matched_amounts_to_zero]] - `calls` [EXTRACTED]
- [[test_square_off_partial_leaves_residual]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off