# Campaign Auto Battle route contract

The semantic contract extends the existing one-pulse Campaign AP model. A separate local
BlueStacks adapter now binds native 800x1280 OCR/templates and emits one checked action at a time.
It is not a registered production or scheduled task.

## Configured route

A stage uses `tier-chapter-stage`, for example `1-20-9`. The adapter positively
recognizes all three components before Challenge:

- the selected tier (`1` or `2` at the top of the Campaign map);
- the chapter header, such as `Ch.3 Teton Ranch`;
- the exact stage dialog, such as `[3-1] Teton Ranch`.

AP cost, current AP, an explicit AP budget, and a maximum run count are mandatory. Whole runs are
bounded by fresh available AP, remaining budget, and the run cap. AP is re-read before every run;
independently observed natural regeneration is recorded separately from stage spend. Refills and
unknown costs fail closed.

## Captured route

The local BlueStacks session
`.local-captures/bluestacks/consume-ap-campaign/20260716T014118395232Z/` established this sequence:

1. Home/Base to Campaign.
2. Campaign tier/chapter map.
3. Exact stage selection (`[3-1] Teton Ranch`, 20 AP).
4. The fixed bottom lineup Challenge button; hero identities and lineup contents are ignored.
5. Active battle and explicit Auto enablement.
6. Screenshot polling while battle remains active.
7. Success only when `WINNER`, `Loot`, and `Tap to continue` are jointly recognized.
8. Continue back to the chapter map, verify stage spend plus any independently observed AP
   regeneration, and repeat only while the fresh bounded plan permits.
9. When AP is insufficient, close the stage dialog, leave the chapter map, use the Campaign exit,
   and finish at Home/Base. An explicit loss continues to the chapter map, unwinds to Home, and
   disables repeats before any stage can be selected again.

Battle duration is deliberately not modeled as a fixed sleep. The hard polling ceiling is 180
seconds. Timeout or an unknown result is unresolved/blocked, never success.

The supervised BlueStacks `1-20-9` run on 2026-07-16 established a 16 AP cost, six consecutive
victories, battle durations ranging beyond 30 seconds, natural AP regeneration during the loop,
and an insufficient state that renders the 16 cost red without automatically opening a refill.
The run spent 96 AP and returned to Home/Base with 6/120 AP after three regenerated AP.

The executable BlueStacks validation on the same day started from 21/120 AP, panned directly to
chapter 20 without clicking intermediate chapters, selected `[20-9] Westwinds`, verified the
16-AP cost, pressed only the lineup Challenge control, enabled Auto, recognized the full victory
signature, and verified 6/120 after the victory (16 spent plus one regenerated). During return,
an incorrect bottom-left exit binding repeated a navigation-only tap; the runner was terminated,
the exact lower-right highlighted Campaign exit was captured and bound, and a generic identical
input retry guard was added. One correct exit input returned to Home/Base. A final fresh run
recognized 9/120 as insufficient and terminated without input.

The supplied native defeat frame adds a separate three-part signature: `LOSE`, `Improve Might`,
and the bottom `Tap to continue`. Only that bottom continuation ROI is bound. The nearby `Buy Now`
panel is explicitly excluded. After continuation, `loss_seen` takes priority over AP affordability,
so chapter, tier, and Home states can only unwind and complete; they cannot re-enter the stage.

Project-owned templates are retained under `tasks/assets/campaign_auto_battle/800x1280/`.
`scripts/bluestacks_campaign_ap.py` is dry-run by default, requires the exact local BlueStacks
serial and explicit stage/cost/budget/run cap, and records every frame and command locally.

## Promotion gaps

Before a live Bliss adapter can be promoted, capture and validate Bliss-native 800x1280 source,
target, immediate-before, and successor evidence for each input.

BlueStacks frames are route-translation sources only. Runtime registration and scheduler eligibility
remain disabled.
