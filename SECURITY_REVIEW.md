# Security & Code Review - business_needed_solutions

**Date:** 2026-04-16
**Reviewed by:** Claude Opus 4.6 (automated review)
**Scope:** Full codebase - overrides, utils, reports, dashboard, JS frontend, hooks, GST integration, doctypes, patches, reconciliation modules

---

## CRITICAL (3)

### 1. SQL Injection via f-string table name interpolation

**File:** `business_needed_solutions/business_needed_solutions/report/expected_sales_person_wise_predicted_transaction_summary/expected_sales_person_wise_predicted_transaction_summary.py`
**Lines:** 163-196

`filters["doc_type"]` is interpolated directly into the SQL table name via `.format()`:

```python
entries = frappe.db.sql(
    """... FROM `tab{}` dt, `tab{} Item` dt_item, `tabSales Team` st ...
    """.format(
        ..., filters["doc_type"], filters["doc_type"], ...
    ), ...
)
```

A crafted request can inject arbitrary SQL through the `doc_type` filter parameter.

**Fix:** Whitelist allowed `doc_type` values (`Sales Order`, `Delivery Note`, `Sales Invoice`) and reject anything else before interpolation.

---

### 2. SQL Injection via f-string lft/rgt interpolation

**File:** Same as above
**Lines:** 213-214

```python
lft, rgt = frappe.get_value("Sales Person", filters.get("sales_person"), ["lft", "rgt"])
conditions.append(
    f"exists(select name from `tabSales Person` where lft >= {lft} and rgt <= {rgt} ...)"
)
```

While `lft`/`rgt` come from the database, they are interpolated directly into SQL rather than parameterized. If an edge case produces unexpected types, this could be exploitable.

**Fix:** Use `%s` parameterized placeholders instead of f-string interpolation.

---

### 3. Stored XSS via unescaped party names in HTML

**File:** `business_needed_solutions/business_needed_solutions/report/unlinked_customer_supplier_by_pan/unlinked_customer_supplier_by_pan.py`
**Lines:** 58-68

Customer and supplier names are interpolated directly into `onclick` HTML without escaping:

```python
customer_to_supplier_btn = (
    f"<button class='btn btn-success' ... "
    f" onclick=\"createPartyLink('{customer['name']}', '{supplier_name}', ...)\">"
)
```

A supplier named `'); alert(1);//` would execute arbitrary JavaScript. A name containing single quotes (e.g., `O'Brien`) would break the HTML.

**Fix:** Escape all interpolated values with `frappe.utils.escape_html()` or use data attributes instead of inline event handlers.

---

## HIGH (8)

### 4. Permission gate too weak on 7 mutating endpoints

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 6925, 7085, 7335, 7511, 8067, 8340, 8484

All `convert_*_to_bns_internal()`, `link_dn_pr()`, `link_si_pr()`, and `link_si_pi()` functions call `_bns_require_accounts_read()` instead of `_bns_require_accounts_write()`. These functions perform significant write operations: they set `is_bns_internal_customer`, `status`, `bns_inter_company_reference`, and `per_billed` via `db_set()` on submitted documents.

Any user with only **read** permission on BNS Branch Accounting Settings (Accounts User, Purchase User) can modify submitted Sales Invoices, Purchase Invoices, Delivery Notes, and Purchase Receipts.

By contrast, `bulk_convert_to_bns_internal` (line 8868) and `backfill_item_references` (line 9086) correctly use `_bns_require_accounts_write()`.

**Fix:** Change `_bns_require_accounts_read()` to `_bns_require_accounts_write()` on all 7 endpoints.

---

### 5. Race condition in convert functions - no row lock

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 6928, 7087, 7338, 7513

`convert_sales_invoice_to_bns_internal` does `frappe.get_doc("Sales Invoice", sales_invoice)` without `for_update=True`. Two concurrent calls could both pass the "already converted?" check and both proceed to write `bns_inter_company_reference`. Same pattern in all 4 convert functions.

The `link_*` functions (lines 8069, 8486) correctly use `for_update=True`.

**Fix:** Add `for_update=True` to all `frappe.get_doc()` calls in convert functions.

---

### 6. sle.copy().update() returns None

**File:** `business_needed_solutions/business_needed_solutions/overrides/warehouse_negative_stock.py`
**Lines:** 335-336, 343-344

```python
exc = sle.copy().update({"diff": diff})
self.exceptions.setdefault(sle.warehouse, []).append(exc)
```

`dict.update()` returns `None`, so `exc` is always `None`. The exceptions list gets `None` appended instead of actual error data. Downstream code that iterates over exceptions will fail or produce incorrect error messages.

