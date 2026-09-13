# Stage 10 phase 5 startup-surface recovery accounting repair r2

## Task ID and objective
- Task ID: `runtime-reliability-stage-10-phase-5-startup-surface-recovery-r2`.
- Objective: Correct the outer DevelopmentSession terminal and retained-input accounting after a successfully reconciled shared startup recovery consumes the complete session input ceiling.
- Supersession: r2 supersedes r1 for integration only. The immutable r1 manifest and retained r1 history remain unchanged.

## Frozen stage control
- Host: `cursor`.
- Parent conversation ID: `stage-10-phase-5-reproof-20260826`.
- `control_plane_owner`: `sol_parent`.
- Revision ID: `runtime-reliability-stage-10-phase-5-startup-surface-recovery-r2`.
- Stage type: `local_defect_repair`.
- Product precondition: `proven_from_retained_successful_recovery`.
- Failure class: `local_defect`.
- Explicit continuation: user authorized “let's fix that” and supplied the r2 continuation packet.

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol` | freeze, implementation ownership, integration acceptance, durable closure |
| `independent_tester` | `gpt-5.6-terra-high` | read-only incremental r2 review/recheck |
| `bounded_implementer` | `not used` | parent-owned bounded repair |

## Immutable budgets
- One parent-owned accounting repair.
- One independent review, at most one consolidated correction, and one recheck.
- Zero live Scarlett inputs and zero live rechecks.

## Frozen architecture decision
- Keep the flow-owned DevelopmentSession as the single runtime/input owner.
- A successful shared startup recovery that consumes the complete ceiling is a successful recovery-only terminal, not a route failure.
- The outer session adopts the retained recovery transport, binds the post-recovery typed observation, prevents the route runner from executing, reports split and total counts exactly, and releases ownership.
- Full-frame hashes remain provenance/invocation metadata only. Stable current-frame ROIs remain selector and revalidation authority.
- No input budget is reopened and identical retry remains denied.

## Writable scope
- `AGENTS.md` — include only the animated-screen full-frame-hash/ROI invariant already present.
- `scripts/pnsctl.py` — outer recovery-only terminal, route veto, typed post-recovery observation, and retained-count adoption.
- `scripts/flow_delivery_recruitment_bluestacks.py` — required consumer of `route_max_inputs` and `startup_recovery_result`; it enforces the conditional 11/12 route ceiling and exact recovery/route/total reconciliation.
- `tests/test_development_session.py` — exact full-ceiling recovery-only regression.
- `tests/test_flow_delivery_recruitment_bluestacks.py` — Recruitment shared-accounting consumer coverage.
- `docs/execution-manifests/runtime-reliability-stage-10-phase-5-startup-surface-recovery-r2.md`.
- `docs/runtime-reliability-convergence-status.md` — durable live and r2 disposition after acceptance.
- `CURRENT_HANDOFF.md` — current post-r2 truth after acceptance.
- The r1 implementation paths remain part of the integrated Stage A candidate but are not relabeled as r2 repair work.

## Acceptance checks
- A reconciled one-input shared recovery with `max_inputs=1` executes no route runner and sends zero route input.
- Outer and nested results report `recovery_input_count=1`, `route_input_count=0`, `total_input_count=1`, and outer `input_count=1`.
- The outer terminal is successful and explicitly recovery-only; it is not reported as a route failure.
- The post-recovery typed observation is retained and bound to the invocation.
- Ownership is released, no budget is reopened, and identical retry remains denied.
- There is no duplicate runtime owner.
- Stable current-frame ROI recognition and animation-variance coverage remain intact; full-frame hashes do not become selector authority.
- VIP recovery behavior, real-money denial, Android Back prohibition, registration `NOT_REGISTERED`, and scheduler-disabled state remain unchanged.
- No out-of-scope production mutation is included.

## Validation commands
- Exact outer-summary regression only.
- `python -m unittest tests.test_startup_recovery`
- `python -m unittest tests.test_development_session`
- Affected Campaign and Recruitment route tests.
- Shared-navigation profile once.
- Governance validation once.
- `git diff --check`.
- Full unittest discovery is prohibited.

## Retained live facts
- No-effect misbound attempt: `.local-captures/development-sessions/AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE-20260826T204338924759Z/`.
- Corrected successful recovery: `.local-captures/development-sessions/AUTONOMY-SERVICE-CAMPAIGN-NAVIGATION-PROVING-SLICE-20260826T205944685287Z/`.
- Settled canonical Home: `.local-captures/development-sessions/observe-20260826T210014287650Z/`.
- Correct retained counts: recovery `1`, route `0`, total `1`.
- Stage B is `not_applicable` for this occurrence because the successor was canonical Home. Separate shop full-page/modal variants remain `evidence_required` until a natural native occurrence is retained.

## Safety limits
- No Scarlett input, app restart, reproduction attempt, route input, Campaign input, purchase, Confirm, real-money action, Android Back, registration, or scheduler action during r2.
- Protected `.local-captures/` evidence is read-only and must not be staged.
- Commit only explicitly enumerated active-task paths; never use `git add .`.
