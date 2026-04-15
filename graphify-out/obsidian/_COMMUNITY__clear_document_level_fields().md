---
type: community
cohesion: 0.18
members: 12
---

# _clear_document_level_fields()

**Cohesion:** 0.18 - loosely connected
**Members:** 12 nodes

## Members
- [[Clear warehouse and accounting dimension fields at document level.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Clear warehouse and accounting dimension fields at document level._1]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Return True if any already-received quantity exists for source item keys.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Set missing values for the target Purchase Invoice.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Set missing values for the target Purchase Receipt from Sales Invoice.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Set missing values for the target Purchase Receipt.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_clear_document_level_fields()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_clear_document_level_fields_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_has_any_positive_received_qty()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_set_missing_values()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_set_missing_values_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_set_missing_values_pr_from_si()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/_clear_document_level_fields()
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_utils.py]]

## Top bridge nodes
- [[_has_any_positive_received_qty()]] - degree 5, connects to 1 community
- [[_set_missing_values()]] - degree 5, connects to 1 community
- [[_set_missing_values_pi()]] - degree 5, connects to 1 community
- [[_clear_document_level_fields()]] - degree 4, connects to 1 community
- [[_set_missing_values_pr_from_si()]] - degree 4, connects to 1 community