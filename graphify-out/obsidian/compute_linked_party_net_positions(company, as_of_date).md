---
source_file: "business_needed_solutions/bns_branch_accounting/common_party_squareoff.py"
type: "code"
community: "Common Party GL Square-Off"
location: "L58-L122"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Common_Party_GL_Square-Off
---

# compute_linked_party_net_positions(company, as_of_date)

## Connections
- [[_PARTY_ROLES = (Customer, Supplier)]] - `references` [EXTRACTED]
- [[_active_party_links()_1]] - `calls` [EXTRACTED]
- [[_get_party_signed_balance(party_type, party, account, company, as_of_date)]] - `calls` [EXTRACTED]
- [[_pair_key()_1]] - `calls` [EXTRACTED]
- [[execute_common_party_squareoff(company, as_of_date, pair_keys, posting_date, cost_center)]] - `calls` [EXTRACTED]
- [[execute_historical_backfill(company, cutoff_date, pair_keys, cost_center)]] - `calls` [EXTRACTED]
- [[preview_common_party_squareoff(company, as_of_date) whitelisted]] - `calls` [EXTRACTED]
- [[preview_historical_backfill(company, cutoff_date)]] - `calls` [EXTRACTED]
- [[square_off_all_common_parties(company, as_of_date, pairs, dry_run, ...)]] - `calls` [EXTRACTED]
- [[test_detects_crossed_pair]] - `calls` [EXTRACTED]
- [[test_no_crossed_pair_when_aligned]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Common_Party_GL_Square-Off