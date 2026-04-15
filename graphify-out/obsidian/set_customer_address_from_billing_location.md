---
source_file: "business_needed_solutions/bns_branch_accounting/overrides/billing_location.py"
type: "code"
community: "Group 42"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Group_42
---

# set_customer_address_from_billing_location

## Connections
- [[Address]] - `references` [EXTRACTED]
- [[Location]] - `references` [EXTRACTED]
- [[_set_place_of_supply_from_address]] - `calls` [EXTRACTED]
- [[bns_branch_accounting.utils.is_bns_internal_customer]] - `calls` [EXTRACTED]
- [[frappe.contacts.doctype.address.get_address_display]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Group_42