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

- **What:** Internal transfer flow – DN→PR, SI→PI, SI→PR; status updates; convert/link/unlink.
- **Why:** Support inter-branch transfers with `is_bns_internal_customer` / `is_bns_internal_supplier`.
- **Impacted:** DN, PR, SI, PI (client JS + doc_events).
- **Settings:** BNS Branch Accounting Settings – `stock_in_transit_account`, `internal_transfer_account`, `internal_branch_debtor_account`, `enable_internal_dn_ewaybill`.

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
| BNS Settings | Global app settings (PAN, GST, stock, submission, print, reconciliation, etc.) |
| BNS Branch Accounting Settings | Internal transfer accounts, internal DN e-Waybill |

---

## 6. Migration Implications

- **BNS Branch Accounting:** Uses `bns_inter_company_reference`, `bns_reference_dn`, `bns_reference_si`, etc. Custom fields are in fixtures.
- **Patch:** `migrate_internal_dn_ewaybill_to_branch_accounting.py` – copies `enable_internal_dn_ewaybill` from BNS Settings to BNS Branch Accounting Settings before field removal.
- **Warehouse negative stock:** Patches applied via `after_app_init` in hooks.

---

## 7. Removed Logic

- **test_bns_settings.py:** Tests for `warehouse_validation`, `auto_transit_validation`, `warehouse_filtering` removed — those modules never existed. Replaced with minimal `test_bns_settings_loads` test.
- **BNS Settings:** `enable_internal_dn_ewaybill` field removed from field_order — migrated to BNS Branch Accounting Settings.

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
