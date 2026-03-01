# Business Needed Solutions – Technical Handbook

**App:** business_needed_solutions  
**Last updated:** 2026  
**Purpose:** Technical reference for developers – what exists, why, impacted modules, and migration implications.

---

## 1. App Overview

BNS extends ERPNext with:

- Document submission controls (role-based)
- PAN uniqueness validation (Customer/Supplier)
- Stock update vs. reference validation (SI/PI)
- Per-warehouse negative stock restriction
- BNS internal transfer accounting (DN↔PR, SI↔PI)
- GST compliance (same-GSTIN PI block, internal DN e-Waybill)
- Address preferred-flag suppression
- Item expense account validation (non-stock)
- Stock Entry component qty variance
- Custom reports (Party GL, Bank GL, Outgoing Stock Audit, etc.)

---

## 2. Module Structure

| Path | Purpose |
|------|---------|
| `business_needed_solutions/` | Core app – overrides, utils, doctypes, reports |
| `bns_branch_accounting/` | Internal transfer logic – DN/PR/SI/PI linking, status updates, accounting |

---

## 3. Key Modules and Impact

### 3.1 Submission Restriction (`overrides/submission_restriction.py`)

- **What:** Role-based submission control for stock, transaction, and order doctypes.
- **Why:** Allow draft-only for most users; only override roles can submit.
- **Impacted:** Stock Entry, Stock Reconciliation, DN, PR, SI, PI, JE, PE, SO, PO, Payment Request.
- **Settings:** BNS Settings → `restrict_submission`, `submission_restriction_override_roles`.

### 3.2 BNS Branch Accounting (`bns_branch_accounting/utils.py`)

- **What:** Internal transfer flow – DN→PR, SI→PI, SI→PR; status updates; convert/link/unlink. Bulk linkage verification and repost.
- **Why:** Support inter-branch transfers with `is_bns_internal_customer` / `is_bns_internal_supplier`.
- **Impacted:** DN, PR, SI, PI (client JS + doc_events).
- **Settings:** BNS Branch Accounting Settings – `stock_in_transit_account`, `internal_sales_transfer_account`, `internal_purchase_transfer_account`, `internal_branch_debtor_account`, `internal_branch_creditor_account`, `enable_internal_dn_ewaybill`, `internal_validation_cutoff_date`.
- **PR/PI standard fields:** BNS does **not** set standard ERPNext fields `represents_company` or `inter_company_reference` / `inter_company_invoice_reference` on Purchase Receipt or Purchase Invoice. Only BNS fields are used: `bns_inter_company_reference`, `supplier_delivery_note`, `is_bns_internal_supplier`, etc. Representing-company logic uses Customer/Supplier `bns_represents_company` (with fallback read of `represents_company` for validation only).

### 3.2a Bulk Linkage Verification & Repost (`bns_branch_accounting/utils.py`)

- **What:** `verify_and_repost_internal_transfers()` – scans all internal transfer chains after a cutoff date and verifies 100% linkage at both doc-level and item-level. Five chain types are detected:
  1. **DN→PR** (same GSTIN): `bns_inter_company_reference` + `delivery_note_item`
  2. **SI→PI** (different GSTIN, direct): `bns_inter_company_reference` + `sales_invoice_item`
  3. **SI→PR→PI** (different GSTIN, via PR): SI→PR via `bns_inter_company_reference`, PR→PI via `purchase_receipt`/`purchase_receipt_item`
  4. **DN→SI→PI** (different GSTIN, DN-originated): DN→SI via `delivery_note`/`dn_detail`, SI→PI via `bns_inter_company_reference`
  5. **DN→SI→PR→PI** (different GSTIN, full chain): DN→SI→PR→PI with item-level tracing throughout
- **Categorization:** Each chain is categorized as `fully_linked`, `partially_linked`, or `unlinked`.
- **Repost:** Fully-linked chains are reposted in dependency order (upstream first) using `create_repost_item_valuation_entry`.
- **Background:** `enqueue_verify_and_repost_internal_transfers()` wraps the function in `frappe.enqueue` for large datasets.
- **Fix Partial DN→PR:** Optional `fix_partial_dn_pr` flag. When enabled, iterates partially linked DN→PR chains and attempts to set `bns_inter_company_reference` bidirectionally plus status/flags. **Skips** any pair where:
  - Item code mismatch (items in DN not in PR or vice-versa)
  - Per-unit rate mismatch
  - Taxable amount mismatch
  - Location/warehouse mismatch (DN `target_warehouse` vs PR `warehouse`)
  Fixed chains are promoted to `fully_linked` and become eligible for repost in the same run. Results include per-pair action (fixed/skipped/error) with skip reasons.
- **UI:** "Verify & Repost Internal Transfers" button in BNS Branch Accounting Settings, with preview (Verify) and execute (Run) modes. Includes "Fix Partial DN→PR" checkbox. Download CSV report of partial/unlinked/fix results.

### 3.2b-1 Bulk Convert DN→PR Reference Fix (2026)

