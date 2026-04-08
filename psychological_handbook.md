# Business Needed Solutions – Psychological Handbook

**App:** business_needed_solutions  
**Purpose:** Architectural intent, business reasoning, constraints, and anti-patterns. Read this before making changes.

---

## 1. Architectural Intent

BNS is a **control and compliance layer** on top of ERPNext. It does not replace ERPNext; it adds:

- **Guards** – validations that prevent invalid or non-compliant operations.
- **Workflow controls** – who can submit what, when.
- **Indian compliance** – GST, PAN, e-Waybill for internal transfers.
- **Internal transfer accounting** – branch-to-branch stock and invoice flows with proper GL.

The app is designed to be **configurable via settings** – most features can be turned on/off without code changes.

---

### Decision note (2026-04-09, negative stock override skips non-stock items)
- The negative stock cutoff feature is a **stock** guard — it must only validate items that actually maintain bin/SLE quantities (`is_stock_item=1`). Non-stock items on mixed documents (e.g. service line on a Delivery Note) must pass through unchecked.
- The batch lookup (`_get_stock_item_set`) avoids per-row DB hits. The set is built once per document submit, which is acceptable since the items table is bounded and submit is not a hot path.

### Decision note (2026-04-09, SI-PI amount tolerance on reports)
- The mismatch report must be consistent with submit-time validation: if a PI was accepted within the configured tolerance, the report must not flag it as a mismatch. Inconsistency erodes trust in the dashboard counts.
- Tolerance applies only to amounts (taxable value, grand total, taxes). Qty remains strict — quantity discrepancies are a counting/operational error, not a rounding issue.
- DN-PR comparisons in the same report keep their existing hardcoded tolerances (₹5 for amounts, 0.01 for qty/tax) because those reflect a different workflow (same-GSTIN stock transfers) and have no corresponding settings field. Unifying them is a future consideration.

### Decision note (2026-04-09, PI expense fix batching)
- GL reposting is the most expensive operation in the fix cycle (~0.5-2s per PI). Synchronous processing of 50+ PIs exceeds web-request timeouts.
- Background processing via `frappe.enqueue` is the Frappe-native solution: the user's browser is never blocked, partial progress is committed every 10 PIs so a worker crash does not lose all work, and realtime events keep the UI informed.
- Batch size 10 balances commit overhead vs durability. Timeout 1500s (25 min) covers ~500 PIs with headroom.
- No new DocType for job tracking: realtime events are ephemeral. If the user navigates away, the job still completes; the next dashboard load shows updated data. This avoids schema bloat for a correction workflow that should trend toward zero usage.
- Errors are collected per-PI so one bad invoice does not abort the rest (same as the prior synchronous behavior).

---

## 2. Business Reasoning

### 2.1 Submission Restriction

**Intent:** Allow users to create drafts but restrict who can submit. Supports approval workflows and segregation of duties.

**Constraint:** Override roles must be explicitly granted. Do not bypass this for "convenience."

### 2.2 BNS Internal Transfer

**Intent:** Model inter-branch transfers (same legal entity, different locations) with:

- DN → PR (stock movement, same GSTIN)
- SI → PI (invoice flow, different GSTIN)
- SI → PR → PI (invoice creates receipt, then invoice on purchase side)
- DN → SI → PI (delivery note creates sales invoice, then purchase invoice)
- DN → SI → PR → PI (full chain from stock to invoice on both sides)
- Correct GL: Stock in Transit, Internal Sales Transfer Account (DN), Internal Purchase Transfer Account (PR), Internal Branch Debtor/Creditor Accounts
- Tiny precision residues (e.g. 0.0001) after internal GL rewrite are handled by ERPNext's `process_debit_credit_difference()` which posts them to the Company round-off account. BNS must not absorb residuals into transfer or branch accounts.

