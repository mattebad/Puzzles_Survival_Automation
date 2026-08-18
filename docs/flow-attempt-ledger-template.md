# Flow-attempt ledger

This is the routine artifact for substantive live gameplay-flow development. It
replaces per-defect frozen manifest proliferation. The unit of work is the
*flow*, not the defect. Keep exactly one stateful ledger per active flow, update
it after every live iteration, and use it to own the CONTINUE / STEP_BACK /
ESCALATE / STOP decision without user involvement for ordinary cases.

A frozen execution manifest ([`execution-manifest-template.md`](execution-manifest-template.md))
is required only for the STEP_BACK redesign, architecture, cross-contract, or
safety-boundary case — not for ordinary in-session local repair.

## Header

- Task ID / flow ID: `<stable identifiers>`
- Product goal: `<one line naming the real terminal outcome, e.g. one live canonical-Home round trip>`
- Input ceiling: `<per-session and per-task caps; autonomy never lifts a ceiling>`
- Inputs used: `<running count>`

## Framing gate (before the first live input)

Scale effort to uncertainty, not to task size:

- **Existing, contracted flow that only needs live proof** (e.g. Ultimate
  Challenge): no route derivation. Just record the product goal, input ceiling,
  and consulted durable knowledge, then pass the checklist.
- **New or ambiguous flow** (no contract, multiple valid routes, unknown
  hazards): derive the intended route once here, from durable knowledge, before
  spending any input.

Then self-answer the checklist below. Any `no`/unknown blocks the first input
until resolved. This is a falsifiable checklist, not a prose self-review; a plan
that reviews itself in prose is confirmation bias. Reserve an *independent* plan
review for the architecture / cross-contract / safety-boundary case only (the
same scope that requires a frozen manifest).

- [ ] **Intent match** — the intended route's terminal postcondition equals the
  flow contract's real product outcome (for every non-world flow, canonical Home).
- [ ] **No documented-unsafe input** — the route uses no input a durable artifact
  already records as unsafe for its source state (e.g. Android Back on
  Base/Home/Campaign); each such step is replaced by the measured positive
  control.
- [ ] **No manual-only precondition** — the route never requires a
  login/tutorial/CAPTCHA/account/credential state.
- [ ] **Consequential actions enumerated** — any real combat dispatch or
  real-money confirmation is named up front; real-money confirmation is
  unsupported and rejected.
- [ ] **Decisions resolved** — any choice with no dominant safe option is
  escalated to the user, not guessed.
- [ ] **Durable-knowledge-consulted list below is non-empty.**

## Furthest-progress ratchet

- Furthest confirmed milestone: `<milestone name>`
- Input index at that milestone: `<n>`
- Evidence reference: `<session/frame/hash pointer>`

The ratchet only advances on a proven semantic successor. It never moves
backward and is never inferred from transport success alone.

## Durable knowledge consulted before this attempt

List the durable artifacts checked *before* any navigation input. This list must
be non-empty to authorize navigation input. An unconsulted documented hazard is
a process failure, not a discovery.

- [`android-back-state-matrix.md`](android-back-state-matrix.md)
- [`runtime-input-safety-policy.md`](runtime-input-safety-policy.md)
- `<flow contract path>`
- `<retained hazard / evidence pointers>`

## Iteration record (append one per live iteration)

| # | Outcome | Defect signature `{subsystem, short_id}` | Ratchet after | Safety envelope intact | Decision | Rule fired |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `ADVANCED | NEW_DEFECT | REPEAT_DEFECT | EXTERNAL_BLOCK` | `{<subsystem>, <short_id>}` | `<milestone>` | `<true|false>` | `CONTINUE | STEP_BACK_REDESIGN | ESCALATE_USER | STOP_DONE` | `<row>` |

## Convergence counters

- Iterations since furthest-progress advance: `<n>`
- Distinct defect signatures this task: `<n>`
- Repeat defect signatures this task: `<n>`
- Per-subsystem defect counts: `<subsystem: n, ...>`
- STEP_BACK redesigns spent this task: `<0 or 1>`

## Outcome classification

- **ADVANCED** — reached a strictly further confirmed milestone than any prior
  iteration, or unblocked the previously furthest milestone.
- **NEW_DEFECT** — fail-closed on a defect signature never seen this task, at or
  before the current furthest milestone.
- **REPEAT_DEFECT** — fail-closed on a signature already in the ledger, or a
  hazard already documented in a durable matrix/contract.
- **EXTERNAL_BLOCK** — a precondition the agent cannot satisfy safely
  (unsupported Home zoom, login/tutorial/CAPTCHA/account, payment, or a
  consequential action that is the only path forward and is not authorized).

## Decision rule (agent-owned; no user for ordinary cases)

| Condition | Decision |
| --- | --- |
| ADVANCED, or NEW_DEFECT with positive furthest-progress trend over the last 3 iterations, and safety envelope intact | **CONTINUE** — in-session repair-and-continue; no new frozen manifest, independent review, or clean-commit gate |
| REPEAT_DEFECT, or ≥3 defects clustered in one subsystem, or 2 consecutive iterations with no furthest-progress advance | **STEP_BACK_REDESIGN** — stop patching; re-derive the entire remaining route from durable knowledge in one batch, then one canary (freeze a manifest for this case) |
| EXTERNAL_BLOCK, or STEP_BACK already spent once this task with no subsequent advance, or continuing would require weakening the safety envelope | **ESCALATE_USER** — surface exact blocker plus evidence, then stop |
| Product goal's terminal postcondition proven | **STOP_DONE** |

Offline review/repair rounds are subject to the same brake. When a recheck keeps
raising brand-new findings while no furthest-progress milestone advances, that is
`diminishing_returns`: STEP_BACK_REDESIGN or ESCALATE_USER, never another
identical repair round. A brand-new recheck finding is admissible only if the
parent classifies it as clearing the must-fix bar in
[`flow-delivery-validation-policy.md`](flow-delivery-validation-policy.md); a
nice-to-have is recorded as a Note and does not authorize a repair.

## Fail-closed teardown checklist

On any block, before releasing the session:

- Attempt bounded safe-state restoration for known-benign dialogs only (for
  example the exit dialog: Cancel only, never Confirm).
- If the runtime is left on a consequential or unknown surface, state that
  explicitly in the escalation. Never silently leave a modal on screen.
- Never issue an identical retry to force teardown.

## User-blocker reasons (absolute STOP)

`manual_state` (login/tutorial/CAPTCHA/account/credentials), unsupported
`product_state` precondition, required `consequential_action`,
`architecture_ambiguity` with no dominant safe option, `envelope_weaken`, or a
failed second redesign.
