# BNS Security & Code Review

Date: 2026-04-16 | Reviewer: Claude Opus 4.6 | Scope: Full codebase

---

## Fix Now - Security Holes

### SQL Injection in Sales Person Report

Someone can type SQL into the doc_type filter and it runs directly on your database.

File: `report/expected_sales_person_wise_predicted_transaction_summary.py` line 163

The doc_type filter value goes straight into the SQL table name with no validation:
```python
FROM `tab{doc_type}` dt, `tab{doc_type} Item` dt_item
```

This is the most dangerous finding. Any logged-in user who can run this report can read or destroy any table.

Fix: Add a whitelist check before the query:
```python
ALLOWED = {"Sales Order", "Delivery Note", "Sales Invoice"}
if filters["doc_type"] not in ALLOWED:
    frappe.throw("Invalid document type")
```

Same file line 213-214: lft/rgt values also go into SQL via f-string instead of parameterized query.

---

### XSS in Unlinked PAN Report

Party names go directly into onclick HTML. A supplier named `'); alert(1);//` runs JavaScript in every user's browser who opens the report.

File: `report/unlinked_customer_supplier_by_pan.py` line 58-68

```python
onclick="createPartyLink('{customer['name']}', '{supplier_name}', ...)"
```

Even a simple name like O'Brien breaks the button.

Fix: Use `frappe.utils.escape_html()` on all names, or switch to data attributes:
```html
<button data-customer="{escaped_name}" data-supplier="{escaped_name}">
```

---

### 10 Endpoints Let Read-Only Users Write Documents

Any Accounts User or Purchase User (read-only on BNS Branch Accounting Settings) can call these endpoints and modify submitted invoices, delivery notes, purchase receipts:

- `convert_sales_invoice_to_bns_internal`
- `convert_purchase_invoice_to_bns_internal`
- `convert_delivery_note_to_bns_internal`
- `convert_purchase_receipt_to_bns_internal`
- `link_dn_pr`, `link_si_pr`, `link_si_pi`
- `make_bns_internal_purchase_receipt`
- `make_bns_internal_purchase_invoice`
- `make_bns_internal_purchase_receipt_from_si`

File: `bns_branch_accounting/utils.py`

All use `_bns_require_accounts_read()` but should use `_bns_require_accounts_write()`.

The bulk endpoints (`bulk_convert_to_bns_internal`, `backfill_item_references`) already use the write check correctly. These 10 were missed.

---

## Fix Soon - Bugs That Hit Users

### Customer/Supplier Form Breaks When Both Open

Both `bns_customer.js` and `bns_supplier.js` define the same global function `_sync_standard_internal_visibility`. Second one loaded overwrites the first. If you open a Customer form then a Supplier form, Customer fields show wrong visibility.

Fix: Rename to `_sync_bns_internal_customer_visibility` and `_sync_bns_internal_supplier_visibility`.

---

### Negative Stock Error Messages Are Empty

File: `overrides/warehouse_negative_stock.py` line 335

```python
exc = sle.copy().update({"diff": diff})
```

`dict.update()` returns None. So `exc = None`. Every negative stock error appends None to the exceptions list. Users see blank error messages when negative stock is blocked.

Fix: Split into two lines:
```python
exc = sle.copy()
exc.update({"diff": diff})
```

---

### Convert Functions Have Race Conditions

File: `bns_branch_accounting/utils.py` lines 6928, 7087, 7338, 7513

All 4 `convert_*_to_bns_internal` functions load the document without a row lock. Two users clicking "Convert" at the same time can both succeed, creating duplicate references.

The `link_*` functions already use `for_update=True`. The convert functions forgot it.

---

### GL Balance Tolerance Too Loose

File: `bns_branch_accounting/utils.py` lines 2116, 2186, 2590

GL rewrite accepts imbalances up to 0.50 INR. Standard accounting tolerance is 0.01. An entry that's off by 0.49 gets silently posted.

---

### E-Waybill Required for Non-Stock Invoices

File: `overrides/attachment_validation.py` line 122-143

Server-side check does NOT call `_has_stock_items()` even though the function exists (line 146). Service-only Purchase Invoices above the threshold get blocked for missing e-Waybill attachment. The client-side check does call it - inconsistency.

---

## Fix When Possible - Performance and Cleanup

### Bank GL and Party GL Load Everything

Both reports run `SELECT name, is_group FROM tabAccount` with no company filter (every account across all companies loaded into memory). Both also load all Purchase Invoices with a bill_no.

Files: `report/bank_gl/bank_gl.py` line 31, 579 | `report/party_gl/party_gl.py` line 31, 654

On a multi-company system with years of data this is slow and wasteful.

---

### Party GL Ageing Is Wrong

File: `report/party_gl/party_gl.py` line 1043-1048

The PLE query doesn't select `voucher_type` or `voucher_no`. So grouping keys are always `(None, None, date)`. All invoices on the same date collapse into one bucket. Ageing numbers are inaccurate.

---

### Duplicate Remarks Column in Party GL

File: `report/party_gl/party_gl.py` line 167-174

`remarks` is always in the SELECT, then added again when `show_remarks` is on. Duplicate column in SQL.

---

### BNS Settings Readable by Everyone

File: `doctype/bns_settings/bns_settings.json` line 541

Role "All" has read access. Every logged-in user including website users can read all business configuration. Should be restricted to Desk User or specific roles.

---

### PAN Validation Doesn't Work Cross-Doctype

File: `overrides/pan_validation.py` line 85-89

Docstring says "unique across customers and suppliers" but code only checks within the same doctype. A Customer and Supplier can have the same PAN.

---

### Hardcoded Fiscal Year Fallback

File: `report/pure_accounts_receivable_summary.py` line 44

```python
return "2023-04-01", "2024-03-31"
```

If fiscal year lookup fails, report uses FY 2023-24 dates regardless of current year.

---

### SRBNB GSTIN Check Always Returns False

File: `bns_branch_accounting/srbnb_reconciliation.py` line 444-448

Looks up GSTIN by matching warehouse name to Address.name. Warehouse names look like "Stores - ABC", Address names look like "ABC-Shipping-1". Never matches. `is_same_gstin` is always False.

---

### Synchronous AJAX Freezes Browser

Files: `public/js/sales_invoice_form.js` line 18-37 | `public/js/doctype_item_grid_controls.js` line 90-98

`async: false` blocks the entire browser tab. Deprecated by all modern browsers. User sees frozen UI during validation calls.

---

### Stuck Repost Records Can't Be Cleared

File: `doctype/bns_repost_tracking/bns_repost_tracking.json`

Only System Manager can write. Accounts Manager has no way to clear a stuck "In Progress" record without calling IT.

---

## What's Good

- All 40+ doc_event hooks point to existing functions - no dead references
- Every whitelisted endpoint has a permission gate - none wide open
- All Journal Entry creation paths produce balanced debits and credits
- SQL in reconciliation modules is fully parameterized
- Rollback/savepoint patterns correct in all financial modules
- Fixture configuration is correct
- internal_party.py and billing_location.py are clean

---

## Fix Order

1. SQL injection in sales person report - exploitable now
2. XSS in unlinked PAN report - exploitable now
3. 10 read-gated write endpoints - any Accounts User can modify submitted docs
4. JS function collision - Customer/Supplier forms break
5. Negative stock error messages empty - users see nothing
6. GL tolerance 0.5 -> 0.01
7. Race conditions in convert functions
8. Unbounded queries in Bank GL and Party GL
