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
| Personal Might first row | `(170,220)-(560,325)` | corrected Rankings successor | `GNB-DAILY-LEADERBOARD-PRAISE` |
| first-row Check | `(590,245)-(775,315)` | corrected Rankings successor | `GNB-DAILY-LEADERBOARD-PRAISE` |
| Personal Might header | `(150,0)-(650,70)` | Check successor | `GNB-DAILY-LEADERBOARD-PRAISE` |
| rank-one Praise icon | `(690,155)-(755,220)` | Check successor | `GNB-DAILY-LEADERBOARD-PRAISE` |
| Personal Might Back | `(45,5)-(130,60)` | Check successor | `GNB-DAILY-LEADERBOARD-PRAISE` |
| Rankings Back | `(45,5)-(130,60)` | Rankings successor | `GNB-DAILY-LEADERBOARD-PRAISE` |
| VIP Points Close | `(260,750)-(540,870)` | corrected popup source | none |

Rankings entry replaces historical broad `(0,1120)-(800,1185)` target. Its current center is
`(646,1152)`, not `(400,1152)`.

## Provisional-anchor gate

Current Praise route anchors now have raw Bliss evidence. `NavigationRunner` still returns
`ANCHOR_EVIDENCE_REQUIRED` before policy evaluation or transport whenever any future route declares
a provisional source, target, or postcondition anchor.

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

- Praise semantic postcondition after exactly one input;
- Rankings/Personal Might Back transition successors;
- completed-unclaimed Daily Praise row and exact Claim pre/postcondition.

Missing dependencies block only dependent routes. They do not weaken coordinates or permit
fallback taps.

## Corrected live Rankings result

One supervised navigation-only input at `(646,1152)` targeted exact
`(602,1138)-(690,1167)`. Immediate binding matched. First post frame positively showed
Leaderboard with Personal Might Rank first row; journal status is confirmed with one transport
call. No Help WebView appeared.

The successor proves the list already exposes both Personal Might Rank and its Check control.
Therefore no separate row tap is valid or needed. Route now recognizes row identity and sends only
the Check navigation input from Rankings.

## Personal Might leaderboard result

One exact Check tap `(682,280)` from ROI `(590,245)-(775,315)` produced the Personal Might Rank
leaderboard with one transport call. The raw screen binds header, Back, and the rank-one gold
thumbs-up. Praise is icon-only: recognition requires header identity, local template similarity,
and constrained gold HSV occupancy. No broad right-column or OCR-only target is allowed.
