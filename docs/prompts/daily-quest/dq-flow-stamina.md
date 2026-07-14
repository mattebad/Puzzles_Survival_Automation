# DQ-FLOW-STAMINA

Repository authority: catalog owns `consume_stamina`; matrix owns disabled policy/status; backlog owns
task. Main Quest Claim excluded.

Scope: Consume 20 Stamina. Reuse world/stamina accounting primitive only for offline contract.
Route: Daily row → future eligible world action. Source: current row and stamina counter; target:
declared stamina-consuming action; successor: exact counter delta and progress. Bind all to a
current frame in any future implementation.

Policy: DISABLED_POLICY. Transaction and resource use prohibited during planning and future work
until product approval. Offline contract is implemented in `tasks/stamina_disabled.py`: it
recognizes selected-Daily stamina-counter evidence, verifies same-day counter arithmetic, and
blocks every dispatch request. Postcondition must prove no live dispatch. Recovery: fail closed on
any authorization or budget ambiguity. Daily maps `consume_stamina`; Claim separate.
Persistence/scheduler dormant.

Tests: `tests/test_stamina_disabled.py` covers disabled-flow validation, no registry entry,
scheduler false, offline counter contract, Main/static negatives, and Claim separation. Bliss
evidence cannot override policy; GnBots cannot authorize.
Future navigation read-only only. Prohibit runtime registration, scheduler eligibility, ADB, live
input/evidence, worker/VM, leases, journal migration. Update matrix/status/docs. Commit:
`docs(tasks): map every Daily objective to an execution task`. Continue offline; stop only on
policy contradiction.