- **What:** `convert_delivery_note_to_bns_internal()` now auto-discovers the matching PR via `_get_submitted_prs_for_dn()` when no PR is explicitly provided. Previously, calling with `purchase_receipt=None` (as `bulk_convert_to_bns_internal()` does) would set status/flags on the DN but skip setting `bns_inter_company_reference`, leaving the DN→PR chain partially linked.
- **Root cause:** `bulk_convert_to_bns_internal()` processed DNs with `purchase_receipt=None`, skipping the linking block. The "already converted" early-return also didn't check for missing reference, so re-running bulk convert wouldn't fix existing gaps.
- **Changes:**
  1. `convert_delivery_note_to_bns_internal()`: Auto-discovers PR when none provided; "already converted" check now requires `bns_inter_company_reference` to be set.
  2. `convert_delivery_note_to_bns_internal()`: PR validation relaxed — accepts PR found via `bns_inter_company_reference` in addition to `supplier_delivery_note`.
  3. `bulk_convert_to_bns_internal()`: DN conversion condition now includes missing `bns_inter_company_reference` check; fetches field in query.
  4. `get_bulk_conversion_preview()`: DN count condition aligned with convert logic.
- **Migration:** Re-running "Bulk Convert to BNS Internal" will retroactively fix all DNs with missing `bns_inter_company_reference`.
- **Impacted:** All internal transfer document types (DN, PR, SI, PI). Creates Repost Item Valuation entries.

### 3.3 GST Compliance (`overrides/gst_compliance.py`)

- **What:**
  1. Block PI when Supplier GSTIN = Company GSTIN.
  2. Mandate Vehicle No or GST Transporter ID for internal DN (intra-state, above e-Waybill threshold).
  3. Auto-generate e-Waybill for internal DN when same GSTIN.
- **Why:** GST rules for self-invoicing and internal transfers.
- **Impacted:** PI (validate), DN (on_submit).
- **Settings:** BNS Settings → `block_purchase_invoice_same_gstin`; BNS Branch Accounting Settings → `enable_internal_dn_ewaybill`.
- **Dependencies:** India Compliance (e-Waybill API, GSTIN from addresses).

### 3.4 Stock Update Validation (`overrides/stock_update_validation.py`)

- **What:** When `update_stock` is off on SI/PI, all stock items must reference DN/PR.
- **Why:** Enforce traceability when stock is not updated from the invoice.
- **Impacted:** SI, PI (validate).
- **Settings:** BNS Settings → `enforce_stock_update_or_reference`.

### 3.5 Warehouse Negative Stock (`overrides/warehouse_negative_stock.py`)

- **What:** Per-warehouse `bns_disallow_negative_stock`; blocks SLE when enabled.
- **Why:** Allow negative stock in some warehouses, disallow in others.
- **Impacted:** Stock Ledger Entry (validate), Warehouse doctype (custom field).
- **Settings:** BNS Settings → `enable_per_warehouse_negative_stock_disallow`.

### 3.6 PAN Validation (`overrides/pan_validation.py`)

- **What:** Enforce unique PAN across Customer and Supplier.
- **Why:** Avoid duplicate party records by PAN.
- **Impacted:** Customer, Supplier (validate).
- **Settings:** BNS Settings → `enforce_pan_uniqueness`.

### 3.7 Address Preferred Flags (`overrides/address_preferred_flags.py`)

- **What:** Suppress preferred billing/shipping when saving Address.
- **Why:** Control which addresses are auto-selected.
- **Impacted:** Address (before_save).
- **Settings:** BNS Settings → `suppress_preferred_billing_shipping_address`.

### 3.8 Item Validation (`overrides/item_validation.py`)

- **What:** Non-stock items (except fixed assets) must have expense account.
- **Impacted:** Item (validate).
- **Settings:** BNS Settings → `enforce_expense_account_for_non_stock_items`.

### 3.9 Stock Entry Override (`overrides/stock_entry_component_qty_variance.py`)

- **What:** BNS variance qty for manufacturing; component qty variance control.
- **Impacted:** Stock Entry (override_doctype_class).
- **Settings:** BNS Settings → `enable_bns_variance_qty`, `bns_default_variance_qty`.

### 3.10 Billing Location → Customer Address (`overrides/billing_location.py`)

- **What:** When `billing_location` is set and customer is BNS internal, server sets `customer_address`, `address_display`, `billing_address_gstin`, `gst_category`, `place_of_supply` from Location's `linked_address` on validate. `customer_address` is read-only when both `billing_location` and `is_bns_internal_customer` are set.
- **Why:** Mirrors location_based_series pattern for company address; ensures BNS internal customers use location-driven billing address and GST details.
- **Impacted:** Sales Invoice, Delivery Note, Sales Order (validate). For outside customers, `billing_location` is left as-is and `customer_address` remains editable.
- **Dependencies:** `gst_compliance._is_bns_internal_customer`; optional `india_compliance.gst_india.utils.get_place_of_supply` for place_of_supply.

---

## 4. Doc Events Summary (hooks.py)

