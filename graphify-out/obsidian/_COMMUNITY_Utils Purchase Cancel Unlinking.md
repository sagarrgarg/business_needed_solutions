---
type: community
cohesion: 0.50
members: 4
---

# Utils Purchase Cancel Unlinking

**Cohesion:** 0.50 - moderately connected
**Members:** 4 nodes

## Members
- [[On PRPI cancel, only remove BNS links; never cancel parent SIDN.      Policy]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[On PRPI cancel, skip backlink-enforced parent cancellation.      Desired behavi]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[ignore_parent_cancellation_links_for_bns_internal()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[unlink_references_on_purchase_cancel()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Utils_Purchase_Cancel_Unlinking
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Core Utils & Runtime Patches]]

## Top bridge nodes
- [[ignore_parent_cancellation_links_for_bns_internal()]] - degree 3, connects to 1 community
- [[unlink_references_on_purchase_cancel()]] - degree 3, connects to 1 community