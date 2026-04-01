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

- **What:** Internal transfer flow – DN→PR, SI→PI, SI→PR; status updates; convert/link/unlink. Bulk linkage verification and repost. Credit note → debit note conversion (SI return → PI return). Full ERPNext v15+ Serial and Batch Bundle (SBB) support for all internal transfer mappings.
- **Serial and Batch Bundle Support:** All three mapping flows (DN→PR, SI→PI, SI→PR) use `_duplicate_serial_and_batch_bundle()`, a shared helper that clones the source SBB using `SerialBatchCreation.duplicate_package()`. Legacy `serial_no`/`batch_no` fields are removed from `field_map` and added to `field_no_map` to prevent raw copying; the helper handles three scenarios: (1) SBB present → duplicate, (2) legacy fields present → copy with `use_serial_batch_fields=1`, (3) neither → no-op. Batch parity is enforced in `_enforce_one_to_one_item_and_amount_parity()` via `_validate_batch_serial_parity()`.
- **Why:** Support inter-branch transfers with `is_bns_internal_customer` / `is_bns_internal_supplier`.
- **Impacted:** DN, PR, SI, PI (client JS + doc_events).
- **Credit Note → Debit Note:** SI credit notes (is_return=1) can be converted to PI debit notes via `make_bns_internal_purchase_invoice`. The function detects `is_return` on the source SI, sets `is_return=1` on the target PI, and resolves `return_against` by looking up the original PI linked to `si.return_against`. Item mapping uses `qty != 0` to handle negative quantities.
- **Credit Note / Debit Note GL Rewrite:** `_rewrite_bns_internal_si_gl_entries` and `_rewrite_bns_internal_pi_gl_entries` are return-aware. When `is_return=1`, amounts are `abs()`-normalized and debit/credit sides are swapped: SI credit note puts Internal Branch Debtor on credit side and Internal Sales Transfer on debit side; PI debit note puts Internal Branch Creditor on debit side and Internal Purchase Transfer on credit side. Tax legs and stock valuation legs are similarly reversed.
- **Settings:** BNS Branch Accounting Settings – `stock_in_transit_account`, `internal_sales_transfer_account`, `internal_purchase_transfer_account`, `internal_branch_debtor_account`, `internal_branch_creditor_account`, `enable_internal_dn_ewaybill`, `internal_transfer_cutoff_fy` (Link to Fiscal Year), `accounting_rewrite_cutoff_fy` (Link to Fiscal Year). Old `internal_validation_cutoff_date` is hidden/deprecated.
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
- **Return Exclusion:** SI query in `verify_and_repost_internal_transfers` filters out `is_return = 1` (credit notes). Credit note chains are not eligible for bulk chain-level repost since they operate outside the standard forward-flow chain model.

### 3.2b-1 Bulk Convert DN→PR Reference Fix (2026)

- **What:** `convert_delivery_note_to_bns_internal()` now auto-discovers the matching PR via `_get_submitted_prs_for_dn()` when no PR is explicitly provided. Previously, calling with `purchase_receipt=None` (as `bulk_convert_to_bns_internal()` does) would set status/flags on the DN but skip setting `bns_inter_company_reference`, leaving the DN→PR chain partially linked.
- **Root cause:** `bulk_convert_to_bns_internal()` processed DNs with `purchase_receipt=None`, skipping the linking block. The "already converted" early-return also didn't check for missing reference, so re-running bulk convert wouldn't fix existing gaps.
- **Changes:**
  1. `convert_delivery_note_to_bns_internal()`: Auto-discovers PR when none provided; "already converted" check now requires `bns_inter_company_reference` to be set.
  2. `convert_delivery_note_to_bns_internal()`: PR validation relaxed — accepts PR found via `bns_inter_company_reference` in addition to `supplier_delivery_note`.
  3. `bulk_convert_to_bns_internal()`: DN conversion condition now includes missing `bns_inter_company_reference` check; fetches field in query.
  4. `get_bulk_conversion_preview()`: DN count condition aligned with convert logic.
- **Migration:** Re-running "Bulk Convert to BNS Internal" will retroactively fix all DNs with missing `bns_inter_company_reference`.

### 3.2b-2 Amended DN Item Re-mapping & Zero-Rate GL Fix (2026)