| DocType | Event | Handler |
|---------|-------|---------|
| Address | before_save | enforce_suppress_preferred_address |
| Customer, Supplier | validate | validate_pan_uniqueness |
| Item | validate | validate_expense_account_for_non_stock_items |
| Stock Ledger Entry | validate | validate_sle_warehouse_negative_stock |
| Stock Entry | on_submit | validate_submission_permission |
| Delivery Note | validate, on_submit, on_cancel | BNS internal + GST compliance |
| Purchase Receipt | on_submit | submission + BNS internal |
| Stock Reconciliation | on_submit | validate_submission_permission |
| Sales Invoice | validate, on_submit | stock update + BNS internal |
| Purchase Invoice | validate, on_submit | stock update + same GSTIN + BNS internal |
| Journal Entry, Payment Entry, SO, PO, Payment Request | on_submit | validate_submission_permission |

---

## 5. Settings Doctypes

| DocType | Purpose |
|---------|---------|
| BNS Settings | Global app settings (PAN, GST, stock, submission, print, etc.) |
| BNS Branch Accounting Settings | Internal transfer accounts, internal DN e-Waybill |

### 3.11 Internal Transfer Receive Mismatch Report (`bns_branch_accounting/report/`)

- **What:** Prepared Script Report identifying DN/SI with internal customers missing or mismatched PR/PI. Enhanced with:
  - **Transfer Chain** column: identifies the chain type (DN→PR, SI→PI, SI→PR→PI, DN→SI→PI, DN→SI→PR→PI)
  - **Source Dest. Warehouse** / **Purchase Warehouse** columns: shows target warehouse from DN/SI and actual warehouse on PR/PI
  - **Location Mismatch** column: flags when destination warehouse differs from purchase-side warehouse
  - **Item Mismatch** column: flags when item codes differ between linked source and destination items
  - **SI→PR chain detection**: reports mismatches across SI→PR→PI chains in addition to direct SI→PI
- **Why:** Provides comprehensive visibility into internal transfer linkage health, warehouse routing accuracy, and item-level integrity.
- **Impacted:** Report output only (read-only). No data modifications.
- **Cutoff:** Respects `internal_validation_cutoff_date` from BNS Branch Accounting Settings as default `from_date`.

---

## 6. Migration Implications

- **BNS Branch Accounting:** Uses `bns_inter_company_reference`, `bns_reference_dn`, `bns_reference_si`, etc. Custom fields are in fixtures.
- **Patch:** `migrate_internal_dn_ewaybill_to_branch_accounting.py` – copies `enable_internal_dn_ewaybill` from BNS Settings to BNS Branch Accounting Settings before field removal.
- **Warehouse negative stock:** Patches applied via `after_app_init` in hooks.

---

## 7. Removed Logic

- **test_bns_settings.py:** Tests for `warehouse_validation`, `auto_transit_validation`, `warehouse_filtering` removed — those modules never existed. Replaced with minimal `test_bns_settings_loads` test.
- **BNS Settings:** `enable_internal_dn_ewaybill` field removed from field_order — migrated to BNS Branch Accounting Settings.
- **PR/PI standard inter-company fields:** BNS no longer sets `represents_company` or `inter_company_reference` (PR) / `inter_company_invoice_reference` (PI) on Purchase Receipt or Purchase Invoice. All internal-transfer linking uses BNS fields only (`bns_inter_company_reference`, `supplier_delivery_note`, etc.). Removed from: DN→PR mapping, PR status update on_submit, PI status update on_submit.
- **FIFO auto payment reconciliation system:** Removed end-to-end from BNS Settings and backend service. Deleted `auto_payment_reconcile.py`, removed manual "Run FIFO Reconciliation" action from `doctype/bns_settings/bns_settings.js`, and removed reconciliation fields from `doctype/bns_settings/bns_settings.json` (`enable_auto_fifo_reconciliation`, `include_future_payments_in_reconciliation`, `reconciliation_batch_size`, `last_reconciliation_run`, `last_reconciliation_status`).

---

## 8. Code Audit Findings (2026)

| Issue | Severity | Location | Resolution |
|-------|----------|----------|------------|
| Orphan field_order reference | **Bug** | BNS Settings JSON had `enable_internal_dn_ewaybill` in field_order but no field definition | Removed from field_order |
| Dead test imports | **Bug** | test_bns_settings.py imported non-existent modules | Replaced with minimal passing test |
| Duplicate `is_bns_internal_customer` logic | Refactor | gst_compliance._is_bns_internal_customer + ~20 inline checks in bns_branch_accounting/utils.py | Consider adding `is_bns_internal_customer(doc)` helper in bns_branch_accounting, import from gst_compliance |
| Legacy wrappers unused | Dead code | submission_restriction: validate_stock_modification, validate_transaction_modification, validate_order_modification | Kept for backward compatibility; not in hooks |

---

## 9. Dependencies

- **ERPNext:** Required (stock, accounts, sales, purchase).
- **India Compliance:** Optional but recommended for GST; used for e-Waybill API and GSTIN resolution.

---

## 10. Fixtures

- Custom Field, Property Setter (modules: Business Needed Solutions, BNS Branch Accounting)
- Terms and Conditions (General)

---

## 11. Post-Change Commands

After changes to fields, JS, Vue, or assets:

```bash
bench clear-cache && bench migrate && bench build --app business_needed_solutions && bench clear-cache
```
