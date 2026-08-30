# Daily Quest handler status

Current status authority: `tasks/daily_quest_execution_matrix.json`.
Objective identity authority: `tasks/daily_quest_catalog.json`.

Catalog status values are retained legacy observation snapshots only. This file mirrors matrix
status; it must not become an independent status source. All scheduler eligibility is false.

## Live-validated

- Historical Bliss evidence for Help, Praise, and Personal Might Claim remains
  retained, but those legacy gameplay adapters and operator registrations are
  retired.

Objective completion attribution remains separate from the single aggregate
Daily Claim flow. All scheduler eligibility remains false.

## Offline implemented

- Aggregate Daily Claim contract: `tasks/available_daily_claim.py` and
  `scripts/daily_row_claim_bluestacks.py`; one ordinary free non-milestone
  Claim tap must increase points and clear all ordinary Claim controls.
- Milestone Claim contract: `tasks/activity_milestones.py`.
- Supply Depot free contract and selected-Daily adapter:
  `tasks/supply_depot.py` plus `tasks/daily_supply_depot.py`.
- Free Recruitment contract and integrated Noah's Tavern route:
  `tasks/free_recruitment.py`, `tasks/daily_recruitment.py`,
  `tasks/noahs_tavern_recruit.py`, `tasks/noahs_tavern_recruit_runtime.py`, and
  `tasks/noahs_tavern_recruit_vision.py`.
- Bioenhancer free-research contract and selected-Daily adapter:
  `tasks/bioenhancer.py` plus `tasks/daily_bioenhancer.py`.
- Nanoweapon pure offline Craft contract: `tasks/nanoweapon.py` plus
  `tasks/daily_nanoweapon.py`; these retain useful policy/postcondition primitives but still encode
  legacy selected-weapon, zero-cost, and non-exact-duration assumptions.
- Gear/Chip/Module shared enhancement contract: `tasks/enhancement.py` (all three variants
  complete offline).
- Daily Gear/Chip/Module row adapter: `tasks/daily_enhancement.py` (all three variants).
- Campaign Auto Battle implementation: `tasks/campaign_auto_battle.py`,
  `tasks/campaign_auto_battle_runtime.py`, and `tasks/campaign_auto_battle_vision.py`; the older
  `tasks/campaign_ap.py` and `tasks/daily_campaign_ap.py` Sweep/Auto Complete semantics are retained
  implementation debt and are not approved execution policy.
- Ultimate Challenge navigation/reset primitives: `tasks/ultimate_challenge_daily.py` plus the
  navigation-only BlueStacks adapter; Flee execution is not implemented.
- Zombie Lair pure offline contracts: `tasks/zombie_lair.py` and `tasks/daily_zombie_lair.py`;
  these retain transaction primitives but still model a World/static-Daily-row, single-lair flow
  with stale generic level/cost assumptions.
- Shared World/stamina primitive: `tasks/world_stamina.py` (route, resource, and budget replay
  only).
- Zombie Lair contract: `tasks/zombie_lair.py` (allowlisted Lair, march, and stamina replay only).
- Disabled Stamina contract: `tasks/stamina_disabled.py` (counter replay and unconditional
  no-dispatch guard only).
- Gathering family contract: `tasks/gathering.py` (Wood, Steel, and Gas node/march variants
  complete offline; Gather Food excluded).
- Disabled Training contract: `tasks/training_disabled.py` (Fighter, Rider, Shooter, and Vehicle
  queue replay with unconditional no-dispatch guard).
- Disabled Building Upgrade contract: `tasks/building_upgrade_disabled.py` (generic identity/
  level replay; Vehicle Depot remains Main-only and no-dispatch guard is unconditional).
- Disabled Hero Duel contract: `tasks/hero_duel_disabled.py` (event/Join/progress replay with
  unconditional no-PvP-dispatch guard).
- Disabled Tech Upgrade contract: `tasks/tech_upgrade_disabled.py` (prerequisite/level replay
  with unconditional no-research-dispatch guard).
- Disabled Hero Upgrade contract: `tasks/hero_upgrade_disabled.py` (selected-hero/material/level
  replay with unconditional no-upgrade-dispatch guard).
- Disabled Purchase contracts: `tasks/purchases_disabled.py` (Box, Ruins, Rare Earth, and
  Alliance Shop offer/cost replay with unconditional no-purchase-dispatch guard).
- Disabled Alliance Technology donation contract: `tasks/donation_disabled.py` (tech/resource/count
  replay with unconditional no-donation-dispatch guard).
- Disabled Speedup contract: `tasks/speedup_disabled.py` (180-minute timer/item replay with
  unconditional no-speedup-dispatch guard).
- Disabled Ruins Challenge contract: `tasks/challenge_disabled.py` (challenge identity/cost/result
  replay with unconditional no-entry-dispatch guard).
