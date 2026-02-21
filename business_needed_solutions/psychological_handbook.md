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
