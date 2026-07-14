# Bliss profile provenance and Phase C gates

Profile: `pns-blissos-poc-virgl-800x1280-v1`

Vendor manifest IDs explain semantic lineage only. Production geometry always comes from raw
800×1280 Bliss evidence.

## Production-validated anchors used by current slice

| Anchor | Bliss ROI | Bliss evidence | Manifest lineage |
|---|---:|---|---|
| Home Quest | `(250,1130)-(410,1280)` | `home-base-settled.png` | `GNB-DAILY-QUEST-CLAIMS` |
| Daily tab | `(300,70)-(500,140)` | `quest-main-settled.png` | `GNB-DAILY-QUEST-CLAIMS` |
| standard Back | `(45,5)-(130,60)` | `reset-reconcile-current.png` | `GNB-DAILY-CHAPTER` |
| Home More | `(680,1130)-(800,1280)` | `home-base-settled.png` | `GNB-DAILY-LEADERBOARD-PRAISE` |
| Rankings entry | `(602,1138)-(690,1167)` | raw More frame word bounds | `GNB-DAILY-LEADERBOARD-PRAISE` |
| VIP Points Close | `(260,750)-(540,870)` | corrected popup source | none |

Rankings entry replaces historical broad `(0,1120)-(800,1185)` target. Its current center is
`(646,1152)`, not `(400,1152)`.

## Explicitly provisional anchors

These retain provisional search ROIs only and now set `production_validated=False`:

- Personal Might Rank row;
- Personal Might Check;
- Personal Might leaderboard identity;
- Praise action;
- Personal Might Back;
- Rankings Back.

Each carries stable `GNB-DAILY-LEADERBOARD-PRAISE` lineage and an explicit raw Bliss evidence
dependency. `NavigationRunner` returns `ANCHOR_EVIDENCE_REQUIRED` before policy evaluation or
transport whenever a route step declares any provisional source, target, or postcondition anchor.

## NavigationRunner audit

Failing tests first proved three declared-contract gaps:

1. target anchor did not have to match immediate observation identity and ROI;
2. declared postcondition anchor was ignored;
3. `old_anchor_must_disappear` was ignored.

Runner now enforces all three, requires recognized foreground successors, and blocks provisional
anchors. Existing exactly-one navigation dispatch and one safe no-effect retry semantics remain
unchanged.

## Popup scope

Navigation popup registry recognizes only:

- `vip-points-reset`;
- `help-webview`.

Unknown benign popups return `UNKNOWN`; cost/resource/premium dialogs return `BLOCKING`; hard stops
return `FATAL`. At most one popup is handled from one frame hash. Action transactions handle only
their exact declared confirmation dialog. Live Personal Might adapter uses this registry before VIP
or Help WebView dismissal.

## Remaining evidence dependencies

- settled Rankings successor produced by the corrected local target;
- Personal Might row and exact Check;
- Personal Might leaderboard and Praise pre/postcondition;
- Rankings/Personal Might Back states;
- completed-unclaimed Daily Praise row and exact Claim pre/postcondition.

Missing dependencies block only dependent routes. They do not weaken coordinates or permit
fallback taps.
