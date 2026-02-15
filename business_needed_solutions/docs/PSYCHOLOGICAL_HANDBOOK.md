# Business Needed Solutions (BNS) — Psychological Handbook

> **Purpose:** Documents the *why* behind each feature — user need, business context, design intent, and rationale. For future you (or any developer) who asks: "Why did we build it this way?"
>
> **Version:** 1.0 — Created 2026-02-15
> **Companion:** [TECHNICAL_HANDBOOK.md](./TECHNICAL_HANDBOOK.md) — the "what" and "how"

---

## Why This Document Exists

Code tells you *what* and *how*. It rarely tells you *why*. When you revisit a module months later, you forget:

- Which real-world pain drove the design
- Which tradeoffs were deliberate vs accidental
- What you would do differently if you started again

This handbook captures that context so future you (or a new developer) can understand intent before changing code.

---

## Core Philosophy

1. **Business-first, not tech-first** — Every feature exists because a user or business process needed it. If a module has no clear "who benefits and how," it's tech debt.
2. **Indian compliance is non-negotiable** — GST, PAN, FSSAI, MSME, e-Waybill — these aren't "nice to have." They're legal requirements. BNS exists to make ERPNext usable for Indian businesses without constant manual hacks.
3. **Control over process** — Submission restriction, preferred address suppression, BOM enforcement — all serve the same goal: the business decides *how* documents flow, not the system's defaults.
4. **Minimal invasiveness** — Prefer hooks and overrides over forking ERPNext. Easier to upgrade, easier to reason about.

---

## Feature Intent Map

### BNS Branch Accounting

**Why it exists:**  
ERPNext's built-in inter-company workflow assumes different legal entities with different GSTINs. Many Indian businesses have:

- Same company, multiple branches (same GSTIN)
- Or: multiple companies in a group that transfer goods internally (different GSTIN)

The standard flow (SI → PI for inter-company, DN → PR for branch) doesn't fit. Billing, per_billed, and status get messy. BNS replaces it with a single mental model: "BNS Internally Transferred" — we've moved goods internally; no external billing needed; we track DN↔PR and SI↔PI ourselves.

**What we're really solving:**  
*"Our branches transfer stock to each other. We don't want to create invoices. We want to see DN and PR linked, and we want e-Waybill when needed. The default ERPNext flow is wrong for us."*

**Design choices (and why):**

- **Bidirectional reference** — So you can navigate either way. DN shows PR, PR shows DN. No orphan links.
- **Same-GSTIN = no invoice** — Per_billed 100 on DN so ERPNext doesn't nag about billing. We know it's internal.
- **Bulk convert** — Migrating hundreds of old DN/PR/SI/PI to BNS internal status. One-time need, but critical for adoption.
- **Vehicle/transporter mandate for internal DN** — E-Waybill rules require it for movement above threshold. We enforce at submit so you can't forget.

---

### Submission Restriction

**Why it exists:**  
Only certain roles should be able to submit documents. Others can draft, but submission = commitment. Common in manufacturing, finance, and controlled environments.

**What we're really solving:**  
*"Our shop-floor can create Delivery Notes. Only the manager should submit. Same for Sales Invoice — only accounts can submit."*

**Design choices (and why):**

- **Single toggle + override roles** — Simple. One setting: "restrict or not." Override roles bypass. The three-category system (stock/transaction/order) in the code was never wired to separate toggles — it's architectural debt, but the core need is met.
- **Draft-all-you-want** — Users can still create and edit. Only Submit is blocked. Matches how businesses actually work.

---

### Triple Discount (D1/D2/D3)

**Why it exists:**  
Indian B2B sales often use cascading discounts: base discount, volume discount, early-payment discount. ERPNext has a single `discount_percentage`. We needed three.

**What we're really solving:**  
*"We quote with D1=10%, D2=5%, D3=2%. The customer sees one effective rate. We need to record all three for audit and margin analysis."*

**Design choices (and why):**

- **Cascade rule** — D2 readonly until D1 > 0; D3 until D1 and D2. Prevents invalid states (e.g., D2 without D1).
- **Rate read-only in Triple mode** — Rate is computed. You can't override it manually without breaking the formula. Intentional.
- **Purchase side excluded** — Our clients negotiate discounts on sales. Purchase follows different logic. We didn't over-engineer.
- **Property Setters from BNS Settings** — Visibility is dynamic. Switch to Single mode, D1/D2/D3 hide. No code deploy needed.

