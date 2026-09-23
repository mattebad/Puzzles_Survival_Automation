# Capture Findings

## Confirmed from the game UI

- The owned Hero roster contains 36 entries and the Not Obtained roster contains 13 entries with all filters set to All.
- Scrolling the entire owned list revealed IDs 509, 527, 557, 558, and 566 in lower rows. All five were owned and their three non-Tactical skill panels were captured.
- The other eight requested IDs were captured from Not Obtained. All 14 requested heroes therefore have three non-Tactical skill records each.
- Skill titles, Economy/Military labels, headline text, star progression values, and activation lines in the data files are transcribed from screenshots. The user requested that Tactical Skill details generally be skipped; those rows are not included in the skill CSV.
- Beepboop No.7 has three visible entries: Build Speed, Free Research Speedup, and Troop Size, each under Economy. The panels do not show an explicit `(Passive)` label, so the manifest stores `passive: null` and the CSV leaves it blank.

## Strong inference

- None added. The audit preserves displayed text and values without interpreting beyond the explicit labels.

## Needs user confirmation

- No gameplay meaning was assigned to unlabeled passive states. For Beepboop No.7, the source panels do not explicitly call these entries passive; the blank/null field is deliberate.
- The Troop Size panel headline reads `Troop Size +1250` while the progression row displays values from 4,000 through 30,000. Both are recorded exactly as shown; this audit does not reconcile the two displays.

## Correction to the earlier roster report

The previous report that five targets were absent was incorrect because the owned roster had not been scrolled through completely. The full scroll found all five targets. `coverage.csv`, `manifest.json`, README, and roster evidence now reflect the complete scan.