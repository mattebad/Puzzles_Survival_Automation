# New Hero Troop Skill Audit

Read-only capture of the troop-skill panels available in the open Puzzles & Survival Windows client. The data is intended to support later spreadsheet mapping; it does not assign Column F templates or interpret ambiguous gameplay semantics.

## Source and scope

- Source: the in-game client, opened at **Heroes → Hero / Not Obtained → Troop Skill**.
- Targets: the 14 IDs listed in the attached collection request.
- The user directed us to skip Tactical Skill details generally. Overview screenshots retain the visible Tactical Skill row; `troop_skill_count` counts only the non-Tactical stat/economy rows. `displayed_troop_skill_row_count` records all visible rows when present.
- The filter panel showed **All** for Star Level, Unit Type, and Battle Style. Both owned and Not Obtained rosters were reviewed, then carefully re-scanned once. The current client showed 16 owned entries and 13 Not Obtained entries.

## Results

Nine targets were found and captured: one under Hero (owned) and eight under Not Obtained (unowned). Each found hero has three non-Tactical skills; all nine detail tables and overview screenshots are included. The currently visible skill tables use 6★ → 7★ rows. No captured target displayed four non-Tactical skills.

The following five targets were absent from both rosters after the re-scan: 509 Patty Potts, 527 Mr. Crosshair, 557 BeepBoop No.7 / Don Don, 558 Bumblebee / Morgan Strange, and 566 Luna. Their `found` and `complete` values are false in `coverage.csv`; no skill values were inferred for them.

## Files

- `manifest.json`: structured hero and skill records, target coverage, screenshot paths, roster checks, and capture notes.
- `troop_skills.csv`: one row per captured non-Tactical troop skill. Unavailable/dash cells are written as `null`, not zero.
- `coverage.csv`: one row per requested target.
- `screenshots/<id>_<name>/overview.png`: skill row order/count evidence.
- `screenshots/<id>_<name>/skill_XX.png`: individual progression panels with category, headline, star rows, and activation line.
- `screenshots/roster_owned_overview.png` and `screenshots/roster_not_obtained_overview.png`: current roster evidence for found/missing status.

## Capture and verification

Each visible non-Tactical skill was opened in the game UI and saved as a full-window screenshot. Tables were transcribed from the in-game panels, including explicit nulls for dashes and decimals where shown. GPT-6 Luna visually checked the captured progression rows and activation text; it confirmed the exact Lv.3 and Lv.13 strings after enlarged comparison. Screenshots were converted from the client capture's JPEG bytes into PNG files without resizing or cropping. All 38 PNG files were opened and dimension-checked after conversion.

The five absent targets may be unavailable in this client's current roster. Their gameplay data remains unknown here. No Google Sheets were modified, no resources were spent, and no upgrades, promotions, purchases, recruitments, equipment changes, or combat actions were performed. Only the new `spreadsheet-assets/hero-troop-skill-audit/` directory contains task output.
