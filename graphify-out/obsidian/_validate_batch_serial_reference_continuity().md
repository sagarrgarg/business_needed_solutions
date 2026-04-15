---
source_file: "business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py"
type: "code"
community: "Stock Update Validation"
location: "L243"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Stock_Update_Validation
---

# _validate_batch_serial_reference_continuity()

## Connections
- [[Verify batchserial info on invoice items matches the referenced source document]] - `rationale_for` [EXTRACTED]
- [[_is_stock_item()]] - `calls` [EXTRACTED]
- [[_validate_purchase_invoice_references()]] - `calls` [EXTRACTED]
- [[_validate_sales_invoice_references()]] - `calls` [EXTRACTED]
- [[stock_update_validation.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Stock_Update_Validation