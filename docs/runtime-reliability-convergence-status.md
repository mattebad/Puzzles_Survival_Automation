# Runtime Reliability Convergence Status

This is a durable status map, not a mutable execution manifest. The Stage 2
closure is commit `dde9b1c` on branch
`feature/runtime-reliability-convergence`; its parent is
`8c73b932dc09ca4569f6e1082b3680ead876c18c`.

## Stage map

| Stage | Status | Evidence and qualification |
| --- | --- | --- |
| 0 — authority freeze | Complete | Recorded by the retained `CURRENT_HANDOFF.md` and the checked-in runtime/product-policy artifacts. This chronology is inferred from the handoff because no separate Stage 0 commit is present. |
| 1 — typed product authority and contracts | Complete in branch candidate | `tasks/product_authority.py`, `tasks/flow_delivery_product_policy.json`, and the three bound BlueStacks contracts now carry the exact static-UTC policy and revision/digest binding. Offline authority tests are the verification evidence. |
| 2 — Resource Effect Authority | Complete in branch candidate | `safe_action_core/resource_effect_authority.py` releases active reconciliation claims transactionally with terminal observe-only reconciliation; `scripts/pnsctl.py` binds Resource identity to validated product authority. Focused Resource tests are the verification evidence. |
| 3 — control primitives | Complete in commit containing this file | Revision r1 added the pure primitives and trace projection; r3 closed the sole canonical-consumer blocker with provenance-bound Enhancement replay, giving Nova + Enhancement as distinct transition consumers. Focused, affected-package, shared-navigation, independent-review, and parent integration gates are accepted. Production adapters, registration, scheduling, and runtime authority remain unchanged. |

## Frozen product rule

Daily reset is exactly `00:00:00 UTC` every `86400` seconds. The typed
policy is `daily-reset-static-utc-midnight`, scoped to `global.daily_reset`,
`explicitly_approved`, and sourced from
`explicit_user_direction_2026-08-20`.

## Retained canary and terminal semantics

The retained canary row intentionally remains
`FIXED_RUNTIME_BINDING_RESET_OBSERVED` with its historical Quest/OCR evidence.
The production path now derives static UTC identity from the validated
fixed-slot authority. A retained row is reusable only when account, server,
runtime scope, reset start, and reset deadline are exactly equal; the
candidate does not rewrite historical identity evidence.

The retained `result.json` uses adapter state `HOME`. The canonical terminal
observation and terminal projection explicitly store `HOME_CANONICAL`; these
are distinct evidence layers.

Prospectively, terminal observe-only reconciliation releases claims in
`ACTIVE` or `RECONCILIATION_ONLY` state in the same transaction as the
reservation, attempt, and generic action terminalization, while leaving
`RELEASED` and `EXPIRED` claims unchanged. The existing canonical historical
claim row's literal durable state column remains `ACTIVE`; its `expires_at` has
elapsed, so it is expired by lease semantics and therefore non-authorizing. It
was not rewritten by this candidate.

No extra live canary was run for this closure. Production registration remains
`NOT_REGISTERED`, scheduler eligibility remains disabled, and the active
runtime target remains private local BlueStacks.

## Validation status

The final focused Resource profile passed 65 tests with receipt digest
`a77ba8c3a0365bab64e3eceb35f5f6fa843afed8ab2e6a9bca2ae4ad70ebcc6d`.
The direct authority/identity/Resource suites passed 65 tests, and the adjacent
catalog/Nova suites passed 46 tests. Independent review and recheck reported no
remaining must-fix finding.

The architecture baseline was repaired offline after Stage 2. The canonical
Resource queue record now uses a contiguous archived-attempt ordinal,
path-form focused tests, and the terminal `completed` stage. Architecture tests
now recognize the Resource flow and current handoff schema, keep the checked-in
managed-agent hook, construct their own ready-flow fixture when the production
queue has no ready flow, and test missing-verifier behavior with valid retained
evidence instead of an invalid path.

