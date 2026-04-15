---
type: community
cohesion: 0.33
members: 6
---

# Verify batch/serial information is co...

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Compare batch entries between two Serial and Batch Bundles.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Compare serial number entries between two Serial and Batch Bundles.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify batchserial information is consistent between paired source and target i]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_validate_batch_serial_parity()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_validate_sbb_batch_parity()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_validate_sbb_serial_parity()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Verify_batch/serial_information_is_co...
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_utils.py]]

## Top bridge nodes
- [[_validate_batch_serial_parity()]] - degree 5, connects to 1 community
- [[_validate_sbb_batch_parity()]] - degree 3, connects to 1 community
- [[_validate_sbb_serial_parity()]] - degree 3, connects to 1 community