---

### Custom Update Items (SO/PO)

**Why it exists:**  
ERPNext's "Update Items" on submitted SO/PO is limited. We needed: triple discounts, UOM restrictions, item code changes, reserved stock awareness, subcontracting FG handling.

**What we're really solving:**  
*"We submitted the Sales Order. The customer changed the item. We need to update the SO without cancelling and recreating. And we use D1/D2/D3 and specific UOMs."*

**Design choices (and why):**

- **Replace, don't extend** — We replaced the Update Items button and dialog entirely. Cleaner than patching ERPNext's JS in 10 places.
- **Server-side validation** — Quantities, UOMs, workflow, subcontracting — all revalidated. Client can't lie.
- **No transaction lock** — Race condition risk if two users update same SO/PO at once. Known tradeoff; locking adds complexity. For low-concurrency use, acceptable.

---

### Per-Warehouse Negative Stock

**Why it exists:**  
Global "Allow Negative Stock" is all-or-nothing. Some warehouses (e.g., production floor) might allow negative; others (e.g., finished goods) must not.

**What we're really solving:**  
*"We allow negative in WIP. We never want negative in our main store. One setting for the whole system isn't enough."*

**Design choices (and why):**

- **Monkey patches at app init** — We couldn't add a hook to ERPNext's stock ledger easily. Patches run before any transaction. Invasive, but effective.
- **Triple validation** — Overkill, but defensive. Each of the three points catches slightly different code paths. We'd simplify if we could, but removing one might leave a gap.
- **Known bugs** — BNS-NEG-001, BNS-NEG-002. The logic has flaws. Use with caution; fix when time permits.

---

### GST Compliance & E-Waybill

**Why it exists:**  
Internal movement of goods above threshold requires e-Waybill. India Compliance handles generation; we handle "when to enforce" and "when to auto-generate."

**What we're really solving:**  
*"When we transfer between branches, we need e-Waybill. We don't want to remember — generate it on submit. And don't let us submit without vehicle/transporter when required."*

**Design choices (and why):**

- **Part A only: gst_transporter_id sufficient** — Vehicle number not always available at DN creation. Transporter ID from Part A is enough per India Compliance. We aligned with that.
- **Failure = warning, not block** — E-Waybill API can fail (network, invalid data). We don't block DN submit. User gets a warning; they can retry or fix manually. Blocking would hurt operations.
- **enable_internal_dn_ewaybill in Branch Accounting Settings** — It's a branch-accounting flow setting. Moved from BNS Settings to keep config closer to the feature.

---

### PAN Validation

**Why it exists:**  
Duplicate PAN across Customers/Suppliers causes GST and compliance issues. One PAN = one party identity.

**What we're really solving:**  
*"We had two suppliers with the same PAN. Our GST return failed. We need to block duplicates at save."*

**Design choices (and why):**

- **Same-doctype only (for now)** — We check Customer vs Customer, Supplier vs Supplier. Not Customer vs Supplier. Cross-doctype would catch more but adds complexity. Known gap.
- **No format validation** — We don't validate PAN format (5 letters + 4 digits + 1 letter). We could; we didn't. Low priority.

---

### BOM Enforcement & Variance

**Why it exists:**  
Manufacturing without BOM leads to wrong quantities, wrong costing. And strict equality (BOM says 10.0, you enter 10.01 → error) is impractical for real production (wastage, rounding).

**What we're really solving:**  
*"We must use BOM for manufacture. But we allow ±2% variance on some components. ERPNext's all-or-nothing doesn't work."*

**Design choices (and why):**

- **Override Stock Entry class** — Only way to intercept BOM validation. Hook wasn't enough.
- **from_bom mandatory when enforce_bom** — Prevents "BOM attached but not used" confusion.
- **Per-item variance from BOM Item** — Some components are strict (e.g., catalyst); others flexible (e.g., packing). BOM Item.bns_variance_qty allows that.
- **Client-side mandatory field** — Red field highlight before save. Better UX than server-side throw.

---

### Address Preferred Flags Suppression

**Why it exists:**  
ERPNext auto-selects "Preferred Billing" and "Preferred Shipping" addresses. When you use Location-Based Series or internal transfers, you want address selection driven by Location/link, not these flags. Showing them confuses users; setting them causes wrong behavior.

