# Stage 10 phase 2 World navigation promotion r2

## Control
- Task: `stage-10-phase-2-navigation-r2`.
- Parent: `gpt-5.6-sol-medium`, sole control-plane and live-runtime owner.
- Mutable role: one mapped `gpt-5.6-luna-xhigh` bounded implementation.
- Independent role: one mapped `gpt-5.6-terra-high` read-only review; one consolidated repair/recheck only for a concrete finding.
- User continuation: explicit on 2026-08-25; continue autonomously through Phase 6 unless a user-only blocker exists.
- Entry HEAD: `2f4266b84706b932d50469119ae4742622cedaa4`, synchronized with upstream and clean.
- Failure class entering r2: `local_defect`.

## Frozen correction and promotion contract
Recreate the accepted r1 bounded World bridge with these corrections included from inception:
1. The production registry defaults disabled and may contain exactly one strict `WORLD-MAP-NAVIGATION-FOUNDATION` phase-canary registration bound to the checked-in selection handler and `pns-bluestacks-5-p64-800x1280-v1`.
2. Scheduler selection is zero-transport, terminally fenced across duplicate/restart, and cannot bind a target, start/acquire runtime, create a DevelopmentSession, or invoke the World route.
3. Parent runs the existing World `DevelopmentSession` separately after selection, review, integration, and zero-input observation.
4. A live World full route atomically validates and consumes the exact current registration to canonical disabled state before DevelopmentSession creation or runtime observation, then keeps the immutable REGISTERED dispatch snapshot in runtime context and retained evidence. This strict pre-admission claim prevents snapshot-to-consume races.
5. Every completion, block, unknown result, or exception leaves registration disabled. A second invocation rejects before runtime observation/runner.
6. Post-consumption evidence verification rehydrates only an exact immutable World snapshot from retained result fields. It must validate REGISTERED status, true eligibility, exact fixed handler/profile, exact flow/product binding, and agreement between result and causal trace before use. Retained values cannot authorize arbitrary registration.
7. Dry-run, diagnostics, recovery, verification, and offline scheduler selection never consume or re-enable registration.

## Safety and scope
- Only World navigation: `HOME_READY -> World -> Search -> World -> HOME_READY`.
- Maximum live inputs: 20 existing navigation/popup inputs; zero resource, Daily, claim, combat, purchase, maintenance, AP/stamina, node, march, formation, or currency input.
- Unknown/blocked live result permanently closes this canary budget; no identical retry.
- Phase 3 remains separately admitted only after Phase 2 acceptance and disabled final registration.
- Writable paths: `automation_service/{registry,handlers,service,cli}.py`, `scripts/pnsctl.py`, `scripts/flow_delivery_world_map_bluestacks.py`, `tasks/flow_delivery_disabled_production_registry.json`, exact affected automation-service/World tests, and parent closure files.

## Acceptance
- Strict registry cardinality/default-disabled tests.
- First healthy offline pulse selects only World with zero transport; duplicate and reopened-store pulses cannot select it again.
- Product/registration/owner/clock/reset/unresolved mismatches select nothing.
- Live full-route registration is consumed atomically before runner; second attempt rejects before runtime observation and runner.
- Valid retained dispatch snapshot verifies after consumption; forged/mismatched snapshot fails.
- Existing Stage 9 persistence/rollback/reset tests and World safety suite pass.
- Terra returns `ADMIT_LIVE_CANARY`; parent integration accepts before runtime.
- One fresh zero-input observation, then at most one full World canary.
- Final registry is disabled whether accepted or failed.

## Execution outcome
- Parent integration passed 81 focused automation-service/World tests and 20 DevelopmentSession regressions. The final disabled-registry closure suite must remain green before publication.
- The required pre-canary observation completed at `.local-captures/development-sessions/observe-20260825T195948130828Z` with `dispatch=false`, `input_count=0`, and ownership released.
- The one r2 live canary ran at `.local-captures/development-sessions/WORLD-MAP-NAVIGATION-FOUNDATION-20260825T195954253466Z`. It atomically consumed the World registration, issued exactly one navigation input, and failed closed.
- The retained source bound `home-to-world` to broad ROI `[0,1167,631,1268]`; its center `[315,1217]` opened Daily Quest rather than World. Successor frame `fe28ec5ac027e2fd4a3f79f527a430120984619ed358cc8a10776fddcc1e59ff` semantically shows Daily Quest and was not accepted as `WORLD_READY`.
- Result: `status=blocked`, `reason=unknown_state_or_modal`, `terminal_runtime_state=safe_blocked_terminal`, one navigation transport, zero resource/AP/stamina/currency/combat/node/march/formation inputs, ownership released, and no lifecycle state.
- Failure class: `local_defect`. The bounded repair intersects a current-frame footer candidate with `_FOOTER_NAVIGATION_REGION`, changing the prior broad ROI to `[0,1167,150,1268]`; its exact regression and the 60-test World suite pass. Independent review found no issue and returned `ADMIT_MATERIALLY_CHANGED_CANARY`.
- No second canary ran. The supported `pnsctl bluestacks recover-home` attempt produced a zero-input blocked Troop Training recovery receipt at `.local-captures/development-sessions/TROOP-TRAINING-END-TO-END-CONSOLIDATION-20260825T200733654079Z`; it did not restore Home. The game remains on an unsupported Daily Quest panel, which is a manual-only state and an explicit hard stop.
- Final registration is `NOT_REGISTERED`; registered flows are empty and scheduler eligibility is false. Phases 3-6 remain unadmitted behind failed Phase 2 semantic-terminal acceptance. Phase 7 combat remains unauthorized.

## Decision and bounded correction prompt
Decision: `REJECT_STAGE_10` after Phase 1 acceptance and Phase 2 semantic-terminal failure.

Correction prompt: starting from the published disabled closure, independently authorize and implement an exact, current-frame-bound, navigation-only recovery for the retained Daily Quest panel or establish Home manually outside automation. Re-freeze a new Phase 2 revision with a fresh one-shot World registration, rerun duplicate/restart/offline gates and independent review, take a new zero-input observation, and permit at most one materially changed canary. Do not admit Phases 3-6 or Phase 7 before Phase 2 reaches World/Search/Home semantic success and canonical Home terminal.
