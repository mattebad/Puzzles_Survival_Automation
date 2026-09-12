# Stage 10 phase 4 Recruitment maintenance promotion r2

## Control
- Task: `stage-10-phase-4-recruitment-r2`.
- Supersedes r1 without altering its history. Refreeze reason: integration review found that the existing unified route did not expose its already-persisted three-tier maintenance state to the flow-delivery verifier.
- Parent: `gpt-5.6-sol`, sole implementation, integration, and live-runtime owner under the continuing Solo route.
- Entry HEAD: `02c35d5cf253b46de17f9dc2e4f21020a2ec6c46`, synchronized with upstream and clean.
- User authorization: explicit on 2026-08-26 through phases 4–6, Stage 11, convergence completion, and the merge boundary.
- Phase 7 means PvP/player attack only. Zombie Lair Quick Join remains ordinary PvE stamina/march maintenance.

## Candidate and product precondition
- Exact flow: `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE`.
- Exact product: `noahs_tavern_recruitment-v1`, profile `pns-bluestacks-5-p64-800x1280-v1`.
- One current uninterrupted production-path canary must inspect Basic, Intermediate, and Advanced and retain the independent 600/86400/172800-second tier state.

## Frozen architecture
1. Canonicalize the existing unified Recruitment controller under the maintenance flow identity; the Daily contract remains attribution/history, not a second executable controller.
2. Keep the checked-in registry as the sole admission authority with at most one exact registered flow.
3. Select only from a fresh explicit cooldown projection. Selection is zero-transport and cannot bind targets or acquire runtime ownership.
4. Consume registration atomically before DevelopmentSession observation or runtime connection; every terminal path leaves it disabled.
5. Extend the existing unified route result only to expose its already-persisted maintenance state. Do not create another controller or state store.
6. Verify exact tier identities, cooldown constants, observed outcomes, state identity, immutable registration snapshot, native action/transport counts, one continuous causal trace, and canonical Home.
7. Unknown or ambiguous effect denies identical retry and closes the canary budget.

## Writable paths
- `automation_service/registry.py`
- `automation_service/handlers.py`
- `automation_service/service.py`
- `scripts/pnsctl.py`
- `scripts/flow_delivery_recruitment_bluestacks.py`
- `scripts/noahs_tavern_recruit_bluestacks.py`
- `tasks/flow_delivery_bluestacks_registry.json`
- `tasks/flow_delivery_disabled_production_registry.json`
- `tasks/flow_delivery_queue.json`
- Exact affected Recruitment, automation-service, scheduler-pulse, conductor, authority-consistency, gameplay-contract, and DevelopmentSession tests.
- Parent closure: `CURRENT_HANDOFF.md`, `docs/runtime-reliability-convergence-status.md`, r1, and this r2 manifest.

## Acceptance
- Exact fixed Recruitment registration is accepted; malformed, multiple, cross-bound, missing, and forged registrations fail closed.
- Fresh due cooldown projection selects Recruitment with zero transport; missing, stale, future, deferred, duplicate, and restart-replayed projection occurrences select nothing.
- Live route consumes registration before observation and rejects a repeat before ownership or transport.
- Result and causal trace retain exact registration and maintenance state equality.
- Maintenance state contains exactly Basic/Intermediate/Advanced, cooldowns 600/86400/172800, valid remaining attempts, non-default per-tier outcomes, and matching account/server/reset identity.
- Focused Recruitment, scheduler, service, registry, conductor, authority, and DevelopmentSession checks pass.
- One fresh zero-input observation precedes at most one live canary.
- Success requires all three tiers inspected, every currently eligible zero-cost single accounted for, exact successor/persistence proof, exact action/transport counts, and canonical Home.
- Final registry disabled, scheduler false, singleton released, and identical retries zero.

## Live budget
- One bounded Recruitment maintenance canary.
- Maximum twelve total inputs and maximum three zero-cost free-single transports.
- Zero paid, premium, item-backed, 10x, resource, AP, stamina, march, PvP/player attack, or real-money inputs.
- Identical retries: zero.
- Phase 5 remains unadmitted until Phase 4 is accepted or truthfully dispositioned.
