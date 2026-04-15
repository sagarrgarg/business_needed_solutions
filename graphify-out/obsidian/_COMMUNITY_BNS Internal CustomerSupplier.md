---
type: community
cohesion: 0.18
members: 17
---

# BNS Internal Customer/Supplier

**Cohesion:** 0.18 - loosely connected
**Members:** 17 nodes

## Members
- [[BNS Internal Create buttons]]
- [[Convert to BNS Internal]]
- [[Duplicate Internal SI for DN guard]]
- [[Link DNPR]]
- [[Link SIPI]]
- [[Link SIPR (different GSTIN)]]
- [[Purchase Attachment Visibility]]
- [[Same GSTIN Gate]]
- [[bns_customer.js_1]] - code
- [[bns_supplier.js_1]] - code
- [[check_ewaybill_applicability]]
- [[delivery_note.js_1]] - code
- [[is_bns_internal_customer_1]]
- [[is_bns_internal_supplier_1]]
- [[purchase_attachment_fields.js_1]] - code
- [[purchase_receipt_form.js_1]] - code
- [[sales_invoice_form.js_1]] - code

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/BNS_Internal_Customer/Supplier
SORT file.name ASC
```
