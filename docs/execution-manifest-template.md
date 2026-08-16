# Compact execution manifest

## Task ID and objective
- Task ID: `<stable task identifier>`
- Objective: `<one-sentence objective>`

## Execution routing and timing
- Host: `<cursor | codex | other>`
- Parent conversation ID: `<stable host conversation identifier>`
- Model values must be exact usage-export slugs including reasoning level, for
  example `gpt-5.6-sol-high`, not display names such as `GPT-5.6 Sol`.
- Record start immediately before invocation and completion immediately after
  return as RFC 3339 UTC milliseconds (`YYYY-MM-DDTHH:MM:SS.sssZ`).
- Never infer an unknown execution timestamp. Use `not recorded`, then populate
  usage-event UTC from an exact retained CSV match when available.

| Role | Exact model slug | Agent/session ID | Started UTC | Completed UTC | Usage-event UTC |
| --- | --- | --- | --- | --- | --- |
| `architecture_planner` | `<exact slug>` | `<identifier>` | `<RFC3339 UTC milliseconds>` | `<RFC3339 UTC milliseconds>` | `<matched UTC value(s) or pending>` |
| `execution_coordinator` | `<exact slug>` | `<identifier>` | `<RFC3339 UTC milliseconds>` | `<RFC3339 UTC milliseconds>` | `<matched UTC value(s) or pending>` |
| `bounded_implementer` | `<exact slug or not used>` | `<identifier or not used>` | `<UTC or not used>` | `<UTC or not used>` | `<matched UTC or not used/pending>` |
| `independent_tester` | `<exact slug or not used>` | `<identifier or not used>` | `<UTC or not used>` | `<UTC or not used>` | `<matched UTC or not used/pending>` |
| `escalation_architect` | `<exact slug or not used>` | `<identifier or not used>` | `<UTC or not used>` | `<UTC or not used>` | `<matched UTC or not used/pending>` |

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
