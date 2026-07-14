# DQ-FLOW-CAMPAIGN-AP

Repository authority: catalog owns `consume_ap`; matrix owns resource policy/status; backlog owns task.
Main Quest Claim excluded.

Scope: Consume 20 AP through Campaign route. Reuse Daily inventory, AP counter, Campaign
navigation, safe action core. Route: Daily row → Campaign → eligible AP action. Source: completed
row and current AP; target: exact AP-consuming action; successor: AP delta and row progress.
Bind source/target/successor to current frame.

Policy: evidence-gated material resource use; explicit AP budget required. Transaction: one bounded
action dispatch, unresolved-action block. Postcondition: exact AP consumption confirmed without
exceeding budget. Recovery: fail closed on stale AP, missing target, budget mismatch, or absent
successor. Daily maps `consume_ap`; Claim independent. Persistence/scheduler dormant.

Tests: AP budget guard, offline replay, route identity, cardinality, successor proof, Main negative,
registration false, scheduler false. Bliss-native evidence required; GnBots cannot authorize.
Future navigation read-only. Prohibit ADB, worker/VM, leases, journal migration, live input/evidence,
registration, scheduler eligibility. Update docs/matrix/status. Commit:
`feat(tasks): add Campaign AP offline contract`. Current boundary: `tasks/campaign_ap.py` plus
`tasks/daily_campaign_ap.py` and `tests/test_daily_campaign_ap.py` cover selected-Daily binding,
bounded Sweep/Auto Complete semantics, exact AP/progress deltas, and pure replay; fresh
Bliss-native Campaign target, AP cost, and positive result remain required for promotion. Continue
offline.
