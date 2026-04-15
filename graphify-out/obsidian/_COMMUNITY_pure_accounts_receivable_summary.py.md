---
type: community
cohesion: 0.16
members: 22
---

# pure_accounts_receivable_summary.py

**Cohesion:** 0.16 - loosely connected
**Members:** 22 nodes

## Members
- [[.adjust_ageing_fifo()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[.get_columns()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[.get_data()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[.get_party_total()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[.init_party_total()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[.run()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[.set_party_details()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[AccountsReceivablePayableSummary]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[After ARAP netting, some ageing buckets may be negative. Redistribute by 	treat]] - rationale - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[Get GL balance for parties filtered by account_type. 	For Receivable (Asset) de]] - rationale - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[Get customer invoice amounts (Sales Invoices including Credit Notes) for custome]] - rationale - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[Get supplier invoice amounts (including debit notes) for parties that are linked]] - rationale - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[ReceivablePayableReport]] - code
- [[Virtually apply unallocated payments (negative outstanding) to the oldest 		invo]] - rationale - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[execute()_6]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[get_customer_invoice_and_paid_amounts()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[get_fiscal_year_dates()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[get_gl_balance()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[get_party_type_options()_1]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.js
- [[get_supplier_invoice_and_received_amounts()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[pure_accounts_receivable_summary.py]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py
- [[redistribute_negative_ageing_buckets()]] - code - business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/pure_accounts_receivable_summary.py
SORT file.name ASC
```
