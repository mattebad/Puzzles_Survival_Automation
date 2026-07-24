# Flow-delivery coverage

Machine-readable companion: `tasks/flow_delivery_coverage.json`.

This matrix separates Daily objective ownership from independent maintenance. Retained gameplay,
navigation, offline replay, and supervised evidence are cumulative classifications: none of them
alone proves a production-controller replay or authorizes runtime input. Every flow below requires
a canonical Home terminal, remains not registered and scheduler-ineligible, and has zero live
attempts authorized.

## Coverage summary

| Flow | Identity | Offline implementation | Retained gameplay / navigation | Production positive replay | Evidence still required |
| --- | --- | --- | --- | --- | --- |
| `NANOWEAPON-BLUESTACKS-INTEGRATION` | Daily: one Normal Craft per reset | legacy one-craft semantic replay | none | not proven | native Normal Craft, 100 parts, claim-first, 12-hour timer, reset guard, Home |
| `NANO-MATERIAL-PRODUCTION-MAINTENANCE` | maintenance; no Daily ownership | not implemented | none | not proven | native idle/active/complete, claim/restart, six-hour timer, defer, Home |
| `RECRUITMENT-BLUESTACKS-INTEGRATION` | Daily: five Basic free singles | shared + integrated controller replay retained | 2026-07-16 semantic-frame mechanics/navigation | not proven | hash-bound production replay of five Basic windows and Home |
| `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE` | maintenance; inspect Basic/Int./Advanced | integrated three-tier replay retained | 2026-07-16 semantic-frame mechanics/navigation | not proven | independent cooldown persistence, per-tab defer, production replay, Home |
| `CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION` | Campaign AP maintenance | navigation, destination, vision, controller, battle replay retained | supervised BlueStacks mechanics + nonterminal production navigation attempts | not proven | native configured-stage Auto Battle production replay and Home |
| `CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY` | shared Campaign atlas navigation | atlas build, localizer, destination bind, shared seam, zero-transport replay | accepted survey corpus + offline zero-transport for atlas-supported destinations | not proven (live) | stage-9 under-chapter bind + live canary remain unauthorized |
| `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION` | Daily: one verified Flee per reset | entry/idempotency + ordered policy controller; missing-evidence gate is zero transport | offline navigation only; no Flee evidence | not proven | native Challenge → Exit → Flee, no-resource result, journal-backed replay, Home |
| `ZOMBIE-LAIR-BLUESTACKS-INTEGRATION` | Daily: first eligible join | legacy selected-Daily one-Lair replay | no Home-notification evidence | not proven | native notification, eligible join, 28 stamina, Daily result, Home |
| `ZOMBIE-LAIR-HOME-MAINTENANCE` | maintenance; continues after Daily | World/stamina primitives only | no Home-notification evidence | not proven | native defer/multi-lair/refill/recovery/Quick Join states and Home |

## Nanoweapon Daily craft

Flow: `NANOWEAPON-BLUESTACKS-INTEGRATION`

The retained `tasks/nanoweapon.py` and `tasks/daily_nanoweapon.py` replay is useful offline work,
but it does not yet encode the final Normal-only, exact-100-parts, completed-claim-first,
exact-12-hour, one-craft-per-reset contract. Exclusive Craft has no coverage. Navigation,
consequential execution, production replay, and supervised canary proof remain evidence-gated.

## Nano Material Production maintenance

Flow: `NANO-MATERIAL-PRODUCTION-MAINTENANCE`

This is independent maintenance and never owns the Daily craft objective. No implementation or
native evidence currently proves idle, active, complete/claim, restart, exact six-hour duration,
or normal defer behavior. It must reuse the eventual Nanoweapon screen navigation and return Home.

## Recruitment Daily objective

Flow: `RECRUITMENT-BLUESTACKS-INTEGRATION`

Daily completion belongs exclusively to five Basic free singles in the current reset, one per
availability window. Existing free-recruit, Daily, integrated semantic, recognition, controller,
result-overlay, and navigation work is retained rather than rebuilt.

