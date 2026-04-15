---
type: community
cohesion: 0.14
members: 20
---

# Migration Hooks

**Cohesion:** 0.14 - loosely connected
**Members:** 20 nodes

## Members
- [[Add 'BNS Internally Transferred' status option to transfer doctypes.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[BNS Branch Accounting - Migration Handler  Holds migration tasks specific to bra]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Backfill split DNPR transfer accounts from legacy shared field.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Create transfer DocType links used in Connections sidebar.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Disable custom scripts that force Purchase Invoice.update_stock.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Ensure Purchase Receipt Item has sales_invoice_item.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Ensure Sales Invoice has bns_purchase_receipt_reference.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Normalize stale lock rows in BNS Repost Tracking after migration.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Post-migration hook for BNS branch accounting setup.      Ensures     1. Intern]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[Remove deprecated Purchase Receipt is_bns_internal_customer field.]] - rationale - business_needed_solutions/bns_branch_accounting/migration.py
- [[add_bns_internal_transfer_links()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[add_bns_status_option()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[after_migrate()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[disable_pi_update_stock_mandatory_script()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[ensure_pr_item_sales_invoice_item_field()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[ensure_si_pr_reference_field()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[initialize_bns_repost_tracking_state()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[migrate_split_internal_transfer_accounts()]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[migration.py]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[remove_old_pr_internal_customer_field()]] - code - business_needed_solutions/bns_branch_accounting/migration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Migration_Hooks
SORT file.name ASC
```
