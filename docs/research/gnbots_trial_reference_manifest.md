# GnBots trial reference manifest

Static facts from 12 officially authorized Puzzles & Survival free-trial modules. Source profile is
400×652 at 120 DPI. Runtime target is independent Bliss 800×1280,
`com.global.ztmslg`.

This document and its JSON companion contain normalized facts, not vendor source. Production code
must never read `.local-reference/`, execute vendor JavaScript, use vendor binaries/selectors, or
copy vendor PNGs into runtime assets.

## Coordinate and evidence rules

- Vendor points remain source-profile observations until centralized calibration and Bliss-native
  target binding pass.
- Vendor ROIs are recorded first as `[x,y,width,height]`, then normalized to
  `[x1,y1,x2,y2] = [x,y,x+width,y+height]`.
- Negative, zero-size, or off-profile decoded geometry remains recorded as an anomaly. It is never
  silently repaired or made actionable.
- `basis=direct` means value/control flow appears in authorized static text. Inference is named
  explicitly in field text or a per-field basis.
- Template `tries` and `confirms` are matcher budgets, not semantic action proof.
- Raw 800×1280 evidence controls Bliss production coordinates. Editor previews, thumbnails, and
  rendered images have no coordinate authority.

Machine-readable authority: `docs/research/gnbots_trial_reference_manifest.json`.

## Inventory

| Module | Stable entries | Main coverage |
|---|---|---|
| `puzzlebot.base.alliancebase` | `GNB-ALLIANCE-MENU-OPEN`, `GNB-ALLIANCE-SECTION-ENTRY` | Alliance menu and section entry |
| `puzzlebot.base.base` | `GNB-BASE-LAUNCH-PULSE`, `GNB-BASE-MAP-STATE`, `GNB-BASE-MAP-TOGGLE`, `GNB-BASE-POPUP-SWEEP`, `GNB-BASE-TOWN-SWIPE-MACROS` | launch, map state, recovery, popup sweep, camera movement |
| `puzzlebot.base.dailies` | `GNB-DAILY-*` | Chapter, Quest claims, milestones, Praise, Depot, Quiz, free recruitment |
| `puzzlebot.base.gameconfig` | `GNB-GAMECONFIG-POPUP-REGISTRY` | map/popup template catalog and callbacks |
| `puzzlebot.base.gathervip` | `GNB-GATHERVIP-LIFECYCLE` | bounded tile work list and march count |
| `puzzlebot.base.launchlib` | `GNB-LAUNCH-DONT-SHOW` | launch popup and pulse grace |
| `puzzlebot.base.recruitment` | `GNB-RECRUITMENT-TRAIN` | troop training and amount selection |
| `puzzlebot.base.tilebase` | `GNB-TILE-*` | VIP search, dialogs, rally, troops, march |
| `puzzlebot.base.townbase` | `GNB-TOWN-*` | injected selector, camera refs, upgrade/build, resources, research |
| `puzzlebot.base.townpaths` | `GNB-TOWNPATH-*` | Hospital, Mansion, Productions, Wall paths |
| `puzzlebot.base.wall` | `GNB-WALL-REPAIR` | wall repair |
| `puzzlebot.base.worldbase` | `GNB-WORLD-*` | world check and coordinate menu |

## Shared runtime behavior

### `GNB-BASE-LAUNCH-PULSE`

`launch()` delegates to launch pulses only on first action/run. A normal pulse reports done after
more than three calls. Other branches return true because launch is inapplicable. No game screen
proves completion.

### `GNB-BASE-MAP-STATE`

Town/world state uses only the bottom-left toggle family:

| Visible template | Source ROI xywh | Normalized xyxy | Threshold | Meaning |
|---|---:|---:|---:|---|
| TownButton1 | `[11,594,48,48]` | `[11,594,59,642]` | 0.89 | current map World |
| TownButton2 | `[2,595,61,50]` | `[2,595,63,645]` | 0.90 | current map World |
| WorldButton1 | `[9,593,51,48]` | `[9,593,60,641]` | 0.89 | current map Town |
| WorldButton2 | `[2,594,59,51]` | `[2,594,61,645]` | 0.90 | current map Town |

Detection uses one try/one confirm. Ten unknown observations trigger Android Back and reset the
counter. `GNB-BASE-MAP-TOGGLE` waits 500 ms, refreshes, taps one matching toggle, waits 2000 ms,
then leaves destination recognition to a later pulse. Vendor `townCheck/worldCheck` test the
pre-transition state, so their return value does not prove a successful toggle.

### `GNB-BASE-TOWN-SWIPE-MACROS`

