---
type: community
cohesion: 0.33
members: 6
---

# BNS Internal Party Fields

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[enforce_bns_over_standard_internal_customer]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[enforce_bns_over_standard_internal_supplier]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[is_bns_internal_customer]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[is_bns_internal_supplier]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[is_internal_customer (ERPNext)]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[is_internal_supplier (ERPNext)]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/BNS_Internal_Party_Fields
SORT file.name ASC
```
