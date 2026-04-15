# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This App Is

Business Needed Solutions (BNS) is a Frappe/ERPNext app that adds enterprise controls, Indian compliance, and internal transfer accounting on top of standard ERPNext. It does NOT replace ERPNext — it adds guards, validations, and workflow controls via doc_events and override classes.

Two main modules:
- **Business Needed Solutions (core)** — submission restrictions, PAN validation, negative stock enforcement, dynamic print formats, discount manipulation, attachment validation
- **BNS Branch Accounting** — inter-branch internal transfers (DN↔PR, SI↔PI linking), GL rewrite, transfer rate mirroring, common party square-off, GST/e-waybill integration, reconciliation

## Common Commands

```bash
# Run bench (from bench directory: /home/ubuntu/frappe-bench-new)
bench start

# Run a single test file
bench --site <site> run-tests --app business_needed_solutions --module business_needed_solutions.business_needed_solutions.tests.test_submission_restriction

# Run all app tests
bench --site <site> run-tests --app business_needed_solutions

# Migrate after doctype/patch changes
bench --site <site> migrate

# Export fixtures (custom fields, property setters)
bench --site <site> export-fixtures --app business_needed_solutions

# Clear cache after JS changes
bench --site <site> clear-cache

# Build assets after JS changes
bench build --app business_needed_solutions
```

## Architecture

### Hook-Driven Design (hooks.py)

All business logic attaches to standard ERPNext doctypes via `doc_events`. The app registers 40+ hooks across 16 doctypes. Key pattern:
- `validate` — data integrity checks (PAN, GST, internal party, stock references)
- `before_submit` — stock patches, negative stock enforcement, attachment validation
- `on_submit` — submission permission checks, status updates, GL rewrites
- `on_cancel` — reference unlinking, linked document cleanup
- `on_change` — repost tracking (Repost Item Valuation)

One override class registered: `Stock Entry` → `BNSStockEntry` (component qty variance).

### Runtime Monkey Patches

Three patches applied on every request/job via `before_request` and `before_job` hooks. All are idempotent (guarded by sentinel flags). See `hooks.py` lines 435-442.

### Two-Phase Cutoff Model

Internal transfer GL mutations are gated by two dates in BNS Branch Accounting Settings:
1. **Internal Transfer Cutoff Date** (Phase 1) — gates transfer creation/linking
2. **Accounting Rewrite Cutoff Date** (Phase 2) — gates SLE incoming_rate sync and GL rewrite

**Critical rule:** SLE mutation and GL rewrite must always be gated identically. Never write standard fields without Phase 2 check.

### Internal Transfer Document Chains

- DN ↔ PR (stock movement only)
- SI ↔ PI (invoice only)
- SI → PR → PI (complex chain)
- DN → SI → PR → PI (full chain)

All linking/unlinking goes through whitelisted API endpoints in `bns_branch_accounting/utils.py`.

### Key Files by Size/Importance

| File | Lines | Purpose |
|------|-------|---------|
| `bns_branch_accounting/utils.py` | ~10K | 223 functions, 30 whitelisted APIs — core transfer logic |
| `bns_branch_accounting/common_party_squareoff.py` | ~24K | Auto square-off for common customer/supplier |
| `bns_branch_accounting/common_party_reconciliation.py` | ~17K | Party GL reconciliation |
| `bns_branch_accounting/gst_integration.py` | ~14K | e-waybill generation, GST validation |
| `bns_branch_accounting/migration.py` | ~13K | Post-migrate setup, GL structure rewrite |
| `bns_branch_accounting/srbnb_reconciliation.py` | ~14K | Internal transfer reconciliation |

### Fixtures

Custom Fields and Property Setters are exported as fixtures filtered by module ("Business Needed Solutions" or "BNS Branch Accounting"). Run `bench export-fixtures` after changing custom fields via UI.

### Scheduled Tasks

One daily scheduler event: `common_party_squareoff.scheduled_squareoff_run` — checks BNS Settings schedule (Disabled/Weekly/Monthly/Quarterly/Yearly) and runs if due.

### Frontend (public/js/)

21 JS files included via `app_include_js` with version query params. Major files:
- `sales_invoice_form.js` / `purchase_invoice_form.js` — internal transfer UI, document creation
- `delivery_note.js` / `purchase_receipt_form.js` — linking UI, status management
- `discount_manipulation_by_type.js` — triple compounded discount calculator
- `direct_print.js` — keyboard shortcut printing
- `pan_gstin_mismatch_banner.js` — compliance warning banners

After editing JS: bump the `?v=` version number in hooks.py and run `bench build`.

### Patches

Located in `business_needed_solutions/patches.txt`. Pre-model-sync patches run before doctype migration; post-model-sync after. Add new patches to the appropriate section.

### Print Formats

9 Jinja templates under `print_format/`. Configuration via BNS Settings Print Format child table. See `PRINT_FORMAT_GUIDE.md` for details.

### Reports

11+ Script Reports under `report/` directories in both modules. Each has a `.py` (data) and `.js` (filters/UI) file.

## Conventions

- Whitelisted API methods use `@frappe.whitelist()` and live in `bns_branch_accounting/utils.py`
- Override modules go in `overrides/` directories, one file per concern
- Bulk operations (>50 docs) must be enqueued async with batch size 10 and realtime progress events
- Amendment handling must re-map by `item_code + qty + rate`, not row IDs (stale after amend)
- Zero-rate items (samples) are skipped in transfer rate operations