Named camera movement uses fixed two-swipe macros. Full geometry, including anomalous
`fastBottomLeft` destination x=1200, is preserved in JSON. These are route observations, not safe
Bliss gestures. `GNB-TOWN-REFERENCE-CAMERA` scans small reference templates at 0.92–0.94 and
applies a named macro when absent.

### `GNB-BASE-POPUP-SWEEP` and `GNB-GAMECONFIG-POPUP-REGISTRY`

Popup catalog thresholds range 0.88–0.96. Handlers may tap a local template, send Back, terminate
on maintenance, or execute short coordinate macros. `closeAllDialogs` has three rounds. One sweep
can continue after one handler fires because callback return does not stop registry iteration.
Lost-resource and free-broadcast handlers are action-like, so this generic catalog is unsafe inside
consequential transactions.

## Daily Activities

### `GNB-DAILY-LIFECYCLE`

Observed pulse order:

1. recenter world;
2. town check;
3. Chapter;
4. recruit;
5. Quest;
6. Quiz;
7. Depot;
8. leaderboard;
9. finish.

Every subtask completion flag is set after its function returns, including early failures. This is
attempt tracking, not verified completion.

### `GNB-DAILY-CHAPTER`

- Open `(27,495)`; wait 1000 ms.
- `IndicatorChapterMenu`: xywh `[13,186,57,49]`, xyxy `[13,186,70,235]`,
  threshold 0.90, tries 3, confirms 1.
- `ChapterClaimBtn`: xywh `[287,280,77,143]`, xyxy `[287,280,364,423]`,
  threshold 0.90, max 10, tries 3, confirms 2, 1000 ms after each.
- Exit `(196,573)`, wait 2000 ms, tap `(45,48)` twice, wait 1000 ms.

Claim-template exhaustion is the only completion signal; reward state is not independently proven.

### `GNB-DAILY-QUEST-CLAIMS`

- Open Quest `(158,621)`; wait 2000 ms.
- Main tab `(66,60)`.
- Main Claim xywh `[286,107,103,532]` → xyxy `[286,107,389,639]`.
- Daily tab `(200,57)`.
- Daily Claim xywh `[282,202,103,308]` → xyxy `[282,202,385,510]`.
- Both claim loops: maximum 20, threshold 0.90, tries 2, confirms 2, 250 ms after each.

Vendor flow does not bind each claim to an exact row or prove a row-local postcondition.

### `GNB-DAILY-MILESTONES`

Five `IndicatorBlueBar` ROIs map to y=125 taps:

| Source ROI xywh | Normalized xyxy | Tap |
|---:|---:|---:|
| `[48,162,9,10]` | `[48,162,57,172]` | `(48,125)` |
| `[125,163,11,8]` | `[125,163,136,171]` | `(125,125)` |
| `[202,165,10,7]` | `[202,165,212,172]` | `(202,125)` |
| `[282,163,10,10]` | `[282,163,292,173]` | `(282,125)` |
| `[361,161,10,11]` | `[361,161,371,172]` | `(361,125)` |

Loop stops at first missing marker. No chest/reward postcondition exists.

### `GNB-DAILY-LEADERBOARD-PRAISE`

- Route `(376,623)` → wait 2000 ms → `(312,569)` → wait 1000 ms.
- Leaderboard indicator xywh `[140,4,105,26]` → xyxy `[140,4,245,30]`,
  threshold 0.90, tries 4, confirms 1.
- Red marker xywh `[369,124,22,195]` → xyxy `[369,124,391,319]`,
  threshold 0.90, tries 2, confirms 1.
- Select dynamic row `(350, markerY+10)`; wait 2000 ms.
- Praise xywh `[354,66,41,283]` → xyxy `[354,66,395,349]`,
  threshold 0.90, tries 3, confirms 2, maximum four attempts/leaders, wait 1000 ms.
- Missing Praise sends Back.

Vendor completion does not prove Praise eligibility changed. Independent Praise remains a
single-input, no-cost, immediate-frame-bound transaction.

### `GNB-DAILY-DEPOT-FREE`

Vendor selector `1024_ope` is prohibited. Source resource points are Food `(50,550)`, Wood
`(150,550)`, Steel `(250,550)`, Gas `(350,550)`. Free marker xywh `[31,602,36,29]` normalizes to
`[31,602,67,631]`, threshold 0.92, tries 2, confirms 2. Maximum five rounds. Vendor triple-taps
without reacquisition; independent runtime must not.

### `GNB-DAILY-QUIZ`

Vendor selector `13_po` is prohibited. Coordinate macro is `(104,189)`, 500 ms, `(52,279)`,
1000 ms, `(199,536)`, 1000 ms, Back, 1500 ms. No phase anchor. Quiz remains disabled.

