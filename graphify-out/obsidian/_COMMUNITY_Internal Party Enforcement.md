---
type: community
cohesion: 0.33
members: 6
---

# Internal Party Enforcement

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[BNS internal party guard.  When BNS internal flags are enabled, standard ERPNext]] - rationale - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[If BNS internal customer is on, keep standard internal customer off.]] - rationale - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[If BNS internal supplier is on, keep standard internal supplier off.]] - rationale - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[enforce_bns_over_standard_internal_customer()]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[enforce_bns_over_standard_internal_supplier()]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py
- [[internal_party.py]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Internal_Party_Enforcement
SORT file.name ASC
```
