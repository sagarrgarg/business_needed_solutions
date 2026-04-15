---
type: community
cohesion: 1.00
members: 2
---

# AR/AP Reports

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[Party Link DocType]] - document - business_needed_solutions/report/
- [[Pure AR Summary Report]] - document - business_needed_solutions/report/pure_accounts_receivable_summary/

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/AR/AP_Reports
SORT file.name ASC
```
