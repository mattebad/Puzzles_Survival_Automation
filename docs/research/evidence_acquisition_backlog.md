# Ordered evidence-acquisition backlog

This is a capture inventory, not runtime authorization. Capture related states in the same manual
session where practical. Preserve raw full frames before deriving bounded OCR crops. Platform must
be recorded with every artifact; BlueStacks evidence is discovery evidence and Bliss evidence is
production acceptance evidence.

Both supplied BlueStacks town-home frames are native 800×1280 screenshots. The earlier frame is
user-confirmed zoomed in and is the source of the atlas ROIs; the later frame is user-confirmed
fully zoomed out, although the entire base is still not visible. No coordinates are transformed
between them. The annotated 781×1248 image is label-only. None establishes Bliss coordinates.

## 1. Bliss town-home baseline and state variants

Highest value because every building and bottom-navigation route depends on a recognized source
and camera state.

Capture in one Bliss session:

1. Original raw ADB 800×1280, 160 dpi town-home screenshot with package
   `com.global.ztmslg` foreground, no overlay, and the fully-zoomed-out camera state. Capture a
   zoomed-in comparison separately; do not derive either from the other.
2. A short manual camera-reset recording covering zoomed-in → fully-zoomed-out and a displaced
   pan → intended reference position. Include the final untouched full frame, the zoom gesture,
   at least one intermediate zoom, and two materially different pan/drift frames. Record whether
   the game clamps consistently at the fully-zoomed-out limit.
3. Build queue full frames for free/available, busy with countdown, and completed/claimable. Save
   tight OCR crops for `0/2` or equivalent and the countdown, plus an unavailable/full-queue state.
4. Research queue full frames for free/available, busy with countdown, and completed/claimable.
   Save queue-count and timer OCR crops.
5. Each Fighter, Shooter, Rider, and Vehicle camp in idle, training/countdown, and
   completed/claimable states. Include a negative frame where a green upgrade arrow or unrelated
   marker is near a camp so claimable-vs-upgrade detectors can be separated.
6. Pit home widget in Idle, mining/countdown, full/claimable, and unavailable/locked states.
7. Orange stamina and blue AP bars at ordinary values, plus low and refill-dialog states when they
   occur naturally. Save bounded OCR crops with their original full-frame parents.
8. Post-tap successor and Back-to-home full frames for Player Profile, World, Hero, Quest, Bag,
   Alliance, and More. Include a More/Help intercepted-webview or overlay negative if encountered.

Do not manufacture low-resource, busy, or unavailable states by spending resources solely for
capture. Record them when they naturally exist.

## 2. Campaign AP transaction

Capture one continuous manual flow, ideally with the corresponding Daily quest visible before and
after:

- town-home entry frame with readable blue AP;
- Campaign entry and selected stage, including stage cost;
- Challenge, formation, battle/sweep/auto-complete choice, and any confirmation dialog;
- immediate success/result frame and return screen;
- post-action AP frame proving the exact delta;
- post-action Daily quest progress/claimable state;
- bounded AP OCR crops from before and after;
- unavailable variants: insufficient AP, refill dialog, locked stage, no sweep/auto-complete,
  formation blocked, defeat, and battle still in progress.

The recording must show whether AP is consumed at Challenge, formation confirmation, battle start,
or result. This determines the consequential boundary.

## 3. World stamina, zombie lairs, and gathering marches

Capture these together because they share World search, formation, march slots, and resource bars:

- Town and positive World-map entry full frames;
- search/VIP panel, Zombie Lair choice, level selection, stamina cost, and target result;
- rally/attack choices, 5/15/30/60-minute rally selector if present, formation, and March;
- immediate before/after stamina full frames and OCR crops proving the exact cost;
- dispatched march line/status and the semantic result or return state;
- level-60 or project-target lair state if materially different from lower levels;
- no target, occupied/changed target, insufficient stamina/refill, no march slot, formation error,
  rally unavailable, and defeat/cancelled variants;
- Food, Wood, Steel, and Gas search results; one complete gathering dispatch; resource type/level,
  Gather, formation, March, and the march/status successor;
- occupied tile, disappeared tile, no tile, and no march slot variants;
- Daily quest progress before/after the stamina and gathering actions.

Preserve short recordings for both a lair action and a gathering action. Still frames alone may not
reveal when a volatile target becomes bound.

## 4. Troops, building work, generic research, Bioenhancer, and Pit

These routes share town buildings, queues, timers, and completion indicators.

### Troops

- open each camp once, then capture whether a single training screen exposes Fighter, Shooter,
  Rider, and Vehicle type tabs without returning to town;