**Constraint:** `is_bns_internal_customer` and `is_bns_internal_supplier` are the source of truth. Do not introduce parallel flags.
**Constraint:** Do not add BNS-specific round-off logic. ERPNext's `process_debit_credit_difference` / `make_round_off_gle` handles GL residuals via Company round-off account. BNS rewrite functions must not interfere with this by absorbing diffs into transfer accounts or discarding rewrites for small diffs.

### 2.2b Bulk Linkage Verification & Repost

**Intent:** Provide a post-cutoff verification mechanism that ensures all internal transfer chains are 100% linked at both doc-level and item-level before triggering repost. This is a manual, controlled operation — not automated — to avoid unintended mass financial updates.

**Reasoning:** After a cutoff date (e.g., system stabilization point), all internal transfers should be fully linked. Partially linked or unlinked chains indicate data integrity issues that must be resolved before financial repost. The function categorizes chains into fully_linked/partially_linked/unlinked so the team can address issues systematically.

**Constraint:** Only fully-linked chains are reposted. Partial or unlinked chains are reported for manual attention. The function must never repost documents it cannot fully verify.

**Fix Partial DN→PR Intent:** Some DN→PR chains are "partially linked" only because `bns_inter_company_reference` was not set bidirectionally (data migration gaps, manual PR creation, etc.). The fix option auto-repairs these references, but **only** when the underlying data is consistent: same items, same rates, same taxable amounts, and same warehouses. Any mismatch indicates a real data problem that requires manual resolution — the fix must never paper over genuine discrepancies.

**Constraint:** The fix must skip (not force-link) whenever item codes, rates, taxable amounts, or source-to-destination warehouses differ. Skipped pairs are reported with reasons so users can address root causes.

**Amendment Resilience:** When a DN is amended, the new DN has different item row IDs but the linked PR still references the old IDs. All linking and verification paths must detect this condition and re-map by item_code + qty + rate rather than failing on stale references. Zero-rate items (samples, free goods) are legitimate and must not block GL rewrite — they are skipped, not treated as errors.

### 2.2a Billing Location → Customer Address

**Intent:** For BNS internal customers, billing location drives customer address (like location_based_series for company address). On save, server sets customer_address from billing_location's linked address; customer_address is read-only when both are set. For outside customers, billing_location and customer_address are independent—customer_address remains editable.

**Constraint:** Only apply auto-update and read-only when `is_bns_internal_customer` is true. Do not extend this logic to outside customers.

### 2.2c Credit Note → Debit Note Conversion (SI Return → PI Return)

**Intent:** Enable BNS internal SI credit notes to be converted to PI debit notes using the same `make_bns_internal_purchase_invoice` conversion function. This mirrors the standard SI→PI flow but handles negative quantities and sets return linkage on the target PI.

**Reasoning:** When goods are returned between internal branches, the selling branch issues a credit note (SI return). The purchasing branch needs a corresponding debit note (PI return) linked to the original PI. Blocking returns entirely was too restrictive — branches need a formal return mechanism for adjustments, damages, and corrections.

**Constraint:** The PI debit note must have `is_return = 1` and `return_against` pointing to the original PI (found via `bns_inter_company_reference` on the original SI). Item quantities remain negative. The previous return-blocking validations (`validate_bns_internal_customer_return`, `validate_bns_internal_delivery_note_return`) were removed to enable this flow — returns are now allowed for BNS internal customers.

### 2.2d Internal Transfer Accounting Audit

**Intent:** Provide a read-only audit report that validates whether GL and SLE entries for BNS internal documents (DN, SI, PR, PI) conform to the expected BNS branch-accounting patterns. This is a detective control — it does not fix anything, only surfaces deviations.

**Reasoning:** The GL rewrite functions may be skipped (missing settings, zero amounts, pre-cutoff documents) or overwritten by repost. SLE transfer rates may diverge from `bns_transfer_rate` after repost. This report gives the accounting team visibility into which documents have non-conforming entries so they can trigger targeted reposts or manual corrections.

