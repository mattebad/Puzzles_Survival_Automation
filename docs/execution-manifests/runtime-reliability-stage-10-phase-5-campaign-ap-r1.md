# Stage 10 phase 5 Campaign AP promotion r1

## Control
- Task: `stage-10-phase-5-campaign-ap-r1`.
- Parent: `gpt-5.6-sol`, sole implementation, integration, and live-runtime owner under the continuing Solo route.
- Entry HEAD: `b43cd7b` with Stage 10 Phase 4 truthfully closed as `blocked_evidence_required` and production registration disabled.
- User authorization: explicit on 2026-08-26 through phases 4–6, Stage 11, convergence completion, and the merge boundary.
- Phase 7 means PvP/player attack only. Campaign AP is resource-funded PvE maintenance.

## Candidate and product precondition
- Exact flow: `CAMPAIGN-AP-AUTO-BATTLE-LIVE-CANARY`.
- Exact product: `campaign_ap-v1`, profile `pns-bluestacks-5-p64-800x1280-v1`.
- Exact first destination: `1-15-9`; exact static cost: 14 Campaign AP; exact quantity: one Auto Battle.
- Selection requires a fresh AP-regeneration projection with an observed balance of at least 14 and a due eligibility timestamp.

## Frozen architecture
1. Keep `flow_delivery_campaign_bluestacks.py` and the existing Campaign runtime controller as the only executable Auto Battle route; do not create a second controller or ledger.
2. Keep the checked-in production registry as the sole admission authority with at most one exact registered flow.
3. Select only from a fresh explicit AP-regeneration projection. Selection is zero-transport and cannot bind targets or acquire runtime ownership.
4. Consume registration atomically before DevelopmentSession observation or runtime connection; every terminal path leaves it disabled.
5. Bind the immutable registration snapshot into result and causal-trace evidence with exact type-sensitive equality.
6. Verify exact destination, static cost, AP before/after delta of 14, one battle result successor, one accounted campaign action, no Sweep/Blitz/Auto Complete/refill action, and canonical Home terminal.
7. Any post-input ambiguity requires effect reconciliation, denies identical retry, and closes the canary budget.

## Writable paths
- `automation_service/registry.py`
- `automation_service/handlers.py`
- `automation_service/service.py`
- `scripts/pnsctl.py`
- `scripts/flow_delivery_campaign_bluestacks.py`
- `tasks/flow_delivery_disabled_production_registry.json`
- Exact affected Campaign, automation-service, scheduler-pulse, conductor, authority-consistency, gameplay-contract, and DevelopmentSession tests.
- Parent closure: `CURRENT_HANDOFF.md`, `docs/runtime-reliability-convergence-status.md`, and this manifest.

## Acceptance
- Exact fixed Campaign AP registration is accepted; malformed, multiple, cross-bound, missing, and forged registrations fail closed.
- Fresh due AP-regeneration projection with observed balance at least 14 selects Campaign with zero transport; missing, stale, underfunded, future, duplicate, and restart-replayed projection occurrences select nothing.
- Live route consumes registration before observation and rejects a repeat before ownership or transport.
- Result and causal trace retain exact immutable registration equality.
- Focused Campaign, scheduler, service, registry, conductor, authority, and DevelopmentSession checks pass.
- One fresh zero-input observation precedes at most one bounded live canary.
- Success requires exact stage `1-15-9`, cost 14, AP delta 14, one victory-or-defeat successor, no refill or forbidden action, exact action/transport counts, and canonical Home.
- Final registry disabled, scheduler false, singleton released, and identical retries zero.

## Live budget
- One bounded Campaign AP canary.
- Maximum twelve total native inputs and exactly one Campaign AP Auto Battle action.
- Maximum Campaign AP spend: 14.
- Zero premium currency, refill, item-backed AP, Sweep, Blitz, Auto Complete, stamina, march, PvP/player attack, or real-money inputs.
- Identical retries: zero.
- Phase 6 remains unadmitted until Phase 5 is accepted or truthfully dispositioned.
