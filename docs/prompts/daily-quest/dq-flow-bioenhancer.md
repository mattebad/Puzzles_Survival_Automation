# DQ-FLOW-BIOENHANCER

Repository authority: catalog owns `bioenhancer_research`; matrix owns policy/status; backlog owns task.
Exclude Main Quest Claim and all unrelated research.

Scope: Bioenhancer research. Reuse Daily inventory, research screen recognizers, safe action core,
and evidence-gated contract. Route: selected Daily row → direct Bioenhancer Research screen.
Source: selected `bioenhancer_research` row at 0/1 and research target; target: exact free
single research action; successor: research level/count changed and Daily 0→1 reconciliation.
Bind all recognizers to current frame.

Policy: supervised validation for the proven zero-cost single action; declare any resource cost
before future promotion. Transaction: one exact dispatch with bounded retry and unresolved-action
block. Postcondition: requested research confirmed. Recovery: fail closed on stale, missing
resource, ambiguous target, or mismatch.
Daily reconciliation maps `bioenhancer_research`; Claim independent. Persistence/scheduler dormant.

Tests: offline contract, source/target/successor replay, cost guard, dispatch cardinality,
negative Main recognition, and no registration/scheduler assertions. Bliss-native evidence required;
GnBots is provenance only. Navigation-only evidence may proceed through `pnsctl`; consequential
input for research requires explicit current-frame authorization and policy approval. Do not touch Research
10x, premium, paid, or Claim controls. No runtime registration or scheduler eligibility.
Current boundary: `tasks/bioenhancer.py` plus `tasks/daily_bioenhancer.py` implement the contract
and selected-Daily row binding. The supervised action
`bioenhancer-free-1784069057` is live confirmed: one Free Research 1x dispatch, zero cost,
quantity one, positive result/cooldown postcondition, and Research 10x untouched. Matrix status
is split as `BIOENHANCER_RESEARCH_CONFIRMED` and
`BIOENHANCER_DAILY_RECONCILIATION_PENDING`. The later selected-Daily inspection followed the
`daily-2026-07-14` reset and showed the exact row at `0/1`, so no same-day Claim-ready state is
asserted. Claim remains independent and unperformed; no registration or scheduler eligibility.
Canonical action evidence:
`evidence/sessions/20260714-bioenhancer-live-transaction/bioenhancer-free-1784069057-result.json`.
Commit:
`feat(tasks): validate Bioenhancer free research`.
