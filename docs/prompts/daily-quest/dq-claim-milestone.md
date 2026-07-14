# DQ-CLAIM-MILESTONE

Repository authority: catalog owns objective identity; matrix owns milestone Claim status and
policy; `BACKLOG.md` owns this task. Exclude Main Quest Claim and ordinary row Claim semantics.

Scope: activity Daily milestone chest Claim, independent from row completion. Reusable components:
selected Daily inventory, milestone recognition, safe action core, persistence contract. Route:
selected Daily screen → milestone chest. Source recognizer: Daily milestone progress; target:
milestone chest Claim control; successor: chest opened and milestone state advanced.

Bind source, target, and successor to current frame. Policy: explicit milestone authorization;
resource/transaction cost must be declared. Transaction: one exact chest dispatch with bounded
retry and unresolved-action blocking. Postcondition: requested milestone Claim confirmed, never
row Claim. Recovery: fail closed on stale, ambiguous, already-claimed, or Main-vs-Daily frames.

Daily reconciliation: milestone belongs to support flow, not catalog objective. Persistence and
scheduler dormant. Tests: milestone-vs-row separation, exact dispatch, successor proof, negative
Main recognition, and offline replay. Bliss evidence must show chest state; GnBots is provenance.
Future navigation read-only only. Prohibit ADB, live input/evidence, worker/VM changes, lease,
journal migration, registration, and scheduler eligibility. Update docs/matrix/status. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline.
