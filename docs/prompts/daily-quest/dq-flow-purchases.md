# DQ-FLOW-PURCHASES

Repository authority: catalog owns `buy_box`, `ruins_shop_purchase`, `rare_earth_shop_purchase`,
`alliance_shop_purchase`; matrix owns disabled policy/status; backlog owns task. Main Quest Claim
excluded.

Scope: parameterized shop identity; preserve four distinct objective keys and exact shop variants.
Route: Daily row → declared shop. Source: row, shop, item; target: exact purchase control;
successor: inventory/currency/shop state. Bind all to current frame.

Policy: DISABLED_POLICY; no currency transaction, live input, registration, or scheduler eligibility.
Parameterized shop/offer/cost contract is implemented in `tasks/purchases_disabled.py` for all four
variants; every purchase dispatch remains blocked. Postcondition: offline contract proves no
purchase. Recovery: fail closed on shop/item/currency/stale-frame ambiguity. Daily reconciliation
preserves shops; Claim independent. Persistence dormant.

Tests: `tests/test_purchases_disabled.py` covers four-way shop-variant separation, disabled
validator, no registry, scheduler false, offline cost/inventory arithmetic, Main/ambiguous
negatives, and Claim separation. Bliss/GnBots cannot override policy. Future navigation read-only.
Update docs/matrix/status. Commit: `feat(tasks): add disabled purchase contracts`. Continue offline.
