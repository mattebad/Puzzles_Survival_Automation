# DQ-FLOW-BIOENHANCER

Repository authority: catalog owns `bioenhancer_research`; matrix owns policy/status; backlog owns task.
Exclude Main Quest Claim and all unrelated research.

Scope: Bioenhancer research. Reuse Daily inventory, research screen recognizers, safe action core,
and evidence-gated contract. Route: Daily row → Bioenhancer research. Source: selected completed
row and research target; target: exact research action; successor: research level/count changed.
Bind all recognizers to current frame.

Policy: evidence-gated; declare any resource cost before future promotion. Transaction: one exact
dispatch with bounded retry and unresolved-action block. Postcondition: requested research
confirmed. Recovery: fail closed on stale, missing resource, ambiguous target, or mismatch.
Daily reconciliation maps `bioenhancer_research`; Claim independent. Persistence/scheduler dormant.

Tests: offline contract, source/target/successor replay, cost guard, dispatch cardinality,
negative Main recognition, and no registration/scheduler assertions. Bliss-native evidence required;
GnBots is provenance only. Future navigation read-only until promotion. Prohibit ADB, worker/VM,
lease/journal changes, live input/evidence, runtime registration, and scheduler eligibility.
Update matrix/status/docs. Commit: `docs(tasks): map every Daily objective to an execution task`.
Continue autonomous offline work.
