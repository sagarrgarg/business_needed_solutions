---
type: community
cohesion: 1.00
members: 2
---

# POW Dashboard

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[POW Dashboard]] - document - warehousesuite/page/pow_dashboard/pow_dashboard.py
- [[POW Stock Concern DocType]] - document - warehousesuite/doctype/pow_stock_concern/pow_stock_concern.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/POW_Dashboard
SORT file.name ASC
```