- each selected type, level, quantity control, resource cost, Train button, and confirmation;
- idle/available, busy/countdown, completed/claimable, and post-claim states;
- insufficient resources, queue full/busy, locked troop level, and no-trainable-unit states;
- one safe manual training start and one later claim, with immediate before/post frames and a short
  recording of any cross-type tab navigation.

### Build or upgrade

- green upgrade arrow associated with its exact building, plus a nearby unrelated green-marker
  negative;
- selected eligible building/site, Build or Upgrade menu, prerequisites, cost, and confirmation;
- free queue and busy/full queue responses;
- immediate pre-start, confirmation, immediate post-start, home countdown, and completion/claimable
  states;
- ineligible prerequisite, insufficient resource, and unavailable-builder states.

### Research and free daily Bioenhancer

- research building/menu and Bioenhancer category entry;
- exact Bioenhancer item, Free 1x enabled, immediate-before, tap/transport, result, and postcondition;
- Daily quest or availability proof after completion;
- non-free 1x, 10x, insufficient material, already-used/cooldown, research queue busy, and locked
  variants;
- full frames plus bounded OCR crops for `Free`, costs, counts, and timers.

### Pit mining

- home Pit Idle widget, post-tap entry, Alliance Territory/mine selection, resource choice, formation
  and March;
- immediate post-dispatch home status, mining countdown, mine-full/claimable, post-claim, and Daily
  progress;
- mine not built/locked, already mining, no march slot, mine full, and unavailable-resource states.

## 5. Enhancement, nano weapon, hero, and Bag discovery

No meaningful vendor route exists for these workflows. Capture each as a short uninterrupted manual
recording with raw full-frame stills at every decision point.

### Gear, chip, and module enhancement

For each item family separately capture:

- entry from town and the exact item selected;
- enhancement screen with auto-select disabled if possible;
- material picker, a clearly identified 1-star material, quantity exactly one, preview delta, and
  confirmation dialog;
- immediate success animation/result and post-level/material-count state;
- no 1-star material, insufficient material/currency, locked item, max-level item, accidental
  multi-select warning, and cancellation states.

Do not infer that the three families share coordinates or confirmation behavior merely because the
screens look similar.

### Nano weapon

- route to Build/Craft Weapon, recipe/item selection, required materials, quantity, timer, and start
  confirmation;
- immediate post-start, busy timer, completion/claim, and inventory/result;
- insufficient materials, locked recipe, queue busy, material-production alternative, and
  inherit/replace dialogs if present.

### Hero upgrade and reset/re-promote

- Hero entry, selected eligible non-max hero, material/cost, one upgrade action and post-level;
- a three-upgrade sequence showing whether the same button remains stable and when costs change;
- insufficient material and max-level states;
- max-level hero reset entry, cost, warning/confirmation, cancellation, result, and returned
  materials/level;
- promote/re-promote entry, requirements, confirmation, result, and blocked/insufficient states.

The reset is consequential: discovery evidence should be manual and reversible-state consequences
must be recorded before any future automation task is proposed.

### Bag resource item

- Bag entry, resource category, a specific resource item, item detail, Use dialog, quantity set to
  exactly one, confirmation, and post-inventory/resource delta;
- quantity default greater than one, locked/non-usable item, insufficient quantity, and cancel
  states;
- bounded OCR crops for item count, quantity, and resulting resource value.

## 6. Alliance gifts, technology, and Praise refresh

Capture these in one Alliance/More session:

- Alliance entry; Gifts normal list, gift available, Open/Claim, immediate result, post-count,
  empty list, cooldown/limit, and unavailable states;
- Alliance Technology tree, recommended and ordinary available nodes, selected node, contribution
  cost/count, Donate, immediate post-count and quest progress;
- locked node, insufficient contribution currency, no-more-attempts/cooldown, confirmation, and
  any scrolling/loading variants;
- More -> Rankings -> leader -> Praise entry, enabled Praise, immediate result/postcondition,
  disabled/already-used state, no eligible leader, and webview/interception negative;
- short recordings for gifts, one contribution, and Praise, with source and return-home frames.

## Capture packaging requirements

For every session retain:

- platform (`bluestacks` or `bliss`), device/serial alias without credentials, logical viewport,
  physical frame size, DPI, package, timestamp, and game-day identity where applicable;
- raw full frame for entry, immediate-before, immediate-post, success, busy/unavailable, and each
  confirmation dialog;
- recording segment names that map to still frames and a human-written action sequence;
- OCR crops only as children of retained raw full frames, with crop `xyxy`, engine configuration,
  expected text class, and positive/negative labels;
- hashes and a manifest separating BlueStacks discovery evidence from Bliss acceptance evidence.

No production coordinate is accepted from a scaled chat image, vendor image, vendor coordinate, or
BlueStacks frame. A BlueStacks detector candidate becomes portable only after independent Bliss
full-frame reacquisition and verification.