**Constraint:** The report must remain read-only. It must not modify GL, SLE, or document data. It must use the same scope-detection logic as the rewrite functions (same GSTIN vs different GSTIN, DN-linked vs SI-linked) to ensure consistency.

### 2.3 Same-GSTIN Purchase Invoice Block

**Intent:** Prevent self-invoicing when Supplier GSTIN = Company GSTIN. GST does not allow this.

**Constraint:** Validation runs on validate; GSTIN is resolved from doc or from Company/Supplier addresses. Do not skip when India Compliance is present.

### 2.3b Serial and Batch Bundle Support (ERPNext v15+)

**Intent:** All stock-related code in BNS must support ERPNext v15+ Serial and Batch Bundle (SBB) alongside legacy `serial_no`/`batch_no` fields. This ensures batch and serial traceability across all internal transfer mappings, negative stock validations, and reports.

**Pattern:** Use `_duplicate_serial_and_batch_bundle()` for all document-to-document item mappings (DN→PR, SI→PI, SI→PR). Never copy `serial_and_batch_bundle` directly between documents — each document needs its own SBB created via `SerialBatchCreation.duplicate_package()`.

**Constraint:** Do not reintroduce legacy `serial_no`/`batch_no` into `field_map` for mappings. These fields are in `field_no_map` to prevent raw copying. The helper handles all four scenarios (SBB, legacy fields, cross-FY item without tracking, non-batch/serial item) in a single codepath.

**Constraint:** Reports that query SLE must handle both `batch_no` on SLE and `serial_and_batch_bundle` references. When `batch_no` is empty, fall back to querying the SBB's child entries (`Serial and Batch Entry`).

**Fiscal Year Transition:** When enabling batch/serial tracking on items from a new fiscal year:
- Complete all pending cross-FY internal transfers before enabling `has_batch_no`/`has_serial_no`.
- Set `internal_validation_cutoff_date` to the new FY start date to isolate old-FY documents.
- The SBB duplication helper logs a warning (not an error) for cross-FY items missing batch/serial on the source.
- Parity validation uses warnings for one-side-missing scenarios, not hard errors — this accommodates the transition period without breaking existing workflows.

### 2.4 Stock Update vs. Reference

**Intent:** When SI/PI do not update stock, every stock item must trace back to DN/PR. Ensures audit trail. Includes batch continuity: the batch_no on the invoice item must match the referenced source item's batch_no.

**Constraint:** Do not relax this for "special cases" without explicit business approval.

### 2.5 Per-Warehouse Negative Stock

**Intent:** Some warehouses (e.g. retail) must never go negative; others (e.g. manufacturing) may. ERPNext's global setting is insufficient. Supports batch-level negative stock detection — when items use SBB instead of legacy `batch_no`, batch numbers are extracted from the bundle and each is validated individually.

**Constraint:** Works only when ERPNext allows negative stock globally. Warehouse-level setting is additive.

### 2.6 PAN Uniqueness

**Intent:** One PAN = one party identity. Avoids duplicate Customer/Supplier records.

**Constraint:** Applies to both Customer and Supplier. Do not exempt one without the other.

---

## 3. Design Principles

1. **Settings-driven:** Features are toggled in BNS Settings or BNS Branch Accounting Settings. Avoid hardcoded behavior.
2. **Override, don't fork:** Extend ERPNext via doc_events, override_doctype_class, and custom fields. Do not copy-paste ERPNext code.
3. **Single source of truth:** BNS internal logic lives in `bns_branch_accounting/utils.py`. Re-exports from `business_needed_solutions.utils` for backward compatibility only.
4. **India Compliance integration:** Use India Compliance APIs and address GSTIN when available. Do not duplicate GST logic.
5. **Graceful degradation:** If a setting is off or data is missing, skip validation rather than fail. Log at debug level.
6. **Avoid broad auto-financial writes:** Automated mass reconciliation logic was intentionally removed to reduce risk from high-impact background updates and broad whitelisted entry points.

