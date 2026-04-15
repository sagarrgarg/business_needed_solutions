---
type: community
cohesion: 0.67
members: 3
---

# BNS Dashboard Pipeline

**Cohesion:** 0.67 - moderately connected
**Members:** 3 nodes

## Members
- [[BNS Dashboard Backend]] - document - business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[Common Party Reconciliation Module]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Common Party Square-Off Module]] - document - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/BNS_Dashboard_Pipeline
SORT file.name ASC
```
