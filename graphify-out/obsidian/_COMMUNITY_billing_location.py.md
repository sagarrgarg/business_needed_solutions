---
type: community
cohesion: 0.40
members: 6
---

# billing_location.py

**Cohesion:** 0.40 - moderately connected
**Members:** 6 nodes

## Members
- [[BNS Branch Accounting - Billing Location → Customer Address  On validate if bil]] - rationale - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[Set customer_address and GST fields from billing_location.linked_address on save]] - rationale - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[Set place_of_supply from address. Uses India Compliance if available, else addre]] - rationale - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[_set_place_of_supply_from_address()]] - code - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[billing_location.py]] - code - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py
- [[set_customer_address_from_billing_location()]] - code - business_needed_solutions/bns_branch_accounting/overrides/billing_location.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/billing_location.py
SORT file.name ASC
```
