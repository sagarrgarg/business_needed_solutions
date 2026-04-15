---
type: community
cohesion: 1.00
members: 2
---

# Workspace Removal Patches

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[filepatchremove_bns_health_check_workspace.py]]
- [[filepatchremove_old_bns_workspace.py]]

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Workspace_Removal_Patches
SORT file.name ASC
```
