# Capture Findings

## Confirmed from the game UI and user clarification

- The owned Hero roster contains 36 entries and the Not Obtained roster contains 13 entries with all filters set to All.
- Scrolling the entire owned list revealed IDs 509, 527, 557, 558, and 566 in lower rows. All five were owned and their three non-Tactical skill panels were captured.
- The other eight requested IDs were captured from Not Obtained. All 14 requested heroes therefore have three non-Tactical skill records each.
- Skill titles, Economy/Military labels, headline text, star progression values, and activation lines in the data files are transcribed from screenshots. Tactical Skill details were skipped per user direction.
- Beepboop No.7 has three visible Economy entries: Build Speed, Free Research Speedup, and Troop Size. The panels do not show an explicit `(Passive)` label, so the manifest stores `passive: null` and the CSV leaves it blank.
- Per user clarification, Beepboop No.7 Troop Size headline is `+12500` (12.5K), matching the value shown for Beepboop at +5.

## Strong inference

- None added. The audit preserves displayed text and values without interpreting beyond the explicit labels.

## Needs user confirmation

- None for the captured non-Tactical fields.

## Correction to the earlier roster report

The previous report that five targets were absent was incorrect because the owned roster had not been scrolled through completely. The full scroll found all five targets. `coverage.csv`, `manifest.json`, README, and roster evidence reflect the complete scan.