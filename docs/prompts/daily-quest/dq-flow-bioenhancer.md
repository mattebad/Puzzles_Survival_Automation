# DQ-FLOW-BIOENHANCER

Repository authority: catalog owns `bioenhancer_research`; matrix owns policy/status; backlog owns task.
Exclude Main Quest Claim and all unrelated research.

Scope: Bioenhancer research. Reuse Daily inventory, research screen recognizers, safe action core,
and evidence-gated contract. Route: selected Daily row → direct Bioenhancer Research screen.
Source: selected `bioenhancer_research` row at 0/1 and research target; target: exact free
single research action; successor: research level/count changed and Daily 0→1 reconciliation.
Bind all recognizers to current frame.

Policy: evidence-gated; declare any resource cost before future promotion. Transaction: one exact
dispatch with bounded retry and unresolved-action block. Postcondition: requested research
confirmed. Recovery: fail closed on stale, missing resource, ambiguous target, or mismatch.
Daily reconciliation maps `bioenhancer_research`; Claim independent. Persistence/scheduler dormant.

Tests: offline contract, source/target/successor replay, cost guard, dispatch cardinality,
negative Main recognition, and no registration/scheduler assertions. Bliss-native evidence required;
GnBots is provenance only. Navigation-only evidence may proceed through `pnsctl`; consequential
input for research requires explicit current-frame authorization and policy approval. Do not touch Research
10x, premium, paid, or Claim controls. No runtime registration or scheduler eligibility.
Current boundary: `tasks/bioenhancer.py` plus `tasks/daily_bioenhancer.py` implement the offline
contract and selected-Daily row binding. Bliss-native navigation and pre-dispatch evidence is
retained at `evidence/sessions/20260714-daily-flow-acquisition/bioenhancer-free-pre-dispatch.json`;
the flow is `PRE_DISPATCH_READY` but matrix promotion remains `EVIDENCE_GATED` pending game-day
identity, explicit approval, one supervised free-research result, and Daily 0→1 reconciliation.
Claim remains independent. Continue with Supply Depot navigation-only evidence if approval is
unavailable. Commit:
`docs(evidence): capture Bioenhancer free-action pre-dispatch boundary`.
