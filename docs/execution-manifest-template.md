# Compact execution manifest

## Task ID and objective
- Task ID: `<stable task identifier>`
- Objective: `<one-sentence objective>`

## Frozen stage control
- Host: `<cursor | codex | other>`
- Parent conversation ID: `<stable host conversation identifier>`
- `control_plane_owner`: `sol_parent`
- Revision ID: `<immutable revision identifier>`
- Stage type: `<implementation | repair | live | ...>`
- Product precondition: `<proven | not_applicable | evidence_required | failed>`
- Failure class: `<product_state | core_contract | local_defect | process_state | none>`
- Stage start UTC: `<RFC 3339 UTC milliseconds or not recorded>`
- Continuation checkpoint UTC: `<RFC 3339 UTC milliseconds or not recorded>`
- Model values must be exact usage-export slugs including reasoning level, for
  example `gpt-5.6-sol-high`, not display names.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `<exact Sol slug>` | `<stage freeze, acceptance, live, termination>` |
| `procedure_coordinator` | `<exact Luna slug or not used>` | `<optional checklist assistance only>` |
| `bounded_implementer` | `<exact Luna slug or not used>` | `<assigned paths only>` |
| `independent_tester` | `<exact Terra slug or not used>` | `<read-only review/recheck>` |
| `escalation_architect` | `<exact Sol slug or not used>` | `<architecture conflicts only>` |

## Immutable budgets
- Per stage: one implementation, one review, at most one repair and one
  recheck, one live attempt.
- Per parent conversation: at most three stage revisions and eight managed
  turns.
- Timing: visible checkpoint at 60 minutes; at 90 minutes require recorded
  user continuation later than the stage start.

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

## Evidence/history references
- `<pointer to compact development-session or retained evidence records>`

## Escalation conditions
- Approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Ordinary test failures, syntax errors, and known repairs do not escalate.