- Disabled Resource Boost contract: `tasks/resource_boost_disabled.py` (resource-building
  identity/resource/duration/cost replay with unconditional no-boost-dispatch guard).
- Task-state and one-pulse scheduler contracts: `tasks/scheduler.py`,
  `safe_action_core/task_state.py`, and `safe_action_core/store.py`.

These contracts remain unregistered and evidence-gated where matrix says so. “Offline
implemented” does not mean that the newly approved policy, production replay, or supervised canary
is complete.

## Reconciled Daily and maintenance identities

The five affected families own eight distinct identities. None is production-complete, registered,
or scheduler-eligible.

### Nanoweapon Daily Craft

- Daily owner: one Normal Craft start per verified reset from canonical Home; claim a completed
  weapon on entry, require exactly 100 nano parts and an enabled Craft control, use an exact
  43,200-second duration, and return Home.
- Existing work: pure offline Nanoweapon and Daily adapters plus synthetic policy fixtures.
- Gap/evidence: reconcile legacy zero-cost/selected-weapon assumptions; add Gear Factory radial,
  Nanoweapon, claim, Normal Craft, parts/control/timer, reset-ledger, and Home selectors; then obtain
  production-path replay and a separately authorized canary. Exclusive Craft and rotating-display
  selection are prohibited.

### Nano Material Production maintenance

- Maintenance owner: independently inspect Material Production; claim a completed batch and start
  the next, start one when idle, or record/refresh the due time and defer when active. Exactly one
  batch may be active, duration is 21,600 seconds, and resource/item/currency cost is zero.
- Existing work: distinct schema-v2 contract only; the old synthetic fixture is merely a negative
  for Daily Craft and is not positive maintenance evidence.
- Gap/evidence: implementation, native state/selector evidence, due-time persistence, zero-resource
  postconditions, production replay, supervised canary, and canonical Home terminal proof.

### Recruitment Basic-five Daily objective

- Daily owner: five Basic free single recruits in the current reset, one per exact ten-minute
  availability window. Int. and Advanced do not own Daily completion; already-complete is
  idempotent.
- Existing work/evidence: the integrated route and Daily/free adapters are retained. The
  `evidence/sessions/20260716-noahs-tavern-daily-free/record.md` session is valid
  gameplay/mechanics evidence for Home → Tavern, three Basic plus one Int. plus one Advanced
  zero-cost recruits, result-overlay closure, observed cooldowns, Daily 5/5, and Home return.
- Gap/evidence: extend Basic reset/cooldown persistence to the approved five-window contract and
  obtain a production-grade recognizer/controller/persistence replay. The semantic-frame session is
  not hash-bound journal-backed production proof.

### Recruitment free-attempt maintenance

- Maintenance owner: inspect Basic, Int., and Advanced independently; use every currently available
  free single; persist exact ten-minute Basic, 24-hour Int., and 48-hour Advanced estimates; defer
  cooling-down or exhausted tabs and return Home. Paid, premium, item-backed, 10x, and ambiguous
  recruitment are prohibited.
- Existing work/evidence: reuse the same integrated navigation, tab recognition, free recruit,
  overlay, and Home-return primitives and the retained 2026-07-16 gameplay/mechanics evidence.
- Gap/evidence: implement the full three-tab maintenance loop and independent persistence, then
  prove the production controller replay and later supervised canary.

### Campaign AP Auto Battle

- Owner: on every Campaign entry navigate to and verify configured stage `1-15-9`/14 AP,
  `1-20-9`/16 AP, or `2-2-9`/20 AP; maximum AP is 120 and regeneration is one AP per 360 seconds.
  Use Auto Battle only, run while displayed AP permits, prohibit every refill, and return Home.
- Existing work/evidence: the Campaign Auto Battle model, runtime controller, vision, templates,
  local executable adapter, and retained 2026-07-16 gameplay/mechanics sessions already prove
  bounded repeated Auto battles, AP/result handling, insufficient AP, refill avoidance, and Home
  return on BlueStacks.
- Gap/evidence: integrate the static map/max/regeneration policy, remove stale Sweep/Blitz/Auto
  Complete claims, and obtain a production-controller positive replay plus supervised production
  canary. Retained local evidence is not production journal proof.

### Ultimate Challenge Daily

- Daily owner: canonical Home → Campaign → Ultimate Challenge → Challenge → Hero Lineup Challenge
  → upper-right Exit → Flee → canonical Home. Flee completes the reset objective without AP,
  stamina, currency, item, or Auto Battle use; already-complete is idempotent.
- Existing work: Campaign Home Atlas entry reuse, Ultimate Challenge entry recognition,
  already-complete evaluation, reset-window persistence, the exact ordered execution policy,
  zero-resource/Auto Battle/refill guards, canonical-Home completion gating, and a fail-closed
  zero-transport replay evidence gate are implemented offline.
