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

## 2. Business Reasoning

### 2.1 Submission Restriction

**Intent:** Allow users to create drafts but restrict who can submit. Supports approval workflows and segregation of duties.

**Constraint:** Override roles must be explicitly granted. Do not bypass this for "convenience."

### 2.2 BNS Internal Transfer

**Intent:** Model inter-branch transfers (same legal entity, different locations) with:

- DN → PR (stock movement)
- SI → PI (invoice flow)
- Correct GL: Stock in Transit, Internal Transfer Account, Internal Branch Debtor Account

**Constraint:** `is_bns_internal_customer` and `is_bns_internal_supplier` are the source of truth. Do not introduce parallel flags.

### 2.2a Billing Location → Customer Address

**Intent:** For BNS internal customers, billing location drives customer address (like location_based_series for company address). On save, server sets customer_address from billing_location's linked address; customer_address is read-only when both are set. For outside customers, billing_location and customer_address are independent—customer_address remains editable.

**Constraint:** Only apply auto-update and read-only when `is_bns_internal_customer` is true. Do not extend this logic to outside customers.

### 2.3 Same-GSTIN Purchase Invoice Block

**Intent:** Prevent self-invoicing when Supplier GSTIN = Company GSTIN. GST does not allow this.

**Constraint:** Validation runs on validate; GSTIN is resolved from doc or from Company/Supplier addresses. Do not skip when India Compliance is present.

### 2.4 Stock Update vs. Reference

**Intent:** When SI/PI do not update stock, every stock item must trace back to DN/PR. Ensures audit trail.

**Constraint:** Do not relax this for "special cases" without explicit business approval.

### 2.5 Per-Warehouse Negative Stock

**Intent:** Some warehouses (e.g. retail) must never go negative; others (e.g. manufacturing) may. ERPNext's global setting is insufficient.

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

---

## 6. Module Boundaries

| Module | Responsibility | Do not |
|--------|-----------------|--------|
| `overrides/` | Validation, enforcement | Business logic for DN/PR/SI/PI creation |
| `bns_branch_accounting/utils.py` | Internal transfer logic, status, conversion | GST validation, submission restriction |
| `gst_compliance.py` | GST validations, e-Waybill | Internal transfer accounting |
| `business_needed_solutions/utils.py` | Re-exports, shared helpers | Core BNS internal logic (moved to bns_branch_accounting) |

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
