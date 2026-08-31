# Flow-delivery routing and validation policy

This policy is the project-local companion to [`../AGENTS.md`](../AGENTS.md). It applies to
substantive live gameplay-flow development while preserving the runtime safety rules in
[`runtime-input-safety-policy.md`](runtime-input-safety-policy.md), singleton ownership in
[`chat-execution-ownership-policy.md`](chat-execution-ownership-policy.md), and the checked-in
flow queue contract.

## Route and review ownership

The route matrix and review ownership are authoritative in [`../AGENTS.md`](../AGENTS.md). An
explicit user route selection wins and remains active until changed; otherwise use the matrix
before entering this ladder. This document keeps the runnable validation mechanics and the stage
admission contract.

For Heavy work, every frozen manifest records exactly one review class and rationale:

- `sol`: Heavy architecture or cross-contract work that does not change
  runtime-input authority/enforcement, consequential-action authority,
  registration/scheduler authority, credentials/protected-evidence durability,
  or architecture/cross-contract decisions governing those boundaries. It
  requires the bounded parent Sol diff/acceptance review and final integration
  acceptance bound to the final clean candidate content fingerprint. Normal PR
  review may be deferred when the deferral is recorded as pending.
- `sol_plus_terra`: any change to runtime-input authority/enforcement,
  consequential-action authority, registration/scheduler authority,
  credentials/protected-evidence durability, or an architecture/cross-contract
  decision governing one of those boundaries. It requires the bounded parent
  Sol diff/acceptance review, then conditional independent read-only Terra
  review before live admission and, after a consolidated repair, one Terra
  recheck. All authorized repairs must be complete. The parent records final
  integration acceptance only after the required Terra evidence and binds it to
  the final clean candidate content fingerprint. That acceptance is the last
  acceptance gate before live admission. Normal PR review is additive and
  cannot defer or replace this pre-live safety review.

An explicitly selected `Solo` route is the recognized single-agent exception
defined in `AGENTS.md`. It replaces role choreography and ordinary independent
review with one named agent's serial plan/implement/validate/self-review/close
loop only outside the `sol_plus_terra` safety gate. It does not waive this
validation ladder, atomic scope, failure classification, evidence truth, runtime
authorization. For any `sol_plus_terra` scope, Solo must record that review
class and complete the required Terra review (and one recheck after any
consolidated repair). After all authorized repairs and required Terra evidence,
the final parent Sol integration acceptance and live admission remain mandatory.
If normal PR review is deferred, that deferral is permitted only for `sol` work
and is recorded as pending.

## Stage admission

Absent an explicit `Solo` selection, the Sol parent is the mandatory
`control_plane_owner` for Heavy work. Before implementation, review, repair, or
canary, the parent records the frozen revision, stage type, explicit review
class and rationale, failure class, budgets, and product precondition.
Diagnostic probes may begin at `evidence_required`; the Luna implementation and
parent review require `proven` or `not_applicable`. A failed product precondition
terminates the stage without implementation, review, or repair iteration. Any
live failure is classified as `product_state`, `core_contract`, `local_defect`,
`process_state`, or `diminishing_returns` before continuation is considered.
For `sol_plus_terra`, all authorized repairs and the required Terra evidence
must be recorded before the final parent Sol integration acceptance bound to
the final clean candidate content fingerprint. That final acceptance is the
last acceptance gate before canary/live admission, including on Solo.

Routine live flow development is convergence-governed (see the primary rule in
[`../AGENTS.md`](../AGENTS.md) and the stateful
[`flow-attempt-ledger-template.md`](flow-attempt-ledger-template.md)): the unit
of work is the flow, local defects are repaired and continued in-session under
the unchanged safety envelope, and the operator owns the CONTINUE /
STEP_BACK_REDESIGN / ESCALATE_USER / STOP decision. A frozen manifest and Heavy
review-class gate are required only for the STEP_BACK redesign, architecture,
cross-contract, or safety-boundary case. `sol` uses the parent Sol review and
final fingerprint-bound integration acceptance; `sol_plus_terra` additionally
uses conditional Terra review/recheck before that final acceptance.
`diminishing_returns` — a repeat or documented-hazard defect signature, ≥3
defects clustered in one subsystem, or two iterations without a furthest-
progress advance — mandates STEP_BACK or escalation and never authorizes
another identical local patch. Convergence, not stage/turn counts, is the
primary brake; the safety envelope is never relaxed by autonomy.