- Gap/evidence: native Challenge/lineup/Exit/Flee/Home selectors, consequential SafeAction/SafetyStore
  and journal integration, production-controller positive replay, supervised Flee canary, and Home
  terminal proof. Synthetic observations and self-declared hashes do not satisfy this gate.

### Zombie Lair Daily completion

- Daily owner: the first successful eligible Home-notification join in the reset completes the
  Daily objective. It is not launched as a static Daily-row flow when no lair exists.
- Existing work: the old Daily adapter supplies reusable one-join arithmetic only.
- Gap/evidence: bind Daily completion to the first successful maintenance join and add reset
  idempotency; no positive native Lair evidence or production replay exists.

### Zombie Lair Home maintenance

- Maintenance owner: observe Home notifications, accept levels 30–55 only, prohibit level 60,
  spend exactly 28 stamina per Quick Join, and join
  `min(eligible_lair_count, floor(current_stamina / 28))`. Continue after Daily completion; defer
  normally when no lair exists or stamina is below 28, estimate recovery, never refill, and return
  to canonical Home or a recognized safe Home-equivalent state.
- Existing work: reusable pure transaction/stamina primitives; no notification-driven controller.
- Gap/evidence: Home notification and multi-lair recognition, exact level/cost/stamina selectors,
  Quick Join, safe refill-prompt cancellation, recovery persistence, per-join postconditions,
  production replay, supervised canary, and terminal Home evidence.

## Evidence-gated planned flows

The reconciled Nanoweapon Daily, Nano Material Production maintenance, Recruitment Daily,
Recruitment maintenance, Campaign AP Auto Battle, Ultimate Challenge Daily, Zombie Lair Daily,
and Zombie Lair Home maintenance identities remain evidence-gated as detailed above.
`gather_wood`, `gather_steel`, `gather_gas`, `enhance_gear`, `enhance_chip`, and
`enhance_module` retain their existing evidence gates and are not changed by this reconciliation.

## Bioenhancer historical evidence retained; current proof required

`bioenhancer_research` has retained historical transaction artifacts, including
`bioenhancer-free-1784069057`. Those artifacts remain immutable historical evidence only. The
current schema-2 gameplay contract is `evidence_required`, production-ineligible, and
registration-disabled; the retained action is not rebound to the current Stage 8 contract or
HEAD.

The current admissible route remains one zero-cost Free Research 1x with a positive research/
cooldown successor, current reset identity, one continuous flow-owned DevelopmentSession,
canonical Home, and separate Claim ownership. No new observation or input is authorized in Stage
8. Current production-controller replay and current Daily reconciliation remain
`EVIDENCE_REQUIRED`.

The historical journal, action count, and retained Daily frames remain preserved as evidence
metadata. They do not authorize research dispatch or Claim execution.

## Evidence acquired, collection policy-gated

`supply_depot` has retained Bliss-native navigation evidence at selected Daily `0/5`: exact
row-local Go `(554,786)-(731,878)`, direct Supply Depot successor, four visible Free controls,
annotated first free-single reward target `(35,1170)-(174,1261)`, observed basic reward, no
overlay, and bounded return through Home/Base → Quest → selected Daily. No collection input
occurred. Promotion remains `POLICY_GATED`; game-day identity, known-reward approval, positive
collection postcondition, and Daily progress reconciliation remain required. Claim remains
separate. Evidence package:
`evidence/sessions/20260714-daily-flow-acquisition/supply-depot-navigation.json`.

## Policy-disabled flows

`upgrade_building`, `upgrade_tech`, `train_fighter`, `train_rider`, `train_shooter`,
`train_vehicle`, `upgrade_hero`, `consume_stamina` (counter-only contract; spend remains blocked),
`buy_box`, all shop purchases,
`boost_resource_building_output`, `donate_alliance_tech`, `speedup_using_items`,
`ruins_challenge`, and `join_hero_duel` remain offline-only, unregistered, and
scheduler-ineligible.

The provenance audit's retained selected-row snapshot still classifies the observed Ultimate
Challenge candidate, Vehicle Depot, Hunt Zombie, and Own Hero as Main-only; Gather Food/Gathered
Food as synthetic-only; and Headquarters attack/win as documentation-only. That historical
classification is not promoted or rewritten. The approved separate Ultimate Challenge
daily-reset flow does not claim selected-Daily-row provenance, and Hunt Zombie remains distinct
from the catalogued Defeat Zombie Lair objective.

## Separation rules

- Main Quest Claim is explicitly excluded from active scope.
- One aggregate selected-Daily Claim flow owns every ordinary Daily Claim tap;
  milestone Claim remains separate.
- Objective flows provide completion attribution only and never own Claim.
- Static GnBots geometry and calibration output never authorize input.
- Existing runtime registrations are not inferred from offline modules.
- No new runtime registration, scheduler eligibility, worker wiring, live task-state row, lease,
  journal migration, ADB operation, or gameplay input occurs in this planning run.
