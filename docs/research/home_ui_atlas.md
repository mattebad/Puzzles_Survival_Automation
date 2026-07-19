# Town-home UI atlas

This atlas records semantic discovery facts, not production input authority. Both clean BlueStacks
sources are original 800×1280 PNGs. The earlier source was later identified by the user as zoomed
in; the second is a single fully zoomed-out viewport, not the completed multi-viewport atlas. A
coordinate is valid only in the exact BlueStacks source and camera state where it was observed.
The annotated chat image is 781×1248 and contributes labels only; none of its coordinates were
scaled or converted.

Machine-readable companion: `docs/research/home_ui_atlas.json`.

## Executable BlueStacks atlas (2026-07-18)

The project now has an executable BlueStacks-only stitched atlas at
`tasks/assets/home_atlas/bluestacks/800x1280/atlas.json`; its pixel mosaic is `atlas.png` in the
same directory. This supersedes the provisional BlueStacks screen ROIs below whenever the native
Home camera is classified as `fully_zoomed_out`. The older entries remain research history and are
not transformed into the new atlas.

- Profile: `pns-bluestacks-5-p64-800x1280-v1`, package `com.global.ztmslg`, native portrait
  `800×1280`. Bliss calibration and assets remain separate.
- Zoom mechanism: held left Ctrl plus wheel-down in the exact BlueStacks window. A measured live
  step changed scale by `1.2660` with `0.1948 px` residual; the following clamp measured scale
  `1.0000` with `0.0053 px` residual. The cursor is bound to verified empty road so BlueStacks'
  simulated pinch contacts do not land on a building.
- Atlas coordinates: origin `(0,0)`, size `1447×2769`, units canonical BlueStacks atlas pixels.
  Thirty unique native viewports were accepted; two scan frames were rejected as duplicates.
- Registration: translation for stable camera pans and similarity only where live measurements
  required it. Maximum residual is `0.213 px`; maximum retained loop-closure disagreement is
  `1.161 px`, below the `8 px` conflict threshold.
- Coverage: `coverage_polygons` are the union of verified safely actionable scene regions;
  `registration_coverage_polygons` separately retain the stricter HUD-masked feature support.
  Four measured edge clamps and five overlapping boustrophedon rows establish full reachable base
  coverage with zero interior actionable or registration gaps. Black pixels outside the verified
  contour are outside the reachable camera envelope or fixed-HUD exclusions and were never filled
  by interpolation.
- Boundary scan: 30 bounded navigation-only click-drags, 23 accepted moving frames, and explicit
  top/right/left/bottom no-progress clamps. Camera origins span approximately `x=0.86..646.79`,
  `y=0.08..1488.01`.
- Live localizer: the newly mapped bottom-left clamp recognized `fully_zoomed_out`, `left+bottom`,
  confidence `0.55961`, residual `0.10094 px`, with support from viewports 030/005/024. Final
  canonical Home localized at confidence `0.99007`, residual `0.11912 px`, and `3.99 px` center
  error from `viewport-001`.
- Semantic registry: 65 positively labeled facilities/instances. This includes 31 unique named
  facilities or landmarks and 34 production instances: seven Farms, six Lumber Mills, four
  Bootcamps, six Steel Plants, three Infirmaries, and eight Gas Fields. Sixty-three entries have a
  HUD-free supporting viewport. Forum is mapped and label-proven at the left clamp but explicitly
  non-actionable because its center remains behind the fixed left HUD. A registry-completion audit
  added Parade Grounds from accepted viewports 018/019; its label and staging-pad geometry are
  proven, but the physical facility remains behind the fixed right event HUD at the maximum verified
  camera origin, so it is also mapped but non-actionable on this BlueStacks profile.
- Supply Depot: semantic ID `home.building.supply_depot`, polygon
  `[(1166.7,908.6),(1326.7,908.6),(1326.7,1043.6),(1166.7,1043.6)]`, center
  `(1246.7,976.1)`. The executable direct route localized Home, bound the current label/helicopter
  pad, opened the building radial, selected only `Claim Supply`, and recognized the exact Supply
  Depot screen without using Daily Quest Go.
