---
type: community
cohesion: 0.09
members: 26
---

# DN-PR Link Fixup

**Cohesion:** 0.09 - loosely connected
**Members:** 26 nodes

## Members
- [[Check whether a partially linked DN-PR pair can be auto-fixed.      Skips (retu]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Compare quantities with no tolerance; round to 6 decimals.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Detect which internal transfer chain type a document belongs to.      Args]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Fix a partially linked DN-PR pair by setting bidirectional references,     stat]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Format item verification issues into human-readable strings.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Get submitted Sales Invoices created from a Delivery Note.]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Repost all documents in a fully-linked chain in dependency order.      Includes]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify all internal transfer chains after a cutoff date and optionally repost fu]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify item-level linkage between DN and PR (same GSTIN).      First attempts ma]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify item-level linkage between DN and SI.      SI items reference DN via deli]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify item-level linkage between PR and PI (PR-PI flow).      PI items referen]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify item-level linkage between SI and PI (different GSTIN).      Returns]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[Verify item-level linkage between SI and PR (SI-PR flow).      PR items referen]] - rationale - business_needed_solutions/bns_branch_accounting/utils.py
- [[_check_dn_pr_fixable()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_detect_chain_type()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_fix_dn_pr_link()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_format_item_issues()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_get_sis_from_dn()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_qtys_equal_bulk()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_repost_chain()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_verify_dn_pr_item_linkage()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_verify_dn_si_item_linkage()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_verify_pr_pi_item_linkage()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_verify_si_pi_item_linkage()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_verify_si_pr_item_linkage()]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[verify_and_repost_internal_transfers()]] - code - business_needed_solutions/bns_branch_accounting/utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/DN-PR_Link_Fixup
SORT file.name ASC
```

## Connections to other communities
- 19 edges to [[_COMMUNITY_Internal Transfer Engine]]

## Top bridge nodes
- [[_detect_chain_type()]] - degree 12, connects to 1 community
- [[_qtys_equal_bulk()]] - degree 8, connects to 1 community
- [[verify_and_repost_internal_transfers()]] - degree 8, connects to 1 community
- [[_fix_dn_pr_link()]] - degree 4, connects to 1 community
- [[_verify_dn_pr_item_linkage()]] - degree 4, connects to 1 community