---
type: community
cohesion: 0.06
members: 38
---

# AccountsReceivablePayableSummary

**Cohesion:** 0.06 - loosely connected
**Members:** 38 nodes

## Members
- [[APAR netting via Party Link + common-party logic]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[AccountsReceivablePayableSummary_1]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[BNS one-way cancellation policy (PRPI not cascading to DNSI)]] - code - business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py
- [[BOM]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[Bin]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[Delivery Note]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[Item]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[Party Link]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[Purchase Invoice]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[Purchase Receipt]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[Sales Invoice]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[Stock Ledger Entry]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[Supplier]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[_as_list]] - code - business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py
- [[analyze_bom_availability]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[analyze_episode]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[build_report_data]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[convert_to_stock_qty]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[find_alternative_warehouse]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[frappe get_submitted_linked_docs]] - code - business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py
- [[get_bin_qty (batch-aware)]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[get_customer_invoice_and_paid_amounts]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[get_default_bom]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[get_delivery_note_items]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[get_purchase_invoice_items]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[get_purchase_receipt_items]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[get_sales_invoice_items]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[get_sle_data_bulk]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[get_submitted_linked_docs (BNS override)]] - code - business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py
- [[get_supplier_invoice_and_received_amounts]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[negative-stock voucher detection (qty_after_transaction0)]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[negative_stock_resolution.execute]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[outgoing_stock_audit.execute]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[pure_accounts_payable_summary.execute]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[redistribute_negative_ageing_buckets]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_payable_summary/pure_accounts_payable_summary.py
- [[sale-below-valuation detection (net_rate vs SLE valuation_rate)]] - code - business_needed_solutions/business_needed_solutions/report/outgoing_stock_audit___1_bns/outgoing_stock_audit___1_bns.py
- [[stock_ledger_negative_episodes.find_negative_episodes]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py
- [[stock_ledger_negative_episodes.get_stock_ledger_data]] - code - business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/AccountsReceivablePayableSummary
SORT file.name ASC
```
