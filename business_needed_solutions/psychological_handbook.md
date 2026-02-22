# Business Needed Solutions — Psychological Handbook

## Architectural intent

- Keep internal-transfer behavior deterministic and direction-aware.
- Use one-way parent authority for cancellation in transfer chains.
- Avoid surprise data loss from child-side cancellation actions.

## Cancellation philosophy

- `Sales Invoice` and `Delivery Note` are parent-side commercial/dispatch sources.
- `Purchase Invoice` and `Purchase Receipt` are receiving mirrors.
- Parent cancel may cascade to receiving mirrors.
- Receiving-side cancel must never force parent cancellation.

## Current policy (implemented)

- Cancelling `Purchase Receipt` or `Purchase Invoice`:
  - Do not cancel linked `Delivery Note` / `Sales Invoice`.
  - Remove BNS inter-company links on cancel.
- Cancelling `Delivery Note`:
  - Cancel linked submitted `Purchase Receipt` records.
- Cancelling `Sales Invoice`:
  - Cancel linked submitted `Purchase Invoice` and `Purchase Receipt` records.

## Constraints and anti-patterns

- Do not implement bidirectional auto-cancel loops.
- Do not keep stale link references after cancellation.
- Do not rely on UI-only link actions for integrity; enforce on server hooks.
- Do not keep branch-accounting migration or internal-party guard logic in the generic app module; keep it under `bns_branch_accounting`.
- Do not rely on cache-only idempotency for critical repost paths where worker restart or race conditions can replay side effects.

## Change log

- Added asymmetric cancellation enforcement:
  - Hooked `before_cancel` for PR/PI to ignore parent backlink cancellation checks.
  - Hooked `on_cancel` for PR/PI to unlink references.
  - Hooked `on_cancel` for SI to cascade cancel linked purchase documents.
- Consolidated branch-accounting ownership:
  - `after_migrate` now points to `bns_branch_accounting.migration.after_migrate`.
  - Customer/Supplier internal-flag exclusivity moved to `bns_branch_accounting/overrides/internal_party.py`.
  - Bulk convert action moved from `BNS Settings` UI to `BNS Branch Accounting Settings` UI.
- Hardened repost execution semantics:
  - Repost lock is claimed before repost work starts.
  - Repost lock is always released in `finally` paths.
  - Processed state is persisted in `BNS Repost Tracking` for restart-proof idempotency.
- Extended transfer-rate authority from DN->PR to SI->PI/SI->PR stock flows:
  - Source-of-truth remains selling-side item `incoming_rate` (valuation mirror), never billing/net rate.
  - Receiving-side stock valuation is forced through `bns_transfer_rate` during SLE processing for both PR and PI.
  - Same anti-inflation rule now applies uniformly: internal transfer stock must preserve cost, not invoice value.
- Added SI repost propagation principle:
  - When SI valuation is reposted, downstream PI/PR `bns_transfer_rate` and valuation fields are synchronized and reposted.
  - Repost sequencing uses lock + processed tracking to prevent duplicate side effects in worker races/restarts.
- Hardened repost source-discovery principle:
  - Repost sync must resolve impacted source vouchers from multiple channels (direct transaction, affected transactions, and item+warehouse fallback scan).
  - This prevents missed SI/DN sources when repost context does not carry direct transaction references.
- Formalized DB-update behavior for valuation mirrors:
  - ERPNext updates SI item `incoming_rate` via DB-level writes during repost; document update hooks are not a reliable sync trigger.
  - Internal transfer-rate synchronization must remain bound to repost completion callbacks.
- Repost callback trigger policy updated:
  - For `Repost Item Valuation`, use `on_change` hooks to align with ERPNext status transitions performed through `db_set`.
  - Avoid relying on `on_update_after_submit` for repost completion flows that bypass save/update-after-submit lifecycle.