The 2026-07-16 Computer Use session is valid gameplay/mechanics and semantic navigation evidence:
it proves Home → Tavern, Basic/Int./Advanced zero-cost singles, observed cooldowns, safe result
closure, Daily 5/5, no Claim input, and Home return. It retains semantic frame identifiers, not
raw hash-bound screenshots, a consequential journal, or a production-controller attempt record.
It therefore does not prove a production-grade automated replay or current-standard supervised
canary.

## Recruitment free-attempt maintenance

Flow: `RECRUITMENT-FREE-ATTEMPT-MAINTENANCE`

This independent pass inspects all three tabs, uses every currently available free single, tracks
Basic/Int./Advanced cooldowns independently, and explicitly defers unavailable tabs. The existing
integrated controller already supplies substantial three-tier recognition, recruit, result, and
cooldown machinery; final inspect-all-tabs/defer ownership and a production replay remain gated.

## Campaign AP farming

Flow: `CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION`

| Coverage field | State |
| --- | --- |
| `home_navigation_state` | offline navigation implementation retained |
| `story_destination_navigation_state` | offline destination implementation retained |
| `ap_execution_state` | offline Auto Battle controller/vision/replay retained |
| `destination_policy_id` | `campaign-supported-destinations` |

Supported and rejected Story destinations remain owned by product policy entry
`campaign-supported-destinations`; coverage does not duplicate those arrays. Tuple format is
`<story difficulty>-<stage>-<chapter>`. `1-2-9`, `ultimate-challenge`, and all other unsupported
tuples fail closed.

Retained supervised BlueStacks sessions are valid gameplay/mechanics evidence for configured-stage
Auto Battle, AP costs, repeated wins, natural regeneration, insufficient AP, refill avoidance, and
Home return. Retained Home Atlas/destination code and navigation-only attempts are navigation
evidence, but no terminal production route or production-controller positive replay is proven.
Fresh native replay must verify the displayed stage and cost on every entry, static costs, 120 AP
maximum, 360-second regeneration accounting, no refill, bounded repetition, defer, and Home.

## Campaign atlas navigation integration

Flow: `CAMPAIGN-ATLAS-NAVIGATION-INTEGRATION-AND-REPLAY`

Offline atlas build, viewport localization, current-frame destination binding, and shared
Campaign AP / Ultimate Challenge navigation seam are implemented. Production-path zero-transport
replay is retained for atlas-supported destinations (chapters present in the accepted survey plus
Ultimate Challenge). Atlas projection never authorizes input. Product Campaign AP destinations
`1-20-9`, `1-15-9`, and `2-2-9` map to atlas Chapters 20/15/2; stage 9 is selected after chapter
open. No live input, registration, or scheduler eligibility is authorized.

## Ultimate Challenge Daily

Flow: `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`

Ultimate Challenge remains separate from Campaign AP. Campaign entry reuse, Ultimate Challenge
entry binding, already-complete detection, reset idempotency, the exact ordered execution policy,
zero-resource/Auto Battle/refill guards, canonical-Home-only success persistence, and a truthful
zero-transport missing-evidence gate are implemented offline. The gate currently returns
`evidence_required` with zero transport: Challenge, Hero Lineup Challenge, upper-right Exit, Flee,
the no-resource completion result, and canonical Home have no native selector sequence or positive
production-controller replay/canary proof. Consequential SafeAction/SafetyStore journal integration
also remains required. Registration and scheduler eligibility remain disabled.

## Zombie Lair Daily completion

Flow: `ZOMBIE-LAIR-BLUESTACKS-INTEGRATION`

The first successful eligible Home-notification join in a reset owns Daily completion. The retained
selected-Daily/World one-Lair replay is offline support only; it is not evidence for the final
notification-driven route, exact 30–55 level policy, exact 28-stamina cost, Quick Join, refill
cancellation, Daily successor, or Home terminal.

## Zombie Lair Home maintenance

Flow: `ZOMBIE-LAIR-HOME-MAINTENANCE`

This independent Home pulse continues after Daily completion and plans up to
`min(eligible_lair_count, floor(current_stamina / 28))` joins. Existing World/stamina primitives
are retained, but no native evidence proves notification absence/defer, multi-lair ordering,
level-60 rejection, insufficient-stamina recovery, Quick Join, refill cancellation, or a safe
Home-equivalent terminal. Production replay and supervised canary proof remain required.
