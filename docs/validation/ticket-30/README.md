# #30: shared service-route contract — offline proof

Scope: test-only consolidation based on integration commit `d4dd8db`, implemented
on `wt/ticket-30`. The shared fake seed was `8c44a81`. No production path under
`automation_service/`, `scripts/`, `tasks/`, or `safe_action_core/` differs from
`origin/cleanup/offline-hygiene-pass` (the requested diff-stat command was empty).
The separately requested local-agent cleanup is a separate commit, `212e238`.

This is **offline-proven test behavior, not live acceptance**. No device, ADB,
BlueStacks, VM, registration, scheduling, deployment, or live-state operation was
performed. Services and controls below belong only to disposable test databases.

## Implemented contract

`tests/support/service_route_contract.py` defines the registry-keyed `RouteSpec`
table and `RouteRig`; runner keywords derive from each canonical CLI name.
`tests/test_service_route_contract.py` contains the fifteen named invariant
methods covering all eight servable routes. World is explicitly navigation-only.

The original guarded runners now have one implementation in
`tests/support/service_route_fakes.py`; all seven migrated dispatch modules import
them. Recruitment's existing native-service tests remain unchanged. The offline
workflow now includes both Recruitment and the shared contract. `scripts/check.py`
is unchanged.

[case-map.json](case-map.json) records every one of the 31 removed methods and its
replacement contract method(s). [cases-before.txt](cases-before.txt) contains 218
service test IDs; [cases-after.txt](cases-after.txt) contains 202. An AST inventory
verified that the removed set equals the mapping's keys exactly, that all fifteen
added IDs belong to the contract, and that every replacement method exists.

| Module | Before | After |
| --- | ---: | ---: |
| test_service_supply_dispatch | 6 | 1 |
| test_service_ultimate_dispatch | 7 | 3 |
| test_service_enhancement_dispatch | 7 | 3 |
| test_service_personal_might_dispatch | 6 | 2 |
| test_service_bioenhancer_dispatch | 5 | 1 |
| test_service_campaign_dispatch | 15 | 12 |
| test_service_nova | 19 | 12 |
| test_service_route_contract | 0 | 15 |

All other service-module counts are unchanged. The four cooldown/AP restart tests
remain in their original modules. Bounded-count, no-work, retained-state,
repeat-claim, Campaign AP, Nova operator-block/native-exception/normalization,
Recruitment, startup, and cooldown-edge scenarios remain. The retained
Enhancement/Personal Might/Campaign complete-count tests keep their accounting
assertions; their duplicated ownership fragments are covered by invariant D.

Assertion migration also preserves the originals' product/revision and recurrence
checks, the no-work-first Supply and already-complete-first Ultimate restart
scenarios, Ultimate connection/Flee counts, Enhancement Use counts, Personal Might
Praise counts, and uncertain-result committed-action/AP counters. The contract
additionally exercises work-first restart scenarios and cross-route stop signals.

## Production gap recorded, not repaired

`AutomationService.serve` at `automation_service/service.py:668` defaults omitted
`flow_ids` to Recruitment. With a Recruitment runner installed and enabled, a
transport-patched standalone probe observed one completed Recruitment call with
no explicit selection. Therefore the proposed omitted-selection assertion cannot
hold for Recruitment.

`EXCEPTIONS[(RECRUITMENT_FLOW_ID, "explicit_service_selection")]` records
`PRODUCTION GAP:` with this source location and the existing
`tests.test_service_recruitment.ServiceRecruitmentTests.test_native_pass_cooldown_restart_and_later_eligibility`
coverage. Only that assertion is excepted: Recruitment's disabled defaults,
selection-only registration, snapshot round-trip, and explicit CLI parsing remain
covered. This is not a skip, a production fix, or a claim that the gap is accepted.

The five planned AP/cooldown/reset exceptions also resolve to retained tests.
Invariant A2 imports each exception's module, class, and method to reject stale
coverage references.

## Executed proof

Environment: Windows x64, Python 3.12.10, Tesseract 5.5.0.20241111,
`OMP_THREAD_LIMIT=1`, `PYTHONDONTWRITEBYTECODE=1`, and a non-symlinked temporary
root. Linux/macOS results are not claimed by this receipt.

