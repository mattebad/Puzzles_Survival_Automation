# Optional implementation notes

This document replaces the retired model-specific execution template. It is an optional
human-readable note format, not a required development gate or a machine-readable admission
manifest. Do not create a participant registry, routing matrix, receipt, queue, or controller
from it. Ordinary offline work follows [AGENTS.md](../AGENTS.md) and the existing task contract.

Record only information useful for the actual change:

- Task and objective: the defect or requested outcome.
- Scope and non-goals: exact affected paths and boundaries that must remain unchanged.
- Decision: the chosen correction and why it fits existing contracts.
- Acceptance: observable behavior and important failure cases.
- Verification: exact focused commands, results, and limits of the evidence.
- Remaining risks: unresolved findings or genuinely missing prerequisites.
- References: existing issue, PR, contract, and immutable evidence locations.

These notes do not select models, agents, reviewers, stage sequences, or repair budgets.
They must not duplicate runtime state or imply that a completed checklist authorizes input.

Live work is separate: it requires explicit current authorization and every safety check
required by the applicable existing controller/flow contract, including ownership, leases,
fencing, unresolved-action handling, evidence, and input limits. This optional format cannot
replace a structured record required by an existing runtime command. See
[validation boundaries](flow-delivery-validation-policy.md) and
[execution ownership](chat-execution-ownership-policy.md).

Original model-specific execution records are retained under [archive/](archive/README.md)
as non-authoritative history.
