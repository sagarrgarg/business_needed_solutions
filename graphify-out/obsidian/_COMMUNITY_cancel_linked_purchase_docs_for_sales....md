---
type: community
cohesion: 0.33
members: 6
---

# cancel_linked_purchase_docs_for_sales...

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Cancel linked submitted PIPR when cancelling Sales Invoice.      One-way policy]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Cancel linked submitted Purchase Receipts when cancelling Delivery Note.      On]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Cancel submitted documents safely and return cancelled count.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_cancel_submitted_docs()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[cancel_linked_purchase_docs_for_sales_invoice()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[validate_delivery_note_cancellation()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/cancel_linked_purchase_docs_for_sales...
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_utils.py]]

## Top bridge nodes
- [[_cancel_submitted_docs()]] - degree 4, connects to 1 community
- [[cancel_linked_purchase_docs_for_sales_invoice()]] - degree 3, connects to 1 community
- [[validate_delivery_note_cancellation()]] - degree 3, connects to 1 community