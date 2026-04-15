---
source_file: "business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py"
type: "code"
community: "Stock Update Validation"
location: "L32"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Stock_Update_Validation
---

# validate_stock_update_or_reference()

## Connections
- [[Validate if either update_stock is enabled or all items are referenced      from]] - `rationale_for` [EXTRACTED]
- [[_is_sales_invoice_rate_adjustment_debit_note()]] - `calls` [EXTRACTED]
- [[_is_stock_update_validation_enabled()]] - `calls` [EXTRACTED]
- [[_validate_item_references()]] - `calls` [EXTRACTED]
- [[_validate_sales_invoice_rate_adjustment_without_dn_links()]] - `calls` [EXTRACTED]
- [[stock_update_validation.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Stock_Update_Validation