**Fix:** Split into two lines: `exc = sle.copy()` then `exc.update({"diff": diff})`.

---

### 7. ignore_permissions=True on Item save and Party Link insert

**File:** `business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py`
**Lines:** 151, 682

```python
item_doc.save(ignore_permissions=True)  # line 151
party_link.insert(ignore_permissions=True)  # line 682
```

Although there are manual permission gates (`_require_dashboard_write`), `ignore_permissions=True` bypasses Frappe's field-level permission checks, workflow restrictions, and user permission rules. Any user who passes the BNS Settings write check can modify any Item or create any Party Link.

**Fix:** Remove `ignore_permissions=True` and let Frappe's ORM enforce permissions, or document why it is required.

---

### 8. Unbounded query - all Purchase Invoices loaded into memory

**File:** `business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py`
**Lines:** 579-588

```python
for d in frappe.db.sql(
    """ select name, bill_no from `tabPurchase Invoice`
    where docstatus = 1 and bill_no is not null and bill_no != '' """,
    as_dict=1,
):
```

Loads every submitted Purchase Invoice with a `bill_no` into memory on every report execution. Same pattern in `party_gl/party_gl.py:654-668`.

**Fix:** Filter by company and date range from the report filters.

---

### 9. Unbounded query - all Accounts loaded into memory

**File:** `business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py`
**Line:** 31

```python
for acc in frappe.db.sql("""select name, is_group from tabAccount""", as_dict=1):
```

Fetches every Account across all companies. Same in `party_gl/party_gl.py:31`.

**Fix:** Add `WHERE company = %s` filter.

---

### 10. Global function name collision between bns_customer.js and bns_supplier.js

**File:** `business_needed_solutions/public/js/bns_customer.js:16` and `bns_supplier.js:16`

Both files define `function _sync_standard_internal_visibility(frm)` at global scope. Whichever loads second overwrites the first. When a user opens a Customer form then a Supplier form, the Customer version gets replaced by the Supplier's logic (checking `is_bns_internal_supplier` instead of `is_bns_internal_customer`), causing incorrect field visibility.

**Fix:** Namespace the functions: `_sync_bns_internal_customer_visibility` and `_sync_bns_internal_supplier_visibility`.

---

### 11. Document creation endpoints use read-only permission gate

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 4177, 5883, 6204

`make_bns_internal_purchase_receipt`, `make_bns_internal_purchase_invoice`, and `make_bns_internal_purchase_receipt_from_si` all use `_bns_require_accounts_read()` but they create new documents. Document creation should require write permission.

**Fix:** Change to `_bns_require_accounts_write()`.

---

## MEDIUM (18)

### 12. GL rewrite balance tolerance too generous

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 2116, 2186, 2590

GL rewrite functions check `abs(debit_total - credit_total) > 0.5` before rejecting. A 0.5 tolerance on currency amounts is large - an imbalance of 0.49 would be silently accepted. Standard accounting tolerance is 0.01 or at most 0.02.

---

### 13. _has_stock_items() not called in server-side e-Waybill check

**File:** `business_needed_solutions/business_needed_solutions/overrides/attachment_validation.py`
**Lines:** 122-143

`_is_ewaybill_required` checks enable flag and threshold but does NOT call `_has_stock_items(doc)` despite the docstring requiring it. Non-stock-only Purchase Invoices/Receipts above threshold incorrectly require an e-Waybill attachment. The client-side endpoint `check_ewaybill_applicability` (line 232-244) DOES check for stock items - inconsistency between server and client validation.

---

### 14. PAN uniqueness not cross-doctype

**File:** `business_needed_solutions/business_needed_solutions/overrides/pan_validation.py`
**Lines:** 85-89

PAN uniqueness is only checked within the same doctype (Customer or Supplier). The docstring claims cross-doctype uniqueness ("checks if the PAN number is unique across all customers and suppliers"), but a Customer and Supplier can share the same PAN without triggering validation.

---

### 15. Translation calls at module import time

**File:** `business_needed_solutions/business_needed_solutions/overrides/submission_restriction.py`
**Lines:** 35-36, 48, 59

`_()` called at module import time in `DOCUMENT_CATEGORIES` dict. Translations are baked in permanently and won't respect per-user language preferences.

---

### 16. Fragile string-matching for exception detection

**File:** `business_needed_solutions/business_needed_solutions/overrides/gst_compliance.py`
**Lines:** 80-84

Checks `"Same GSTIN Validation Error"` in exception message string. If the title text changes or is translated, the check fails silently.

