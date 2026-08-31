# Compact execution manifest

Use this frozen manifest only for the STEP_BACK redesign, architecture,
cross-contract, or safety-boundary case. Routine live flow delivery uses
`pnsctl conduct <flow_id>` and conductor-owned state under
`.local-orchestrator/conductor/`; the human-readable framing notes may still
follow [`flow-attempt-ledger-template.md`](flow-attempt-ledger-template.md).
Do not freeze a new Heavy manifest per local defect.

## Task ID and objective
- Task ID: `<stable task identifier>`
- Objective: `<one-sentence objective>`

## Frozen stage control
- Host: `<cursor | codex | other>`
- Parent conversation ID: `<stable host conversation identifier>`
- `control_plane_owner`: `sol_parent`
- Revision ID: `<immutable revision identifier>`
- Stage type: `<implementation | repair | live | ...>`
- Review class: `<sol | sol_plus_terra>`
- Review rationale: `<which exact boundary criteria select this class>`
- Product precondition: `<proven | not_applicable | evidence_required | failed>`
- Failure class: `<product_state | core_contract | local_defect | process_state | diminishing_returns | none>`
- Stage start UTC: `<RFC 3339 UTC milliseconds or not recorded>`
- Final clean candidate content fingerprint: `<immutable fingerprint bound to review evidence and admission>`
- Final parent Sol integration acceptance: `<accepted only after all authorized repairs and required Terra evidence for sol_plus_terra; last acceptance gate before live admission; bound to the fingerprint above>`
- Model values must be exact usage-export slugs including reasoning level, for
  example `gpt-5.6-sol-high`, not display names.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `<exact Sol slug>` | `<stage freeze, initial/final acceptance, live, termination>` |
| `procedure_coordinator` | `<exact Luna slug or not used>` | `<optional checklist assistance only>` |
| `bounded_implementer` | `<exact Luna XHigh slug>` | `<one implementation/self-check and at most one repair; assigned paths only>` |
| `independent_tester` | `<exact Terra slug if sol_plus_terra; not used for sol>` | `<mandatory conditional sol_plus_terra read-only review and one recheck only after repair; must precede final Sol acceptance>` |
| `escalation_architect` | `<exact Sol slug or not used>` | `<architecture conflicts only>` |

## Immutable budgets
- Per stage: one Luna XHigh implementation/self-check, one bounded initial
  parent Sol diff/acceptance review, at most one consolidated Luna repair, and
  one live attempt. For `sol_plus_terra`, the conditional Terra review and,
  if a repair occurs, one Terra recheck must complete. After all authorized
  repairs and required Terra evidence, the final parent Sol integration
  acceptance must be recorded as the last acceptance gate before live
  admission and bound to the final clean candidate content fingerprint. `sol`
  has no Terra step but still requires the fingerprint-bound final acceptance.
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
- Record the final clean candidate content fingerprint and the final parent Sol
  integration acceptance bound to it. For `sol_plus_terra`, acceptance is valid
  only after the required Terra review/recheck evidence; Solo cannot bypass this
  gate.

## Safety limits
- Allowed actions: `<bounded actions>`
- Disallowed actions: `<unsupported or prohibited actions>`
- Runtime/session limits: `<singleton, input, and consequential-action limits>`

## Validation commands
- `<focused deterministic command>`
- `<initial parent Sol diff/acceptance review; for sol_plus_terra, Terra review/recheck must precede final fingerprint-bound parent Sol integration acceptance>`

## Live budget
- Live admission: `<authorized only after required evidence and final fingerprint-bound Sol integration acceptance | not authorized>`
- Input budget: `<bounded count or zero>`
- Iteration budget: `<bounded count>`
## Evidence/history references
- `<pointer to compact development-session or retained evidence records>`

## Escalation conditions
- Approved plan is contradictory or incomplete.
- A genuinely new architecture decision is required.
- Safety authority is ambiguous.
- For `sol_plus_terra`, Terra and implementation evidence conflict; or the
  parent Sol review conflicts with implementation evidence; or required Terra
  evidence is missing before final fingerprint-bound Sol acceptance.
- Two materially different repair hypotheses fail.
- Live evidence disproves the accepted design.
- Convergence stalled (`diminishing_returns`): a repeat/known-hazard defect
  signature, ≥3 defects clustered in one subsystem, or two iterations without a
  furthest-progress advance. This mandates STEP_BACK redesign or, if a redesign
  was already spent, user escalation — never another identical local patch.
- Ordinary test failures, syntax errors, and known repairs do not escalate.
