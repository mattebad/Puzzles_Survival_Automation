# Retire Legacy Bliss Runtime — repair stage 2

## Task ID and objective
- Task ID: `retire-legacy-bliss-runtime`
- Objective: Resolve the three material defects from the final cutover recheck without expanding the retirement plan.

## Frozen stage control
- Host: `cursor`
- Parent conversation ID: `6f7e9bb4-7ecf-4dfe-ac13-98cf0ba2b2fa`
- `control_plane_owner`: `sol_parent`
- Revision ID: `retire-legacy-bliss-runtime-repair-2`
- Stage type: `repair`
- Product precondition: `proven`
- Failure class: `local_defect`
- Stage start UTC: `not recorded`
- Continuation checkpoint UTC: `not recorded`

| Role | Exact model slug | Authority |
| --- | --- | --- |
| `control_plane_owner` | `gpt-5.6-sol-high` | Stage freeze, integration acceptance, live authority, and termination |
| `procedure_coordinator` | `not used` | None |
| `bounded_implementer` | `gpt-5.6-luna-xhigh` | Assigned repair paths and self-check only |
| `independent_tester` | `gpt-5.6-terra-high` | Read-only diff and acceptance recheck |
| `escalation_architect` | `not used` | None |

## Immutable budgets
- Per stage: one implementation, one review, at most one consolidated repair and one recheck, and zero live attempts.
- Per parent conversation: this is stage revision 2; managed turns remain within the existing limit.

## Frozen architecture decision
- Active runtime authorization must require `pns-bluestacks-5-p64-800x1280-v1`; matching request/observation values cannot admit the retired Bliss profile.
- A selected Daily screen may expose multiple ordinary free non-milestone Claim controls. Bind any one independently safe eligible control, dispatch exactly once, and require a positive points delta plus zero remaining eligible ordinary Claim controls.
- Active authority documentation must report retired Help/Praise operator registrations and BlueStacks-native promotion evidence.
- Preserve manual-only Bliss tooling, historical evidence/manifests, unrelated user work, registration state, scheduler state, and all other accepted cutover behavior.

## Writable paths
- `safe_action_core/policy.py`
- `scripts/daily_row_claim_bluestacks.py`
- `tests/test_input_capability_firewall.py`
- `tests/test_safe_action_core.py`
- `tests/test_daily_row_claim_bluestacks.py`
- `docs/daily-quest-execution-matrix.md`
- `docs/daily-quest-handler-roadmap.md`

## Acceptance checks
- Central policy denies the retired Bliss profile even when request and observation agree, while retaining BlueStacks authorization behavior.
- Aggregate Daily Claim accepts multiple independently safe eligible Claim controls, deterministically binds one, preserves one-input accounting, and still fails closed for unsafe or ambiguous geometry.
- Postcondition requires increased Daily points and all eligible ordinary Claim controls cleared.
- Active matrix and roadmap contain no live Help/Praise registration or Bliss-native promotion requirement.
- Focused affected tests, checked-in focused profile, shared-navigation profile, lint/compile/JSON checks, and `git diff --check` pass.
- One Terra High read-only recheck reports no material findings.

## Safety limits
- Allowed actions: offline source, test, and documentation repair only.
- Disallowed actions: emulator input, live canary, direct ADB, registration, scheduling, remote tooling, evidence mutation, and unrelated cleanup.
- Runtime/session limits: no development session and zero input.

## Validation commands
- Focused unit tests for capability firewall, safe action policy, Daily Claim, authority consistency, and documentation contracts.
- `python scripts/run_flow_delivery_validation.py focused --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- `python scripts/run_flow_delivery_validation.py shared-navigation --flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`
- `git -c core.whitespace=cr-at-eol diff --check`

## Live budget
- Live admission: `not authorized`
- Input budget: `0`
- Iteration budget: `0`

## Evidence/history references
- Initial recheck: Terra agent `55c1f4d4-eb82-4acf-86b6-4204d9d77b50`
- Zero-input observation: `.local-captures/development-sessions/observe-20260817T043426964464Z`

## Escalation conditions
- The frozen architecture becomes contradictory or incomplete.
- Safety authority is ambiguous.
- Tester and implementation evidence conflict.
- Two materially different repair hypotheses fail.
- Ordinary test failures, syntax errors, and known repairs do not escalate.
