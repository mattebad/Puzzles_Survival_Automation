# Nova Praise lean reproof — frozen revision r2

This revision supersedes `nova-praise-lean-reproof-r1` only for the newly measured
recognizer-performance defect. All r1 safety, input, review, and live limits remain
unchanged.

## Frozen stage control
- Task / flow: `nova-praise` / `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`
- Revision ID: `nova-praise-lean-reproof-r2`
- Stage type: `consolidated_local_repair`
- Product precondition: `not_applicable` for offline repair
- Failure class: `local_defect`
- Evidence: `tests.test_nova_navigation_canary` passed 37 tests in `217.022s`; `recognize_nova_frame` performs five unconditional Tesseract calls and a sixth full-frame Home fallback per frame.
- `control_plane_owner`: `gpt-5.6-sol-medium`
- `bounded_implementer`: `gpt-5.6-luna-xhigh`
- `independent_tester`: `gpt-5.6-terra-high`

## Frozen repair decision
- Make recognition staged and lazy. Cheap native-frame geometry/template/color
  evidence chooses the candidate state before OCR.
- For Nova, read only the spatially associated header/body/attempt/cooldown/Praise
  ROIs required to prove that state.
- For a template-bound Research Lab radial with measured Home context, do not run
  unrelated OCR; template identity remains the actionable binding.
- When Home Atlas context is already positively measured and no radial/Nova state is
  recognized, classify Home from that measured context instead of full-frame OCR.
- Preserve fail-closed behavior for unknown, stale, incompatible, ambiguous, or
  unmeasured states. Do not weaken target binding or change ROI authority.

## Additional writable paths
- `tasks/nova_praise_vision.py`
- `tests/test_nova_navigation_canary.py`
- `tests/test_nova_praise.py`
- `tests/test_nova_praise_centralized_boundary.py`

The r1 writable paths remain available only to finish the interrupted implementation.
No queue, handoff, plan, scheduler, registration, evidence, or protected local path
is writable by the implementer.

## Acceptance
- `tests.test_nova_navigation_canary` completes in under 30 seconds on this host.
- Tests prove radial and measured-Home paths do not call Tesseract.
- Nova screen tests prove OCR is limited to the named narrow ROIs and still yields
  attempts, enabled/disabled Praise, and cooldown semantics.
- Existing retained-frame outcomes and all r1 focused tests pass.
- No live runtime input.
