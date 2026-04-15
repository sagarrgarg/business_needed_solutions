---
type: community
cohesion: 0.08
members: 24
---

# PR Return Linking & Internal Supplier

**Cohesion:** 0.08 - loosely connected
**Members:** 24 nodes

## Members
- [[Find supplier that represents the given company.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Find the Purchase Invoice created from the original Sales Invoice     so it can]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Return an address linked to supplier via Dynamic Link.      1. If preferred_a]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update addresses for internal transfer Purchase Invoice.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update addresses for internal transfer.      For BNS internal transfers the DN's]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update bidirectional linked document references.          Args         doctype]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update delivery note with purchase receipt reference.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update details for the Purchase Invoice from Sales Invoice.          TRANSFER UN]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update details for the Purchase Receipt from Delivery Note.          TRANSFER UN]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update sales invoice with purchase invoice reference.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update taxes for the purchase invoice.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update taxes for the purchase receipt.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_find_internal_supplier()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_find_return_against_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_resolve_supplier_address()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_addresses()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_addresses_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_delivery_note_reference()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_details()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_details_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_sales_invoice_reference()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_taxes()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_taxes_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[update_linked_doc()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/PR_Return_Linking_&_Internal_Supplier
SORT file.name ASC
```

## Connections to other communities
- 18 edges to [[_COMMUNITY_Core Utils & Runtime Patches]]
- 1 edge to [[_COMMUNITY_Submission & Stock Validation]]

## Top bridge nodes
- [[_find_internal_supplier()]] - degree 6, connects to 2 communities
- [[_update_details_pi()]] - degree 8, connects to 1 community
- [[_update_details()]] - degree 7, connects to 1 community
- [[_update_addresses()]] - degree 5, connects to 1 community
- [[_update_delivery_note_reference()]] - degree 5, connects to 1 community