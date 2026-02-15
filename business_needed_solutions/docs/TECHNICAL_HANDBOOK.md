# Business Needed Solutions (BNS) — Technical Handbook

> **Version:** 1.1 — Updated 2026-02-13
> **Author:** Sagar Ratan Garg
> **License:** Commercial
> **Framework:** Frappe + ERPNext + India Compliance

---

### Changes Log (v1.1)

| Change | Files Modified | Bug Fixed |
|--------|---------------|-----------|
| **BOM enforcement activated** — `override_doctype_class` uncommented, `BNSStockEntry` now active | `hooks.py` | BNS-BOM-001 |
| **From BOM validation** — `from_bom` must be checked when BOM is enforced for Manufacture | `stock_entry_component_qty_variance.py` | — |
| **BOM field red highlighting** — Client-side mandatory toggle for `bom_no` + `from_bom` | `doctype_item_grid_controls.js` | — |
| **Internal Transfer Mismatch → Prepared Report** — runs in background, dashboard reads cached data | `internal_transfer_receive_mismatch.json`, `bns_dashboard.py`, `bns_dashboard.js` | — |
| **Dashboard: eliminated duplicate API calls** — PAN + Mismatch no longer fetched twice | `bns_dashboard.py` | — |
| **Dashboard: `load_expense_accounts` unblocked** — moved into `Promise.all` | `bns_dashboard.js` | — |
| **Dashboard: batch Party Link lookup** — replaced N+1 `db.exists` with single pre-fetch | `bns_dashboard.py` | — |
| **Dashboard: stale prepared report handling** — `FileNotFoundError` returns "Not Prepared" cleanly | `bns_dashboard.py` | — |

---

## Table of Contents

