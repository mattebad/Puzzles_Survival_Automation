# Compact execution manifest

## Task ID and objective
- Task ID: `<stable task identifier>`
- Objective: `<one-sentence objective>`

## Execution routing and timing
- Host: `<cursor | codex | other>`
- Parent conversation ID: `<stable host conversation identifier>`

| Role | Model | Agent/session ID | Started UTC | Completed UTC |
| --- | --- | --- | --- | --- |
| `architecture_planner` | `<resolved model>` | `<identifier>` | `<ISO-8601 UTC>` | `<ISO-8601 UTC>` |
| `execution_coordinator` | `<resolved model>` | `<identifier>` | `<ISO-8601 UTC>` | `<ISO-8601 UTC>` |
| `bounded_implementer` | `<resolved model or not used>` | `<identifier or not used>` | `<ISO-8601 UTC or not used>` | `<ISO-8601 UTC or not used>` |
| `independent_tester` | `<resolved model or not used>` | `<identifier or not used>` | `<ISO-8601 UTC or not used>` | `<ISO-8601 UTC or not used>` |
| `escalation_architect` | `<resolved model or not used>` | `<identifier or not used>` | `<ISO-8601 UTC or not used>` | `<ISO-8601 UTC or not used>` |

## Frozen architecture decision
- Decision: `<accepted architecture and rationale>`
- Preserved invariants: `<safety, runtime, Git, validation, and evidence boundaries>`

## Writable paths
- `<exact production paths>`
- `<exact test paths>`
- `<exact documentation paths>`

## Acceptance checks
- `<check and expected receipt>`

## Safety limits
- Allowed actions: `<bounded actions>`
- Disallowed actions: `<unsupported or prohibited actions>`
- Runtime/session limits: `<singleton, input, and consequential-action limits>`

## Validation commands
- `<focused deterministic command>`
- `<required architecture or integration gate>`

## Live budget
- Live admission: `<authorized | not authorized>`
- Input budget: `<bounded count or zero>`
- Iteration budget: `<bounded count>`

## Evidence references
- `<source, immediate-before, transport, immediate-post, semantic, or test receipt>`

## Escalation conditions
- Approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Ordinary test failures, syntax errors, and known repairs do not escalate.

## Next authorized action
- `<single action authorized by this manifest>`