---

## 4. Constraints

- **Do not create GST entries manually** – use standard tax logic. BNS only validates and triggers e-Waybill.
- **Do not bypass submission restriction** – even for system scripts; use override roles if needed.
- **Do not bypass stock update validation** – all stock items must reference source when `update_stock` is off.
- **Do not introduce new "internal" flags** – use `is_bns_internal_customer` / `is_bns_internal_supplier` only.
- **Do not move BNS Branch Accounting logic back** into `business_needed_solutions` – keep it in `bns_branch_accounting/utils.py`.

---

## 5. Anti-Patterns to Avoid

1. **Scattered validation logic** – Keep validation in `overrides/` modules. Do not add ad-hoc checks in doctype controllers.
2. **Hardcoded doctype names** – Use constants or config if the same list appears in multiple places.
3. **Silent failures** – If validation is skipped, log at debug. If it fails, throw with a clear message.
4. **Bypassing hooks** – All validations must run via doc_events. Do not call validation only from client JS.
5. **Duplicate accounting logic** – Use BNS Branch Accounting Settings for accounts. Do not hardcode account names.
6. **Handbook drift** – After any logic change, update both `technical_handbook.md` and `psychological_handbook.md` so the docs match the code.
7. **Direct SBB field copy in mappings** – Never copy `serial_and_batch_bundle` via `field_map`. Each target document needs its own SBB created via `duplicate_package()`. Use `field_no_map` to block raw copying.
8. **Ignoring SBB in batch-aware code** – When checking `batch_no`, always add a fallback path for `serial_and_batch_bundle`. ERPNext v15+ may populate only the SBB field.
9. **Cross-FY repost without account verification** – Never repost old-FY documents after BNS Branch Accounting Settings have changed. The GL rewrite reads accounts at execution time; reposting with new accounts breaks the debit/credit pairing with the counter-document that was written with the old accounts. Use `allow_cross_fy_repost=True` only after verifying account consistency.
10. **Premature reference writes** – Never write `bns_inter_company_reference` on a source document before the target document is saved/submitted. Use `on_submit` hooks for reference writes to avoid dangling refs.
11. **Link/convert without locks** – Always use `frappe.get_doc(doctype, name, for_update=True)` (SELECT FOR UPDATE) in link/convert operations to prevent duplicate creation from concurrent requests.
12. **Empty GSTIN as same-GSTIN** – Treat missing/empty GSTINs as "unknown", not "same". Do not trigger same-GSTIN GL rewrite when either GSTIN is absent.
13. **Unlinking without status reset** – Clearing `bns_inter_company_reference` alone leaves documents visually in "transferred" state. Always reset `is_bns_internal_*`, `status`, and `per_billed` when unlinking.
14. **Duplicate attachment enforcement on PR and PI** – When a PI is created from a PR, do not require attachments on the PI. The PR holds the supplier invoice, e-Waybill, and builty; the PI hides those fields entirely and shows an info headline linking to the PR. Only enforce attachments on the document that "owns" the physical receipt.
15. **Generic File-based attachment counting** – Never count generic `File` records to determine whether specific attachments are present. Use dedicated Attach fields (`bns_supplier_invoice_attachment`, `bns_ewaybill_attachment`, `bns_builty_attachment`) so each document type is explicitly identifiable. This prevents ambiguity when users attach unrelated files.
16. **Showing mandatory fields that don't apply** – The e-Waybill attachment field must be hidden when the document doesn't meet the threshold or stock-item criteria. Showing a mandatory field that the user can never fill correctly creates confusion. Use dynamic visibility via server-side applicability check.
17. **BNS internal supplier purchases** – Inter-branch PR/PI against a BNS internal supplier does not mirror a third-party purchase; supplier invoice, builty, and e-waybill attachments are optional and the UI hides that block. External suppliers restore full enforcement immediately when the party is changed (client reads Supplier master; server double-checks on submit).
17. **Phase 2 without Phase 1** – Never enable GL/SLE rewriting (Phase 2) without first enabling status/linking (Phase 1). The accounting rewrite assumes BNS internal flags and references are already set. Enforced at settings validation and runtime.
18. **Blanket top-level guard on mixed functions** – The PR and PI `on_submit` hooks contain both Phase 1 (status updates) and Phase 2 (transfer rate sync, GL repost) operations. A blanket Phase 1 early-return would skip Phase 2 even when it should run independently. Use split gating: top-level Phase 1 guard, then Phase 2 operations individually wrapped in their own cutoff check.
19. **Checking target doc date instead of source doc date** – When evaluating cutoff for PR/PI, always use the source DN/SI's posting date, not the PR/PI's own posting date. A DN created before cutoff means the entire chain is pre-cutoff. Use `_resolve_source_posting_date(doc)` consistently.
20. **Raw date cutoffs** – Cutoff dates must align with fiscal year boundaries. Never allow arbitrary dates as cutoffs; users select a Fiscal Year and the system resolves it to `year_start_date`. This prevents partial-FY cutoffs that could leave accounting in an inconsistent state.

