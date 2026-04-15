---
type: community
cohesion: 0.33
members: 6
---

# Group 51

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Bulk update all Address records to set is_primary_address=0 and is_shipping_addr]] - rationale - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py
- [[Force is_primary_address and is_shipping_address to 0 on every Address save]] - rationale - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py
- [[Override Address to suppress is_primary_address and is_shipping_address when BNS]] - rationale - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py
- [[address_preferred_flags.py]] - code - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py
- [[clear_existing_address_flags()]] - code - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py
- [[enforce_suppress_preferred_address()]] - code - business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Group_51
SORT file.name ASC
```
