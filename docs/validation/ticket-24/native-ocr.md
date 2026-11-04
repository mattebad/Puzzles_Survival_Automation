# Ticket #24: native OCR portability

Status: implemented on the candidate branch and offline-proven on local Windows.
Native Linux acceptance for this change remains `evidence_required` until its
candidate diagnostics finish. This is not live acceptance.

## Observed cause

[The unmodified Linux observation](native-ocr-linux-before.json) comes from
[run 41794694971](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41794694971),
commit `4e9bdefb8f67267fca79b35f611ec63e8ca4e060`, Python 3.11.17,
Tesseract 5.5.0. Its SHA-256 is
`9b85cefea372503d017bd324dc160d8373453fd9a87876e4a9aff9933c04d918`.
The committed PNGs were read without modifying them. No device-executable attempt
was observed under the probe's `subprocess.Popen` guard.

| Module | Class | Cause and decision |
| --- | --- | --- |
| `test_personal_might_bluestacks` | b, real bug | Unconstrained alphabetic OCR reads the native Rank 1 numeral as `a`. Declare the medal field numeric; allow **all** digits, then retain the exact `1` comparison. The unique gold medal, page/table headers, thumb shape, row alignment and canonical resource fences remain required. |
| `test_campaign_victory_native` — glow phase | b, real bug | A glow particle becomes punctuation, producing `winner.` for `current-winner-46.png`. Declare the title alphabetic. Retain the complete literal `winner`, unique title, exact Loot and same-row/non-overlapping complete continue phrase requirements. No alias or confidence threshold changes. |
| `test_campaign_victory_native` — retained caption | c, environment | OCR tokenization includes a lower orange particle in Windows' `continue` word box but splits it into a separate token on Linux. The incidental historical rectangle is not the caption's semantic boundary. Replace that metadata pin with the consumer contract: a measured rectangle inside the caption search region and the actual integer dispatch center inside the visible caption. No production ROI is hard-coded or expanded. |

The caption test still requires every native glow phase and retained layout to
recognize RESULT, Winner, Loot and Continue, and requires the controller to issue
CONTINUE_VICTORY. Wrong/incomplete titles, missing captions, unknown popup,
duplicate/split-row captions and defeat separation retain their negative checks.

## Local verification

Environment: Windows, Python 3.12.10, Tesseract 5.5.0.20241111.

- `t24-native-field-alphabets-windows.json`: the two complete native modules,
  34 tests, zero failures/errors/skips; 58.625 seconds including driver overhead.
- `t24-numeric-rank-regression-windows-final.json`: one additional native-field
  regression with Rank 1 as a positive control and ranks 2, 3 and 9 rejected;
  zero failures/errors/skips; 2.406 seconds including driver overhead.
- Both invocations observed zero forbidden device-executable attempts.

The new regression changes only the numeral, retaining the connected gold medal.
Its first fixture draft erased the medal border and failed the positive control;
that draft is not acceptance evidence. The repair preserves the independent
medal prerequisite rather than changing an assertion or a production threshold.

## Owner decisions

Approve the two field-specific OCR alphabet changes before merging: they change
which historical native frames the classifier accepts. They do not grant runtime
authority, enable scheduling, or bypass identity, freshness, lease, input or
resource-effect checks. No BlueStacks/device input was used for this work.

NEEDS SUPERVISED LIVE RUN: Nova radial initial bind. That separate Nova gate is
unchanged by these offline OCR fixes.
