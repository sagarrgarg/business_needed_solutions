---
source_file: "business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py"
type: "code"
community: "Stock Update Validation"
location: "L181"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Stock_Update_Validation
---

# _validate_sales_invoice_references()

## Connections
- [[Validate that all stock items in Sales Invoice are referenced from Delivery Note]] - `rationale_for` [EXTRACTED]
- [[_get_non_referenced_stock_items()]] - `calls` [EXTRACTED]
- [[_raise_sales_invoice_reference_error()]] - `calls` [EXTRACTED]
- [[_validate_batch_serial_reference_continuity()]] - `calls` [EXTRACTED]
- [[_validate_item_references()]] - `calls` [EXTRACTED]
- [[stock_update_validation.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Stock_Update_Validation