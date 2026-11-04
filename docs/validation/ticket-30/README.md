# #30: shared service-route contract — offline proof

The original test-only consolidation was based on integration commit `d4dd8db`,
implemented on `wt/ticket-30`, with shared fake seed `8c44a81`. The review follow-up
includes an explicitly owner-approved **production change**: service and CLI
callers must select routes; neither defaults to Recruitment. Only
`automation_service/service.py` and `automation_service/cli.py` change production
behavior. The separately requested local-agent cleanup remains commit `212e238`.

This is **offline-proven test behavior, not live acceptance**. No device, ADB,
BlueStacks, VM, registration, scheduling, deployment, or live-state operation was
performed. Services and controls below belong only to disposable test databases.

## Implemented contract

`tests/support/service_route_contract.py` defines the registry-keyed `RouteSpec`
table and `RouteRig`; runner keywords derive from each canonical CLI name.
`tests/test_service_route_contract.py` now contains seventeen invariant methods
covering all eight servable routes. World is explicitly navigation-only.

The original guarded runners now have one implementation in
`tests/support/service_route_fakes.py`; all seven migrated dispatch modules import
them. Recruitment's native-service helper now passes its flow ID explicitly. The
offline workflow includes both Recruitment and the shared contract. `scripts/check.py`
is unchanged.

The retained initial-consolidation receipts are historical: [case-map.json](case-map.json)
maps the 31 removed methods; [cases-before.txt](cases-before.txt) contains 218
service test IDs and [cases-after.txt](cases-after.txt) contains 202 at `1c2b9dc`.
Their AST inventory verified the removed set and all fifteen original replacements.
The follow-up retains those assertions, adds two generation methods, and renames
`MultiRouteTests.test_default_remains_recruitment_and_unknown_selection_is_rejected`
to `test_omitted_and_unknown_selection_are_rejected` for the approved no-default
behavior. The old disable/re-enable scenario remains as
`GenerationChangeTests.test_disable_then_reenable_after_first_input_stops_further_input`;
the fixed-name F method now isolates a pure flow-generation change.

| Module | Before | After |
| --- | ---: | ---: |
| test_service_supply_dispatch | 6 | 1 |
| test_service_ultimate_dispatch | 7 | 3 |
| test_service_enhancement_dispatch | 7 | 3 |
| test_service_personal_might_dispatch | 6 | 2 |
| test_service_bioenhancer_dispatch | 5 | 1 |
| test_service_campaign_dispatch | 15 | 12 |
| test_service_nova | 19 | 12 |
| test_service_route_contract | 0 | 17 |

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

## Explicit selection: approved production change

The owner chose removal of the implicit Recruitment default after the review.
`AutomationService.serve` rejects omitted, empty, and unknown selection with
`ServiceError`, even when an enabled Recruitment runner is installed.
The CLI requires `serve --flow ROUTE`; omission is an argument error before
state or device setup. Repeated explicit selections remain supported.
The native Recruitment test helper now selects Recruitment explicitly, and the
`explicit_service_selection` exception has been removed.

The five planned AP/cooldown/reset exceptions remain and resolve to retained tests.
Invariant A2 imports each exception's module, class, and method.

The standard `tests/__init__.py` package marker enables the documented full
discovery command and defines no tests. The before-review comparison checkout
uses the identical marker so collection is comparable.

## Generation-only review coverage

Invariant F enables an already-enabled flow after its first input. A separate
method does the same for the service. Both record the enabled-to-enabled
generation increment and prove the run remains `RUNNING`, not `STOP_REQUESTED`.
They require a `GENERATION_MISMATCH` report, exactly one input, the route's
pinned consumption counts, no completed effects, and the matching read-only
dispatch-validation reason. Original disable/re-enable coverage is separate.
Assertions run outside the fake's exception-to-partial-result boundary.

`GuardedCampaignRunner` documents its deliberate iteration checkpoint and
`CampaignApRunnerError` partial-result wrapping, matching the native claimed-run
boundary rather than silently reproducing the old local fake's omission.

## Review-fixup proof

At production-change commit `ccacd32`, the contract and eight route modules pass
**56 tests**. Including the omitted-selection and preserved missing-authorization
CLI checks gives **58 passing tests, zero skips**. `subprocess.Popen` and available
`os` spawn/fork/exec/system/startfile launchers are blocked throughout imports and
execution; transport tripwires also reject `ADBRunner` construction and native
connection. `python scripts/check.py` passes **396 tests, zero skips**.

The direct offline service smoke rejects omitted selection with an enabled
Recruitment runner installed: no runner calls and no runs. The real CLI returns
argument-error status 2. No generation-fence production change was necessary.

The scratch mutation removes only the two generation predicates from
`checkpoint_fences` and the two generation-mismatch checks from state dispatch
validation. Stop, run-state, ownership, lease, clock and terminal-projection
fences remain. Pure flow-generation F fails on all eight routes; the separate
service-generation case fails on the same eight routes. Each produces the
following assertion message:

| Route | Failure in both generation-only methods |
| --- | --- |
| Supply | `AssertionError: Tuples differ: (4, 1) != (1, 0)` |
| Ultimate | `AssertionError: Tuples differ: (4, 1) != (1, 1)` |
| Enhancement | `AssertionError: Tuples differ: (6, 3) != (1, 0)` |
| Personal Might | `AssertionError: Tuples differ: (6, 1) != (1, 0)` |
| Bioenhancer | `AssertionError: Tuples differ: (5, 1) != (1, 0)` |
| Campaign | `AssertionError: Tuples differ: (6, 1) != (1, 1)` |
| Nova | `AssertionError: Tuples differ: (4, 1) != (1, 0)` |
| Recruitment | `AssertionError: Tuples differ: (4, 1) != (1, 0)` |

The disable/re-enable method still passes under that mutant. The three-method
run exits 1 with sixteen failed route subtests; after restoring only the scratch
edits, all three methods pass. The historical whole-checkpoint-bypass result
below did not satisfy the generation-only acceptance criterion; this exact
mutation result supersedes it without rewriting the historical receipts.

### Full-discovery comparison

Both trees run the exact `python -B -m unittest discover -s tests -t .` command
on Windows with Python 3.12, Tesseract 5.5.0 and `OMP_THREAD_LIMIT=1`. The
before-review `e73dbd4` checkout receives only the identical test-package marker
to permit collection; it does not receive the generation or default-removal fix.

| Tree | Tests | FAIL | ERROR | Skipped | Test seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before review, e73dbd4 | 3,119 | 9 | 16 | 37 | 1,781.574 |
| Explicit-selection change, ccacd32 | 3,122 | 9 | 16 | 37 | 1,791.773 |

Exact FAIL/ERROR header arrays, including subtest identities, are equal:
**zero new or resolved failure/error IDs**. The three added cases are the two
generation methods and omitted-CLI-selection case. The authorized no-default
method rename is documented above. No unrelated baseline assertion is changed.
These are not full-suite passes; existing failures remain outside this follow-up.
The Troop Training failure appears in both full invocations, unlike the earlier
isolated-module sweep. Elapsed times overlap other proof and are not benchmarks.

## Initial-consolidation proof (historical)

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
