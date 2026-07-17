# Town-home UI atlas

This atlas records semantic discovery facts, not production input authority. Both clean BlueStacks
sources are original 800×1280 PNGs. The earlier source was later identified by the user as zoomed
in; the second is the fully zoomed-out view, although the entire base is still not visible. A
coordinate is valid only in the exact BlueStacks source and camera state where it was observed.
The annotated chat image is 781×1248 and contributes labels only; none of its coordinates were
scaled or converted.

Machine-readable companion: `docs/research/home_ui_atlas.json`.

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