1. [App Architecture Overview](#1-app-architecture-overview)
2. [Functional Area 1: BNS Internal Transfers](#2-bns-internal-transfers)
3. [Functional Area 2: Submission Restriction System](#3-submission-restriction-system)
4. [Functional Area 3: Triple Discount System (D1/D2/D3)](#4-triple-discount-system)
5. [Functional Area 4: Custom Update Items (SO/PO)](#5-custom-update-items)
6. [Functional Area 5: Per-Warehouse Negative Stock Control](#6-per-warehouse-negative-stock-control)
7. [Functional Area 6: GST Compliance & E-Waybill](#7-gst-compliance--e-waybill)
8. [Functional Area 7: PAN Validation](#8-pan-validation)
9. [Functional Area 8: Item Validation](#9-item-validation)
10. [Functional Area 9: Stock Update/Reference Validation](#10-stock-updatereference-validation)
11. [Functional Area 10: BOM Component Qty Variance](#11-bom-component-qty-variance)
12. [Functional Area 11: Auto Payment Reconciliation (FIFO)](#12-auto-payment-reconciliation)
13. [Functional Area 12: Direct Print System](#13-direct-print-system)
14. [Functional Area 13: UOM Restriction & Conversion Overlay](#14-uom-restriction--conversion-overlay)
15. [Functional Area 14: Custom Reports (11 Reports)](#15-custom-reports)
16. [Functional Area 15: Print Formats (11 Formats)](#16-print-formats)
17. [Functional Area 16: BNS Settings DocType](#17-bns-settings-doctype)
18. [Functional Area 17: Migration & Post-Install](#18-migration--post-install)
19. [Schema Changes Reference (Custom Fields + Property Setters)](#19-schema-changes-reference)
20. [Master Bug Registry](#20-master-bug-registry)
21. [File Reference Index](#21-file-reference-index)

---

## 1. App Architecture Overview

### App Identity
- **App Name:** `business_needed_solutions`
- **Module Name:** `Business Needed Solutions`
- **Publisher:** Sagar Ratan Garg
- **Dependencies:** Frappe, ERPNext, India Compliance (india_compliance)

### Component Inventory

| Component | Count |
|-----------|-------|
| Custom DocTypes | 2 (BNS Settings, BNS Settings Print Format) |
| Custom Reports | 11 |
| Custom Print Formats | 11 (7 in print_format/, 4+ in fixtures) |
| Custom Pages | 1 (BNS Dashboard) |
| Workspaces | 1 |
| Override Modules | 8 (in overrides/) |
| Public JS Files | 14 |
| Custom Fields | ~50 across 13 DocTypes |
| Property Setters | 4 (fixture) + dynamic (via BNS Settings) |
| Client Scripts (fixture) | 3 |
| Fixtures | 5 JSON files |

### How It Hooks Into Frappe/ERPNext

```
hooks.py
├── app_include_js (7 files) ────────── Loaded on EVERY desk page
├── doctype_js (8 doctypes) ─────────── Loaded on specific form views
├── doctype_list_js (4 doctypes) ────── Loaded on specific list views
├── override_doctype_class (1) ──────── BNSStockEntry overrides Stock Entry
├── doc_events (14 doctypes) ────────── Python hooks on document lifecycle
├── fixtures (3 types) ──────────────── Schema changes exported with app
├── after_migrate ───────────────────── Post-migration setup
└── after_app_init ──────────────────── Monkey-patches at startup
```

### Core Design Patterns

1. **Hook-based overrides** — Business logic injected via `doc_events` rather than class inheritance
2. **Class override** — `BNSStockEntry` overrides Stock Entry via `override_doctype_class` for BOM enforcement + variance tolerance
3. **Single Settings DocType** — `BNS Settings` is the master toggle for all features
4. **Client-side form extensions** — Heavy use of `app_include_js` and `doctype_js` to modify ERPNext forms
5. **Parallel internal transfer system** — A complete replacement for ERPNext's standard inter-company transactions, using `bns_inter_company_reference` instead of `inter_company_invoice_reference`

---

## 2. BNS Internal Transfers

### Purpose
Replaces ERPNext's standard inter-company transaction system with a custom workflow that handles **same-GSTIN** (branch-to-branch) and **different-GSTIN** (company-to-company) internal transfers.

### How It Works

**Two Flows:**

#### Flow A: Same GSTIN (Branch Transfer)
```
Company A (Branch 1) ──DN──> Company A (Branch 2) ──PR
                              billing_address_gstin == company_gstin

DN submit → status = "BNS Internally Transferred"
         → per_billed = 100 (no invoice needed)
         → auto PR creation available
PR submit → status = "BNS Internally Transferred"
         → bidirectional reference set
```

#### Flow B: Different GSTIN (Inter-Company)
```
Company A ──SI──> Company B ──PI
              billing_address_gstin != company_gstin

SI submit → status = "BNS Internally Transferred"
         → PI creation available (with stock/non-stock routing)
PI submit → traces back to SI via bill_no or bns_inter_company_reference
         → bidirectional reference set
```

### Files Involved

| File | Role |
|------|------|
| `utils.py` (3,738 lines) | Core engine — all creation, linking, unlinking, validation, conversion, bulk ops |
| `sales_invoice_form.js` | SI form buttons: Convert, Link PI, Unlink PI, Create PI, Create PR, Update Vehicle |
| `purchase_invoice_form.js` | PI form buttons: Convert, Link SI, Unlink SI |
| `delivery_note.js` | DN form buttons: Convert, Create PR, Link PR, Unlink PR |
| `purchase_receipt_form.js` | PR form buttons: Convert, Link DN, Unlink DN |
| `sales_invoice_list.js` | Purple "BNS Internally Transferred" indicator |
| `purchase_invoice_list.js` | Purple "BNS Internally Transferred" indicator |
| `delivery_note_list.js` | Purple "BNS Internally Transferred" indicator |
| `purchase_receipt_list.js` | Purple "BNS Internally Transferred" indicator |
| `migration.py` | Adds "BNS Internally Transferred" status option + DocType Links |

### Custom Fields Used
- `Customer.is_bns_internal_customer` + `Customer.bns_represents_company`
- `Supplier.is_bns_internal_supplier` + `Supplier.bns_represents_company`
- `{DN|PR|SI|PI}.bns_inter_company_reference` — bidirectional link
- `{DN|SI}.is_bns_internal_customer` — auto-fetched from Customer
- `{PR|PI}.is_bns_internal_supplier` — auto-fetched from Supplier

### Whitelisted API Endpoints (utils.py)
- `make_bns_internal_purchase_receipt` — DN → PR
- `make_bns_internal_purchase_invoice` — SI → PI
- `make_bns_internal_purchase_receipt_from_si` — SI → PR (stock items)
- `convert_sales_invoice_to_bns_internal` / `convert_purchase_invoice_to_bns_internal`
- `convert_delivery_note_to_bns_internal` / `convert_purchase_receipt_to_bns_internal`
- `link_si_pi` / `unlink_si_pi` / `link_dn_pr` / `unlink_dn_pr`
- `validate_si_pi_items_match` / `validate_dn_pr_items_match`
- `get_sales_invoice_by_bill_no` / `get_purchase_invoice_by_supplier_invoice`
- `get_purchase_receipt_by_supplier_delivery_note` / `get_delivery_note_by_supplier_delivery_note`
- `get_bulk_conversion_preview` / `bulk_convert_to_bns_internal`
- `backfill_item_references`

### System Impact
- Adds a new document status "BNS Internally Transferred" to DN, PR, SI, PI
- Creates `DocType Link` records for sidebar navigation (SI↔PI, DN↔PR)
- Modifies `per_billed` on DN (sets to 100 for same-GSTIN to skip billing)
- Bypasses ERPNext's standard inter-company workflow entirely
- Uses `db_set` and `frappe.db.set_value` to modify submitted documents directly

### Property Setter Impact
- **Hides** `update_billed_amount_in_delivery_note` on Sales Invoice (default=0, hidden=1)
- **Hides** `update_billed_amount_in_sales_order` on Sales Invoice (default=0, hidden=1)
- These prevent Sales Invoice from updating billed amounts back to DN/SO, which would conflict with BNS's internal status management

### Validation Rules
1. DN cancellation blocked if non-cancelled PR exists referencing it
2. SI credit notes blocked for BNS internal customers
3. DN returns blocked for BNS internal customers
4. PR/PI quantities validated against source DN/SI quantities (with `over_delivery_receipt_allowance`)
5. Item matching validated before linking (item_code, qty, taxable_value, taxes, grand_total)

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-INT-001 | **CRITICAL** | ~~Redundant `or not inter_company_reference` in guard~~ — Fixed: simplified to `if not parent_doctype` |
| BNS-INT-002 | **HIGH** | All `@frappe.whitelist()` functions in `utils.py` lack `frappe.has_permission()` checks. Any authenticated user (even website users) can invoke `convert_*`, `link_*`, `unlink_*`, `bulk_convert_*` and modify submitted documents |
| BNS-INT-003 | **HIGH** | `convert_*` functions modify multiple documents (SI + PI + PI items) without database transaction wrapping. Partial failure leaves inconsistent state (e.g., SI marked as internal but PI not linked) |
| BNS-INT-004 | **MEDIUM** | `_update_sales_invoice_pr_reference` is a no-op (`pass`) — SI→PR reference is never established when creating PR from SI |
| BNS-INT-005 | **MEDIUM** | `bulk_convert_to_bns_internal` does N+1 queries per document — `frappe.db.get_value("Customer", ...)` inside a loop for up to 10,000 documents |
| BNS-INT-006 | **MEDIUM** | `validate_delivery_note_cancellation` silently passes on non-ValidationError exceptions — DB errors allow DN cancellation with orphaned PRs |
| BNS-INT-007 | **LOW** | `_get_representing_company` and `_get_representing_company_from_customer` are identical functions — code duplication |
| BNS-INT-008 | **LOW** | `purchase_invoice_form.js` overrides `frappe.utils.fetch_link_title` globally — this affects ALL link fields on ALL doctypes, not just Purchase Invoice |

---

## 3. Submission Restriction System

### Purpose
Restricts document submission to authorized users only. When enabled, only users with specific roles can submit documents — all other users can only save drafts.

### How It Works
```
User clicks Submit → on_submit hook fires → validate_submission_permission()
├── BNS Settings.restrict_submission enabled?
│   ├── No → allow submission
│   └── Yes → categorize document (stock/transaction/order)
│       ├── User has override role? → allow submission
│       └── User lacks override role → frappe.throw() blocks submission
```

### Files Involved

| File | Role |
|------|------|
| `overrides/submission_restriction.py` | Core logic — categorization + permission checking |
| `hooks.py` doc_events | Registered on 13 doctypes' `on_submit` |
| `test_submission_restriction.py` | Manual test script (not unittest) |
| `docs/submission_restriction.md` | User documentation |

### DocTypes Affected (on_submit hook)
Stock Entry, Delivery Note, Purchase Receipt, Stock Reconciliation, Sales Invoice, Purchase Invoice, Journal Entry, Payment Entry, Sales Order, Purchase Order, Payment Request

### Category System

| Category | DocTypes | Setting Field | Override Role Field |
|----------|----------|--------------|-------------------|
| Stock | Stock Entry, Stock Reconciliation, SI (w/ update_stock), PI (w/ update_stock), DN, PR | `restrict_submission` | `submission_restriction_override_roles` |
| Transaction | SI, PI, DN, PR, Journal Entry, Payment Entry | `restrict_submission` | `submission_restriction_override_roles` |
| Order | Sales Order, Purchase Order, Payment Request | `restrict_submission` | `submission_restriction_override_roles` |

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-SUB-001 | **HIGH (Design)** | All three categories share the SAME `restrict_submission` toggle and `submission_restriction_override_roles` field. The three-category architecture is entirely non-functional — you cannot restrict stock submissions independently from transaction submissions. The design suggests per-category control was intended but never implemented. |
| BNS-SUB-002 | **MEDIUM** | Module-level `_()` translation calls in `DOCUMENT_CATEGORIES` dict — translation happens at import time when user language context may not be set. Messages may display in the wrong language. |
| BNS-SUB-003 | **LOW** | `SubmissionRestrictionError` custom exception defined but never raised — all errors use `frappe.throw()` |
| BNS-SUB-004 | **LOW** | ~~Legacy wrapper functions removed (were unused)~~ — Fixed |

---

## 4. Triple Discount System

### Purpose
Replaces ERPNext's single `discount_percentage` with a cascading three-tier discount system (D1, D2, D3) for selling documents.

### How It Works
```
price_list_rate = 1000
D1 = 10% → after D1: 1000 * 0.90 = 900
D2 = 5%  → after D2: 900 * 0.95 = 855
D3 = 2%  → after D3: 855 * 0.98 = 837.90

effective_discount_percentage = 100 - (837.90 / 1000 * 100) = 16.21%
rate = 837.90
```

**Cascade Rule:** D2 is readonly until D1 > 0; D3 is readonly until D1 > 0 AND D2 > 0. If D1 is cleared, D2 and D3 auto-clear.

### Files Involved

| File | Role |
|------|------|
| `discount_manipulation_by_type.js` | Client-side cascade logic + rate computation |
| `bns_settings.py` | `apply_settings()` toggles field visibility via Property Setters |
| `update_items_override.js` | Handles D1/D2/D3 in Update Items dialog |
| `overrides/update_items.py` | Server-side rate computation with triple discounts |
| `fixtures/custom_field.json` | D1/D2/D3 fields on 4 item child tables |

### DocTypes With D1/D2/D3 Fields
- Sales Invoice Item
- Sales Order Item
- Delivery Note Item
- Quotation Item

*Note: Purchase-side documents do NOT have triple discount fields.*

### Mode Toggle (BNS Settings)
- `discount_type = "Single"` → Standard ERPNext behavior, D1/D2/D3 fields hidden
- `discount_type = "Triple"` → D1/D2/D3 visible, `discount_percentage` computed from triple formula, `rate` is read-only

### System Impact
- `bns_settings.py:apply_settings()` dynamically creates Property Setters to:
  - Show/hide `custom_d1_`, `custom_d2_`, `custom_d3_` columns
  - Set `rate` to read-only on ALL item doctypes (sales AND purchase)
  - Control `in_list_view` and `columns` for item grid
- Field visibility changes persist via Property Setters — they survive cache clears

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-DISC-001 | **MEDIUM** | `apply_settings()` sets `rate` to `read_only=1` on ALL item doctypes including Purchase Invoice Item, Purchase Receipt Item, Purchase Order Item — even though purchase documents don't use triple discounts. Users cannot manually set rates on purchase documents in triple mode. |
| BNS-DISC-002 | **LOW** | `discount_manipulation_by_type.js` runs on Quotation but there's no corresponding Update Items override for Quotation — the Update Items dialog won't handle triple discounts on Quotations |

---

## 5. Custom Update Items

### Purpose
Replaces ERPNext's standard "Update Items" button on submitted Sales Orders and Purchase Orders with a custom implementation that supports triple discounts, UOM restrictions, and enhanced item modification.

### How It Works
1. JS (`update_items_override.js`) replaces ERPNext's "Update Items" button on SO/PO
2. Custom dialog shows editable fields including D1/D2/D3 (for SO), item_code change, UOM selection
3. On save, calls `update_items.update_child_items` (whitelisted)
4. Server validates quantities, UOMs, workflow conditions, subcontracting
5. Items are updated, packing lists remade, taxes recalculated

### Files Involved

| File | Role |
|------|------|
| `update_items_override.js` | Client-side dialog replacement |
| `overrides/update_items.py` | Server-side `update_child_items` (635 lines) |

### Features Over Standard ERPNext
- Triple discount support (D1/D2/D3 for Sales Order)
- UOM validation against Item's allowed UOMs
- Reserved stock checking for Sales Orders
- Enhanced item code change with automatic detail refresh
- Conversion factor auto-lookup
- Subcontracting FG item support

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| ~~BNS-UPD-001~~ | ~~CRITICAL~~ | **FIXED** — `item_code_changed` now defined in new-item path (`item_code_changed = False`) to prevent `UnboundLocalError` when adding rows to submitted SO/PO |
| BNS-UPD-002 | **HIGH** | No database lock or transaction guard — concurrent `update_child_items` calls on the same SO/PO can cause race conditions (stale data overwrites, double-counted stock reservations) |
| BNS-UPD-003 | **MEDIUM** | The function is 530+ lines with deeply nested logic — high maintenance/readability risk |

---

## 6. Per-Warehouse Negative Stock Control

### Purpose
When ERPNext's global "Allow Negative Stock" is ON, this feature lets you selectively disallow negative stock on specific warehouses.

### How It Works
```
Stock Settings: allow_negative_stock = 1 (global)
Warehouse "Main Store": bns_disallow_negative_stock = 1

Transaction attempt: -50 qty from "Main Store"
├── Global allows it
├── BNS checks: warehouse has disallow flag?
│   └── Yes → check current qty + transaction impact
│       ├── Result positive → allow
│       └── Result negative → frappe.throw() blocks it

Three enforcement points (all redundant):
1. Monkey-patched make_entry() — before SLE creation
2. SLE validate doc_event — during SLE creation
3. Monkey-patched validate_negative_qty_in_future_sle() — future impact check
```

### Files Involved

| File | Role |
|------|------|
| `overrides/warehouse_negative_stock.py` | Core validation + monkey patches |
| `public/js/warehouse.js` | Shows/hides `bns_disallow_negative_stock` field on Warehouse form |
| `fixtures/custom_field.json` | `Warehouse.bns_disallow_negative_stock` field |
| `hooks.py` `after_app_init` | `apply_patches()` called at app startup |
| `hooks.py` `doc_events` | SLE validate hook |

### Monkey Patches Applied at App Init
1. `erpnext.stock.stock_ledger.validate_negative_qty_in_future_sle` — wrapped to add warehouse-level checks
2. `erpnext.stock.stock_ledger.make_entry` — wrapped to validate before SLE creation
3. `erpnext.stock.stock_ledger.update_entries_after.validate_negative_stock` — patched class method

### System Impact
- **Runs at app initialization** — affects ALL sites on the bench
- **Three validation points per transaction** — significant performance overhead
- Bypassed during `frappe.flags.through_repost_item_valuation`

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-NEG-001 | **HIGH** | Patched `validate_negative_stock` method: `sle.copy().update({"diff": diff})` returns `None` because Python dict `.update()` returns None. `self.exceptions` accumulates `None` values instead of SLE data, causing `AttributeError` downstream when ERPNext tries to format exception details. |
| BNS-NEG-002 | **HIGH** | Patched `validate_negative_stock` double-counts `actual_qty`: `diff = self.wh_data.qty_after_transaction + flt(sle.actual_qty) - flt(self.reserved_stock)` but `qty_after_transaction` already includes `actual_qty`. This makes the threshold too strict — valid transactions may be incorrectly blocked. |
| BNS-NEG-003 | **MEDIUM** | Triple-redundant validation: same warehouse check runs 3 times per transaction, each making multiple DB queries. Significant performance overhead on every stock transaction. |
| BNS-NEG-004 | **LOW** | `get_or_make_bin()` called during validation can CREATE Bin records as side effect, even if the transaction ultimately fails — orphan data. |

---

## 7. GST Compliance & E-Waybill

### Purpose
Enforces Indian GST compliance for internal Delivery Notes: mandates vehicle/transporter info and auto-generates e-Waybills on submission.

### How It Works

**Vehicle Number Mandate (on DN submit):**
```
DN submitted → is BNS internal customer?
├── No → skip
└── Yes → is intra-state (same GSTIN)?
    ├── No → skip (inter-state handled differently)
    └── Yes → does amount exceed e-Waybill threshold?
        ├── No → skip
        └── Yes → vehicle_no OR gst_transporter_id required
            ├── Present → proceed
            └── Missing → frappe.throw() blocks submission
```

**E-Waybill Auto-Generation (on DN submit):**
```
DN submitted → BNS Internal Transfer Settings.enable_internal_dn_ewaybill?
├── No → skip
└── Yes → is BNS internal customer? + are goods supplied?
    ├── No → skip
    └── Yes → call india_compliance._generate_e_waybill()
        ├── Success → e-Waybill generated
        └── Failure → warning only, DN still submits
```

### Files Involved

| File | Role |
|------|------|
| `overrides/gst_compliance.py` | Vehicle validation + e-Waybill generation |
| `update_vehicle.py` | Post-submit vehicle/transporter update |
| `sales_invoice_form.js` | "Update Vehicle/Transporter Info" button |

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-GST-001 | **HIGH** | ~~`validate_purchase_invoice_same_gstin()` never hooked~~ — Fixed: now hooked to Purchase Invoice validate |
| BNS-GST-002 | **CRITICAL** | `update_vehicle.py:_update_document()` uses `doc.save(ignore_permissions=True)` on a `@frappe.whitelist()` endpoint. ANY authenticated user can update ANY document's vehicle/transporter fields, regardless of role. No doctype restriction either — arbitrary doctypes can be targeted. |
| BNS-GST-003 | **MEDIUM** | E-Waybill generation failures are silently swallowed (`msgprint` warning only) — DN submits successfully but e-Waybill may be missing |
| BNS-GST-004 | **MEDIUM** | `_is_inter_state_transfer` compares full GSTIN strings — functionally correct but the standard approach is comparing first 2 characters (state code). Full comparison means same-state, different-business GSTINs are treated as inter-state. |
| BNS-GST-005 | **LOW** | `GSTComplianceError` custom exception defined but never used |
| BNS-GST-006 | **LOW** | `_are_goods_supplied` checks `item.qty != 0` without `flt()` — floating-point residuals like `1e-15` pass as "goods supplied" |

---

## 8. PAN Validation

### Purpose
Ensures PAN (Permanent Account Number) uniqueness across Customers and Suppliers on save.

### How It Works
```
Customer/Supplier saved → validate hook → validate_pan_uniqueness()
├── BNS Settings.enforce_pan_uniqueness enabled?
│   ├── No → skip
│   └── Yes → doc.pan field empty?
│       ├── Yes → skip
│       └── No → frappe.db.exists() for same PAN in same DocType
│           ├── No duplicate → proceed
│           └── Duplicate found → frappe.throw()
```

### Files Involved
- `overrides/pan_validation.py`
- `hooks.py` doc_events on Customer.validate and Supplier.validate

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-PAN-001 | **MEDIUM** | Cross-doctype check missing: Customer "A" with PAN "ABCDE1234F" and Supplier "B" with same PAN are NOT detected as duplicates. The docstring says "across all customers and suppliers" which is misleading. |
| BNS-PAN-002 | **MEDIUM** | No PAN format validation — malformed PANs (e.g., "12345", "HELLO") pass silently. Valid format: 5 uppercase letters + 4 digits + 1 uppercase letter. |
| BNS-PAN-003 | **MEDIUM** | Case-sensitive comparison: "abcde1234f" and "ABCDE1234F" treated as different PANs. |
| BNS-PAN-004 | **LOW** | `doc.pan` accessed without `.get()` — if `pan` custom field isn't installed, raises `AttributeError` instead of graceful message. |
| BNS-PAN-005 | **LOW** | `_find_existing_pan_document` swallows all exceptions and returns `None` — DB errors silently allow duplicate PANs. |

---

## 9. Item Validation

### Purpose
Enforces that non-stock, non-fixed-asset Items must have at least one expense account configured in Item Defaults.

### Files Involved
- `overrides/item_validation.py`
- `hooks.py` doc_events on Item.validate

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-ITEM-001 | **LOW** | Validation errors from `frappe.throw()` get logged via `logger.error()` before re-raise — pollutes error logs with normal validation failures |
| BNS-ITEM-002 | **LOW** | `ItemValidationError` defined but never raised |

---

## 10. Stock Update/Reference Validation

### Purpose
When Sales Invoice or Purchase Invoice has `update_stock = 0`, ensures all stock items have references to their source documents (DN for SI, PR for PI).

### How It Works
```
SI/PI saved → validate hook → validate_stock_update_or_reference()
├── BNS Settings.enforce_stock_update_or_reference enabled?
│   ├── No → skip
│   └── Yes → doc.update_stock == 1?
│       ├── Yes → skip (stock updated directly)
│       └── No → check each item row
│           ├── Is stock item? → must have delivery_note/purchase_receipt reference
│           └── Not stock item → skip
```

### Files Involved
- `overrides/stock_update_validation.py`
- `hooks.py` doc_events on Sales Invoice.validate and Purchase Invoice.validate

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-STOCK-001 | **MEDIUM** | Error messages don't identify WHICH items are missing references — user sees generic "items must reference" message without knowing which rows to fix |
| BNS-STOCK-002 | **MEDIUM** | N+1 query: `_is_stock_item(item.item_code)` called per item row, each making a separate DB query. Should batch-fetch with `frappe.get_all("Item", filters={"name": ["in", codes]})` |
| BNS-STOCK-003 | **LOW** | `_is_stock_item` swallows DB errors and returns `False` — items silently pass as "non-stock" on DB failure |

---

## 11. BOM Component Qty Variance

### Purpose
Enforces BOM discipline on Manufacture Stock Entries and allows configurable +/- percentage variance tolerance on BOM component quantities, instead of ERPNext's strict equality check.

### How It Works
```
Stock Entry saved (purpose = Manufacture) → BNSStockEntry.validate()
├── BNS Settings.enforce_bom_for_manufacture enabled?
│   ├── No → standard ERPNext validation only
│   └── Yes →
│       ├── bom_no empty? → frappe.throw("BOM Required")
│       ├── from_bom unchecked? → frappe.throw("From BOM Required")
│       └── Both set → validate BOM components exact match
│           ├── Extra items not in BOM? → frappe.throw("Invalid BOM Components")
│           └── Missing BOM items? → frappe.throw("Missing BOM Components")
│
├── validate_component_and_quantities() override:
│   ├── BNS Settings.enable_bns_variance_qty enabled?
│   │   ├── No → fall back to ERPNext strict equality
│   │   └── Yes → variance tolerance check:
│   │       ├── Per-item variance from BOM Item.bns_variance_qty
│   │       ├── Default variance from BNS Settings.bns_default_variance_qty
│   │       └── actual_qty within expected ± variance% → allow
│   │           └── outside range → frappe.throw("Quantity Outside Variance Tolerance")
```

**Client-side enforcement:**
When purpose is "Manufacture" and enforcement is on, `bom_no` and `from_bom` are dynamically set as mandatory via `doctype_item_grid_controls.js`. This triggers Frappe's built-in red field highlighting + "Missing Fields" dialog before save even reaches the server.

### Files Involved

| File | Role |
|------|------|
| `overrides/stock_entry_component_qty_variance.py` (336 lines) | `BNSStockEntry` class — BOM enforcement + variance tolerance |
| `hooks.py` `override_doctype_class` | Registers `BNSStockEntry` as Stock Entry controller |
| `public/js/doctype_item_grid_controls.js` | Client-side mandatory field toggle for `bom_no` / `from_bom` |
| `fixtures/custom_field.json` | `BOM Item.bns_variance_qty` (Percent field) |

### BNS Settings Fields
- `enforce_bom_for_manufacture` — master toggle for BOM + from_bom mandatory
- `enable_bns_variance_qty` — toggle for variance tolerance (vs strict equality)
- `bns_default_variance_qty` — default +/- % when per-item variance not set

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| ~~BNS-BOM-001~~ | ~~CRITICAL~~ | **FIXED** — `override_doctype_class` was commented out. Now active in hooks.py. |

---

## 12. Auto Payment Reconciliation

### Purpose
Automatically reconciles outstanding invoices with unallocated payments using FIFO (First-In-First-Out) matching — oldest invoices matched with oldest payments first.

### How It Works
```
Trigger: Scheduled job OR manual @frappe.whitelist() call
├── For each company:
│   ├── For each party_type (Customer, Supplier):
│   │   ├── Find parties with unreconciled balances
│   │   ├── For each party:
│   │   │   ├── Gather: unallocated payment entries + journal entries + DR/CR notes
│   │   │   ├── Gather: outstanding invoices
│   │   │   ├── Run FIFO allocation
│   │   │   ├── Apply: reconcile_against_document() for payments
│   │   │   └── Apply: reconcile_dr_cr_note() for returns
```

### Files Involved
- `auto_payment_reconcile.py` (687 lines)
- `BNS Settings` — toggle + configuration fields

### Settings
- `enable_auto_fifo_reconciliation` — master toggle
- `include_future_payments_in_reconciliation` — include post-dated payments
- `reconciliation_batch_size` — max allocations per party

### Bugs in This Area

| ID | Severity | Description |
|----|----------|-------------|
| BNS-REC-001 | **HIGH** | `reconcile_all_parties` is `@frappe.whitelist()` but has no permission check. Any authenticated user can trigger mass reconciliation across all parties. |
| BNS-REC-002 | **HIGH** | `allocate_fifo` mutates input invoice dicts in-place (`inv["outstanding_amount"] = inv_outstanding - allocated`). The `get_reconciliation_preview` function does `list(invoices)` which creates a new list but shares the same dict objects — preview mutates the same data that actual reconciliation would use. |
| BNS-REC-003 | **MEDIUM** | Hardcoded `limit=1000` on multiple queries — businesses with >1000 outstanding invoices or payments will have some silently skipped. |
| BNS-REC-004 | **LOW** | No idempotency guard per-party — `is_job_enqueued` check is per-company, not per-party. Overlapping scheduled runs could double-reconcile. |

---

## 13. Direct Print System

### Purpose
Overrides ERPNext's default Print button with BNS-configured print formats from BNS Settings, including invoice copy management for Sales Invoice.

### How It Works
```
Document opened → refresh event → direct_print.js
├── Load BNS Settings print format configuration
├── Replace default Print button with BNS version
├── For Sales Invoice:
│   ├── Show dropdown: Original for Recipient / Duplicate for Transporter / etc.
│   └── Set invoice_copy field (1/2/3/4/5)
├── Open PDF in new window → trigger print dialog
└── Handle Ctrl+P / Cmd+P keyboard shortcut
```

### DocTypes Affected
Sales Invoice, Sales Order, Delivery Note, Quotation, Purchase Order, Purchase Receipt, Purchase Invoice, Supplier Quotation, POS Invoice

### Files Involved
- `public/js/direct_print.js`
- `BNS Settings Print Format` child DocType — stores doctype→print format mapping

### System Impact
- Overrides the default Print button behavior on 9 doctypes
- Intercepts Ctrl+P / Cmd+P keyboard shortcut
- Modifies `invoice_copy` field on Sales Invoice (allow_on_submit)

---

## 14. UOM Restriction & Conversion Overlay

### Purpose
Restricts UOM selection on item rows to only the item's configured UOMs (stock_uom + uoms table), and adds visual conversion factor badges.

### How It Works
```
Item selected in grid → uom field query restricted to:
├── Item's stock_uom
└── Item's uoms child table entries

Visual overlay on qty field shows:
"40 KG per BAG" (with color-coded badge based on conversion factor)
```

### Files Involved
- `public/js/doctype_item_grid_controls.js` — UOM restriction + conversion overlay + BOM mandatory enforcement
- `public/js/item.js` — Validates `custom_print_uom` is in UOMs table

### DocTypes Affected
Stock Entry, Sales Invoice, Sales Order, Delivery Note, Purchase Invoice, Purchase Order, Purchase Receipt

### System Impact
- Overrides the UOM field query filter to restrict to allowed UOMs only
- Adds DOM-level visual badges to qty fields (CSS injection)
- **Stock Entry only:** Dynamically sets `bom_no` and `from_bom` as mandatory when purpose is "Manufacture" and BNS enforcement is on (triggers red field highlighting)

---

## 15. Custom Reports

### Report Inventory

| # | Report | Purpose | Key Tables | SQL Style |
|---|--------|---------|------------|-----------|
| 1 | Almonds Sorting Report | Repack yield tracking for almond sorting | SLE, Stock Entry | ORM (N+1) |
| 2 | Bank GL | Bank-focused General Ledger with party detection | GL Entry, Account | Raw SQL |
| 3 | Expected Sales Person Wise Summary | Sales performance with price list comparison | SI/SO/DN, Sales Team, Item Price | Raw SQL + frappe.qb |
| 4 | Internal Transfer Receive Mismatch | Finds DN→PR and SI→PI mismatches (**Prepared Report** — runs in background) | DN, PR, SI, PI + Items | Raw SQL (parameterized) |
| 5 | Negative Stock Resolution | Actionable suggestions for negative stock episodes | SLE, Item, BOM, Bin | ORM (N+1) |
| 6 | Outgoing Stock Audit | Detects negative stock + below-valuation sales | SI/PI/DN/PR, SLE | frappe.qb (cleanest) |
| 7 | Party GL | Party-focused GL with Party Link expansion | GL Entry, Party Link, PI, PE, JE | Raw SQL + frappe.qb |
| 8 | Pure Accounts Payable Summary | AP with AR netting via Party Link | AR/AP Report, Party Link | Inherited + frappe.qb |
| 9 | Pure Accounts Receivable Summary | AR with AP netting via Party Link | AR/AP Report, Party Link | Inherited + raw SQL |
| 10 | Stock Ledger Negative Episodes | Identifies periods of negative stock | SLE | Raw SQL |
| 11 | Unlinked Customer-Supplier by PAN | Finds PAN matches without Party Link | Customer, Supplier, Party Link | ORM |

### Report Bugs

| ID | Severity | Report | Description |
|----|----------|--------|-------------|
| BNS-RPT-001 | **HIGH** | Stock Ledger Negative Episodes | 9 `NOT IN` subqueries (one per DocType for cancelled status) are redundant — `sle.is_cancelled = 0` already handles this. Pure overhead on every execution. |
| BNS-RPT-002 | **HIGH** | Bank GL / Party GL | `select_fields` includes `remarks` unconditionally AND conditionally — duplicate column in SQL SELECT |
| BNS-RPT-003 | **HIGH** | Bank GL | `get_party_details_from_against()` makes 4 DB queries (Customer, Supplier, Shareholder, Employee) per GL entry without a party — catastrophic for large datasets |
| BNS-RPT-004 | **MEDIUM** | Pure AR Summary | Hardcoded fallback fiscal year `"2023-04-01", "2024-03-31"` — wrong for any other year |
| BNS-RPT-005 | **MEDIUM** | Pure AP/AR Summary | `frappe.get_all("Account", ...)` called inside the main loop for every party row — same result every iteration |
| BNS-RPT-006 | **MEDIUM** | Negative Stock Resolution | `if not min_qty` short-circuits on `0.0` — zero-balance episodes silently skipped. `partial_qty` can be `float('inf')` which displays as "inf" in report. |
| BNS-RPT-007 | **MEDIUM** | Almonds Sorting | `fields={"voucher_no"}` uses set literal instead of list. Also N+1 `frappe.get_doc` per Stock Entry. |
| BNS-RPT-008 | **LOW** | Unlinked Customer-Supplier | No XSS protection — party names with single quotes in onclick handlers will break JavaScript |
| BNS-RPT-009 | **LOW** | Stock Ledger Negative Episodes | `prev_balance = 0` for first entry assumes stock starts at zero — can cause false episode detection |
| BNS-RPT-010 | **LOW** | Internal Transfer Mismatch | Inconsistent tolerance: DN→PR uses 0.01 qty / 5.0 amount tolerance, SI→PI uses exact rounded comparison |

---

## 16. Print Formats

| Name | DocType | Key Features |
|------|---------|-------------|
| BNS SI Dynamic V1 | Sales Invoice | Jinja template with GST, payment terms, barcodes, builty, e-invoice/e-waybill |
| BNS SI -V2 (d1d2d3) | Sales Invoice | D1/D2/D3 tiered discount columns |
| BNS SO Dynamic V1 | Sales Order | Dynamic sales order layout |
| BNS PO Dynamic V1 | Purchase Order | Dynamic PO layout |
| BNS PO - V1 | Purchase Order | Full PO with bank details, signatory blocks |
| BNS DN Dynamic V1 | Delivery Note | Transport info, delivery terms |
| BNS Delivery Note - V1 | Delivery Note | Basic DN layout |
| BNS PI Dynamic V1 | Purchase Invoice | Dynamic PI layout |
| BNS QT Dynamic V1 | Quotation | Dynamic quotation layout |
| BNS POS SI 3Inch - V1 | POS Invoice | 3-inch thermal receipt format |
| BNS Quotation - V1 | Quotation | Standard quotation layout |

---

## 17. BNS Settings DocType

### Purpose
Central configuration hub for all BNS features. Single DocType (singleton) that controls every feature toggle.

### Key Fields / Feature Toggles

| Field | Type | Controls |
|-------|------|---------|
| `discount_type` | Select | "Single" or "Triple" discount mode |
| `restrict_submission` | Check | Submission restriction on/off |
| `submission_restriction_override_roles` | Table (Has Role) | Roles that bypass submission restriction |
| `enforce_pan_uniqueness` | Check | PAN uniqueness validation |
| `enforce_expense_account_for_non_stock_items` | Check | Item expense account validation |
| `enforce_stock_update_or_reference` | Check | SI/PI stock reference validation |
| `enable_per_warehouse_negative_stock_disallow` | Check | Per-warehouse negative stock |
| `block_purchase_invoice_same_gstin` | Check | Same-GSTIN PI block (DEAD — not hooked) |
| `enforce_bom_for_manufacture` | Check | BOM + From BOM mandatory for Manufacture Stock Entries |
| `enable_bns_variance_qty` | Check | BOM variance tolerance (±% instead of strict equality) |
| `bns_default_variance_qty` | Percent | Default variance % when per-item variance not set |
| `enable_custom_update_items_po_so` | Check | Custom Update Items on SO/PO |
| `enable_auto_fifo_reconciliation` | Check | Auto payment reconciliation |
| `include_future_payments_in_reconciliation` | Check | Include future payments in reconciliation |
| `reconciliation_batch_size` | Int | Max allocations per party |

*Note: `enable_internal_dn_ewaybill` (Auto e-Waybill for Internal Customer DN) moved to BNS Internal Transfer Settings.*

### Controller: `bns_settings.py`
- `on_update()` — calls `apply_settings()` when `discount_type` changes
- `apply_settings()` — `@frappe.whitelist()` — creates/updates Property Setters for discount fields across all item doctypes

---

## 18. Migration & Post-Install

### `after_migrate` Hook
Runs `migration.after_migrate()` which:
1. Adds "BNS Internally Transferred" to status options on DN, PR, SI, PI via Property Setter
2. Creates DocType Link records for SI↔PI and DN↔PR sidebar navigation
3. Removes old renamed field `is_bns_internal_customer` from Purchase Receipt
4. Migrates `enable_internal_dn_ewaybill` from BNS Settings to BNS Internal Transfer Settings (one-time)
5. Calls `BNS Settings.apply_settings()` to ensure discount configuration is current

### `after_app_init` Hook
Runs `warehouse_negative_stock.apply_patches()` which monkey-patches 3 ERPNext functions at startup.

### Migration Bugs

| ID | Severity | Description |
|----|----------|-------------|
| BNS-MIG-001 | **MEDIUM** | `after_migrate` swallows ALL exceptions — BNS setup can silently fail with only a log entry |
| BNS-MIG-002 | **LOW** | Per-item `frappe.db.commit()` calls — partial migration state if interrupted |
| BNS-MIG-003 | **LOW** | Property Setter fallback creates `"\nBNS Internally Transferred"` with leading newline if default options can't be read |

---

## 19. Schema Changes Reference

### Custom Fields (by DocType)

| DocType | Fields Added |
|---------|-------------|
| Company | `bns_previously_known_as`, `bns_company_cin`, `bns_msme_no`, `bns_msme_type` |
| Warehouse | `bns_disallow_negative_stock` |
| POS Profile | `naming_series` |
| Sales Order | `custom_remarks` |
| BOM Item | `bns_variance_qty` |
| Supplier | `is_bns_internal_supplier`, `bns_represents_company` |
| Customer | `is_bns_internal_customer`, `bns_represents_company` |
| Item | `custom_print_uom` |
| Sales Invoice Item | `custom_d1_`, `custom_d2_`, `custom_d3_` |
| Quotation Item | `custom_d1_`, `custom_d2_`, `custom_d3_` |
| Delivery Note Item | `custom_d1_`, `custom_d2_`, `custom_d3_` |
| Sales Order Item | `custom_d1_`, `custom_d2_`, `custom_d3_` |
| Delivery Note | `custom_builty_no`, `custom_destination`, `custom_doc_no`, `custom_terms_of_delivery`, `is_bns_internal_customer`, `bns_inter_company_reference` |
| Purchase Receipt | `bns_inter_company_reference`, `custom_destination`, `is_bns_internal_supplier` |
| Sales Invoice | `is_print_payment_terms`, `bns_show_item_code`, `is_print_gst_rate_per_row`, `is_print_gst_table`, `bns_show_item_barcode`, `custom_builty_no`, `custom_destination`, `custom_doc_no`, `custom_terms_of_delivery`, `is_bns_internal_customer`, `bns_inter_company_reference`, `is_bns_internal_check` |
| Purchase Invoice | `custom_destination`, `is_bns_internal_supplier`, `bns_inter_company_reference` |

### Property Setters (Fixture)

| DocType | Field | Property | Value |
|---------|-------|----------|-------|
| Sales Invoice | `update_billed_amount_in_delivery_note` | hidden | 1 |
| Sales Invoice | `update_billed_amount_in_delivery_note` | default | 0 |
| Sales Invoice | `update_billed_amount_in_sales_order` | hidden | 1 |
| Sales Invoice | `update_billed_amount_in_sales_order` | default | 0 |

### Dynamic Property Setters (via BNS Settings.apply_settings)

When `discount_type = "Triple"`:
- `custom_d1_`, `custom_d2_`, `custom_d3_` shown in grid, columns set
- `discount_percentage` hidden from grid
- `rate` set to read_only on ALL item doctypes (sales AND purchase)

### Client Scripts (Fixture)
- Lead list: `hide_name_column = true`
- Journal Entry list: `hide_name_column = true`
- Purchase Invoice list: `hide_name_column = true`

---

## 20. Master Bug Registry

### Severity: CRITICAL (3 active, 1 fixed)

| ID | Area | Description |
|----|------|-------------|
| BNS-GST-002 | Vehicle Update | `update_vehicle.py` uses `ignore_permissions=True` on `@frappe.whitelist()` — any user can modify any document |
| ~~BNS-UPD-001~~ | Update Items | **FIXED** — `item_code_changed` now defined in new-item path |
| ~~BNS-BOM-001~~ | ~~BOM Variance~~ | **FIXED** — `override_doctype_class` was commented out. Now active with BOM enforcement + `from_bom` mandatory + client-side red highlighting |
| BNS-INT-001 | Internal Transfer | ~~Unreachable dead code~~ — Fixed |

### Severity: HIGH (10)

| ID | Area | Description |
|----|------|-------------|
| BNS-INT-002 | Internal Transfer | Whitelisted functions lack permission checks — any user can modify submitted documents |
| BNS-INT-003 | Internal Transfer | `convert_*` functions modify multiple docs without transaction wrapping |
| BNS-GST-001 | GST Compliance | ~~Never hooked~~ — Fixed: hooked to PI validate |
| BNS-NEG-001 | Negative Stock | `sle.copy().update()` returns `None` — exceptions accumulate as `None` |
| BNS-NEG-002 | Negative Stock | `actual_qty` double-counted in patched validate_negative_stock |
| BNS-UPD-002 | Update Items | No database lock — concurrent calls cause race conditions |
| BNS-SUB-001 | Submission | Three categories share same toggle/roles — category system is non-functional |
| BNS-REC-001 | Reconciliation | `reconcile_all_parties` has no permission check |
| BNS-RPT-001 | Reports | 9 redundant `NOT IN` subqueries in Negative Episodes report |
| BNS-RPT-002 | Reports | Duplicate `remarks` column in Bank GL / Party GL |
| BNS-RPT-003 | Reports | Bank GL 4x DB queries per GL entry for party detection |

### Severity: MEDIUM (14)

| ID | Area | Description |
|----|------|-------------|
| BNS-INT-004 | Internal Transfer | SI→PR reference function is no-op |
| BNS-INT-005 | Internal Transfer | N+1 queries in bulk operations |
| BNS-INT-006 | Internal Transfer | DN cancellation validation swallows non-validation errors |
| BNS-DISC-001 | Discounts | `rate` set read-only on purchase documents too |
| BNS-PAN-001 | PAN | Cross-doctype duplicates not checked |
| BNS-PAN-002 | PAN | No format validation |
| BNS-PAN-003 | PAN | Case-sensitive comparison |
| BNS-STOCK-001 | Stock Validation | Error messages don't identify which items |
| BNS-STOCK-002 | Stock Validation | N+1 query per item row |
| BNS-NEG-003 | Negative Stock | Triple-redundant validation per transaction |
| BNS-REC-002 | Reconciliation | FIFO allocator mutates input dicts |
| BNS-REC-003 | Reconciliation | Hardcoded 1000 limit |
| BNS-RPT-004 | Reports | Hardcoded fallback fiscal year 2023-24 |
| BNS-RPT-005 | Reports | Account query inside loop |
| BNS-RPT-006 | Reports | Zero-balance episodes skipped + infinity display |
| BNS-MIG-001 | Migration | Exceptions swallowed silently |
| BNS-GST-003 | GST | E-Waybill failures silently swallowed |
| BNS-SUB-002 | Submission | Module-level translations |

### Severity: LOW (16)

| ID | Area | Description |
|----|------|-------------|
| BNS-INT-007 | Internal Transfer | Duplicate helper functions |
| BNS-INT-008 | Internal Transfer | Global `fetch_link_title` override |
| BNS-PAN-004 | PAN | `doc.pan` without `.get()` |
| BNS-PAN-005 | PAN | Exception swallowed in find |
| BNS-ITEM-001 | Item | Validation errors logged as errors |
| BNS-ITEM-002 | Item | Dead custom exception class |
| BNS-STOCK-003 | Stock Validation | `_is_stock_item` swallows DB errors |
| BNS-GST-005 | GST | Dead custom exception class |
| BNS-GST-006 | GST | Float comparison without flt() |
| BNS-SUB-003 | Submission | Dead custom exception class |
| BNS-SUB-004 | Submission | ~~Unused legacy wrappers~~ — Fixed: removed |
| BNS-NEG-004 | Negative Stock | `get_or_make_bin` side effect |
| BNS-REC-004 | Reconciliation | No per-party idempotency |
| BNS-RPT-007 | Reports | Set literal for fields |
| BNS-RPT-008 | Reports | XSS in unlinked report buttons |
| BNS-RPT-009 | Reports | False episode detection |
| BNS-RPT-010 | Reports | Inconsistent tolerances |
| BNS-DISC-002 | Discounts | Quotation lacks Update Items override |
| BNS-MIG-002 | Migration | Per-item commits |
| BNS-MIG-003 | Migration | Leading newline in status options |

---

## 21. File Reference Index

### Python Files — By Functional Area

| Area | File | Lines | Purpose |
|------|------|-------|---------|
| Settings | `doctype/bns_settings/bns_settings.py` | ~200 | Settings controller, `apply_settings()` |
| Settings | `doctype/bns_settings_print_format/bns_settings_print_format.py` | ~5 | Empty controller |
| Internal Transfer | `business_needed_solutions/utils.py` | 3,738 | Core transfer engine |
| Submission | `overrides/submission_restriction.py` | 267 | Submission permission checking |
| GST | `overrides/gst_compliance.py` | 459 | Vehicle validation, e-Waybill |
| GST | `update_vehicle.py` | 175 | Post-submit vehicle update |
| PAN | `overrides/pan_validation.py` | 145 | PAN uniqueness |
| Item | `overrides/item_validation.py` | 131 | Expense account validation |
| Stock | `overrides/stock_update_validation.py` | 197 | SI/PI reference validation |
| Stock | `overrides/warehouse_negative_stock.py` | 376 | Per-warehouse negative stock |
| BOM | `overrides/stock_entry_component_qty_variance.py` | 336 | BOM enforcement + variance tolerance (active via `override_doctype_class`) |
| Update Items | `overrides/update_items.py` | 635 | Custom SO/PO update items |
| Reconciliation | `auto_payment_reconcile.py` | 687 | FIFO auto-reconciliation |
| Migration | `migration.py` | 239 | Post-migration setup |
| Patch | `patch/stock_entry_patch.py` | ~50 | Stock entry data migration |
| Test | `test_submission_restriction.py` | 271 | Manual test script |

### JavaScript Files — By Functionality

| File | DocType(s) | Loaded Via | Purpose |
|------|-----------|-----------|---------|
| `sales_invoice_form.js` | Sales Invoice | `app_include_js` | BNS internal buttons, link/unlink, vehicle update |
| `purchase_invoice_form.js` | Purchase Invoice | `app_include_js` | BNS internal buttons, link/unlink, fetch_link_title override |
| `purchase_receipt_form.js` | Purchase Receipt | `app_include_js` + `doctype_js` | BNS internal buttons, link/unlink |
| `delivery_note.js` | Delivery Note | `app_include_js` + `doctype_js` | BNS internal buttons, link/unlink, create PR |
| `discount_manipulation_by_type.js` | SI, SO, DN, Quotation | `app_include_js` | Triple discount cascade logic |
| `direct_print.js` | 9 doctypes | `app_include_js` | Print button override |
| `item.js` | Item | `app_include_js` | Print UOM validation |
| `doctype_item_grid_controls.js` | 7 doctypes + Stock Entry BOM | `doctype_js` | UOM restriction + conversion overlay + BOM mandatory enforcement |
| `update_items_override.js` | Sales Order, Purchase Order | `doctype_js` | Custom Update Items dialog |
| `warehouse.js` | Warehouse | `doctype_js` | Negative stock field visibility |
| `sales_invoice_list.js` | Sales Invoice | `doctype_list_js` | BNS status indicator |
| `purchase_invoice_list.js` | Purchase Invoice | `doctype_list_js` | BNS status indicator |
| `delivery_note_list.js` | Delivery Note | `doctype_list_js` | BNS status indicator |
| `purchase_receipt_list.js` | Purchase Receipt | `doctype_list_js` | BNS status indicator |

### Configuration Files

| File | Purpose |
|------|---------|
| `hooks.py` | Master hook registration |
| `modules.txt` | Module list ("Business Needed Solutions") |
| `patches.txt` | Patch registry |
| `fixtures/custom_field.json` | ~50 custom fields on 13 doctypes |
| `fixtures/property_setter.json` | 4 property setters (SI billed amount) |
| `fixtures/client_script.json` | 3 list view column-hiding scripts |
| `fixtures/terms_and_conditions.json` | "General" terms template |
| `fixtures/print_format.json` | Print format definitions |

---

*End of Technical Handbook*
