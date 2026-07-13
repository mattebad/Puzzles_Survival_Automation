# Selected Daily-tab correction and live retest — 2026-07-13

## Scope

This evidence records a focused correction and retest of the false-positive Main Quest versus selected Daily Quest recognition. It did not inspect Daily Quest objectives and did not resume the quest-to-claim trial.

Implementation commits:

- `4f26889` — require the selected Daily Quest tab and reject Main Quest as Daily Quest.
- `f3373f8` — tighten the Main Quest Daily-tab target ROI so the tap point is the actual tab.

## Root cause and correction

The first corrected classifier correctly rejected the Main Quest frame as Daily Quest, but the existing target ROI `(260,80,540,300)` was a broad header region. Its center caused the executor to tap `(400,190)`, below the tab label, so the screen remained Main Quest. The retained source and all three post frames had the same Main Quest hash `2af9d0d729fa3d18cf59909b94c15f7165bef715eba808ce665f58f3dbdb6285`.

The fixed Bliss profile now uses the independently captured Main Quest tab ROI `(300,70,500,140)`, whose center is `(400,105)`. The corrected selected-tab recognizer still requires the independently captured Daily selected-state ROI and rejects the Main Quest selected-state negative.

## Live inputs

All inputs used the task-scoped unprivileged worker, private worker-to-VM ADB, fresh profile-compatible captures, the central policy, prepared journal records, immediate-before recapture, and one transport call per action.

1. `SAFE_PROMOTIONAL_BACK`: tap `(87,32)`, one call, confirmed Home/Base successor.
2. `HOME_TO_QUEST`: tap `(330,1205)`, one call, confirmed Quest successor.
3. `QUEST_TO_DAILY` with the old broad target: tap `(400,190)`, one call, no screen change; retained as `unresolved` navigation-only evidence. No consequential action was possible, and this record is not an unresolved consequential block. It was not retried with the same target or action key.
4. `QUEST_TO_DAILY` with the corrected target ROI: tap `(400,105)`, one call, confirmed the selected Daily Quest successor.

The corrected action source was the Main Quest frame hash `2af9d0d729fa3d18cf59909b94c15f7165bef715eba808ce665f58f3dbdb6285`; its immediate-before frame was identical. The confirmed Daily Quest postcondition frame hash was `11f30d6cb904a8370b01054e17affa4f245df70fac3b188fa3f3c4b9b03bafb3`.

No Daily Quest rows, points, reset text, Go controls, Claim controls, objectives, prerequisites, or destinations were inspected after the corrected postcondition. No quest, Go, Claim, spend, combat, account, profile, OS, or other gameplay input occurred.

## Offline validation

- Complete dependency-complete suite: 100 tests passed.
- RT-019: passed; profile `pns-blissos-poc-virgl-800x1280-v1`, canonical hash `195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.
- M6 six-asset validation: passed.
- Main Quest and retained live Main frame: rejected by selected Daily recognizer.
- Selected Daily fixture: accepted by selected Daily recognizer.
- Target geometry: profile center `(400,105)` asserted by task-module tests.

## Journal and cleanup

Retained database: `actions.sqlite3` in this directory. Schema version is 1. Final actions are three confirmed navigation records and one historical unresolved navigation-only no-effect record; nonterminal count is zero and unresolved consequential count is zero. The controller lease is released.

The game was force-stopped. The task worker was removed. The pre-existing ADB daemon was not killed or recreated. No task tunnel or listener remained. The Bliss VM remained running on the selected VirGL profile, and the RT-017 backup remained mode `0600`, size `13522501632` bytes.

Protected files were not modified:

- `crlf-reconciliation.json` SHA-256: `62450f89a34a1872e5b1e6100f94dc641037b3f724026dc7e0f8af35906596c3`.
- `live-reconcile-002.png` SHA-256: `45b65bec9136855d7a5aea23e3573fb03e54e1cdbe2ce7e0b1c328b872f863f9`.

MVP-QUEST-TO-CLAIM remains blocked because this retest intentionally stopped before objective/reset reconciliation; no transition-corpus evidence was promoted.
