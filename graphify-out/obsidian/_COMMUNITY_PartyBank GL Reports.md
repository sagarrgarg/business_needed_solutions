---
type: community
cohesion: 0.07
members: 46
---

# Party/Bank GL Reports

**Cohesion:** 0.07 - loosely connected
**Members:** 46 nodes

## Members
- [[Calculate ageing from Payment Ledger Entry.     Buckets 0-30, 30-60, 60-90, 90-]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Collect all voucher numbers grouped by voucher type for efficient batch queries.]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Fallback Calculate ageing directly from GL entries.     Groups outstanding amou]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Fetch bill_no and bill_date from Purchase Invoice.]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Fetch cheque_no (Reference Number) for Journal Entries. 	 	Args 		voucher_nos]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Fetch is_return status for Sales Invoices and Purchase Invoices. 	 	Args 		sale]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Fetch reference_no (ChequeReference No) for Payment Entries. 	 	Args 		voucher]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Get all metadata needed for the statement print format     - Company info (name]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Get bank account details with preference     1) Default Bank Account for this p]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Get future-dated payment entries for the party.]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[Retrieve the complete list of parties including primary and secondary parties.]] - rationale - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[calculate_ageing_from_gl()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[collect_voucher_nos_by_type()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[downloadStatementPDF()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.js
- [[execute()_9]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_account_type_map()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_accounts_with_children()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_accountwise_gle()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_balance()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_columns()_6]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_company_bank_details()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_complete_party_list()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_conditions()_2]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_data_with_opening_closing()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_future_payments()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_gl_entries()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_invoice_return_status()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_journal_entry_references()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_party_ageing()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_payment_entry_references()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_result()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_result_as_list()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_statement_meta()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_supplier_invoice_details()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[get_totals_dict()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[group_by_field()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[initialize_gle_map()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[loadStatementMeta()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.js
- [[party_gl.py]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[runStatementPDFReport()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.js
- [[set_account_currency()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[set_bill_no()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[updateClosingBalance()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.js
- [[updateDOMWithMeta()]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.js
- [[validate_filters()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py
- [[validate_party()_1]] - code - business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Party/Bank_GL_Reports
SORT file.name ASC
```