---

### 17. Explicit frappe.db.commit() in whitelisted function

**File:** `business_needed_solutions/business_needed_solutions/overrides/address_preferred_flags.py`
**Line:** 70

`frappe.db.commit()` inside whitelisted function breaks Frappe's automatic transaction management. If an error occurs after the commit, the database change cannot be rolled back.

---

### 18. Duplicate remarks field in SQL query

**File:** `business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py`
**Lines:** 167-174

`remarks` is included unconditionally in `select_fields`, then appended again when `show_remarks` is set. Produces duplicate column in SQL query.

---

### 19. remarks_length interpolated unsafely in SQL

**File:** `business_needed_solutions/business_needed_solutions/report/bank_gl/bank_gl.py`
**Line:** 159

```python
select_fields += f",substr(remarks, 1, {remarks_length}) as 'remarks'"
```

`remarks_length` comes from Accounts Settings and is interpolated directly into SQL via f-string. Same issue in `party_gl.py:172`.

---

### 20. Party Link query has no company filter

**File:** `business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py`
**Lines:** 297-300

```python
party_links = frappe.get_all("Party Link", fields=[...])
```

Fetches ALL Party Links across all companies with no filters. Same in `pure_accounts_payable_summary.py:125-128`.

---

### 21. Hardcoded fallback fiscal year

**File:** `business_needed_solutions/business_needed_solutions/report/pure_accounts_receivable_summary/pure_accounts_receivable_summary.py`
**Line:** 44

```python
return "2023-04-01", "2024-03-31"
```

Hardcoded fallback produces wrong results for any year other than FY 2023-24 if the fiscal year lookup fails.

---

### 22. GSTIN lookup uses wrong key - always returns False

**File:** `business_needed_solutions/bns_branch_accounting/srbnb_reconciliation.py`
**Lines:** 444-448

```python
from_gstin = frappe.db.get_value("Address", {"name": se.from_warehouse}, "gstin") or ""
```

Looks up Address by matching warehouse name to Address.name, which never matches. `is_same_gstin` is always False.

---

### 23. BNS Settings readable by all authenticated users

**File:** `business_needed_solutions/business_needed_solutions/doctype/bns_settings/bns_settings.json`
**Line:** 541

`{"read": 1, "role": "All"}` grants read to every authenticated user including Website Users.

---

### 24. stock_entry_patch monkey-patches core ERPNext method

**File:** `business_needed_solutions/business_needed_solutions/patch/stock_entry_patch.py`

Monkey-patches `StockEntry.get_bom_raw_materials` at runtime. Will silently override future ERPNext updates to this method without any version guard.

---

### 25. TOCTOU in update_vehicle.py

**File:** `business_needed_solutions/update_vehicle.py`
**Lines:** 49-50, 170

Permission checked at entry, then `doc.save(ignore_permissions=True)` used later. Race between check and write.

---

### 26. N+1 queries in bulk preview

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 8771-8837

`get_bulk_conversion_preview` issues individual `frappe.db.get_value("Customer", ...)` calls for up to 10,000 documents.

---

### 27. XSS in dialog HTML fields (4 files)

**Files:**
- `public/js/delivery_note.js:55-63`
- `public/js/sales_invoice_form.js:87-94`
- `public/js/purchase_invoice_form.js:100-109`
- `public/js/purchase_receipt_form.js:59-67`

Server-returned document names/fields interpolated into HTML template literals without escaping. Risk mitigated by Frappe ORM sanitization but pattern is unsafe.

---

### 28. Synchronous AJAX blocks UI thread

**File:** `business_needed_solutions/public/js/sales_invoice_form.js`
**Lines:** 18-37

`async: false` in `frappe.call()` blocks the main thread. Deprecated by browsers. Same in `doctype_item_grid_controls.js:90-98`.

---

### 29. cancel_dialog permission level mismatch

**File:** `business_needed_solutions/bns_branch_accounting/overrides/cancel_dialog.py`
**Line:** 44

Permission check uses "read" instead of "cancel" for a cancel-dialog helper.

---

## LOW (15)

### 30. Empty invoice_list produces invalid SQL

**File:** `business_needed_solutions/business_needed_solutions/overrides/purchase_register_fix.py`
**Line:** 36

If `invoice_list` is empty, produces `WHERE parent in ()` which is invalid SQL.

---

### 31. N+1 query in Stock Reconciliation validation

**File:** `business_needed_solutions/business_needed_solutions/overrides/negative_stock_override.py`
**Lines:** 159-168

