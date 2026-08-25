# Stage 10 phase 3 Nova Praise promotion r2

## Control
- Task: `stage-10-phase-3-nova-praise-r2`.
- Parent: `gpt-5.6-sol-medium`, sole control-plane and live-runtime owner.
- Mutable role: one mapped `gpt-5.6-luna-xhigh` bounded correction.
- Independent role: one mapped `gpt-5.6-terra-high` read-only review.
- User continuation: explicit on 2026-08-25 through Phase 6; Phase 7 combat remains unauthorized.
- Entry documentation HEAD: `1a1af40`; the uncommitted r1 candidate and passing parent receipts are preserved.
- R1 disposition: registration bypass resolved; recheck found concrete verifier-required artifact loss in the repaired public supervised branch. Parent classifies `local_defect` and steps back once to this bounded evidence-persistence correction.

## Frozen architecture
1. The r1 registry, zero-transport scheduler, atomic pre-runtime consumption, and exact typed `RegisteredDispatchSnapshot` contracts remain unchanged.
2. The public supervised Nova branch must persist one canonical dispatch-time snapshot into every verifier-required retained artifact: `result.json`, `flow-delivery-result.json`, and causal trace.
3. Missing causal trace is created before persistence. Existing trace content is preserved and augmented only with exact registration aliases and scheduler-disabled dispatch evidence.
4. Retained artifacts describe dispatch-time registration as `REGISTERED`; the checked-in registry remains consumed and `NOT_REGISTERED` on every terminal/error path.
5. The checked-in verifier must accept the branch's genuine retained artifacts and continue rejecting missing, partial, forged, mismatched, or contradictory snapshot evidence.
6. No runtime behavior, route target, input ceiling, effect policy, recovery, registration allowlist, or scheduler authority changes.

## Writable paths
- `scripts/pnsctl.py`
- `tests/test_development_session.py`
- `tests/test_pnsctl_scheduler_pulse.py` only if directly necessary for public-branch persistence proof.
- Parent closure only: `CURRENT_HANDOFF.md`, `docs/runtime-reliability-convergence-status.md`, and this manifest.

## Acceptance
- A focused offline regression executes the public branch with mocked runtime/runner and a real temporary session, then verifies `result.json`, `flow-delivery-result.json`, and causal trace all contain the same rehydratable typed snapshot aliases.
- The checked-in Nova verifier accepts those genuine retained artifacts and rejects a forged/mismatched artifact.
- Atomic consumption still precedes guard/session/runner; a repeat rejects before runtime; the registry remains disabled.
- Exact Phase 3 focused suites pass.
- Terra returns `ADMIT_LIVE_CANARY`; Sol accepts integration before runtime.
- R1 live budget remains unused and unchanged: one current-reset canary, maximum eight inputs, maximum one zero-cost Praise, zero forbidden actions, zero identical retries.
- Phase 4 remains unadmitted; Phase 7 combat remains unauthorized.
