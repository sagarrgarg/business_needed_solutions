---
source_file: "business_needed_solutions/business_needed_solutions/page/bns_dashboard/bns_dashboard.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L1217-L1235"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# execute_common_party_squareoff(company, as_of_date, pair_keys, posting_date, cost_center)

## Connections
- [[_filter_pairs_by_keys(pairs, pair_keys)]] - `calls` [EXTRACTED]
- [[_require_accounts_manager()_1]] - `calls` [EXTRACTED]
- [[compute_linked_party_net_positions(company, as_of_date)]] - `calls` [EXTRACTED]
- [[post_common_party_squareoff() client method]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties(company, as_of_date, pairs, dry_run, ...)]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off