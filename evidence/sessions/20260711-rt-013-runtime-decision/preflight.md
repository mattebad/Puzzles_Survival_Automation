# RT-013 preflight — final Bliss runtime decision

Recorded: 2026-07-11, America/Chicago

## Task

- Task ID: RT-013
- Objective: decide Passed or Rejected for the selected Bliss runtime and finalize the
  reproducible runtime-profile facts without implementing the complete RT-019 manifest.
- Satisfied dependencies: RT-001 through RT-011 are passed and retained; RT-012 is Passed
  after the complete four-hour Unraid-local observe-only soak. The canonical dependency is now
  `RT-012 → RT-013`. RT-016A is a later M7-AccountGuard evidence task, and RT-014A is optional.

## Acceptance criteria

1. Every runtime-selection hard gate is individually marked Passed or explicitly Rejected with
   retained evidence.
2. The selected Bliss profile is reproducible from version, VM, graphics, display, package,
   network, startup, and rollback facts; unresolved limitations are explicit.
3. The RT-001 baseline and later graphics/display rollback artifacts remain available.
4. A rejection fallback trigger is documented without starting a fallback experiment unless a
   remaining hard gate is rejected.
5. Supporting evidence links, known limitations, and authorization for post-selection work are
   recorded. RT-019's full manifest/schema remains a separate task.

## Intended operations

- Read and independently review the canonical plan, current BACKLOG.md, CURRENT_HANDOFF.md,
  RT-001 through RT-012 records, failure evidence, and retained runtime artifacts.
- Create the RT-013 criterion matrix and decision record.
- Update BACKLOG.md, the canonical plan only for stable decision facts, and CURRENT_HANDOFF.md.
- Run repository consistency, evidence, and secret validation; inspect the complete diff; create
  one RT-013-scoped commit.
- No VM mutation, game input, account/profile navigation, credentials, tunnel, observer, or live
  runtime experiment is authorized in this task boundary.

## Verification procedure

- Compare each acceptance criterion and hard gate against the retained RT-001–RT-012 evidence.
- Review selected-profile identity, renderer, effective display, ADB containment, package state,
  restart persistence, capture/input fidelity, four-hour soak, and rollback references.
- Perform a separate final review of unsupported claims, anomalies, limitations, repository diff,
  and final live state before changing RT-013 to Passed or Rejected.

## Evidence, rollback, permissions, dependencies

- Evidence directory: `evidence/sessions/20260711-rt-013-runtime-decision/`.
- Rollback: observation-only decision work; retain the RT-001 QXL/SwiftShader XML and boot
  rollback, the RT-003 VirGL candidate rollback, the RT-007 display rollback, and the RT-012
  cleanup state. No runtime rollback command is needed.
- Permissions required: repository write access for evidence and decision documentation only;
  no SSH, host, VM, ADB, game, or storage permission is required.
- Expected credential dependency: none.
- Expected manual-user dependency: none for technical runtime selection. RT-016A remains manual
  only if later performed, and is not an RT-013 prerequisite.

## Safety boundary

The game remains force-stopped, the VM remains on the selected profile, no observer is active,
and no external ADB tunnel is active. This preflight does not authorize gameplay input,
authentication, account switching, server/state selection, profile navigation, purchases, or
startup-normalization testing.
