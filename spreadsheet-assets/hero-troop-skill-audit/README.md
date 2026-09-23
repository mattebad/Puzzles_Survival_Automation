# New Hero Troop Skill Audit

Read-only capture of troop-skill panels in the Puzzles & Survival Windows client. This records displayed game data for later spreadsheet mapping; it does not assign Column F templates or interpret ambiguous gameplay semantics.

## Source and scope

- Source: the in-game client, opened at **Heroes → Hero / Not Obtained → Troop Skill**.
- Targets: all 14 IDs listed in the collection request.
- The user directed us to skip Tactical Skill details generally. Overview screenshots retain the visible Tactical Skill row; `troop_skill_count` counts only the three non-Tactical stat/economy rows.
- The roster filters showed **All** for Star Level, Unit Type, and Battle Style. The complete owned roster was scrolled from top to bottom: 36 owned entries and 13 Not Obtained entries.

## Results

All 14 targets were found and captured: six in the owned Hero list and eight in Not Obtained. Each target has three non-Tactical skill rows, for 42 skill records. The five heroes initially reported missing (509 Patty Potts, 527 Mr. Crosshair, 557 BeepBoop No.7, 558 Morgan Strange, and 566 Luna) were in lower rows of the owned roster; the earlier roster scan had not gone far enough. Their screenshots and roster evidence are included.

Beepboop No.7 has three Economy entries: Build Speed, Free Research Speedup, and Troop Size. No explicit `(Passive)` label appears on these panels, so `passive` is null in the manifest and blank in the CSV. Displayed units and numbers are transcribed as shown; no game meaning is inferred from the visual labels. Per user clarification, the Troop Size headline is +12500 (12.5K), matching the value shown for Beepboop at +5.

## Files

- `manifest.json`: structured hero and skill records, target coverage, screenshot paths and hashes, roster checks, and capture notes.
- `troop_skills.csv`: one row per captured non-Tactical troop skill. Dashes in progression tables are the literal `null`; an empty `passive` cell means the panel did not explicitly label it passive.
- `coverage.csv`: one row per requested target.
- `screenshots/<id>_<name>/overview.png`: skill row order/count evidence.
- `screenshots/<id>_<name>/skill_XX.png`: individual progression panels with category, headline, star rows, and activation line.
- `screenshots/owned_roster_*.png`: supplemental lower-row owned-roster evidence, including Patty Potts, Mr. Crosshair, Morgan Strange, and Luna. Beepboop No.7 is captured in the 557 skill screenshots; the complete roster scroll showed all five as owned.
- `screenshots/roster_owned_overview.png` and `screenshots/roster_not_obtained_overview.png`: earlier roster overview captures.

## Capture and verification

Each visible non-Tactical skill was opened in the game UI and saved as a full-window screenshot. Tables were transcribed from the in-game panels, including explicit nulls for dashes, decimals, and displayed units. GPT-6 Luna visually checked the titles, categories, headlines, progression values, and activation text across all 42 skill rows for the 14 heroes. Beepboop table abbreviations (`M` for minutes and `K` for thousands of troops) were clear in the source screenshots and are represented as raw values with units in the CSV. Screenshots were converted from the client capture JPEG bytes into PNG files without resizing or cropping. All 61 PNG files are listed in the manifest with dimensions, byte sizes, and SHA-256 hashes and were opened for image validation.

No Google Sheets were modified, no resources were spent, and no upgrades, promotions, purchases, recruitments, equipment changes, or combat actions were performed. Only `spreadsheet-assets/hero-troop-skill-audit/` contains task output.