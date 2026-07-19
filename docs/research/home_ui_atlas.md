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
- Semantic registry: 64 positively labeled facilities/instances. This includes 30 unique named
  facilities or landmarks and 34 production instances: seven Farms, six Lumber Mills, four
  Bootcamps, six Steel Plants, three Infirmaries, and eight Gas Fields. Sixty-three entries have a
  HUD-free supporting viewport. Forum is mapped and label-proven at the left clamp but explicitly
  non-actionable because its center remains behind the fixed left HUD.
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

Key retained local evidence:

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
