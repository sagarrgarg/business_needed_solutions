---
type: community
cohesion: 0.28
members: 9
---

# Interstate Internal Transfer Cutoff

**Cohesion:** 0.28 - loosely connected
**Members:** 9 nodes

## Members
- [[conceptinterstate_internal_transfer_cutoff]]
- [[funcstock_update_validation._get_non_referenced_stock_items]]
- [[funcstock_update_validation._is_stock_item]]
- [[funcstock_update_validation._raise_purchase_invoice_reference_error]]
- [[funcstock_update_validation._raise_sales_invoice_reference_error]]
- [[funcstock_update_validation._validate_batch_serial_reference_continuity]]
- [[funcstock_update_validation._validate_item_references]]
- [[funcstock_update_validation._validate_purchase_invoice_references]]
- [[funcstock_update_validation._validate_sales_invoice_references]]

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Interstate_Internal_Transfer_Cutoff
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Core Classes & Exceptions]]

## Top bridge nodes
- [[funcstock_update_validation._validate_item_references]] - degree 3, connects to 1 community