# Ticket #24: native OCR portability

Status: implemented on the candidate branch; native Linux module proof is now
present, but this is not whole-suite or live acceptance. The d4db4c8 inner-crop-
only subset is historical and was invalidated by the Rank 10/11 safety
regression. The full-medal-band highlight-containment guard has native Linux
proof; macOS hosted proof is not established here.

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
| `test_personal_might_bluestacks` | b, real bug | The numeral crop includes the shield's bright border, and unconstrained OCR reads the resulting badge as `a`. Bind the inner numeric field relative to the independently measured medal; allow **all** digits, then retain the exact `1` comparison. The unique gold medal, page/table headers, thumb shape, row alignment and canonical resource fences remain required. |
| `test_campaign_victory_native` — glow phase | b, real bug | A glow particle becomes punctuation, producing `winner.` for `current-winner-46.png`. Declare the title alphabetic. Retain the complete literal `winner`, unique title, exact Loot and same-row/non-overlapping complete continue phrase requirements. No alias or confidence threshold changes. |
| `test_campaign_victory_native` — retained caption | c, environment | OCR tokenization includes a lower orange particle in Windows' `continue` word box but splits it into a separate token on Linux. The incidental historical rectangle is not the caption's semantic boundary. Replace that metadata pin with the consumer contract: a measured rectangle inside the caption search region and the actual integer dispatch center inside the visible caption. No production ROI is hard-coded or expanded. |

The caption test still requires every native glow phase and retained layout to
recognize RESULT, Winner, Loot and Continue, and requires the controller to issue
CONTINUE_VICTORY. Wrong/incomplete titles, missing captions, unknown popup,
duplicate/split-row captions and defeat separation retain their negative checks.

## Native Linux intermediate proof

[Run 41797717049](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41797717049)
at `ae4d923` runs the real native modules on Ubuntu 24.04 (Tesseract 5.3.4)
and Ubuntu latest (5.5.0). All six Campaign tests pass on both engines, including
the existing negative controls. Numeric-alphabet restriction alone does **not**
repair Personal Might: both jobs retain three failures and 15 errors, and the
native Rank 1 field returns no digit. These are failed candidate observations,
not acceptance receipts.

The next candidate excludes the decorative shield border from the medal-relative
numeral crop. It does not map `a` to `1`, reduce an identity check, or retry a
resource action. The complete numeric field and the independent medal remain
required.

## Historical inner-crop subset and safety regression

[Run 41801356827](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41801356827)
at `d4db4c8` passed six Campaign and 29 Personal Might tests on both Tesseract
5.3.4 and 5.5.0. The source-hashed documents are retained in
[`native-ocr-linux-d4db4c8.json`](native-ocr-linux-d4db4c8.json). This
inner-crop-only subset is invalidated: a subsequent derived-frame smoke and
permanent regression found synthetic ranks 10 and 11 bound as Rank 1 because the
crop hid part of the second numeral.

The repair inspects bright, low-saturation numeral highlights across the full
medal band and requires their complete horizontal extent to fit inside the OCR
field. Missing or out-of-field highlights fail closed before OCR. This adds a
strict gate; it does not change a confidence threshold, map characters, permit
only digit 1, alter the source frame or retry an action. The existing native
positive/disabled-state controls remain required, and the numeric regression now
also rejects ranks 10, 11, 12 and 21.

In the Windows local run, the permanent regression failed before the guard for
ranks 10 and 11. Afterwards both full native modules passed: 36 tests, zero
failures/errors and one host symlink-privilege skip, 61.063 seconds including
driver overhead. No forbidden device-executable attempt was observed. This is
local Windows evidence, not hosted Windows or macOS guard proof.

## Native Linux full-band guard proof

[Run 41811529483](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41811529483)
at `5d4ca3e6a6c0bf42827fc01a08b2cea9299f1ee6` ran the two native modules on
Ubuntu 24.04 with Tesseract 5.3.4 and Ubuntu latest with Tesseract 5.5.0.
The source-labelled raw receipts, per-file SHA-256 hashes and runner provenance
are retained in
[`native-ocr-linux-5d4ca3e.json`](native-ocr-linux-5d4ca3e.json).

| Runner / Tesseract | Campaign victory | Personal Might |
| --- | --- | --- |
| Ubuntu 24.04 / 5.3.4 | 6 tests; 14.766 s | 30 tests; 59.511 s |
| Ubuntu latest / 5.5.0 | 6 tests; 13.175 s | 30 tests; 53.017 s |

All four module receipts report zero failures, errors, skips and forbidden
process attempts. The passing Linux Personal Might module provides native proof
that Rank 1 is accepted and ranks 2, 3, 7, 9, 10, 11, 12 and 21 are rejected;
the other native controls remain intact. This is two-runner native-module
evidence only, not a whole-suite or live green claim.

## Local verification

Environment: Windows, Python 3.12.10, Tesseract 5.5.0.20241111.

- `t24-native-field-alphabets-windows.json`: the alphabet-only stage's two native modules,
  34 tests, zero failures/errors/skips; 58.625 seconds including driver overhead.
- `t24-numeric-rank-regression-windows-final.json`: one additional native-field
  regression with Rank 1 as a positive control and ranks 2, 3 and 9 rejected;
  zero failures/errors/skips; 2.406 seconds including driver overhead.
- Both invocations observed zero forbidden device-executable attempts.
- `t24-inner-rank-field-windows.json`: the revised numeral crop, four tests
  covering native Rank 1, persistent disabled state/rewards, disabled antialias
  negatives and the synthetic Rank 1/2/3/7/9 control; zero failures/errors/skips;
  8.875 seconds including driver overhead and zero forbidden attempts.

The new regression changes only the numeral, retaining the connected gold medal.
Its first fixture draft erased the medal border and failed the positive control;
that draft is not acceptance evidence. The repair preserves the independent
medal prerequisite rather than changing an assertion or a production threshold.

## Owner decisions

Approve the native field-alphabet and numeral-crop changes before merging: they
change which historical native frames the classifier accepts. They do not grant
runtime authority, enable scheduling, or bypass identity, freshness, lease, input
or resource-effect checks. No BlueStacks/device input was used for this work.

NEEDS SUPERVISED LIVE RUN: Nova radial initial bind. That separate Nova gate is
unchanged by these offline OCR fixes.
