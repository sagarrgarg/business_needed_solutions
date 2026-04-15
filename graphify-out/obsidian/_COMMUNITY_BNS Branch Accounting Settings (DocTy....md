---
type: community
cohesion: 0.32
members: 8
---

# BNS Branch Accounting Settings (DocTy...

**Cohesion:** 0.32 - loosely connected
**Members:** 8 nodes

## Members
- [[BNS Branch Accounting Settings (DocType controller)]] - code - business_needed_solutions/bns_branch_accounting/doctype/bns_branch_accounting_settings/bns_branch_accounting_settings.py
- [[BNS Repost Tracking DocType]] - code - business_needed_solutions/bns_branch_accounting/doctype/bns_repost_tracking/bns_repost_tracking.js
- [[Fiscal Year Cutoff (internal_transfer  accounting_rewrite)]] - code - business_needed_solutions/bns_branch_accounting/doctype/bns_branch_accounting_settings/bns_branch_accounting_settings.py
- [[Internal Transfer Accounting Audit report]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_accounting_audit/internal_transfer_accounting_audit.py
- [[Internal Transfer Receive Mismatch report]] - code - business_needed_solutions/bns_branch_accounting/report/internal_transfer_receive_mismatch/internal_transfer_receive_mismatch.py
- [[bns_branch_accounting.gst_integration (e-Waybill)]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[bns_branch_accounting.migration]] - code - business_needed_solutions/bns_branch_accounting/migration.py
- [[update_vehicle_or_transporter whitelisted API]] - code - business_needed_solutions/update_vehicle.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/BNS_Branch_Accounting_Settings_(DocTy...
SORT file.name ASC
```