- **What:** Two fixes for amended/zero-rate internal DNs:
  1. **Stale `delivery_note_item` references:** When a DN is amended, PR items still reference old DN item IDs. `_verify_dn_pr_item_linkage` now detects stale refs (IDs not in current DN) and falls back to aggregate matching by `item_code` + `qty`. New `_remap_pr_delivery_note_items()` function re-maps PR items to current DN item IDs by matching `item_code` + `qty` + `rate`. Called automatically in `link_dn_pr`, `_fix_dn_pr_link`, `convert_delivery_note_to_bns_internal`, and `convert_purchase_receipt_to_bns_internal`.
  2. **GL rewrite blocked by zero-rate items:** `_resolve_dn_transfer_amount` and `_resolve_pr_transfer_amount` treated zero-rate items (samples, free goods) as "missing transfer rate" and blocked the entire GL rewrite. Now items with `rate <= 0` are silently skipped — only items with positive rate but zero computed amount are flagged as missing.
- **Root cause:** Amendment creates new item row IDs; ERPNext doesn't update `delivery_note_item` on existing PRs. Zero-rate items are legitimate (samples) but the `missing` flag was overly strict.
- **Impacted:** All DN→PR linking paths, GL rewrite for DN and PR.
- **Impacted:** All internal transfer document types (DN, PR, SI, PI). Creates Repost Item Valuation entries.

### 3.2b-3 Internal GL Precision Round-Off (2026)