---

## 6. Module Boundaries

| Module | Responsibility | Do not |
|--------|-----------------|--------|
| `overrides/` | Validation, enforcement | Business logic for DN/PR/SI/PI creation |
| `overrides/attachment_validation.py` | Purchase attachment enforcement | e-Waybill generation, GST calculations |
| `bns_branch_accounting/utils.py` | Internal transfer logic, status, conversion | GST validation, submission restriction |
| `gst_compliance.py` | GST validations, e-Waybill | Internal transfer accounting |
| `business_needed_solutions/utils.py` | Re-exports, shared helpers | Core BNS internal logic (moved to bns_branch_accounting) |

### 6.1 Pure AR/AP Summary – FIFO Ageing for Running Accounts

The FIFO ageing adjustment is a **report-level presentation layer** — it does not modify any underlying data. The checkbox redistributes ageing buckets to give a realistic picture of where outstanding amounts truly sit when payments are on running accounts.

**Reasoning:** Running accounts are the norm for most parties. Requiring full payment reconciliation just to see correct ageing is impractical. This feature gives the same insight without forcing users through the reconciliation tool.

**Constraint:** The adjustment must never alter total outstanding, invoiced, paid, credit_note, or opening balance. Only ageing bucket distribution and total_due (which is derived from buckets) may change. The invariant `sum(range1..rangeN) == outstanding` must always hold. If it doesn't, the adjustment has a bug.

### 6.2 Party GL Report – Multi-Currency Philosophy

The Party GL report is a **read-only view** over GL Entry data. Its multi-currency toggle (`show_in_account_currency`) follows the principle of **surfacing existing data, not transforming it**: GL Entry already stores amounts in three currency layers (company, account, transaction). The toggle simply selects which layer to display.

**Reasoning:** Users dealing with foreign-currency accounts need ledger balances in the account's native currency for reconciliation and statement purposes. Forcing them through presentation currency or manual conversion adds friction.

**Constraint:** The toggle does not perform currency conversion. It reads `debit_in_account_currency`/`credit_in_account_currency` directly from GL Entry. If a party has entries across accounts with different currencies, the toggle has no effect (falls back to company currency) to avoid mixing incompatible amounts.

---

## 7. When Adding New Features

1. Read both handbooks.
2. Decide: BNS Settings vs. BNS Branch Accounting Settings.
3. Add validation in `overrides/` or `bns_branch_accounting/` as appropriate.
4. Register in `hooks.py` doc_events.
5. Update both handbooks.

---

## 8. When Removing Logic

1. Add to `technical_handbook.md` → "Removed Logic" section: what, why, risk.
2. Remove from `psychological_handbook.md` if it affected architectural intent.
3. Add migration patch if needed (e.g. data cleanup, setting migration).
