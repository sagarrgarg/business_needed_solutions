---
type: community
cohesion: 0.25
members: 8
---

# _apply_bns_repost_accounting_ledger_p...

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[Ensure BNS runtime monkey patches are applied in every process (webworker).]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Patch Repost Accounting Ledger start_repost to run BNS correction after ERPNext]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Patch Repost Item Valuation GL phase to run BNS-scoped failsafe correction.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Replace ERPNext's repost error emailer with a no-op.      Repost Item Valuation]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_apply_bns_repost_accounting_ledger_patch()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_apply_bns_repost_gl_failsafe_patch()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_suppress_repost_error_emails()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[apply_bns_runtime_patches()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/_apply_bns_repost_accounting_ledger_p...
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_utils.py]]

## Top bridge nodes
- [[apply_bns_runtime_patches()]] - degree 7, connects to 1 community
- [[_apply_bns_repost_accounting_ledger_patch()]] - degree 3, connects to 1 community
- [[_apply_bns_repost_gl_failsafe_patch()]] - degree 3, connects to 1 community
- [[_suppress_repost_error_emails()]] - degree 3, connects to 1 community