---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L245-L275"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# maybe_auto_squareoff_on_payment_entry(doc, method)

## Connections
- [[Why block accountant can settle on wrong side of a linked pair via PE; auto-post contra JV so BSTB reconcile; failure must never block the PE - log and continue]] - `rationale_for` [EXTRACTED]
- [[_find_crossed_pair_for_party(party_type, party, company)]] - `calls` [EXTRACTED]
- [[doc_events'Payment Entry'.on_submit += maybe_auto_squareoff_on_payment_entry]] - `references` [EXTRACTED]
- [[square_off_linked_party(pair, posting_date, cost_center, remark, submit)]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off