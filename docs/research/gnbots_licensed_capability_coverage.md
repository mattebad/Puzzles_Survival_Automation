# GnBots licensed-reference capability coverage

This is a normalized static-research inventory. No vendor JavaScript, binary, installer, or runtime
was executed. The archive describes a 400×652 at 120 dpi source environment; its coordinates,
ROIs, thresholds, and timing are evidence about the vendor flow only. They are not authorization
and must never be scaled into the 800×1280 Bliss production profile.

Machine-readable companion: `docs/research/gnbots_licensed_capability_coverage.json`.

## Inventory and classification

- Archive SHA-256: `9c04aa67ccec01574cadef36f8a584d19b3406bd749009b21f10b429b0a80ab5`
- 31 module identities, 29 unique JavaScript payloads, 218 PNG templates, and 24 decrypted
  `.bin` image payloads were inventoried.
- **Direct reference coverage** means an advertised vendor route and action exist. It does not mean
  the route is safe, semantically complete, or portable.
- **Partial reference coverage** means only part of the exact requested workflow exists.
- **Infrastructure-only coverage** means only shared navigation, detection, or transport concepts
  exist. **No reference coverage** means the workflow is absent. **Unverified** is reserved for an
  archive identity that cannot establish behavior.

## Every vendor module

The template column is the count of associated PNGs. Full normalized mechanics, including waits,
retries, ROIs, checks, translation boundaries, and required evidence, are in the JSON companion.

| Module | Class | PNGs | Function or logical section | Project relevance / important static facts |
|---|---|---:|---|---|
| `accountswitch` | direct reference coverage | 2 | account selection/switch | Manual-only; no runtime translation permitted |
| `alliancebase` | infrastructure-only coverage | 7 | Alliance entry/shared navigation | Named menu successors; vendor selector and coordinates excluded |
| `alliancedonation` | direct reference coverage | 10 | gifts and technology contribution | `OpenGift` .90; Donate .96/.94; list swipe; not-enough/no-more states; anomalous ROIs |
| `alliancegather` | direct reference coverage | 1 | Alliance Territory/Pit | resource choices and shared march; `IndicatorBuilt` .92; anomalous `tap(0)` |
| `alliancestore` | direct reference coverage | 12 | alliance store | Unmapped capability; store/buy/limit states |
| `arena` | direct reference coverage | 10 | arena battle | Unmapped capability; opponent/formation/result flow |
| `autoshield` | direct reference coverage | 10 | shield activation | Unmapped consequential inventory action |
| `bank` | direct reference coverage | 3 | bank/deposit | Unmapped building action |
| `base` | infrastructure-only coverage | 43 | image/action/popup primitives | Bounded matching concepts only; vendor cleanup and geometry unsafe |
| `buffs` | direct reference coverage | 16 | buff activation | Unmapped automatic item use |
| `build` | direct reference coverage | 2 | construct buildings | Build menu; dynamic unavailable ROI .92; initiation lacks queue proof |
| `campaign` | direct reference coverage | 20 | Campaign stage/battle | stage scan 4×11; Challenge tries4/confirms2; 15s + 40×500ms battle wait; no AP ledger |
| `dailies` | direct reference coverage | 11 | quest claims, Praise, Depot, recruit, chapter, quiz | Main/Daily claim loops up to 20; Praise up to 4×4; several action-attempt completions |
| `gameconfig` | infrastructure-only coverage | 0 | vendor option metadata | Names/defaults only |
| `gathervip` | direct reference coverage | 0 | monsters/lairs/resources and rally search | delegates to `tilebase`; uninitialized `state.tries` guard |
| `gathervip_1` | direct reference coverage | 0 | packaged alias/copy of `gathervip` | no independent payload or corroboration |
| `heal` | direct reference coverage | 2 | troop healing | Unmapped automatic resource action |
| `joinrally` | direct reference coverage | 2 | join alliance rally | Unmapped list-to-march route |
| `launch` | infrastructure-only coverage | 0 | vendor bootstrap | No game-route facts |
| `launchlib` | infrastructure-only coverage | 1 | startup helper | Foreground/source concept only |
| `productions` | direct reference coverage | 0 | collect/start production | Unmapped, weak action-attempt semantics |
| `recruitment` | direct reference coverage | 7 | four troop types | busy tries2; level scan max12; Train tries3/confirms2; no claim/completion proof |
| `research` | direct reference coverage | 5 | generic research | up to five scrolls; no Bioenhancer/free-only path; automatic resources unsafe |
| `tilebase` | infrastructure-only coverage | 24 | target/action/formation/march | search tries3/2, menu max5×800ms; missing/undefined `indicatorStamina` |
| `townbase` | infrastructure-only coverage | 21 | building selector/queues/resources | prohibited `setprop/getprop` selector; weak queue helper |
| `townpaths` | infrastructure-only coverage | 0 | town camera macros | out-of-frame x=1200/y=-1500 destinations; no canonical-camera proof |
| `transfer` | direct reference coverage | 5 | account/state transfer | Sensitive/manual-only; no project mapping |
| `upgrade` | direct reference coverage | 1 | building upgrade | prerequisites/resources; attempted input can be returned as success |
| `wall` | direct reference coverage | 2 | wall repair/defense | Unmapped consequential action |
| `worldbase` | infrastructure-only coverage | 1 | Town/World mode | Named source/successor concept |
| `puzzlebot.png` | unverified | 0 | packaging image/pseudo-module | no executable logic or capability evidence |