The architecture profile now passes all 92 tests with receipt digest
`102bac590580861dba3fe972e1217fec7c6e3e0692f46f836ac91f1d996ffe1e`.
The repair used no runtime input and did not change Resource product behavior,
registration, or scheduling.

## Stage 3 control-primitives closure

Frozen manifests:

- r1: `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r1.md`
  (SHA-256 `0a8cb90b283a4209a5f9e590d807548e1abcd401b6584097d10e1c20366399ad`).
- r2: `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r2.md`.
  It terminated before mutation as `process_state` because the parent packet
  transcribed the retained event digest incorrectly.
- r3: `docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r3.md`
  (SHA-256 `bdf221ee636af73e7dcd21748ac0e9df99ff3d5b573295c9fb519fb973242f36`).

The candidate adds three small, pure, input-free primitives for stable
transition polling, list/card search state, and source-context modal/recovery
classification, plus a read-only causal trace projection. Existing
SafetyStore authority, native-frame/current-frame binding, runtime singleton
ownership, route controllers, product policy, Home Atlas panning, and
production flow adapters remain unchanged. The trace cannot authorize input or
infer transport/semantic success from dispatch alone.

Validation on the integrated r3 candidate:

- 9/9 exact causal-trace/replay tests passed.
- 16/16 combined primitive and replay tests passed.
- 66/66 affected perception/navigation/VIP tests passed with one existing skip.
- Shared-navigation passed 20 tests with receipt digest
  `d26b941e771229b19d6e4600d461dd377cae587cbc4661e21716b26a34745c95`.
- The post-closure architecture profile passed 92 tests with receipt digest
  `1b062eceb783b6f932e49ac0076a3cc07b1019ba1698614fb2a449a1d8bfe3c6`.
- `git diff --check` passed.

The initial independent review raised two must-fix findings. The single
consolidated repair resolved the mixed-action causal-trace merge and introduced
no new must-fix regression. The r1 recheck left transition-stability canonical
coverage unresolved because Nova was its only provenance-bound consumer. r3
binds the retained Enhancement result (`bc36407f...dde0b`), corrected event log
(`4a78a4a...fc07b`), native BlueStacks profile, 800×1280 dimensions, and exact
immediate-post/settled frame hashes into an executable zero-input replay.
Nova + Enhancement now satisfy the two-consumer canonical requirement.

The r3 independent review found one test-proof defect: deleting or duplicating
the terminal-settled phase could still pass. The final consolidated repair adds
an exact unique four-phase assertion; the parent reran the exact regression and
all affected suites successfully. No production or evidence value changed.

Remaining qualifications are non-blocking for these promoted shared
primitives. The Resource sessions were captured on the unchanged standard
BlueStacks profile; the older record merely omits repeating that profile field,
so no fresh Resource run is required. Ultimate modal/recovery evidence already
exists in the retained Flee, false-Home Resource Shop, exit-dialog, measured
Campaign-exit, and Home-recovery sessions; it is not yet indexed into the new
control-replay corpus, so no fresh Ultimate run is required. Incomplete retained
causal traces remain diagnostic/unknown and never authorize runtime behavior.

The deferred shop/list product choice is Alliance Shop as its own flow, not a
representative route for Ruins or Rare Earth Shop. Its selected route is
Alliance → Alliance Shop → Weekly Offers (already selected), preferring Joy
Coins or Bioenhance Scheme when present. Otherwise use Shop → Other → 1★ Gear
Enhance Material → Buy → quantity 1 → Buy, then return Home. This decision does
not authorize a Stage 3 purchase or registration change.

The accepted Gathering continuation reuses the completed Home → World → Search
menu foundation, proceeds through resource category, exact level 5, Gas reveal,
and current-frame node binding, and must stop before march dispatch. Node or
march authority is not granted by Stage 3.

The parent integration decision is `accepted for Stage 3 offline control-primitives scope`.
Production registration remains `NOT_REGISTERED`, scheduler eligibility
remains disabled, runtime ownership is absent, and no emulator, ADB,
BlueStacks, gameplay, or other runtime input occurred. The Stage 3 closure is
the commit containing this file.