- Full-coverage live validation started at the bottom-left clamp, used two measured navigator pans
  to reach the Supply Depot region, stopped safely on partial HUD visibility, then used an exact
  current-frame binding at the right clamp. The radial continuation derived `Claim Supply` from
  current OCR at `(641,682)-(729,746)` and recognized the exact Supply Depot screen. It inspected
  the four Free controls but performed zero additional collections.
- Consequential validation: exactly one authorized food `Free` control was tapped. Daily free
  attempts changed exactly `9→8`, and the visible food amount changed `14,382→14,664`. The action
  key `supply-depot-free:bluestacks:no-reset:attempts-9:food` is terminally confirmed and must not be
  repeated. No Daily Quest progress was inspected.
- Hold-to-exhaust follow-up: with the exact Supply Depot screen freshly recognized at eight remaining
  attempts, the primary `collect-free` workflow bound the Food Free ROI and dispatched one bounded
  `11.1 s` zero-distance long press through the native runtime. A fresh successor proved `Daily free
  attempts: 0` and all four controls had changed to diamond-cost controls. The action key
  `supply-depot-free-hold:bluestacks:no-reset:attempts-8:food` is confirmed for eight free Food
  collections and must not be repeated. The earlier stylized zero was initially OCR'd as `O`; a
  read-only fresh-frame reconciliation resolved it without another hold. `collect-one` remains a
  one-tap diagnostic fallback; `collect-free` is the default hold-to-exhaust route.
  The native Home diamond display remained `25.5K` before and after, proving the held gesture did
  not continue into the newly visible diamond-cost controls.
- Production status: not registered and scheduler-ineligible. No Bliss, Unraid, production, paid,
  premium, Mall, speedup, ticket, resource-item, AP, stamina, Daily Claim, Bank, upgrade, research,
  training, healing, or unrelated workflow input occurred.

### Direct minimal-pan planner validation (2026-07-18)

`tasks/home_atlas_planner.py` now owns platform-neutral target viewport planning, camera-envelope
clamping, inverse drag conversion contracts, measured progress, repeated/no-progress guards, and a
navigation-only result contract. BlueStacks independently supplies safe screen box
`(145,180)-(650,1010)`, stable placement anchor `(400,600)`, fixed HUD masks, native drag bounds,
and the measured `2.1 atlas px / screen-drag px` conversion. Maximum drag components are 150 px
horizontal and 180 px vertical. None of this gesture geometry is valid for Bliss.

Live project-owned validation used three materially different canonical Home origins and never
tapped a facility. Headquarters bound at zero input near origin `(169.41,117.78)`. Supply Depot
started near `(169.45,117.83)` and used two calculated pans: requested `(477.37,258.32)`, measured
`(301.53,162.88)`, then requested `(175.85,95.44)`, measured `(173.26,92.87)`; its final semantic
ROI was `(538,552)-(634,654)` at right-edge origin `(644.20,373.53)`. Bank started there and used
two bounded pans to `(57.34,594.28)`, where OCR bound `(331,552)-(441,659)`. Gear Factory then used
one pan, requested `(288.67,-44.32)` and measured `(287.69,-44.11)`, reaching
`(345.02,550.21)` with a `(343,527)-(458,672)` current-frame binding. Final recovery localized at
origin `(168.99,106.60)`, confidence `0.99769`, residual `0.02772 px`, and `6.71 px` from
viewport-001 origin `(171,113)`.

The planner rejected Supply Depot before input until its existing verified right-edge safe-subregion
policy was made explicit. Canonical recovery also stopped on two no-progress short drags; neither
was repeated at the same target, and a corrected empty-scene anchor produced the final measured
85.46 px move. These are retained fail-closed examples. All building results recorded
`building_opened=false`; no downstream building workflow or consequential control occurred.

Key retained local evidence:

- direct-pan Headquarters zero-input: `.local-captures/home-atlas-direct-pan/dry-run/home-atlas-navigate-building-20260719T001626193128Z/`
- direct-pan Supply Depot: `.local-captures/home-atlas-direct-pan/supply-depot/home-atlas-navigate-building-20260719T001927989642Z/`
- direct-pan Bank: `.local-captures/home-atlas-direct-pan/bank/home-atlas-navigate-building-20260719T002022678534Z/`
- direct-pan Gear Factory: `.local-captures/home-atlas-direct-pan/gear-factory/home-atlas-navigate-building-20260719T002118522476Z/`
- direct-pan final canonical correction: `.local-captures/home-atlas-direct-pan/final-canonical-correction-gap/home-atlas-pan-20260719T002430166504Z/`


### Recovery-aware viewport planning (2026-07-18, offline)

`SafeInteractionRegion.planning_policy` is optional. When absent, `plan_building_viewport`
preserves the exact legacy single-candidate path. When a `ViewportPlanningPolicy` is present,
candidates keep the current localization affine linear component, apply directional radial
footprint margins from the predicted actionable interaction region (including authorized
safe-subregion policies), and require `predicted_recovery_search_zone_available` inside an
adapter-injected recovery-search envelope.

Recovery predictions never emit an executable tap coordinate. Atlas polygons cannot prove live
exit targets because transient units, controls, and effects are absent; current-frame adapter
binding remains required. Label-edge clearance is a soft heuristic unless an authoritative
building binding policy supplies explicit label geometry. Map-edge proximity is a soft penalty;
hard rejection occurs only when clamping breaks coverage, radial footprint, recovery search space,
or registration support. Soft scores are normalized to `[0,1]` with fixed weights and deterministic
tie-break (score desc, pan distance asc, x asc, y asc). Registration support for passing
candidates is a normalized safe-region probe overlap, not a constant 1.0.

BlueStacks injects its policy through `bluestacks_direct_pan_contract()` only. Initial magnitudes
and recovery-search insets are justified from the accepted safe region `(145,180)-(650,1010)` and
radial-exterior-close scan band / `25 px` clearance; they are documented heuristics, not freshly
remeasured in this offline task. No viewport-001 recovery bias is used. Live validation is outside
this authorization.

### Troop Training atlas-entry migration validation (2026-07-18)

The local BlueStacks Troop Training route now selects the first enabled troop type's semantic
building ID and enters through the platform-neutral direct-pan planner. The old source gate that
required Fighter, Shooter, Rider, and Vehicle facilities to be simultaneously visible is removed.
Every pan is followed by fresh atlas localization; projection alone never authorizes a facility
tap. BlueStacks continues to own safe region `(145,180)-(650,1010)`, placement anchor `(400,600)`,
and the measured `2.1 atlas px / drag px` conversion. No BlueStacks geometry is shared with Bliss.

Entry-only live validation covered Fighter Camp and Vehicle Depot. Fighter started at origin
`(168.99,106.60)`, bound `(170,803)-(335,910)` at confidence `0.98`, required zero pans, and
positively recognized its radial Train ROI `(242,904)-(466,1035)`. Vehicle started at right-edge
origin `(646.77,113.99)` and used one calculated pan: requested `(-445.77,+354.01)`, measured
`(-308.72,+244.87)`, residual `(-137.04,+109.14)`. At `(338.05,358.86)` the current frame bound
Vehicle Depot `(170,652)-(355,767)` at confidence `0.98` and its radial Train ROI
`(237,737)-(436,862)`. Live corrective panning was not needed; deterministic corrective-plan,
wrong-direction, no-progress, localization-failure, repeated-viewport, and maximum-pan coverage
passed.

The entry-only path never taps Train. A fresh facility-specific Details/Upgrade/Train radial is
closed through a BlueStacks-only exterior-scene binding: a 20×20 target inside the safe region,
above radial controls, and with its center at least 25 px outside every currently projected semantic
building polygon. Final canonical Home localized at `(168.98,106.61)` for Fighter (confidence
`0.99133`, residual `0.10399 px`) and `(338.05,358.86)` for Vehicle (confidence `0.99057`, residual
`0.11316 px`). No quantity, Warehouse confirmation, resource box, premium, Train, or other
consequential input occurred. Production registration remains `NOT_REGISTERED`; scheduler
eligibility remains false.

Key retained local evidence:

- dry-run zero-input Fighter plan: `.local-captures/troop-training-atlas-entry/dry-run/troop-training-20260719T021721732263Z/`
- Fighter current-frame entry/radial: `.local-captures/troop-training-atlas-entry/fighter-zero-pan/troop-training-20260719T021808597377Z/`
- Fighter safe radial close/final Home: `.local-captures/troop-training-atlas-entry/fighter-exterior-close/troop-training-20260719T023104977845Z/`
- Vehicle calculated pan: `.local-captures/troop-training-atlas-entry/vehicle-calculated-pan-corrected/troop-training-20260719T024102450439Z/`
- Vehicle current-frame binding/radial: `.local-captures/troop-training-atlas-entry/vehicle-current-frame-continuation/troop-training-20260719T024310202414Z/`
- Vehicle safe radial close/final Home: `.local-captures/troop-training-atlas-entry/vehicle-exterior-close/troop-training-20260719T024522835241Z/`

- full corner/grid scan: `.local-captures/home-base-atlas-discovery/full-grid/home-atlas-four-corner-grid-20260718T220754613718Z/`
- completed atlas build: `.local-captures/home-base-atlas-discovery/atlas-build-v4/atlas.json`
- bottom-left localization: `.local-captures/home-base-atlas-discovery/full-grid-validation/home-atlas-localize-20260718T222440309767Z/`
- final Supply Depot radial continuation: `.local-captures/home-base-atlas-discovery/full-grid-validation/supply-depot-radial-20260718T223609701325Z/`
- final canonical recovery: `.local-captures/home-base-atlas-discovery/full-grid-validation/home-atlas-return-canonical-20260718T224709024496Z/`
- canonical zoom proof: `.local-captures/home-base-atlas-discovery/final-home-recovery/home-canonical-zoom-20260718T205934133815Z/`
- collection: `.local-captures/supply-depot-direct-building/supply-depot-collect-one-20260718T205259350054Z/`
- hold collection: `.local-captures/supply-depot-direct-building/supply-depot-collect-free-hold-20260718T233948312187Z/`
- hold reconciliation: `.local-captures/supply-depot-direct-building/supply-depot-reconcile-free-hold-20260718T234250460579Z/`
- hold final canonical Home: `.local-captures/supply-depot-hold-validation/home-atlas-return-canonical-20260718T234604460238Z/`
- final integrated direct route: `.local-captures/supply-depot-direct-building/integrated-route-final/home-atlas-navigate-building-20260718T211815671006Z/`
- final Home localization: `.local-captures/home-base-atlas-discovery/final-home-recovery/home-atlas-localize-20260718T211944500691Z/`

## Source boundary

| Source | Size | Native or scaled | Permitted use |
|---|---:|---|---|
| BlueStacks town home, SHA-256 `34c4177e…650c9160b` | 800×1280 | native, zoomed in | Source of the approximate atlas ROIs; BlueStacks-local only |
| BlueStacks town home, SHA-256 `cbe4c04a…5c2637` | 800×1280 | native, fully zoomed out | Wider BlueStacks camera-state reference; entire base still not visible |
| Annotated chat image, SHA-256 `235fb308…08751fc1` | 781×1248 | scaled | semantic labels only |
| Bliss production | 800×1280 at 160 dpi | not captured in this task | final coordinate, template, OCR, and route acceptance |

Every ROI below is approximate BlueStacks `xyxy` from the earlier zoomed-in source. No coordinate
was mapped or transformed into the fully-zoomed-out source. A production detector must reacquire
the same semantic element on a current raw Bliss frame and positively identify its zoom class.

## Atlas

