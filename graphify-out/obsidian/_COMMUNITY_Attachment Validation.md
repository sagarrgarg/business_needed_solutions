---
type: community
cohesion: 0.11
members: 25
---

# Attachment Validation

**Cohesion:** 0.11 - loosely connected
**Members:** 25 nodes

## Members
- [[BNS Settings DocType]] - code
- [[Business Needed Solutions - Purchase Document Attachment Validation  Enforces ma]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Check if the toggle is on in BNS Settings.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Client-callable endpoint to determine whether the e-Waybill field should be]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Fetch e_waybill_threshold from GST Settings (default 0).]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Return True if any PI item references a Purchase Receipt.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Return True if the document's posting date is BEFORE the cutoff date,     meanin]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Return True when the document needs an e-Waybill attachment.      Conditions (al]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Throw if the bns_ewaybill_attachment field is empty.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[Throw if the bns_supplier_invoice_attachment field is empty.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[True if at least one row references an Item with is_stock_item set.]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[True when PRPI supplier is a BNS internal branch supplier.      Uses the docume]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_get_ewaybill_threshold()_1]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_has_linked_purchase_receipt()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_has_stock_items()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_is_attachment_validation_enabled()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_is_before_attachment_cutoff()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_is_bns_internal_supplier_scope()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_is_ewaybill_required()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_require_ewaybill()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[_require_supplier_invoice()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[attachment_validation.py]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[before_submit hook for Purchase Receipt and Purchase Invoice.      Validates tha]] - rationale - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[check_ewaybill_applicability()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py
- [[validate_purchase_attachments()]] - code - business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Attachment_Validation
SORT file.name ASC
```