The final focused invocation ran the contract plus Supply, Ultimate, Enhancement,
Personal Might, Bioenhancer, Campaign, Nova, and Recruitment: **54 tests passed**
in 59.436 seconds. For the entire import/run, `subprocess.Popen` and every
available `os.posix_spawn`, `spawn*`, `system`, and `startfile` entrypoint were
patched to raise. The rig also forbids both `ADBRunner` construction and
`LocalBlueStacksRuntime.connect`. Thus this includes process-blocked proof for
all fifteen new contract methods, not merely a transport mock assertion.

A separate throwaway program invoked the real `AutomationService` through each
`RouteRig` without invoking unittest methods. All eight work runs reported
`completed`, retained their pinned input/action counts, left their test flow
unblocked, and released the runtime owner for a subsequent acquisition. Supply,
Ultimate, Enhancement, and Personal Might projected `SUCCEEDED`; Bioenhancer,
Campaign, Nova, and Recruitment projected `DEFERRED`. All process launches were
also blocked for this smoke.

Reproduce the normal focused checks from the repository root with Python 3.11+
and the development requirements installed (set `TMPDIR`, `TEMP`, and `TMP` to a
non-symlinked directory first):

```text
python -B -m unittest -v tests.test_service_route_contract
python -B -m unittest tests.test_service_supply_dispatch tests.test_service_ultimate_dispatch tests.test_service_enhancement_dispatch tests.test_service_personal_might_dispatch tests.test_service_bioenhancer_dispatch tests.test_service_campaign_dispatch tests.test_service_nova tests.test_service_recruitment
python -B scripts/check.py
```

### Mutation detection

[mutation-proofs.json](mutation-proofs.json) retains all failure messages. Scratch
changes were restored after each run; none is part of the delivered tree.

- Generation: a checkpoint return on generation mismatch bypassed both mismatch
  detection and the resulting run-stop fence. F failed on all eight routes with
  consumed counts exceeding the pinned one-input boundary.
- Partial result: unblocking an incomplete flow before report emission made E
  fail on all eight routes with `AssertionError: False is not true`.
- Route omission: removing Supply from `ROUTES` made A fail and name
  `SUPPLY-DEPOT-BLUESTACKS-INTEGRATION` as missing.
- Stale exception: a nonexistent Campaign coverage method made A2 exit nonzero
  with `AttributeError` naming `test_missing_exception_target`.

A narrower first generation mutation removed only the generation predicates.
It survived because disabling/re-enabling also marks the run `STOP_REQUESTED`;
that independent fence still stopped input. The full checkpoint-bypass mutation
above was then detected on every route. This defense-in-depth result is retained
rather than misreported as a failed mutation.

### Existing offline gate

`python -B scripts/check.py` passed on both baseline and final code: 396 tests
on each. Baseline test time was 42.500 seconds; final test time was 53.434 seconds
(the latter overlapped the diagnostic sweep). This static gate is deliberately
not described as full discovery. Host-identifier and route-metadata guards also
passed with the retained proof files staged.

## Complete per-module sweep

Every `tests/test_*.py` module ran in its own process, with a 900-second timeout
per module, on both `d4dd8db` and the final code commit `1c2b9dc`. Four independent
module processes ran concurrently. A process guard rejected device/VM executables
while allowing Python and the offline Tesseract worker.

| Receipt | Modules | Tests | FAIL | ERROR | Skipped | Wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline d4dd8db | 235 | 3135 | 8 | 16 | 37 | 490.81 |
| Contract cutover 1c2b9dc | 236 | 3119 | 8 | 16 | 37 | 649.98 |

[sweep-comparison.json](sweep-comparison.json) retains the exact outcome IDs.
The comparison found **zero new FAIL/ERROR IDs**, zero resolved baseline IDs,
and unchanged skips. Every per-module count change equals the 31-method removal
mapping plus the fifteen contract methods; no other module count changed.
The elapsed times are not an isolated performance benchmark: the final run
overlapped the focused suite, standalone smoke, and existing offline gate.

The eight still-failing baseline modules are `test_bluestacks_integrated_routes`,
`test_campaign_claimed_startup`, `test_campaign_home_direct_entry_pan`,
`test_flow_delivery_bioenhancer_bluestacks`, `test_flow_delivery_enhancement`,
`test_nova_praise_centralized_boundary`, `test_personal_might_praise`, and
`test_pnsctl_canonical_serve`. They were not weakened, repaired, or excluded by
this test-only ticket. Full-suite reliability is queued separately under #24.