Reads `actual_qty` from Bin per row - N+1 pattern for documents with many reconciliation rows.

---

### 32. doc.pan without .get() guard

**File:** `business_needed_solutions/business_needed_solutions/overrides/pan_validation.py`
**Line:** 39

`doc.pan` accessed without `.get()`. Raises `AttributeError` if `pan` field doesn't exist on the doctype.

---

### 33. Division by zero if bom.quantity is 0

**File:** `business_needed_solutions/business_needed_solutions/report/negative_stock_resolution_report/negative_stock_resolution_report.py`
**Line:** 201

```python
required_item_qty = (required_qty * item.stock_qty) / bom.quantity
```

No guard for `bom.quantity == 0`.

---

### 34. PLE query missing voucher fields - ageing keys always (None, None, date)

**File:** `business_needed_solutions/business_needed_solutions/report/party_gl/party_gl.py`
**Lines:** 1043-1048

`voucher_type` and `voucher_no` not selected in PLE query, so ageing grouping keys are always `(None, None, posting_date)`, making ageing calculation inaccurate.

---

### 35. N+1 frappe.get_doc per stock entry in almonds report

**File:** `business_needed_solutions/business_needed_solutions/report/almonds_sorting_report/almonds_sorting_report.py`
**Lines:** 94-95

---

### 36. Broad except swallows errors in lookup endpoints

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 6627-6629, 6664-6666

`get_sales_invoice_by_bill_no` and `get_purchase_invoice_by_supplier_invoice` catch `Exception` and return `{"found": False}`. Real errors (permissions, corrupt data) hidden from user.

---

### 37. Debug log grows unbounded

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 78-94

`bns_branch_accounting_debug.ndjson` appends indefinitely with no size limit or rotation.

---

### 38. unlink_si_pi resets status without checking returns/partial payments

**File:** `business_needed_solutions/bns_branch_accounting/utils.py`
**Lines:** 8669-8671

Sets status based on `outstanding_amount > 0` without considering returns (Credit Notes) or other valid statuses.

---

### 39. Silent exception swallowing in migration patch

**File:** `business_needed_solutions/business_needed_solutions/patch/migrate_internal_dn_ewaybill_to_branch_accounting.py`
**Lines:** 39-40

`except Exception: frappe.db.rollback()` silently swallows any error. Migration failure is not logged.

---

### 40. Template literal in __() breaks translation extraction

**File:** `business_needed_solutions/public/js/direct_print.js`
**Line:** 323

```js
message: __(`Print Format not set for ${doctype}...`)
```

Should use `__('Print Format not set for {0}...', [doctype])`.

---

### 41. console.log left in production code

**File:** `business_needed_solutions/public/js/doctype_item_grid_controls.js`
**Line:** 109

---

### 42. Race condition in DirectPrint initialization

**File:** `business_needed_solutions/public/js/direct_print.js`
**Lines:** 42-51

Async `initialize()` not awaited before handlers registered. Form refresh before settings load shows incorrect configuration error.

---

### 43. Synchronous AJAX in UOM restriction

**File:** `business_needed_solutions/public/js/doctype_item_grid_controls.js`
**Lines:** 90-98

`async: false` blocks UI thread. Deprecated by browsers.

---

### 44. Accounts Manager can't clear stuck repost records

**File:** `business_needed_solutions/bns_branch_accounting/doctype/bns_repost_tracking/bns_repost_tracking.json`
**Lines:** 111-125

Only System Manager can write. No whitelisted endpoint to clear stuck "In Progress" records.

---

## Positive Findings

- All 40+ `doc_events` hooks verified - no dangling references
- All whitelisted endpoints have permission gates - none wide-open
- All Journal Entry construction paths produce balanced debits/credits
- SQL in reconciliation modules fully parameterized
- Rollback/savepoint patterns correct in all financial modules
- Fixtures properly configured with module filters and `overwrite: True`
- `internal_party.py` and `billing_location.py` clean and correct
- `cancel_dialog.py` properly restricts one-way cancellation for internal transfers

---

## Priority Fix Order

1. SQL injection (#1, #2) - exploitable via report filters
2. Stored XSS (#3) - via party names in report output
3. Permission gates (#4, #11) - read-gated write operations on 10 endpoints
4. Function collision (#10) - breaks Customer/Supplier forms
5. sle.copy().update() bug (#6) - exceptions silently corrupted
6. GL tolerance (#12) - 0.5 is too loose for accounting
7. Race conditions (#5) - missing for_update on convert functions
8. Unbounded queries (#8, #9) - performance on production data
