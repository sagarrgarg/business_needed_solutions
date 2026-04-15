---
type: community
cohesion: 0.67
members: 3
---

# remove_old_bns_workspace.py

**Cohesion:** 0.67 - moderately connected
**Members:** 3 nodes

## Members
- [[Remove stale workspace records that no longer have a JSON file on disk.]] - rationale - business_needed_solutions/business_needed_solutions/patch/remove_old_bns_workspace.py
- [[execute()_17]] - code - business_needed_solutions/business_needed_solutions/patch/remove_old_bns_workspace.py
- [[remove_old_bns_workspace.py]] - code - business_needed_solutions/business_needed_solutions/patch/remove_old_bns_workspace.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/remove_old_bns_workspace.py
SORT file.name ASC
```
