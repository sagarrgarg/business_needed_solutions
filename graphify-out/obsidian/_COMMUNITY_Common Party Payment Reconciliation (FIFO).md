---
type: community
cohesion: 0.04
members: 66
---

# Common Party Payment Reconciliation (FIFO)

**Cohesion:** 0.04 - loosely connected
**Members:** 66 nodes

## Members
- [[btn-full-pipeline-run]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[btn-reconcile-preview]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[btn-reconcile-run]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[Auto Payment Reconciliation (FIFO)]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Crossed Linked-Party Balance]] - document - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Full Square-Off Pipeline (pre-reconcile, squareoff, post-reconcile)]] - document - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[Per-party savepoint isolation]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Rationale FIFO allocation built-in; verified in ERPNext source lines 149-152 and 376-378]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Rationale PR before+after square-off closes specific invoices, not just GL totals]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Rationale cheap signed-balance prefilter skips parties with nothing to reconcile]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Rationale dashboard APIs gated behind Accounts Manager  System Manager]] - document - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[Rationale lazy import between reconciliation and squareoff to avoid circular import]] - document - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Rationale prefer _Test company so fixture JVs never taint shared production CoA; tag every JV with fixture remark for cleanup]] - document - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[Rationale scheduled cadence over PE hook (auditable, predictable)]] - document - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[Rationale sync up to SQUAREOFF_SYNC_BATCH_CAP (20), else enqueue long job]] - document - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[Rationale test isolation patches _list_companies_for_schedule AND _active_party_links so scheduler never sees production Party Link data on shared dev site]] - document - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[Reconciliation Scope (All vs Only-Linked vs Only-Crossed)]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[Reconciliation Window labels (All time  Last 2 FY  Since Cutoff)]] - document - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[TestCommonPartyReconciliation_1]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[TestCommonPartySquareOff_1]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[_fiscal_years_back()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_get_accounting_rewrite_cutoff_date()_1]] - code - business_needed_solutions/bns_branch_accounting/utils.py
- [[_get_reconcile_settings()_1]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[_iter_parties_for_scope()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_list_companies_for_schedule()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_party_account_has_balance()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_refresh_pair_balances()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_require_accounts_manager()_1]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[_resolve_window()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[_run_reconcile() squareoff wrapper]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[_run_reconcile_batch() RQ job]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[_run_scheduler_scoped (isolation harness)]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[_run_squareoff_or_enqueue()_1]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[_schedule_is_due()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[common_party_reconciliation.py_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[compute_linked_party_net_positions()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[execute_full_squareoff_pipeline()_1]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[execute_payment_reconciliation()_1]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[get_reconciliation_candidates()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[preview_payment_reconciliation()_1]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py
- [[preview_payment_reconciliation() JS]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[reconcile_all_parties()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[reconcile_single_party()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[run_full_squareoff_pipeline() JS]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[run_payment_reconciliation() JS]] - code - business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.js
- [[scheduled_squareoff_run()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[square_off_all_common_parties()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[square_off_linked_party()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_squareoff.py
- [[stamp_reconcile_last_run()_1]] - code - business_needed_solutions/bns_branch_accounting/common_party_reconciliation.py
- [[test_batch_runner_returns_summary]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_common_party_reconciliation.py_1]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[test_common_party_squareoff.py_1]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_detects_crossed_pair]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_historical_backfill_posting_date]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_no_crossed_pair_when_aligned]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_reconcile_all_parties_patched_scope_stays_on_test_company]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[test_reconcile_single_party_noop_when_only_one_side]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[test_reconciliation_candidates_picks_up_nonzero_balances]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[test_resolve_window_all_time]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[test_resolve_window_last_2_fy]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_reconciliation.py
- [[test_schedule_is_due_logic]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_scheduled_run_disabled_is_noop]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_scheduled_run_monthly_posts_when_due]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_scheduled_run_respects_interval]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_square_off_matched_amounts_to_zero]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py
- [[test_square_off_partial_leaves_residual]] - code - business_needed_solutions/bns_branch_accounting/test_common_party_squareoff.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Common_Party_Payment_Reconciliation_(FIFO)
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_GL Entry]]

## Top bridge nodes
- [[TestCommonPartySquareOff_1]] - degree 14, connects to 1 community
- [[scheduled_squareoff_run()_1]] - degree 8, connects to 1 community