- Transfer-rate immediacy principle for SI->PI:
  - When PI item `bns_transfer_rate` changes due to SI valuation sync, PI stock ledger must be refreshed in the same sync flow.
  - Avoid delayed valuation drift by coupling transfer-rate mutation with immediate PI repost, except where repost orchestration is already in progress.
- Status authority reconciliation after repost:
  - ERPNext repost updates outstanding and invokes core `set_status()`, which can overwrite BNS statuses with `Unpaid/Overdue`.
  - Repost completion must re-assert `BNS Internally Transferred` for SI/PI that satisfy BNS internal-flow conditions.
- Immediate valuation consistency on PI transfer-rate updates:
  - When PI item `bns_transfer_rate` changes from SI sync, PI repost should run in the same execution path.
  - Avoid deferred SLE correction windows where item transfer-rate and PI stock valuation temporarily diverge.
- Repost lock portability:
  - Lock tracking must not depend on one DB-wrapper-specific API for affected-row detection.
  - Prefer graceful fallback so repost execution semantics remain consistent across environments.
- Ledger consistency closure:
  - PI transfer-rate correction is not complete until both SLE and GL are aligned to the same valuation authority.
  - Non-repost sync paths must still use valid lock/tracking identities so guarded repost execution cannot be skipped.
- Accounting finality after valuation sync:
  - For internal PI/SI flows, a deterministic GL rebuild is required immediately after SLE transfer-rate corrections.
  - Do not leave GL correction dependent on deferred repost queues when valuation authority has already changed.
- Schema-resilient scope detection:
  - Internal-flow scope checks should not assume optional GSTIN fields exist on every target doctype.
  - Fallback to linked source documents (SI) for GSTIN scope to preserve behavior across schema variants.
- PI rewrite parity principle:
  - PI GL rewrite must preserve ERPNext accounting skeleton (supplier, taxable, taxes, stock valuation) while swapping only internal-transfer legs.
  - Avoid shortcut adjustments that bypass full GL map generation.
- SI->PR valuation authority parity:
  - SI-linked PR must honor the same transfer-rate valuation authority as SI->PI for stock valuation legs.
  - For SI-linked PR, lock GL valuation leg to `Stock In Hand` debit vs `Stock In Transit` credit, without optional alternate routes.
- PR deterministic update sequence:
  - Treat PR transfer-rate changes as incomplete until PR item, PR SLE, and PR GL are all synchronized in one execution path.
  - Avoid relying on later repost side effects for accounting correctness.
- PI source-chain-aware accounting:
  - When PI is raised from PR in SI internal flow, PI should carry only settlement/tax accounting legs, not stock valuation legs.
  - Scope detection must include PR-linked SI inference, not only direct SI reference on PI header.
- DN->SI valuation propagation:
  - In repost contexts, DN valuation updates must be propagated to SI item `incoming_rate` for SI rows sourced from DN.
  - Treat SI `incoming_rate` as the continuity bridge for downstream SI->PR->PI transfer-rate synchronization.
- Chain completion invariant (DN->SI->PR):
  - DN-driven repost handling is incomplete unless SI->PR transfer-rate synchronization also executes for SIs touched by DN->SI incoming-rate updates.
  - Enforce contiguous propagation so PR `bns_transfer_rate`, SLE, and GL cannot remain on pre-repost values.
- PR-linked PI mirror policy:
  - In SI->PR->PI chains, PI item transfer-rate should still mirror upstream transfer-rate for consistency/reporting even when PI does not own stock valuation legs.
  - Allow PR-row linkage (`pr_detail`) as fallback source when direct SI-row mapping is absent.
- Debug instrumentation hygiene:
  - Runtime debug logs must use site-local paths, never developer-machine absolute paths.
  - Debug run identifiers should be dynamic to avoid false correlation across requests/runs.
- Migration correctness guarantee:
  - Post-migration setup must fail fast on unrecoverable top-level errors.
  - Avoid “log-only” failure handling that leaves partial setup while reporting successful migration completion.
