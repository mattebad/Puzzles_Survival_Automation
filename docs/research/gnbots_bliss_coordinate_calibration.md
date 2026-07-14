# GnBots 400×652 to Bliss 800×1280 calibration

Status: development-only, provisional. No transformed point or ROI authorizes production input.

## Models tested

| Model | X scale | Y scale | Offset | Five-point RMSE |
|---|---:|---:|---:|---:|
| direct 2× | 2.0 | 2.0 | `(0,0)` | 43.294 px |
| source top inset 12 | 2.0 | 2.0 | viewport-derived | 32.385 px |
| source bottom inset 12 | 2.0 | 2.0 | viewport-derived | 43.294 px |
| independent axes | 2.0 | 1280/652 = 1.963190 | `(0,0)` | 37.959 px |
| fitted axis-aligned affine | 1.976743 | 2.017040 | `(7.474674,-35.736690)` | 31.422 px |

Affine fitting lowers aggregate error, but its extra complexity does not make all families safe.
Direct 2× remains simplest global starting candidate and is only tested global model that places
the reference Rankings point within raw target bounds. It still touches target boundary and is not
an interior tap.

## Raw correspondences

All Bliss sources are raw 800×1280 PNGs or exact live transaction coordinates. Preview/rendered
dimensions were not used.

| Anchor | Manifest provenance | Source | Observed Bliss | Selected transform | Residual | Total | Safe inside |
|---|---|---:|---:|---:|---:|---:|---|
| Quest open | `GNB-DAILY-QUEST-CLAIMS` | `(158,621)` | `(330,1205)` | bottom-nav corrected `(312.5,1198.5)` | `(17.5,6.5)` | 18.668 | yes, ROI `(250,1130)-(410,1280)` |
| Daily tab | `GNB-DAILY-QUEST-CLAIMS` | `(200,57)` | `(400,105)` | direct `(400,114)` | `(0,-9)` | 9.000 | yes, ROI `(300,70)-(500,140)` |
| More open | `GNB-DAILY-LEADERBOARD-PRAISE` | `(376,623)` | `(731,1196)` | bottom-nav corrected `(748.5,1202.5)` | `(-17.5,-6.5)` | 18.668 | yes, ROI `(680,1130)-(800,1280)` |
| Rankings entry | `GNB-DAILY-LEADERBOARD-PRAISE` | `(312,569)` | `(646,1152)` | direct `(624,1138)` | `(22,14)` | 26.077 | inside only; fails 6 px margin |
| standard Back | `GNB-DAILY-CHAPTER` | `(45,48)` | `(87,32)` | direct `(90,96)` | `(-3,-64)` | 64.070 | no |

Rankings observed center comes from word-level OCR bounds `(602,1138)-(690,1167)` on the raw More
frame. Existing broad binding `(0,1120)-(800,1185)` centered at `(400,1152)` is not a calibrated
Rankings target and explains Help/guide interception risk. This finding is calibration evidence,
not authorization for another input.

## Named screen-family correction

Only bottom navigation has two corresponding anchors:

- Quest open direct residual `(14,-37)`;
- More open direct residual `(-21,-50)`.

Mean correction `(-3.5,-43.5)` leaves bounded residuals of ±17.5 px X and ±6.5 px Y, safely inside
both broad bottom controls. It is named `bottom-navigation` and remains provisional.

No correction is created for:

- standard Back: only one correspondence;
- Rankings submenu: only one reliable local target correspondence;
- Personal Might: no Bliss screen;
- Claim: no completed-unclaimed Bliss row;
- march: no Bliss menu/result corpus.

## ROI normalization examples

Vendor xywh must normalize before any transform:

- Praise: `[354,66,41,283]` → `[354,66,395,349]` → direct candidate
  `[708,132,790,698]`.
- Daily Claim: `[282,202,103,308]` → `[282,202,385,510]` → direct candidate
  `[564,404,770,1020]`.

These broad transformed ROIs are search starting regions only. Production requires a Bliss-native
source anchor, local target, unobscured check, raw annotated artifact, and immediate-frame binding.

## Decision

- Keep all calibration outputs non-authorizing.
- Use direct 2× as simplest global candidate.
- Permit only named `bottom-navigation` correction, supported by Quest and More correspondences.
- Use validated Bliss-native Back coordinates instead of transformed Back.
- Tighten Rankings against raw Bliss target evidence in Phase C before any navigation retry.
- Record missing screens as evidence dependencies and continue independent offline work.