**What we're really solving:**  
*"We pick address by Location. We don't want Preferred Billing/Shipping. Hiding them and forcing 0 keeps the system consistent."*

**Design choices (and why):**

- **Property Setter + before_save enforce** — Hide the fields; on save, force 0. Even if someone sets them via API or import, we override. Defense in depth.
- **Clear Preferred Flags bulk** — One-time cleanup for existing addresses that had 1 set. Gets everyone to a clean state.

---

### Food Company & FSSAI License

**Why it exists:**  
FSSAI license number must appear on bills/invoices for food businesses in India. Not all companies are food companies. Not all addresses need it. We need a lightweight way to capture it and show it only when relevant.

**What we're really solving:**  
*"We're a food company. Our bills need FSSAI number. We have multiple company addresses. Each branch might have its own license. We want the field only when it applies."*

**Design choices (and why):**

- **Company: Is a Food Company** — Simple flag. Under MSME fields because it's another compliance-ish attribute. Doesn't clutter the main Company form.
- **Address: FSSAI License No.** — Stored on Address because different addresses (branches) can have different licenses. Company-level would be wrong for multi-branch.
- **Client Script for visibility** — `depends_on` can't reference Company from Address (link is in Dynamic Link child). We fetch Company.bns_is_food_company and show/hide the field. Clean separation.
- **No print format change** — User adds FSSAI to bill copy themselves. We don't own print formats; keeps scope small.

---

### Direct Print System

**Why it exists:**  
Default Print button uses default format. Businesses have specific formats (invoice copy 1/2/3, different layouts). BNS Settings lets them map doctype → format. And Sales Invoice gets copy selection (Original, Duplicate, etc.).

**What we're really solving:**  
*"We need Invoice Copy 1 for recipient, Copy 2 for transporter. And we use a different print format than the default. One place to configure it."*

---

### Location Backfill

**Why it exists:**  
Location-Based Series adds billing_location and dispatch_location to SI/DN. Old documents don't have them. One-time backfill uses Location.linked_address to populate from customer_address / dispatch_address_name.

**What we're really solving:**  
*"We installed Location Based Series. Our old invoices don't have billing_location. We need a script to fill them so reports work."*

---

## Patterns & Principles

### When to Use Hooks vs Override

- **Hooks (doc_events)** — Use when you need to run logic at a specific lifecycle moment (validate, on_submit, before_save). Low risk, easy to disable.
- **Override class** — Use when you must change core validation (e.g., BOM). Last resort; harder to maintain across upgrades.
- **Monkey patch** — Use only when no hook exists and override isn't suitable (e.g., stock ledger). Document well; test upgrades carefully.

### When to Use Client Script vs Server

- **Client** — UX (show/hide, mandatory highlight, cascading fields). Fast feedback. Don't trust for security.
- **Server** — Validation, permissions, data integrity. Always revalidate on server what you "validated" on client.

### When to Add a Custom Field vs Use Existing

- **Custom field** — When the concept doesn't exist in ERPNext (FSSAI, D1/D2/D3, bns_is_food_company). Or when we need to control visibility separately (BNS Settings toggles).
- **Use existing** — When ERPNext already has it (e.g., vehicle_no, transporter). Don't duplicate.

### When to Put Something in BNS Settings vs Its Own DocType

- **BNS Settings** — Global toggles, single-value config (e.g., restrict_submission, discount_type). One place for "how BNS behaves."
- **Own DocType** — When it's not a toggle but entity data (e.g., BNS Branch Accounting Settings, Print Format mapping as child table).

---

## For Future You

When you add a new feature:

1. **Add to this handbook** — One paragraph: what problem it solves, for whom, and one key design choice + why.
2. **Don't skip the "why"** — "We did X because Y" saves hours of archaeology later.
3. **Call out tradeoffs** — "We didn't do Z because it would require W; we accepted the limitation."
4. **Date it** — Versions matter. When you change rationale, note it.

When you refactor:

1. **Check this handbook first** — If the intent has changed, update it. Dead intent = misleading handbook.
2. **Preserve intent in comments** — If you simplify code, a one-line comment "BNS: per-address FSSAI for multi-branch" helps.

When you're stuck:

1. **Read the Psychological Handbook** — Then the Technical Handbook. Intent before implementation.
2. **Ask: "What would break if we removed this?"** — If nothing obvious, it might be dead code or wrong abstraction.

---

*End of Psychological Handbook*
