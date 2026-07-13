# Help All validation — 2026-07-13

## Scope

This was a short validation of the corrected Alliance Help handler. It did not rerun the full
MVP, did not select another objective, and did not send Go, Claim, quest-completion, spend,
account, or OS input.

## Reconciliation

The retained prior action `alliance-help-20260713-001` used `(650,350)`, below the visible orange
Help All control. Its immutable historical journal remains unresolved with reason
`unexpected_successor`. A separate `reconciled-actions-20260713.sqlite3` copy records
`proven_no_effect_mistarget` and has no unresolved action.

## Corrected live transaction

- Source: Speedup Help surface, positively recognized from the fixed profile and local header ROI.
- Help All ROI: `(556,274)-(727,330)`; derived tap: `(641,302)`.
- Source and immediate-before target ROI: orange control present; immediate-before was fresh and
  profile-compatible.
- Policy: `AUTHORIZED_ZERO_COST_R1`; action kind `ALLIANCE_HELP_ALL`.
- Dispatch: exactly one transport call, `input tap 641 302`.
- No transport retry occurred.
- Postcondition evidence: the Help All control disappeared in post frame 1 while the stable local
  Speedup Help header ROI `(250,0)-(550,120)` remained byte-identical to the source. The original
  live journal recorded unresolved because its first implementation required noisy whole-header
  OCR; the reconciled operational copy records positive postcondition confirmation.

## Validation and cleanup

- SQLite schema: version 1.
- Reconciled operational journal: zero nonterminal and zero unresolved actions; lease released.
- Complete pinned suite: 114 tests passed.
- RT-019: passed with profile `pns-blissos-poc-virgl-800x1280-v1`.
- Six M6 assets: passed; input lock false.
- Worker and task ADB removed through `pnsctl cleanup`.
- Pre-existing loopback ADB was not stopped; no public listener or tunnel remained.
- VM remained running; RT-017 backup remained intact.

## Task result

MVP-QUEST-TO-CLAIM remains blocked. The Help All transaction was validated, but this short
handler check did not establish Daily Quest progress or a Claim row, so no Claim input was sent.
M6-DQ-TRANSITION-CORPUS remains downstream and was not started.
