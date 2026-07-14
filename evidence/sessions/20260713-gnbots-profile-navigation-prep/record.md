# GNB-PHASE-C — profile/navigation/popup preparation

Recorded: 2026-07-13, America/Chicago

## Proven gaps fixed

Failing runner tests showed declared target anchors, postcondition anchors, and
`old_anchor_must_disappear` were not enforced. `NavigationRunner` now enforces them, requires
recognized foreground successors, and returns `ANCHOR_EVIDENCE_REQUIRED` before transport for any
provisional declared anchor.

## Profile correction

Raw 800×1280 More evidence binds Rankings to `(602,1138)-(690,1167)`, center `(646,1152)`.
Historical `(0,1120)-(800,1185)` center `(400,1152)` was removed. Personal Might and route-back
anchors are explicitly provisional and non-authorizing instead of claiming false Home screenshot
provenance.

## Popup scope

Only VIP Points reset and Help WebView are navigation-handled. Unknown benign popups block
dismissal, resource/premium/cost dialogs block, hard stops are fatal, and one frame hash cannot
authorize two popup handlers. Live adapter calls this policy before both allowed dismissals.

## Verification

`python -m unittest discover -s tests`

Result: 172 tests passed. IDE lints: none.

No live input occurred during this preparation. Corrected Rankings navigation and downstream
Personal Might screens still require live raw evidence before Phase C can pass.
