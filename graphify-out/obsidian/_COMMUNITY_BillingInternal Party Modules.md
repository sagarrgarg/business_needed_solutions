---
type: community
cohesion: 1.00
members: 2
---

# Billing/Internal Party Modules

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[overridesbilling_location.py]] - code - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[overridesinternal_party.py]] - code - business_needed_solutions/bns_branch_accounting/overrides/internal_party.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Billing/Internal_Party_Modules
SORT file.name ASC
```