- **What:** BNS internal GL rewrite functions (DN, PR, PI, SI) now allow small debit/credit residuals to pass through to ERPNext's standard `process_debit_credit_difference()` safety net, which books them to the Company round-off account via `make_round_off_gle()`.
- **Why:** Keeps ERP books clean; tiny precision residues (e.g. 0.0001) follow Company round-off policy rather than distorting internal transfer accounts or causing the BNS rewrite to be abandoned.
- **How:** Raised the BNS balance-check threshold from `0.01` to `0.5` (matching ERPNext's `get_debit_credit_allowance` for non-JE/PE vouchers). Removed the PI-only hack that absorbed residue into `internal_purchase_transfer_account`. ERPNext's `process_debit_credit_difference()` in `general_ledger.py` runs on every GL map in `save_entries()` and appends a round-off GL row when needed — it never modifies or removes BNS-rewritten entries.
- **Impacted:** All four BNS internal GL rewrite functions: DN, PR, PI, SI.
- **Migration:** None. Existing vouchers remain as-is. New or reposted vouchers with tiny residuals will have round-off posted by ERPNext's standard path.
- **Fail-safe:** Mismatches `> 0.5` still log an error and fall back to original ERPNext GL entries.

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

- **What:** When `update_stock` is off on SI/PI, all stock items must reference DN/PR. Includes batch/serial reference continuity: invoice item batch_no must match the referenced source DN/PR item batch_no to prevent silent batch mismatches.
- **Why:** Enforce traceability when stock is not updated from the invoice.
- **Impacted:** SI, PI (validate).
- **Settings:** BNS Settings → `enforce_stock_update_or_reference`.

### 3.5 Warehouse Negative Stock (`overrides/warehouse_negative_stock.py`)

- **What:** Per-warehouse `bns_disallow_negative_stock`; blocks SLE when enabled. Supports ERPNext v15+ Serial and Batch Bundle (SBB): when legacy `batch_no` is empty but `serial_and_batch_bundle` is present, batch numbers are extracted from the SBB and each is validated individually for negative stock.
- **Why:** Allow negative stock in some warehouses, disallow in others — including batch-level negative stock detection.
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

- **What:** BNS variance qty for manufacturing; component qty variance control. Batch/serial safe: set-based item_code matching correctly handles batch-tracked items with the same item_code in multiple rows (different batches/SBBs).
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

### 3.11 Internal Transfer Accounting Audit Report (`bns_branch_accounting/report/`)

- **What:** Prepared Script Report that validates GL Entry and Stock Ledger Entry correctness for all BNS internal DN, SI, PR, and PI against the expected BNS branch-accounting patterns. For each submitted internal document, it compares actual GL/SLE rows with the expected pattern and flags deviations. Includes bulk repost actions for fixing flagged documents.
- **GL Checks:**
  - DN (Same GSTIN): expects Internal Branch Debtor Dr, Stock In Transit Dr, Internal Sales Transfer Cr, Stock Cr.
  - DN (Different GSTIN): expects Stock In Transit Dr, Stock Cr.
  - PR (DN-linked Same GSTIN): expects Internal Purchase Transfer Dr, Stock Dr, Internal Branch Creditor Cr, Stock In Transit Cr.
  - PR (SI-linked): expects Stock Dr, Stock In Transit Cr.
  - SI (Different GSTIN): expects Internal Branch Debtor Dr, Internal Sales Transfer Cr, tax legs. Optionally stock legs if update_stock.
  - SI (Credit Note): expects Internal Branch Debtor Cr, Internal Sales Transfer Dr, reversed tax legs. Optionally reversed stock legs if update_stock.
  - PI (SI-linked): expects Internal Branch Creditor Cr, Internal Purchase Transfer Dr, tax legs. Optionally stock legs if update_stock and no PR-linked rows.
  - PI (Debit Note): expects Internal Branch Creditor Dr, Internal Purchase Transfer Cr, reversed tax legs. Optionally reversed stock legs if update_stock and no PR-linked rows.
- **Zero-Amount Skip:** Documents where both `base_grand_total` and `base_net_total` are zero (absolute) are skipped entirely -- no GL is expected for zero-value transactions (e.g., zero-rate credit notes/debit notes).
- **SLE Checks:** For PR/PI with `bns_transfer_rate`, validates `incoming_rate` against expected transfer rate. Does NOT check `stock_value_difference` since SVD is computed by ERPNext's valuation engine and is affected by factors outside BNS control (negative stock, moving average revaluation).
- **Cross-Document Consistency Checks** (`_audit_cross_document_consistency`):
  - **Orphaned GL:** PR/PI that has BNS internal GL but references a cancelled or missing source DN/SI. Deviation type: "Orphaned GL".
  - **Flag Mismatch:** PR/PI has BNS internal GL but the referenced source DN/SI does NOT have BNS internal GL (e.g., customer `is_bns_internal_customer=0`). Deviation type: "Flag Mismatch".
  - **Missing Counter-Document:** DN/SI has BNS internal GL but no submitted counter-document exists. For same-GSTIN DNs, checks for a submitted PR. For different-GSTIN DNs, verifies the DN→SI→PI chain (linked SI via items, then PI via `bns_inter_company_reference` or `bill_no`). For SIs, checks for a submitted PI. Deviation type: "No Counter-Document".
  - Classification functions (`_classify_pr`, `_classify_pi`) now check `docstatus=1` on referenced source documents to avoid classifying against cancelled docs.
- **Bulk Repost Actions:**
  - "Repost SLE" (Actions menu): Enqueues `create_repost_item_valuation_entry` for all report rows with SLE deviations. Runs as background job via `frappe.enqueue`.
  - "Repost GL" (Actions menu): Enqueues `bns_force_rebuild_gl_for_voucher` for all report rows with GL deviations. Runs as background job via `frappe.enqueue`.
  - Both actions validate Accounts Manager / System Manager role before executing.
- **Columns:** Posting Date, Document Type, Document, Internal Scope, Deviation Type, Expected Accounts, Unexpected Accounts, Missing Accounts, SLE Issue, Details.
- **Filters:** Company, From Date, To Date, Document Type (optional: DN/SI/PR/PI).
- **Why:** Provides accounting integrity audit for internal transfers — identifies documents where the GL rewrite was skipped, partially applied, or overwritten by repost. Enables targeted bulk correction.
- **Impacted:** Report output (read-only for display). Bulk repost actions create Repost Item Valuation entries or rebuild GL entries for flagged documents.
- **Cutoff:** Respects `internal_transfer_cutoff_fy` from BNS Branch Accounting Settings (resolved to `year_start_date`) as default `from_date`.

### 3.12 Internal Transfer Receive Mismatch Report (`bns_branch_accounting/report/`)

- **What:** Prepared Script Report identifying DN/SI with internal customers missing or mismatched PR/PI. Enhanced with:
  - **Transfer Chain** column: identifies the chain type (DN→PR, SI→PI, SI→PR→PI, DN→SI→PI, DN→SI→PR→PI)
  - **Source Dest. Warehouse** / **Purchase Warehouse** columns: shows target warehouse from DN/SI and actual warehouse on PR/PI
  - **Location Mismatch** column: flags when destination warehouse differs from purchase-side warehouse
  - **Item Mismatch** column: flags when item codes differ between linked source and destination items
  - **SI→PR chain detection**: reports mismatches across SI→PR→PI chains in addition to direct SI→PI
- **Why:** Provides comprehensive visibility into internal transfer linkage health, warehouse routing accuracy, and item-level integrity.
- **Impacted:** Report output only (read-only). No data modifications.
- **Cutoff:** Respects `internal_transfer_cutoff_fy` from BNS Branch Accounting Settings (resolved to `year_start_date`) as default `from_date`.

### 3.13 Batch/Serial Number Support in Reports (2026)

- **Stock Ledger Negative Episodes:** When `Segregate Serial / Batch Bundle` filter is enabled, episodes are detected at batch level — grouping by `(item_code, warehouse, batch_no)` instead of `(item_code, warehouse)`. Batch No column appears in output when enabled.
- **Outgoing Stock Audit:** SLE query now selects `batch_no`; Batch No column added to report output, populated from SLE data.
- **Negative Stock Resolution Report:** `get_bin_qty()` and `find_alternative_warehouse()` accept optional `batch_no` parameter — queries SLE aggregates instead of Bin when batch is specified (Bin does not track batch-level balances).
- **Almonds Sorting Report:** SLE lookup falls back to Serial and Batch Bundle entries when legacy `batch_no` is empty. Item batch resolution uses `_get_item_batch_no()` helper that checks legacy `batch_no` first, then extracts from linked SBB.

### 3.14 Fiscal Year Transition — Batch/Serial Rollout (2026)

- **Cross-FY internal transfers:** If a source document (DN/SI) was submitted in the old FY without batch/serial info, but the Item now has `has_batch_no=1` or `has_serial_no=1`, `_duplicate_serial_and_batch_bundle()` logs a warning and skips SBB duplication. The target document (PR/PI) must have its batch/serial populated manually before submission.
- **Recommended rollout procedure:**
  1. Complete all pending cross-FY internal transfers before enabling batch/serial on items.
  2. Set `internal_transfer_cutoff_fy` (and optionally `accounting_rewrite_cutoff_fy`) in BNS Branch Accounting Settings to the target Fiscal Year.
  3. Enable `has_batch_no` / `has_serial_no` on items after the cutoff.
  4. All new-FY transactions will carry batch/serial through the SBB duplication path.
- **Report guidance:** When running reports with batch segregation across the FY boundary, filter by `from_date >= new FY start` to avoid split-timeline artifacts.
- **Parity validation:** `_validate_batch_serial_parity()` logs warnings (not errors) when one side of an internal transfer has batch/serial info and the other doesn't, accommodating the transition period.

### 3.15 Purchase Document Attachment Validation (`overrides/attachment_validation.py`)

- **What:** `before_submit` hook for Purchase Receipt and Purchase Invoice that enforces mandatory attachments via dedicated Attach fields on each doctype.
- **Why:** Supplier invoices (and e-Waybills when applicable) must be on file before a purchase document is finalized. Prevents submission without supporting documents. Using explicit Attach fields (instead of generic File attachments) provides clear separation between document types.
- **Custom Fields (on both PR and PI):**
  - `bns_purchase_attachments_section` — Section Break, collapsible.
  - `bns_supplier_invoice_attachment` — Attach (mandatory on submit when feature enabled).
  - `bns_ewaybill_attachment` — Attach (hidden when e-Waybill is not applicable; mandatory when visible and document meets threshold).
  - `bns_builty_attachment` — Attach (always optional, for transport builty / lorry receipt).
- **e-Waybill field visibility:** Controlled client-side via `purchase_attachment_fields.js` calling `check_ewaybill_applicability` API. Field is hidden when: e-Waybill is disabled in GST Settings, document has no stock items (PI without update_stock), or `abs(base_grand_total) < e_waybill_threshold`.
- **Rules:**
  - **PR:** `bns_supplier_invoice_attachment` required. `bns_ewaybill_attachment` required when threshold met. `bns_builty_attachment` always optional.
  - **PI created from PR:** Exempt — all 3 fields are hidden, dashboard headline links to the PR.
  - **PI created directly (no PR items):** Same rules as PR.
- **Settings:** BNS Settings > Stock & Inventory > `enforce_purchase_document_attachments` (Check, default off).
- **Files:** `attachment_validation.py` (server), `purchase_attachment_fields.js` (client), `purchase_invoice_form.js` (headline), `custom_field.json` (field definitions), `hooks.py` (doctype_js + before_submit).

---

## 6. Migration Implications

- **BNS Branch Accounting:** Uses `bns_inter_company_reference`, `bns_reference_dn`, `bns_reference_si`, etc. Custom fields are in fixtures.
- **Patch:** `migrate_internal_dn_ewaybill_to_branch_accounting.py` – copies `enable_internal_dn_ewaybill` from BNS Settings to BNS Branch Accounting Settings before field removal.
- **Warehouse negative stock:** Patches applied via `after_app_init` in hooks.

---

## 6.5 Party GL – Multi-Currency Account Toggle

- **What:** Added `show_in_account_currency` checkbox filter to Party GL report. When enabled, Debit/Credit/Balance columns display amounts in the party's account currency instead of company currency.
- **Why:** Parties with foreign-currency receivable/payable accounts (e.g. USD Receivable) need to view their ledger in the account's native currency. GL Entry already stores `debit_in_account_currency` / `credit_in_account_currency`; this toggle surfaces those values.
- **How it works:**
  - `set_account_currency()` resolves the account currency from the party's GL entries or the account filter. `company_currency` is now always populated as a fallback.
  - When the toggle is on and `account_currency != company_currency`, `get_result_as_list()` swaps each row's `debit`/`credit` with `debit_in_account_currency`/`credit_in_account_currency` before computing the running balance.
  - `get_columns()` labels Debit/Credit headers with the account currency symbol.
  - The HTML print template (`party_gl.html`) uses a `displayCurrency` variable derived from the toggle state for `format_currency` calls.
- **Edge cases:** If the party has entries across accounts with mixed currencies, `set_account_currency()` falls back to company currency, and the toggle has no effect.
- **Impacted files:** `party_gl.py`, `party_gl.js`, `party_gl.html`.

---

## 6.6 Pure AR/AP Summary – FIFO Ageing Adjustment for Running Accounts

- **What:** Added `adjust_running_accounts` checkbox filter to both Pure Accounts Receivable Summary and Pure Accounts Payable Summary reports. When enabled, unallocated/on-account payments (negative outstanding entries) are virtually applied FIFO (oldest invoices first) to redistribute ageing buckets, eliminating misleading negative values in recent buckets and inflated amounts in older buckets.
- **Why:** Most parties operate on running accounts where payments are not reconciled bill-wise. Without reconciliation, ERPNext places on-account payments as negative outstanding in recent ageing buckets while old invoices remain fully outstanding in old buckets. This gives a distorted ageing picture even though total outstanding is correct.
- **How it works:**
  - `adjust_ageing_fifo()` method in `AccountsReceivablePayableSummary` runs after `get_party_total()` when the filter is checked.
  - For each party, entries are separated into positive outstanding (invoices) and negative outstanding (advances/on-account payments).
  - Invoices are sorted by date (oldest first, using the same `ageing_based_on` filter — Posting Date or Due Date).
  - The total negative amount is applied FIFO against invoices, reducing oldest first.
  - Ageing buckets (`range1..rangeN`) and `total_due` are recalculated from adjusted invoice amounts.
  - `outstanding`, `invoiced`, `paid`, `credit_note`, `opening` remain untouched.
- **Post-netting redistribution:** For parties with AR/AP netting (via Party Link or common parties), bucket-by-bucket subtraction can create new negatives. `redistribute_negative_ageing_buckets()` runs after netting in `execute()`: sums all negative buckets, zeroes them, then reduces the oldest positive buckets FIFO. This ensures all buckets are >= 0.
- **Invariant:** `sum(range1..rangeN) == outstanding` — preserved before and after adjustment.
- **Impacted files:** `pure_accounts_receivable_summary.py`, `pure_accounts_receivable_summary.js`, `pure_accounts_payable_summary.py`, `pure_accounts_payable_summary.js`.
- **Shared logic:** `AccountsReceivablePayableSummary` class is used by both AR and AP reports, so the FIFO method works for both automatically. `redistribute_negative_ageing_buckets()` is imported by the AP report from the AR report module.

---

## 7. Removed Logic

- **test_bns_settings.py:** Tests for `warehouse_validation`, `auto_transit_validation`, `warehouse_filtering` removed — those modules never existed. Replaced with minimal `test_bns_settings_loads` test.
- **BNS Settings:** `enable_internal_dn_ewaybill` field removed from field_order — migrated to BNS Branch Accounting Settings.
- **PR/PI standard inter-company fields:** BNS no longer sets `represents_company` or `inter_company_reference` (PR) / `inter_company_invoice_reference` (PI) on Purchase Receipt or Purchase Invoice. All internal-transfer linking uses BNS fields only (`bns_inter_company_reference`, `supplier_delivery_note`, etc.). Removed from: DN→PR mapping, PR status update on_submit, PI status update on_submit.
- **BNS Internal Return Blocking (SI/DN):** `validate_bns_internal_customer_return` and `validate_bns_internal_delivery_note_return` previously threw errors blocking credit notes / returns for BNS internal customers. Functions converted to no-ops (pass) to enable SI credit note → PI debit note conversion flow. Hook registrations retained but inactive.
- **FIFO auto payment reconciliation system:** Removed end-to-end from BNS Settings and backend service. Deleted `auto_payment_reconcile.py`, removed manual "Run FIFO Reconciliation" action from `doctype/bns_settings/bns_settings.js`, and removed reconciliation fields from `doctype/bns_settings/bns_settings.json` (`enable_auto_fifo_reconciliation`, `include_future_payments_in_reconciliation`, `reconciliation_batch_size`, `last_reconciliation_run`, `last_reconciliation_status`).

---

## 8. Code Audit Findings (2026)

| Issue | Severity | Location | Resolution |
|-------|----------|----------|------------|
| Orphan field_order reference | **Bug** | BNS Settings JSON had `enable_internal_dn_ewaybill` in field_order but no field definition | Removed from field_order |
| Dead test imports | **Bug** | test_bns_settings.py imported non-existent modules | Replaced with minimal passing test |
| Duplicate `is_bns_internal_customer` logic | Refactor | gst_compliance._is_bns_internal_customer + ~20 inline checks in bns_branch_accounting/utils.py | Consider adding `is_bns_internal_customer(doc)` helper in bns_branch_accounting, import from gst_compliance |
| Legacy wrappers unused | Dead code | submission_restriction: validate_stock_modification, validate_transaction_modification, validate_order_modification | Kept for backward compatibility; not in hooks |

### 8b. Branch Accounting Bug Fixes (2026)

| Bug | Severity | Fix |
|-----|----------|-----|
| Repost uses current settings, not transaction-time | CRITICAL | Added FY guard to `_repost_chain` / `verify_and_repost_internal_transfers` — vouchers from a prior FY are skipped unless `allow_cross_fy_repost=True`. Prevents GL account mismatch when settings change between FYs. |
| Bulk operations modify old-FY documents | CRITICAL | Added `to_date` parameter to `bulk_convert_to_bns_internal` / `get_bulk_conversion_preview`. Auto-defaults to end of the FY containing `from_date`. Logs warning when `force=1` spans multiple FYs. |
| Premature reference write (dangling ref) | CRITICAL | Removed `_update_delivery_note_reference` / `_update_sales_invoice_reference` calls from `make_bns_internal_purchase_receipt` / `make_bns_internal_purchase_invoice`. Reference is already written in `on_submit` hooks (`update_purchase_receipt_status_for_bns_internal`, `update_purchase_invoice_status_for_bns_internal`) after save. |
| No locking on link/convert operations | CRITICAL | Added `for_update=True` on `frappe.get_doc()` (SELECT FOR UPDATE) at the top of `link_dn_pr`, `link_si_pi`, `make_bns_internal_purchase_receipt`, `make_bns_internal_purchase_invoice` to prevent duplicate creation from concurrent requests. |
| stock_qty mixes UOM and stock UOM | MEDIUM | `_update_item` now multiplies `returned_qty` and `received_qty` by `conversion_factor` before subtracting from `stock_qty`. |
| Empty GSTINs treated as "same GSTIN" | MEDIUM | `_is_same_gstin_internal_delivery_note` now returns `False` when either GSTIN is empty/None, preventing incorrect GL rewrite for non-GST companies. |
| Unlink doesn't reset status/flags | MEDIUM | `unlink_dn_pr` / `unlink_si_pi` now reset `is_bns_internal_customer`/`is_bns_internal_supplier`, `status`, and `per_billed` after clearing `bns_inter_company_reference`. |
| link_si_pi hard-blocks re-linking | MEDIUM | Extended `_is_stale_inter_company_ref` to support SI/PI doctypes. Replaced hard-block in `link_si_pi` with stale-ref auto-clear pattern matching `link_dn_pr`. |

### 8c. Two-Phase Cutoff Dates (2026)

Replaced single `internal_validation_cutoff_date` (Date) with two Fiscal Year Link fields:

| Field | Type | Purpose |
|-------|------|---------|
| `internal_transfer_cutoff_fy` | Link -> Fiscal Year | Phase 1: Status marking, flags, linking, validation, document creation. BNS internal logic applies from this FY's `year_start_date` onward. |
| `accounting_rewrite_cutoff_fy` | Link -> Fiscal Year | Phase 2: GL entry rewriting, SLE valuation override, transfer rate sync, GL reposting. Requires Phase 1 to be active. |

**Key rules:**

1. **Fiscal Year only**: Users select a Fiscal Year, not a raw date. Cutoff is resolved to `Fiscal Year.year_start_date` at runtime.
2. **Empty = disabled**: If a cutoff FY is not set, that phase does not fire. Reversal from old behavior where empty = "apply to everything".
3. **Dependency rule**: Accounting Rewrite cannot be set without Internal Transfer. Accounting FY start cannot precede Transfer FY start. Enforced in `bns_branch_accounting_settings.py:validate()` and at runtime in `is_after_accounting_rewrite_cutoff()`.
4. **Source document governs the chain**: The first/source document (DN or SI) posting date determines cutoff for the entire chain. If a DN is created before the cutoff, the PR created from it is also treated as pre-cutoff regardless of the PR's own posting date. Implemented via `_resolve_source_posting_date(doc)` helper.
5. **Mixed on_submit functions**: `update_purchase_receipt_status_for_bns_internal` and `update_purchase_invoice_status_for_bns_internal` mix Phase 1 (status/flags) and Phase 2 (transfer rate sync, GL repost) operations. They use a split gating pattern: top-level Phase 1 guard, then Phase 2 operations individually wrapped in `is_after_accounting_rewrite_cutoff()`.
6. **Manual repair tools bypass cutoff**: `_force_rebuild_bns_gl_for_voucher` and `bns_debug_internal_gl_scope` intentionally have no cutoff check to allow historical repair.
7. **Migration**: On first save after upgrade, if both new FY fields are empty and old `internal_validation_cutoff_date` has a value, the settings controller auto-populates both new fields from `frappe.get_fiscal_year(old_date)`.

**Helpers added to `bns_branch_accounting/utils.py`:**

| Helper | Purpose |
|--------|---------|
| `_get_internal_transfer_cutoff_date()` | Resolves `internal_transfer_cutoff_fy` to `year_start_date` |
| `_get_accounting_rewrite_cutoff_date()` | Resolves `accounting_rewrite_cutoff_fy` to `year_start_date` |
| `is_after_internal_transfer_cutoff(posting_date)` | Phase 1 gate |
| `is_after_accounting_rewrite_cutoff(posting_date)` | Phase 2 gate (includes Phase 1 check) |
| `_resolve_source_posting_date(doc)` | Returns source DN/SI posting_date for PR/PI documents |
| `is_after_internal_validation_cutoff(posting_date)` | Deprecated alias for `is_after_internal_transfer_cutoff` |

---

## 9. Dependencies

- **ERPNext:** Required (stock, accounts, sales, purchase).
- **India Compliance:** Optional but recommended for GST; used for e-Waybill API and GSTIN resolution.

---

## 10. Fixtures

- Custom Field, Property Setter (modules: Business Needed Solutions, BNS Branch Accounting)
- Terms and Conditions (General)

---

## 11. BNS Health Check Dashboard & Workspace

**Added:** 2026-04-01

### What Changed
- **`bns_dashboard.py`**: Added `get_health_check_overview` API that bundles accounting (AR/AP/overdue + 6-month trend), branch-accounting (DN→PR/SI→PI completion, repost queue), stock (negative stock violations, guarded warehouses, draft reconciliations), and compliance (PR/PI attachment rates) metrics in a single call.
- **`bns_dashboard.js`**: Restructured the BNS Dashboard page into a comprehensive health-check layout:
  - **Accounting Overview**: 4 metric cards (Total Receivables, Total Payables, Overdue Receivables, Overdue Payables) + monthly Sales vs Purchase bar chart using `frappe.Chart`.
  - **Data Health Indicators**: 4 cards reflecting items missing expense accounts, PI fixable count, unlinked PAN pairs, and transfer mismatches.
  - **Branch Accounting Health**: 6 metric cards (DN→PR pending, SI→PI pending, total internal DNs/SIs, repost queued, repost tracked) + completion percentage progress bars.
  - **Stock & Compliance**: Negative stock items/warehouses, guarded warehouse count, draft reconciliations, PR/PI attachment compliance with progress bars.
  - **Quick Links**: Organized links to all BNS reports and settings.
  - **Detail Sections**: Existing collapsible sections (expense fixables, party fixables, food company FSSAI, transfer mismatches) preserved below.
- **`workspace/bns_health_check.json`**: New workspace titled "BNS Health Check" with shortcuts to BNS Dashboard page, BNS Settings, and Branch Accounting Settings; links organized into Accounting Reports, Branch Accounting, Stock Reports, and Other Reports card groups.

### Why
- Users needed a single entry point to assess the overall health of their BNS-managed accounting, branch transfers, stock discipline, and compliance posture.
- Previously the dashboard only covered expense-account fixes and party linking; branch accounting, stock, and compliance metrics were scattered across individual reports with no aggregated view.

### Impacted Modules
- `business_needed_solutions.page.bns_dashboard` (Python + JS)
- `business_needed_solutions.workspace` (new workspace JSON)

### Backend Helpers (internal, not whitelisted)
| Function | Purpose |
|----------|---------|
| `_get_accounting_metrics(company)` | AR/AP totals, overdue splits, 6-month invoice trend |
| `_get_branch_accounting_metrics(company)` | Internal DN/SI completion, repost health |
| `_get_stock_metrics(company)` | Negative stock counts, guarded warehouses, draft reconciliations |
| `_get_compliance_metrics(company)` | PR/PI supplier-invoice attachment rates |

---

## 12. Negative Stock Override (Role-Based Bypass with Cutoff Date)

### What Changed
- Added fields to **BNS Settings** (Stock & Inventory → Negative Stock Override):
  - `allow_negative_stock_override` (Check) — master toggle
  - `negative_stock_cutoff_date` (Date) — posting-date cutoff
  - `negative_stock_override_roles` (Table MultiSelect → Has Role) — authorised roles
- Created **`overrides/negative_stock_override.py`** with:
  - `should_override_negative_stock(posting_date)` — evaluates toggle, cutoff, and user roles
  - `apply_patches()` — monkey-patches `make_sl_entries` and `update_entries_after.__init__` in `erpnext.stock.stock_ledger` to inject `allow_negative_stock=True` when override conditions are met
- Added the patch to `after_app_init` in **hooks.py** (runs after the existing `warehouse_negative_stock` patches)

### Why
- During data migration or historical corrections, users need to submit stock transactions with posting dates in periods where stock may go negative temporarily (e.g., backdated entries). ERPNext's global "Allow Negative Stock" toggle is too broad — turning it on exposes all users to unrestricted negative stock.
- This feature provides a surgical override: only designated roles can bypass, and only for documents posted on or before a cutoff date. After the cutoff, normal Stock Settings behaviour resumes automatically.

### Relationship with Warehouse Negative Stock
- **warehouse_negative_stock** adds restrictions (disallow negative stock per-warehouse when ERPNext allows it globally)
- **negative_stock_override** removes restrictions (allow negative stock for specific roles when ERPNext disallows it globally)
- The two compose correctly: when the override is active, warehouse-level restrictions still apply if both features are enabled simultaneously.

### Impacted Modules
- `business_needed_solutions.doctype.bns_settings` (new fields)
- `business_needed_solutions.overrides.negative_stock_override` (new module)
- `hooks.py` (`after_app_init`)

---

## 13. Post-Change Commands

After changes to fields, JS, Vue, or assets:

```bash
bench clear-cache && bench migrate && bench build --app business_needed_solutions && bench clear-cache
```