| Semantic ID | BlueStacks ROI | Detector | Known states / evidence | Confidence |
|---|---:|---|---|---|
| `home.resource.stamina_orange` | `(0,174)-(108,205)` | orange color + OCR + profile geometry | current/max; low/full/refill variants missing | Medium |
| `home.resource.ap_blue` | `(0,204)-(108,236)` | blue color + OCR + profile geometry | current/max; low/full/refill variants missing | Medium |
| `home.player.profile` | `(0,40)-(310,174)` | template + OCR + edge geometry | portrait, level, VIP, might; profile-open successor missing | High (BlueStacks) |
| `home.queue.build` | `(0,285)-(108,385)` | queue icon + OCR + status color | `0/2` observed; free, countdown, and completion examples required | Medium |
| `home.queue.research` | `(0,390)-(108,486)` | queue icon + OCR + status color | `0/1` observed; free, countdown, and completion examples required | Medium |
| `home.entry.pit_mining` | `(0,485)-(112,574)` | OCR `Pit`/`Idle` + icon | Idle observed; mining, countdown, full/claimable required | High (Idle only) |
| `home.building.fighter_camp` | `(35,830)-(270,1045)` | building template + label + camera signature | idle/training/claimable/upgrade variants required | Medium-high |
| `home.building.shooter_camp` | `(300,745)-(555,965)` | building template + label + camera signature | named building visible | High (BlueStacks) |
| `home.building.rider_camp` | `(540,830)-(745,1048)` | building template + label + camera signature | named building visible | High (BlueStacks) |
| `home.building.vehicle_depot` | `(315,980)-(595,1162)` | building template + label + camera signature | named building visible; Main banner overlaps its lower region | High (BlueStacks) |
| `home.indicator.troop_claimable` | camp-local candidates only | local template/color + building association | not positively distinguished from other green/status markers | Low |
| `home.state.troop_training_timer` | camp-local candidates only | bounded OCR + building association | no camp countdown legible in the supplied frame | Low |
| `home.indicator.building_upgrade_arrow` | primary candidate `(465,830)-(525,935)` | green shape/color + building association | visible candidate; claim/level-badge negatives required | Medium-low |
| `home.nav.world` | `(0,1165)-(114,1280)` | label/template + fixed slot | Town→World destination; positive World successor required | High (BlueStacks) |
| `home.nav.hero` | `(114,1165)-(228,1280)` | label/template + fixed slot | normal and notification variants | High (BlueStacks) |
| `home.nav.quest` | `(228,1165)-(343,1280)` | label/template + fixed slot | Main/Daily successor must be disambiguated | High (BlueStacks) |
| `home.nav.bag` | `(343,1165)-(457,1280)` | label/template + fixed slot | Bag categories/item confirmation evidence missing | High (BlueStacks) |
| `home.nav.alliance` | `(571,1165)-(686,1280)` | label/template + fixed slot | Mail occupies the fifth slot; Alliance is sixth | High (BlueStacks) |
| `home.nav.more` | `(686,1165)-(800,1280)` | label/template + fixed slot | known Help/webview interception remains a negative | High (BlueStacks) |
| `home.state.canonical_town_home` | full frame | multi-anchor composite | town HUD + bottom nav + no blocking overlay | Medium-high (BlueStacks) |
| `home.state.canonical_town_camera` | zoomed-in reference ROI `(80,220)-(760,1160)` | zoom class + multi-building relative geometry | user-confirmed zoomed-in and fully-zoomed-out examples; intermediate/pan negatives missing | Medium-high (BlueStacks only) |

## Detector and action rules

- Resource bars and timers require bounded OCR tied to a local icon/anchor. OCR alone is weak.
- Queue availability, busy, and completion are different states; disappearance or transport success
  does not prove completion.
- Building detections require the canonical camera signature and a locally associated label or
  template. A nearest green arrow is never sufficient.
- The detector must classify the zoom state before using any building ROI. A native 800×1280 frame
  does not make coordinates portable across camera zoom levels.
- Bottom navigation may use fixed slot geometry only after the full-frame 800×1280 profile and the
  Town source are positive.
- A route succeeds only on a named successor. Unknown overlays, account states, cost dialogs, or a
  camera mismatch stop and return control to the operator.

## Current conclusion

The two BlueStacks frames are suitable for zoom-state and local detector development. The
fully-zoomed-out view is the better broad camera reference, while the earlier zoomed-in view remains
the only source for the listed ROIs. The remaining high-value evidence is a matching raw Bliss
fully-zoomed-out home frame, a zoom transition/recovery recording, then queue, camp, and Pit state
variants.
