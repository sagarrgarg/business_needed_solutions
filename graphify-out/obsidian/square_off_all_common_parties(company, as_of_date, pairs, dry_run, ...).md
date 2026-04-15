---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L204-L237"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# square_off_all_common_parties(company, as_of_date, pairs, dry_run, ...)

## Connections
- [[compute_linked_party_net_positions(company, as_of_date)]] - `calls` [EXTRACTED]
- [[execute_common_party_squareoff(company, as_of_date, pair_keys, posting_date, cost_center)]] - `calls` [EXTRACTED]
- [[execute_historical_backfill(company, cutoff_date, pair_keys, cost_center)]] - `calls` [EXTRACTED]
- [[square_off_linked_party(pair, posting_date, cost_center, remark, submit)]] - `calls` [EXTRACTED]
- [[test_batch_runner_returns_summary]] - `calls` [EXTRACTED]
- [[test_historical_backfill_posting_date]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off