---
type: community
cohesion: 0.11
members: 28
---

# Stock Update Guard

**Cohesion:** 0.11 - loosely connected
**Members:** 28 nodes

## Members
- [[Business Needed Solutions - Stock Update Validation System  This module provides]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Check if an item is a stock item.          Args         item_code (str) The it]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Check if stock update validation is enabled in BNS Settings.          Returns]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Enforce that rate-adjustment debit notes are not linked to Delivery Notes.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Get list of stock items that are not referenced from source documents.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Raise an error for Purchase Invoice reference validation failure.          Raise]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Raise an error for Sales Invoice reference validation failure.          Raises]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Return True when any SI item references Delivery Note or DN Item.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Return True when the document is a Sales Invoice marked as Debit Note.      In E]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Validate if either update_stock is enabled or all items are referenced      from]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Validate that all stock items are properly referenced.          Args         do]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Validate that all stock items in Purchase Invoice are referenced from Purchase R]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Validate that all stock items in Sales Invoice are referenced from Delivery Note]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[Verify batchserial info on invoice items matches the referenced source document]] - rationale - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_get_non_referenced_stock_items()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_has_sales_invoice_dn_links()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_is_sales_invoice_rate_adjustment_debit_note()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_is_stock_item()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_is_stock_update_validation_enabled()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_raise_purchase_invoice_reference_error()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_raise_sales_invoice_reference_error()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_validate_batch_serial_reference_continuity()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_validate_item_references()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_validate_purchase_invoice_references()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_validate_sales_invoice_rate_adjustment_without_dn_links()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[_validate_sales_invoice_references()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[stock_update_validation.py]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py
- [[validate_stock_update_or_reference()]] - code - business_needed_solutions/business_needed_solutions/overrides/stock_update_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Stock_Update_Guard
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Submission & Stock Validation]]

## Top bridge nodes
- [[stock_update_validation.py]] - degree 15, connects to 1 community