Template counts sum to 218. Modules without a direct current-quest mapping remain in the inventory
so they are not mistaken for uninspected coverage.

## Requested workflow matrix

| Project workflow | Classification | Vendor section | What transfers | Missing semantic proof / live evidence |
|---|---|---|---|---|
| Consume stamina through zombie lairs | direct reference coverage | `gathervip` + `tilebase` | search/lair/rally/march stages and negatives | stamina before/after, exact cost, dispatch/result, slots and insufficient state |
| Consume AP through campaign | partial reference coverage | `campaign` | stage/challenge/formation/battle stages | AP OCR/delta, refill guard, result and Daily reconciliation |
| Send gathering marches | direct reference coverage | `gathervip` + `tilebase` | resource/type/level and march-slot model | each resource, occupied/no-tile/no-slot, dispatch and status |
| Claim personal praise | direct reference coverage | `dailies.Praise` | More → Rankings → leader → Praise | positive postcondition and intercepted/disabled negatives |
| Free daily Bioenhancer research | infrastructure-only coverage | generic `research` only | research screen/queue concepts | exact Bioenhancer route, Free 1x guard/result, non-free and 10x negatives |
| Enhance gear with one 1-star material | no reference coverage | none | none | complete safe manual flow and all selection/result states |
| Enhance chip with one 1-star material | no reference coverage | none | none | complete safe manual flow and all selection/result states |
| Enhance module with one 1-star material | no reference coverage | none | none | complete safe manual flow and all selection/result states |
| Build or craft a nano weapon | no reference coverage | none | none | recipe/material/timer/start/result and negative variants |
| Claim and train troops | partial reference coverage | `recruitment` | types, quantity and busy states | claimable/completion evidence and safe start/postcondition |
| Train all troop types from one screen when available | partial reference coverage | `recruitment` | four-type enumeration | vendor uses separate building selectors; native type-tab route required |
| Upgrade a hero three times | no reference coverage | none | none | selected eligible hero, three exact actions, max/shortage states |
| Reset and re-promote a max-level hero | no reference coverage | none | none | max/reset/cost/confirm/result/promote sequence and negatives |
| Use one resource item from Bag | no reference coverage | none | none | category/item, quantity exactly one, confirmation and inventory delta |
| Claim alliance gifts | direct reference coverage | `alliancedonation` | gift entry/available model | available/open/post count, empty and cooldown/limit states |
| Contribute to alliance technology | direct reference coverage | `alliancedonation` | node/donate/negative taxonomy | exact pre/post count, locked, not-enough and no-more states |
| Build or upgrade an eligible building | direct reference coverage | `build` + `upgrade` + `townbase` | eligibility/prerequisite/queue concepts | association, cost/confirm, free/busy queue, start/countdown/completion |
| Pit mining | direct reference coverage | `alliancegather` | mine type and march handoff | home status, entry, mining/countdown/full/claimable/unavailable states |

## High-value vendor mechanics, with limits

- Quest claims use Main ROI `[286,107,103,532]` and Daily ROI `[282,202,103,308]`, up to
  20 passes at tries2/confirms2 with 250ms waits. These are source facts, not usable coordinates.
- Praise uses a leaderboard indicator at `[140,4,105,26]`, a Praise ROI at
  `[354,66,41,283]` with threshold `.90`, and loops across at most four leaders. It does not
  provide the project's required durable postcondition.
- Campaign searches next-level variants at `.88`, checks Challenge at `.90, tries4/confirms2`,
  and waits for battle state/result. It does not account for AP.
- Resource/lair routes advertise Food, Wood, Steel, Gas, Zombie, Skeleton, Wolf, and Lair levels
  1–15 plus rally durations 5/15/30/60 minutes. The shared march implementation references a
  missing stamina detector and therefore cannot establish resource-safe completion.
- Recruitment advertises all four troop types, but selects their buildings independently. It
  detects a busy/progress state and presses Train; it does not prove training completion or claim.
- Generic research does not contain Bioenhancer naming, a daily Free 1x route, or a free-only
  postcondition. It is infrastructure coverage for that exact quest, not direct coverage.

## Translation boundary

Reusable ideas are semantic destinations, bounded-state models, negative-state taxonomies, and
candidate sequence structure. Vendor APIs, selector injection, raw coordinates, camera macros,
automatic resource packs, blind repeated taps, popup cleanup, action-attempt completion, and all
vendor images/code are excluded. Every adopted project detector and action requires independent
800×1280 evidence and the repository's current source/before/transport/post/semantic/journal safety
sequence.
