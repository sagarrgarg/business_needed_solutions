---
source_file: "business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py"
type: "rationale"
community: "Stock Update Validation"
location: "L117"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Stock_Update_Validation
---

# Return True when any SI item references Delivery Note or DN Item.

## Connections
- [[_has_sales_invoice_dn_links()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Stock_Update_Validation