### `GNB-DAILY-FREE-RECRUIT`

Vendor selector `5008_ope` is prohibited. Free button xywh `[23,437,342,98]` normalizes to
`[23,437,365,535]`, threshold 0.90, tries 3, confirms 2. Next-free label xywh
`[2,541,394,42]` normalizes to `[2,541,396,583]`, tries 3, confirms 1. Maximum three categories;
result wait 1500 ms, then Back and 1000 ms. Result identity is not verified. Vendor 10× branch is
not free-only.

## Town, paths, build, research, and wall

### `GNB-TOWN-VENDOR-SELECTOR`

Vendor writes `setprop qo.comd.cua <code>_<operation>_<arg>`, waits, taps `(99,50)`, reads
`getprop qo.comd.ret`, then resets it. This injected runtime dependency is prohibited.

### `GNB-TOWNPATH-*`

- Hospital: target callback twice.
- Mansion: two `fastTopLeft` macros, callback four times.
- Productions: 14 fixed fast/directional movement and callback phases.
- Wall: two `fastBottomRight` macros, callback twice.

No path validates phase anchors or propagates callback failures.

### `GNB-TOWN-UPGRADE-BUILD`, `GNB-TOWN-RESOURCE-CONFIRM`, `GNB-TOWN-RESEARCH`

These record useful menu template names and initial matcher budgets but include impossible decoded
ROIs, missing `queueAvailable`, an ineffective loop initializer, and automatic resource-pack
confirmation. Attempts are often returned as success without queue/progress proof. They remain
outside first MVP.

### `GNB-WALL-REPAIR`

Vendor selector `1002_ope`, fixed taps, and local wall indicator precede a repair attempt. Module
clears its wall flag regardless of repair result and finishes next pulse. No healthy-wall
postcondition exists.

## World, tile search, gathering, rally, and march

### `GNB-WORLD-CHECK` and `GNB-WORLD-COORDINATE-MENU`

World check delegates to shared world detection and generic popup cleanup. Coordinate-menu flows
contain off-profile keypad points, anomalous ROI geometry, and inverted/undefined return
semantics. No location-change proof exists.

### `GNB-GATHERVIP-LIFECYCLE`

Configured tile list is processed one type at a time, reducing target level when search fails and
stopping on list exhaustion or march cap. Intended menu failure cap is three, but `state.tries` is
uninitialized; increment can become `NaN`, defeating that guard.

### `GNB-TILE-VIP-SEARCH`

Search uses local resource/monster templates at threshold 0.92, no-tile at 0.90, tile-found at
0.88, and bounded level reduction. Coordinate fallbacks and several decoded points are unsafe.

### `GNB-TILE-DIALOGS`

Gather/Attack/Rally templates use thresholds 0.88–0.90 and up to three attempts. Rally time uses
fixed coordinates only after local Rally recognition. Dialog acceptance is not task completion.

### `GNB-TILE-MARCH`

- No-more-marches: tries 2, confirms 1.
- March menu: intended maximum five checks, 800 ms polls.
- March button: xywh `[142,593,100,36]` → xyxy `[142,593,242,629]`,
  threshold 0.96.
- After tap: wait 1500 ms; recheck tries 2, confirms 1.
- Vendor success: March button disappears.

Static defects include a march-menu loop initializer that prevents template checks, zero-height
antiserum ROI, and off-profile coordinates. Button disappearance is weaker than queue/outbound
march proof. March remains outside first Daily Activities MVP.

## Recruitment module

`GNB-RECRUITMENT-TRAIN` uses a vendor-selected troop building, verifies recruit menu, skips when
progress is present, selects tier/amount, taps Train at threshold 0.94 with tries 3/confirms 2,
calls automatic resource refill, and taps Train again. Work items are removed before success and
final queue/progress is not checked. This is not the free Tavern recruitment flow and remains
disabled.

## Explicitly rejected vendor behavior

- Early return or function return recorded as completion.
- Attempted action recorded as completion.
- Blind triple taps.
- Coordinate-only phases without local verification.
- Automatic resource-pack consumption.
- Generic popup handling during consequential actions.
- Weak negative-only action postconditions without domain evidence.
- `setprop qo.comd.*` injected selector dependency.

## Bliss evidence dependencies

Unblocked calibration and code work continues, but these exact raw correspondences remain
non-actionable until captured:

- settled Town/world toggle;
- settled standalone More target;
- Rankings and Personal Might route states;
- Praise pre/postcondition;
- completed-unclaimed Daily Praise row;
- exact Claim pre/postcondition;
- march menu, button, capacity negative, and queue/outbound result.
