# Ultimate Challenge lean reproof

## Task and authority reconciliation
- Task ID: `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`
- Objective: converge the zero-resource Ultimate Challenge Daily route onto deterministic color/geometry recognition with narrow semantic OCR, then prove one current-reset canonical-Home round trip through `pnsctl`.
- Parent authority decision: the gameplay contract's `evidence_required` state is correct. Queue/backlog completion is stale because retained attempt 14's alleged canonical-Home frame is visibly the Resource Shop. The old broad OCR Home check produced a false positive.
- Retained attempt 13 still proves the gold Flee action and its Ultimate Challenge-main successor with zero resource delta. It does not prove Home.
- This is a local recognition/integration defect, not a product-policy failure.

## Explicit conversation-budget exception
- On 2026-08-17 the user explicitly authorized resetting/bypassing the prior conversation-stage cap and continuing without further commit-approval prompts.
- The exception does not weaken singleton runtime ownership, current-frame binding, input ceilings, review, test, live admission, zero-resource policy, or fail-closed behavior.

## Frozen stage control
- Revision ID: `ultimate-challenge-lean-reproof-r1`
- Stage type: `implementation-review-live`
- `control_plane_owner`: Sol parent
- Product precondition: `retained_flee_valid_home_terminal_invalid`
- Failure class: `local_defect`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-medium` | Architecture, integration acceptance, live admission, failure classification, status, and termination |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | One bounded implementation and focused self-check |
| `independent_tester` | `gpt-5.6-terra-high` | One read-only defect-first review |
| `procedure_coordinator` | `not used` | None |
| `escalation_architect` | `not used` | None |

## Frozen architecture
- Keep `scripts/pnsctl.py development-session run-flow ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION --live --yes --max-inputs 16` as the sole live entry. Its outer `DevelopmentSession` owns singleton runtime access.
- Remove historical-attempt sniffing that permanently forces `post-flee-home-only`. Every new reset evaluates persistent state and otherwise starts the canonical route.
- Pass a current UTC game-day identity and an untracked persistent state path. Persist success only after positively verified template Home; never at Flee or an intermediate screen.
- Actionable controls remain visual-primary:
  - Campaign Ultimate entry: positively recognized Campaign context plus one unique blue vortex in the bounded current-frame ROI; narrow label OCR may corroborate but cannot substitute for vortex geometry.
  - Ultimate main: one red Challenge control in the accepted lower geometry plus narrow title-region `Ultimate Challenge` corroboration.
  - Hero Lineup: one gold Challenge control plus all five selected-card visual checks.
  - Active battle: puzzle-board geometry plus the bounded upper-right Exit icon.
  - Flee warning: exact modal geometry, red Fight control, gold Flee control, and narrow modal-text corroboration. No full-frame OCR.
- Every target is recaptured and revalidated immediately before dispatch. Unknown overlays, stale frames, wrong geometry, ambiguous candidates, resource prompts, or unknown successors stop without retry.
- Replace every generic `base/build/hero` Home check with `tasks.home_nav_recognition.recognize_home_nav`. `HOME` requires native geometry, threshold-passing template evidence, and no contradictory screen.
- After Flee, positively recognize Ultimate main, take one bounded Back to Campaign, positively recognize Campaign, take one bounded Back, and require template Home. Resource Shop or any non-Home terminal is `evidence_required`.
- Preserve zero AP, stamina, currency, item, refill, purchase, and Auto Battle.
- Registration, scheduler eligibility, composition, M6, Bliss, and unrelated flows remain unchanged.

## Writable paths
- `scripts/bluestacks_ultimate_challenge.py`
- `scripts/flow_delivery_ultimate_challenge_bluestacks.py`
- `tests/test_bluestacks_ultimate_challenge.py` (new)
- `tests/test_flow_delivery_ultimate_challenge.py` only if wrapper coverage cannot remain cohesive in the new test

Parent-only checkpoint paths after accepted live evidence:
- `tasks/gameplay_flow_contracts/ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION.json`
- `tasks/flow_delivery_queue.json`
- `BACKLOG.md`
- `CURRENT_HANDOFF.md`

All other paths are read-only during implementation.

## Acceptance
- Retained Resource Shop frame is explicitly rejected as Home.
- Retained Ultimate main, active battle, Flee warning, and Flee-successor frames satisfy only their correct state recognizers.
- Main, lineup, Exit, Flee, and Home binders reject wrong-screen and ambiguous visual negatives.
- Production wrapper uses current UTC reset identity, persistent state, and full `--daily` route; historical queue attempt text cannot select a continuation.
- Success persistence occurs only after verified template Home.
- Existing focused Ultimate policy, flow wrapper, Home template, authority, and governance checks pass.

## Validation
- Exact new recognizer/wrapper tests during repair.
- `python -m unittest tests.test_bluestacks_ultimate_challenge tests.test_ultimate_challenge_daily`
- affected flow-wrapper tests
- `python scripts/run_flow_delivery_validation.py focused --flow-id ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`
- one parent integration gate and zero-input `python scripts/pnsctl.py development-session observe`

## Live ceiling
- No live input during implementation or review.
- After committed candidate and parent acceptance: one current-reset supervised canary from canonical Home.
- Maximum total route inputs: 16.
- Maximum zero-resource challenge inputs: four (`Challenge`, lineup `Challenge`, `Exit`, `Flee`).
- Maximum resource-affecting inputs: zero.
- Maximum combat confirmations: the two challenge-start confirmations already defined by the flow; no Auto Battle.
- No identical retry. Any unknown target/successor or non-Home terminal ends the stage as `evidence_required`.

## Required returns
- Luna: changed paths, compact diff, exact tests/results, blockers; no integration/live claim.
- Terra: material findings only or explicit no findings; no repair authorization.
- Parent: explicit integration decision and one live result.

## Parent-authorized consolidated repair
- Finding 1: rebind the unique Campaign vortex on the exact immediate-before frame used for dispatch; stale entry geometry is forbidden.
- Finding 2: reject any unexpected visual popup/modal or resource prompt before every state/action. The exact Flee warning is the sole expected modal and must pass its full visual/semantic recognizer.
- Finding 3: enforce one aggregate maximum of 16 inputs. Reuse one `LocalBlueStacksRuntime` across canonical Home entry and the full Daily route, expose its actual total count, and fail if the terminal evidence exceeds 16. Do not overwrite the total with the two Back inputs.
- Finding 4: current-reset `already_completed` is zero-input but must capture and positively verify template Home, retain a top-level frame and substantive artifacts, and otherwise block. Never label an arbitrary screen `recognized_home`.
- Finding 5: copy/retain the actual terminal Home frame in the operator's top-level `frames/` evidence, bind `home_frame` to it, and independently reload/re-run `recognize_home_nav` in the delivery wrapper and verifier before persistence or acceptance. A boolean alone is insufficient.
- For the canonical Daily start, require the current source to already be template Home and run Home Atlas Campaign entry in-process. Do not launch nested generic Home-normalization subprocesses. Resume states remain fail-closed and count only their actual inputs.
- One Luna repair and one Terra recheck are authorized. No live input until both pass and the parent accepts integration.

## Refrozen stage r2 — terminal truthfulness
- User continuation exception: the user's explicit instruction to reset/bypass the conversation policy and continue authorizes this narrow second stage without weakening acceptance.
- Revision ID: `ultimate-challenge-lean-reproof-r2`
- Writable paths remain unchanged.
- Fix navigation-only terminal truthfulness:
  - `navigation_only_complete` ends at positively recognized Ultimate Challenge entry and must use a matching non-Home runtime-state identity.
  - `already_completed` may use `recognized_home` only with the new hash-bound template Home evidence.
  - The navigation-only verifier must require the correct state/evidence for each terminal and never accept a generic Home assertion.
- Exact Flee warning must have one and only one visual popup panel spatially matching the expected warning modal. Any additional panel or disassociated panel fails closed.
- Add focused regressions for both defects.
- One Luna implementation and one Terra review are authorized. No live input before parent acceptance.

## Refrozen stage r3 — preserve overbroad popup evidence
- User continuation exception: the explicit reset/bypass instruction authorizes this single-defect stage without weakening any safety or acceptance requirement.
- Revision ID: `ultimate-challenge-lean-reproof-r3`
- Failure class: `local_defect`.
- Writable paths:
  - `scripts/bluestacks_ultimate_challenge.py`
  - `tests/test_bluestacks_ultimate_challenge.py`
- A materially overbroad or full-frame popup candidate must remain independently visible to the Flee authorization gate. It must not be merged into the expected modal cluster and discarded merely because it contains that modal.
- The exact expected modal plus any additional overbroad/full-frame panel must fail closed.
- Add a self-contained regression with `_FLEE_MODAL_ROI` and `(0, 0, 800, 1280)` together.
- One Luna implementation and one Terra review are authorized. No live input before parent acceptance.

## Refrozen stage r4 — development-session runner contract
- User continuation exception: the explicit reset/bypass instruction authorizes redesign of this narrow integration boundary after two distinct zero-input admission failures.
- Revision ID: `ultimate-challenge-lean-reproof-r4`.
- Failure class: `core_contract`.
- Both failed admissions sent zero input and released singleton ownership:
  - the obsolete lease-bound `bluestacks run-flow` command failed before ownership acquisition;
  - the supported `development-session run-flow` acquired ownership, captured its source, then failed before operator dispatch because the runner required the legacy queue `flows` array.
- Writable paths:
  - `scripts/flow_delivery_ultimate_challenge_bluestacks.py`
  - `tests/test_bluestacks_ultimate_challenge.py`
- The Daily runner must accept the current development-session contexts: queue with `active_flow_id`, and runtime context with owner, held ownership, and `max_inputs`.
- It must positively require the active flow ID, held singleton ownership, and a runtime ceiling no greater than 16.
- Legacy controller queue metadata may remain supported, but must not be required for development-session execution. Evidence metadata must truthfully distinguish a legacy configured attempt budget from session-local execution.
- Add a focused regression invoking the Daily wrapper with the minimal current development-session contexts.
- One Luna implementation and one Terra review are authorized. No further live input before parent acceptance and a fresh clean candidate commit.

## Refrozen stage r5 — native capture type integrity
- User continuation exception: the explicit reset/bypass instruction authorizes this zero-input local-defect stage.
- Revision ID: `ultimate-challenge-lean-reproof-r5`.
- Failure class: `local_defect`.
- The r4 canary acquired singleton ownership, captured a native source, then crashed before any input because `LocalBlueStacksRuntime.capture()` returned `CapturedNativeFrame` while the main resume recognizers received that wrapper instead of its NumPy `.frame`. `result.json` was therefore absent and the delivery wrapper failed closed. A subsequent zero-input observation proved singleton ownership released.
- Writable paths:
  - `scripts/bluestacks_ultimate_challenge.py`
  - `tests/test_bluestacks_ultimate_challenge.py`
- Every recognizer, binder, frame hash helper, and semantic observation must receive the correct NumPy frame or explicitly supported capture type. Dispatch/reconcile must retain the `CapturedNativeFrame` object.
- Audit all direct `runtime.capture()` uses in this operator, including navigation-only entry binding, for the same type mismatch.
- Add focused tests using a real `CapturedNativeFrame`-shaped object so NumPy-only mocks cannot conceal this boundary.
- One Luna implementation and one Terra review are authorized. No live input before parent acceptance and a fresh clean candidate commit.
