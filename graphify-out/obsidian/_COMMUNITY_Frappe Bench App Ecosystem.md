---
type: community
cohesion: 0.33
members: 6
---

# Frappe Bench App Ecosystem

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[ERPNext App]] - document - apps/erpnext/
- [[India Compliance App]] - document - apps/india_compliance/
- [[Installed Apps Ecosystem]] - document - frappe-bench-new/
- [[POW Material Request Service]] - document - warehousesuite/services/pow_material_request_service.py
- [[POW Work Order Service]] - document - warehousesuite/services/pow_work_order_service.py
- [[WarehouseSuite App]] - document - warehousesuite/hooks.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Frappe_Bench_App_Ecosystem
SORT file.name ASC
```
