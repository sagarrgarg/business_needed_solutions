---
type: community
cohesion: 0.17
members: 16
---

# GST E-Waybill Integration

**Cohesion:** 0.17 - loosely connected
**Members:** 16 nodes

## Members
- [[Auto-generate e-Waybill for internal customer Delivery Notes when     1. BNS Se]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[BNS Branch Accounting - GST integration for internal transfers.  Handles - Mand]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[Check if goods (not just services) are supplied in the document.      Goods are]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[Check if internal DN e-Waybill feature is enabled in BNS Branch Accounting Setti]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[Determine whether the Delivery Note is an inter-state (different GSTIN)     tran]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[Fetch the e-Waybill threshold amount from GST Settings.      Returns         fl]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[Mandate Vehicle No or GST Transporter ID before submission for internal     cust]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[Validate transportervehicle details required for e-Waybill generation.      Mat]] - rationale - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[_are_goods_supplied()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[_get_ewaybill_threshold()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[_is_inter_state_transfer()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[_is_internal_dn_ewaybill_enabled()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[_validate_transport_details()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[gst_integration.py]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[maybe_generate_internal_dn_ewaybill()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py
- [[validate_internal_dn_vehicle_no()]] - code - business_needed_solutions/bns_branch_accounting/gst_integration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/GST_E-Waybill_Integration
SORT file.name ASC
```
