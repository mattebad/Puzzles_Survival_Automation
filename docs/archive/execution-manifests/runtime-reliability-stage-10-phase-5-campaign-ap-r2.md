# Stage 10 phase 5 Campaign AP reproof r2

## Control
- Task: `runtime-reliability-stage-10-phase-5-campaign-ap-r2`.
- Flow: `CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY`.
- Parent: `gpt-5.6-sol`, sole integration and live-runtime owner.
- Entry HEAD: `0fe5186ea9211922c34f59bf3617f4e00177ae70`, with startup-surface recovery r2 accepted, committed, and pushed.
- User authorization: explicit r2 continuation on 2026-08-26 after successful Scarlett recovery to canonical Home.
- Prior r1 history remains retained: it blocked before input on `CampaignScreen.UNKNOWN` and is not relabeled.

## Product precondition
- Canonical Home or another positively recognized Campaign-admissible current source.
- Exact destination `1-15-9`.
- Exactly one Auto Battle.
- Exact Campaign AP cost and maximum spend `14`.
- Fresh observed AP balance at least `14` with a due AP-regeneration projection.
- If any source, funding, cost, destination, registration, runtime-owner, or safety fact is absent or ambiguous before input, close `blocked_evidence_required` with zero input.

## Frozen architecture
1. Use only the existing `scripts/pnsctl.py` DevelopmentSession/conductor seam and `scripts/flow_delivery_campaign_bluestacks.py` Campaign controller. Do not create a second runtime owner, controller, or ledger.
2. Run one zero-input DevelopmentSession observation before admission. Do not manufacture a source by navigation or restart.
3. After preflight passes, admit exactly one fixed Campaign production registration. Scheduler selection is zero-transport; the live route atomically consumes registration before observation/runtime and every terminal path leaves it disabled.
4. Keep the total native-input ceiling at twelve, with exactly one Campaign AP Auto Battle action and maximum AP spend 14.
5. Require current-frame source/target binding and immediate revalidation. Full-frame hashes are evidence metadata only, never selector authority.
6. Success requires destination `1-15-9`, configured cost 14, AP before/after delta 14, one victory-or-defeat successor, one accounted Campaign action, no refill/forbidden action, and canonical Home terminal.
7. Any unknown post-input effect enters reconciliation, denies identical retry, and closes the live budget.

## Writable scope
- `tasks/flow_delivery_disabled_production_registry.json` — one exact transient Campaign registration, consumed back to `NOT_REGISTERED` by the live path.
- `docs/execution-manifests/runtime-reliability-stage-10-phase-5-campaign-ap-r2.md`.
- `docs/runtime-reliability-convergence-status.md`.
- `CURRENT_HANDOFF.md`.
- No production-code mutation is authorized by this freeze. Any pre-input local defect must stop for explicit refreeze rather than widening scope.

## Acceptance
- Zero-input observation captures one native `800x1280` current frame, sends no input, creates no gameplay effect, and releases ownership.
- Preflight positively proves an admissible source, fresh AP balance at least 14, exact cost 14, destination `1-15-9`, disabled scheduler before admission, and no active runtime owner.
- One exact transient registration is the only registered/scheduler-eligible production flow.
- Live execution occurs only through `pnsctl`, consumes registration before input, and cannot retry identically.
- Successful result reports exact AP delta 14, one Campaign action, no refill/item/premium/Sweep/Blitz/Auto Complete/stamina/march/PvP/real-money action, exact transport/input accounting, and terminal canonical Home.
- Final registration is `NOT_REGISTERED`, scheduler is disabled, and runtime ownership is released.
- If the preflight is unfunded or not exact, disposition is `blocked_evidence_required` with zero live input.

## Live limits
- One r2 canary occurrence and no identical retry.
- Maximum twelve native inputs total.
- Exactly one Auto Battle; maximum AP spend 14.
- No AP refill and no item-backed AP.
- No premium currency.
- No Sweep, Blitz, or Auto Complete.
- No stamina or march action.
- No PvP/player attack.
- No purchase, Confirm, real-money action, Android Back, app restart, or manufactured startup surface.
- Registration must end `NOT_REGISTERED`; scheduler must end disabled.