Each frozen stage permits one Luna XHigh implementation/self-check, one bounded
initial parent Sol diff/acceptance review, at most one consolidated Luna repair,
the conditional Terra review and (if a repair occurs) one Terra recheck only for
`sol_plus_terra`, then one final parent Sol integration acceptance bound to the
final clean candidate content fingerprint, and one live attempt. All authorized
repairs and required Terra evidence must be complete before that final
acceptance, which is the last acceptance gate before live admission. A parent
conversation permits at most three stage revisions and eight managed turns. The
frozen manifest is immutable between revision IDs and contains architecture,
review class/rationale, and budgets only; compact development-session and
evidence records remain history. `CURRENT_HANDOFF.md` is current truth and its
latest modifying commit must be the live Git head before managed delegation.
This avoids an impossible self-referential commit hash inside the tracked handoff
while still rejecting a handoff skipped by a later commit. At 60 minutes record
a visible checkpoint; at 90 minutes require a recorded user continuation later
than the stage start.

## Reviewer scope and re-review contract

This section defines the detailed `independent_tester` (Terra) scope only for
the `sol_plus_terra` class. It is conditional and is not part of the `sol`
topology; every Heavy stage still receives the bounded initial parent Sol
diff/acceptance review and, after any required Terra evidence, final parent Sol
integration acceptance bound to the final clean candidate content fingerprint.
The Terra gate exists to stop the review/repair loop that thrashed the Ultimate
Challenge delivery (r1→r16+ rounds, most of them offline): each recheck was run
as a fresh full review that surfaced a brand-new "improvement," and each new
item was treated as authorization for another Luna repair round, while the
actual live blocker went untouched. The reviewer is defect-first and read-only;
it reports to the parent and never authorizes repair or expands scope.

**Must-fix bar — raise a finding only when the change plausibly causes one of:**

1. Incorrect behavior or wrong output for a real input this change handles.
2. A runtime-input or live-action safety-envelope violation (singleton
   ownership, current-frame binding, fail-closed-on-unknown, never-Confirm,
   consequential-action lifecycle, full-frame bounds/overlay checks).
3. Failure of a stated acceptance criterion of this stage/change.
4. A regression in a component the diff touches — including a test that would
   now pass on broken behavior, i.e. a test that no longer exercises the claimed
   production path.
5. Data or evidence loss/corruption, or credential/secret exposure.

Every finding must name the exact file+location in the diff, the concrete
triggering input or scenario, and which category above it hits. A finding with
no concrete triggering scenario is a non-blocking Note, not a defect.

**Must-not-raise (exclude; record as a Note at most, never as a finding):**
style, naming, formatting; wording or "truthfulness" of labels, comments, or
docstrings that do not change behavior or safety; speculative abstractions or
refactors; public-service, multi-tenant, or scale hardening; theoretical edge
cases with no plausible trigger in this private single-user local project; added
test coverage or de-mocking beyond what is needed to prove this change's stated
acceptance and safety; and any "would be nicer / cleaner / more robust"
improvement that has no named concrete failure. Local deployment does not excuse
a real correctness, safety, data-loss, or credential defect.

**Re-review (recheck) contract.** The one authorized recheck is not a fresh full
review. It verifies exactly two things: (a) each parent-classified finding from
the prior review is resolved, and (b) the repair introduced no new must-fix
regression in the touched diff. A brand-new issue is admissible only if it
independently clears the must-fix bar above and is a real defect/gap; even then
the reviewer only reports it, the parent (Sol) classifies it, and it does not by
itself authorize another repair cycle. Repeated new must-fix findings at recheck
with no furthest-progress advance are a `diminishing_returns` signal that routes
to STEP_BACK_REDESIGN or ESCALATE_USER, never another identical repair round.

## Compact validation ladder

Run the smallest rung that proves the current change, then advance once. Do not
repeat a passed rung merely for ceremony.

1. During repair, rerun the exact failing regression after the correction.
2. Run each affected package suite once.
3. Run the checked-in focused flow profile once before canary:
   `python scripts/run_flow_delivery_validation.py focused --flow-id FLOW-ID`.
4. If shared navigation changed, run the boundary profile once:
   `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id FLOW-ID`.
5. Complete the bounded initial parent Sol diff/acceptance review after
   the Luna self-check and classify its findings. If the class is
   `sol_plus_terra`, complete the conditional Terra review before canary and
   its one recheck only after any consolidated repair; after all authorized
   repairs and required Terra evidence, record final parent Sol integration
   acceptance bound to the final clean candidate content fingerprint. No route,
   including Solo, may admit canary/live work before those required evidence
   and acceptance records.
6. Perform a zero-input observation through the supported interface:
   `python scripts/pnsctl.py development-session observe`.
7. Execute the authorized live flow through its existing `pnsctl`
   development-session interface.
8. Verify the semantic result and retained evidence with the flow's checked-in
   verifier.
9. Full repository discovery is manual-only:
   `python scripts/run_flow_delivery_validation.py full --flow-id FLOW-ID --manual`.

The runner captures full subprocess logs and emits compact success/failure output plus a bound
receipt. Reuse it rather than adding another runner or suppressing test failures. This ladder does
not authorize registration, scheduler promotion, consequential actions, or unsupported payment
confirmation.
