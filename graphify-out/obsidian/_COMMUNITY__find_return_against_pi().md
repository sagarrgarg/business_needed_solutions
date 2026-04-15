---
type: community
cohesion: 0.20
members: 10
---

# _find_return_against_pi()

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[Find the Purchase Invoice created from the original Sales Invoice     so it can]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update addresses for internal transfer Purchase Invoice.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update details for the Purchase Invoice from Sales Invoice.          TRANSFER UN]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update sales invoice with purchase invoice reference.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Update taxes for the purchase invoice.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_find_return_against_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_addresses_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_details_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_sales_invoice_reference()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_update_taxes_pi()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/_find_return_against_pi()
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_utils.py]]

## Top bridge nodes
- [[_update_details_pi()]] - degree 8, connects to 1 community
- [[_find_return_against_pi()]] - degree 3, connects to 1 community
- [[_update_addresses_pi()]] - degree 3, connects to 1 community
- [[_update_sales_invoice_reference()]] - degree 3, connects to 1 community
- [[_update_taxes_pi()]] - degree 3, connects to 1 community