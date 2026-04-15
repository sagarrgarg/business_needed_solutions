---
type: community
cohesion: 0.14
members: 16
---

# Item Transfer Rate Utils

**Cohesion:** 0.14 - loosely connected
**Members:** 16 nodes

## Members
- [[Clear accounting and warehouse fields at item level.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Clear accounting and warehouse fields at item level._1]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Clone a Serial and Batch Bundle from source item row to target item row.      Ha]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Get outgoing valuation mirror for a Delivery Note Item.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Get outgoing valuation mirror for a Sales Invoice Item.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update item details for the purchase invoice item.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update item details for the purchase receipt item from sales invoice item.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update item details for the purchase receipt item.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_clear_item_level_fields()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_clear_item_level_fields_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_duplicate_serial_and_batch_bundle()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_get_dn_item_transfer_rate()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_get_si_item_transfer_rate()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_item()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_item_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_item_pr_from_si()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Item_Transfer_Rate_Utils
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Internal Transfer Engine]]

## Top bridge nodes
- [[_duplicate_serial_and_batch_bundle()]] - degree 5, connects to 1 community
- [[_update_item()]] - degree 5, connects to 1 community
- [[_update_item_pi()]] - degree 5, connects to 1 community
- [[_update_item_pr_from_si()]] - degree 5, connects to 1 community
- [[_clear_item_level_fields()]] - degree 4, connects to 1 community