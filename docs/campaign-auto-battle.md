# Campaign Auto Battle route contract

The semantic contract extends the existing one-pulse Campaign AP model. A separate local
BlueStacks adapter now binds native 800x1280 OCR/templates and emits one checked action at a time.
It is not a registered production or scheduled task.

## Approved configured route

A configured destination uses `<story difficulty>-<chapter>-<stage>` (example `1-20-9` =
difficulty 1, Chapter 20, Stage 9). The approved destinations and static costs are exactly:

| Destination | Static cost |
| --- | ---: |
| `1-15-9` | 14 AP |
| `1-20-9` | 16 AP |
| `2-2-9` | 20 AP |

Maximum AP is 120. Natural regeneration is exactly one AP per 360 seconds. Home scheduling may
use that rate to estimate the next eligible time, but an estimate never authorizes a battle: the
current displayed AP, configured stage identity, and displayed stage cost must be read and matched
again immediately before execution.

The selected stage is not reliably retained. Every Campaign entry therefore navigates to and
positively verifies all three configured destination components before Challenge. The displayed
cost must equal the static cost above; a mismatch, unknown stage, unknown AP, or unknown cost fails
closed.

Execution uses Auto Battle only. Sweep, Blitz, and Auto Complete are prohibited. Each successful
run advances the expected AP ledger by the static stage cost, then re-captures current AP before
another run. The route runs as many configured-stage Auto Battles as current AP safely permits,
never opens or accepts an AP refill, and never consumes an item, currency, or other refill
resource. Insufficient AP returns a deferred outcome with the calculated recovery time and no
resource input. Every safe terminal path returns to canonical Home. Ultimate Challenge is a
separate zero-AP flow.

## Captured route

The local BlueStacks session
`.local-captures/bluestacks/consume-ap-campaign/20260716T014118395232Z/` established this sequence:

1. Home/Base to Campaign.
2. Campaign tier/chapter map.
3. Exact stage selection (`[3-1] Teton Ranch`, 20 AP).
4. The stage-dialog Challenge control, followed by the fixed bottom Hero Lineup Challenge control;
   hero identities and lineup contents are ignored.
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

The earlier `[3-1]` capture is retained gameplay/mechanics evidence for the controller state
sequence, not authorization for an approved configured destination. The supervised BlueStacks
`1-20-9` run on 2026-07-16 established a 16 AP cost, six consecutive
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
`tasks/campaign_auto_battle.py`, `tasks/campaign_auto_battle_runtime.py`,
`tasks/campaign_auto_battle_vision.py`, and `scripts/bluestacks_campaign_ap.py` preserve the
existing destination, AP-ledger, Auto, result, and Home-return implementation. The local script is
dry-run by default and records every frame and command. Its legacy explicit cost/budget/run-cap
configuration is an implementation gap: later policy integration must derive the cost from the
approved static map, enforce the 120 maximum and 360-second regeneration contract, and still
verify the displayed values before each battle.

## Evidence classification and promotion gaps

The retained 2026-07-16 BlueStacks sessions are valid gameplay/mechanics evidence: they establish
stage navigation, displayed AP/cost handling, stage and lineup Challenge controls, Auto enablement,
victory/defeat recognition, repeated bounded runs, insufficient AP behavior, refill avoidance, and
Home return. The checked-in controller, vision code, templates, and focused fixtures provide
offline implementation and replay support.

That retained work does not by itself prove a production-grade controller replay on the production
runtime. It is not a hash-bound production attempt journal or a supervised production canary.
Remaining proof requires native production frames for every approved destination and static cost,
the production recognizer/controller/persistence path in a zero-transport positive replay, AP
regeneration and insufficient-AP defer evidence, refill-prompt rejection, and a separately
authorized supervised consequential canary with canonical Home terminal proof.

No live attempt is authorized by this contract reconciliation. Runtime registration and scheduler
eligibility remain disabled.
