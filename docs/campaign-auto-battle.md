# Campaign Auto Battle route contract

Campaign owns one whole AP-drain run. It enters from Home, repeats every affordable
Auto Battle, and returns Home after a fresh displayed AP reading falls below the
configured stage cost. There is no five-minute wait between battles. The service
schedules the next observation for `completed_at + 300` seconds.

`automation_service` owns the serial scheduler, SQLite claims, controls, and
runtime fencing. Explicit supervised composition installs the consuming Campaign
runner. Ordinary registered selection remains non-consuming and keeps its
14-AP minimum; the explicit runner may observe below-cost AP and complete with
zero inputs. No timer estimate or old receipt substitutes for a fresh AP reading.

## Current acceptance

The October 30 current-source cohort `1d7d1315` completed 7,200.337 seconds with
21 successful passes: two separate AP14→0 drains and 19 zero-input low-AP checks.
Every pass verified Home, correct accounting, and exact completion+300 scheduling.
The audit verified 159 capture hashes, 24 dispatch source bindings, and 185
unchanged source files. Controls were restored off with no active/orphan run,
held controller lease, or unresolved consequential action.

Earlier live evidence includes six consecutive victories in one drain and a
current-Lineup two-win drain with AP27+1 regenerated−28 spent=0. Consuming
acceptance is strongest for `1-15-9`; navigation receipts for other configured
stages do not automatically prove their AP-spending behavior.

The current readers and navigation repairs cover the actual Lineup caption,
exclusive AP-icon crop, low-AP5 misreading, and a mapped building anchor that
needed a bounded camera adjustment before safe binding. Natural live AP5 and AP6
were independently viewed and matched with zero-input Home completion. The route
still requires fresh source/target binding and rejects ambiguous AP or outcomes.

The current-source full native UTC-crossing test is follow-up work. Offline
actual-service tests cover reset changes before runner entry and cross-reset AP
continuation. Current operator state and remaining evidence are recorded in
[`CURRENT_HANDOFF.md`](../CURRENT_HANDOFF.md) and [`BACKLOG.md`](../BACKLOG.md).
This document does not record a live operator or grant execution authority.

The supported live entrypoint is the canonical facade:

```powershell
python scripts/pnsctl.py automation-service --mode supervised --adapter bluestacks `
  --state-path .local-orchestrator/bot-state.sqlite3 serve --live --flow campaign `
  --campaign-stage 1-15-9 --campaign-cadence-seconds 300 `
  --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial emulator-5554 `
  --account-id primary-account --server-id primary-server `
  --output-directory .local-captures/automation-service-live
```

This preserves persisted controls and blocks; it does not enable them. Static
code registration is separate from SQLite service/flow enablement. Ordinary
legacy one-battle execution has been retired; recovery interfaces remain under
their existing guards. Earlier run-by-run notes are retained in the
[historical snapshot](archive/campaign-route-status-before-cleanup-20261030.md).

## Approved configured route

A configured destination uses `<story difficulty>-<chapter>-<stage>` (example `1-20-9` =
difficulty 1, Chapter 20, Stage 9). The approved destinations and static costs are exactly:

| Destination | Static cost |
| --- | ---: |
| `1-15-9` | 14 AP |
| `1-20-9` | 16 AP |
| `2-2-9` | 20 AP |

Maximum AP is 120. Natural regeneration is exactly one AP per 360 seconds. The rate is an
observation aid only: a due check must read the current displayed AP, configured stage identity,
and displayed stage cost again immediately before any entry. The normal service cadence is five
minutes after a completed whole-route drain, regardless of the regeneration estimate.

The selected stage is not reliably retained. Every Campaign entry therefore navigates to and
positively verifies all three configured destination components before Challenge. The displayed
cost must equal the static cost above; a mismatch, unknown stage, unknown AP, or unknown cost fails
closed.

Execution uses Auto Battle only. Sweep, Blitz, and Auto Complete are prohibited. One service claim
owns the entire drain: after each verified Victory and AP debit, it re-captures the current Home or
map balance and immediately continues when the stage remains affordable. Observed regeneration is
added to the same typed ledger and never starts a second claim. The route runs as many
configured-stage Auto Battles as current AP safely permits, never opens or accepts an AP refill,
and never consumes an item, currency, or other refill resource. Completion requires a fresh
terminal Home observation with AP strictly below the stage cost; that is when the five-minute
cadence starts. If the 12-battle or 96-input safety backstop is reached while AP remains
affordable, the route is incomplete/blocked rather than successful. Every safe terminal path
returns to canonical Home. Ultimate Challenge is a separate zero-AP flow.

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
8. Continue back to the chapter map, verify the Victory debit plus any independently observed AP
   regeneration, and repeat immediately under the same claim while the fresh balance permits.
9. When AP is insufficient, close the stage dialog, leave the chapter map, use the Campaign exit,
   and finish at Home/Base with AP below the exact stage cost. Only then is the whole drain complete
   and the 300-second next-check delay scheduled. An explicit loss continues to the chapter map,
   unwinds to Home, and disables repeats before any stage can be selected again.

Battle duration is deliberately not modeled as a fixed sleep. The hard polling ceiling is 180
seconds. Timeout or an unknown result is unresolved/blocked, never success.

The earlier `[3-1]` capture is retained historical gameplay/mechanics evidence for the controller
state sequence, not authorization for an approved configured destination. The supervised
historical BlueStacks `1-20-9` run on 2026-07-16 established a 16 AP cost, six consecutive
victories, battle durations ranging beyond 30 seconds, natural AP regeneration during the loop,
and an insufficient state that renders the 16 cost red without automatically opening a refill.
The run spent 96 AP and returned to Home/Base with 6/120 AP after three regenerated AP.

The historical executable BlueStacks validation on the same day started from 21/120 AP, panned directly to
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
`tasks/campaign_auto_battle_vision.py`, `automation_service/campaign.py`, and
`scripts/bluestacks_campaign_ap.py` now carry the whole-drain destination, AP-ledger, Auto,
result, terminal-Home, and cadence contract. The shared safety limits are `12` battles and `96`
inputs; they are backstops only and cannot authorize completion while another battle is affordable.
The service/controller path is implemented and offline-proven by the 57-check package. One current
native full-drain is accepted with the accounting above. A source audit also confirmed all 146
frame hashes, 37 dispatch sources, six parent links, AP math, and stage intervals of 69, 62, 65,
50 and 66 seconds; none was a five-minute inter-battle pause. The due-boundary eligibility defect
is fixed and native no-work completion is accepted at AP 3→3 with zero inputs/actions/battles and
verified Home. The natural due recheck is also accepted at AP 4→4 with zero inputs/actions/battles,
exact 300-second rescheduling, and clean controls. This proves the current Campaign contract; it
does not establish full portfolio readiness.

## Evidence classification and promotion gaps

The retained 2026-07-16 BlueStacks sessions are historical gameplay/mechanics evidence: they establish
stage navigation, displayed AP/cost handling, stage and lineup Challenge controls, Auto enablement,
victory/defeat recognition, repeated bounded runs, insufficient AP behavior, refill avoidance, and
Home return. The checked-in controller, vision code, templates, and focused fixtures provide
offline implementation and replay support.

That historical work does not by itself prove a current production-grade controller replay. The
current service/controller checks and one native full-drain provide the first current within-day
acceptance, but broader serial portfolio operation, next-day AP boundaries, and the native reset bridge for the fixed cross-midnight AP scope still require follow-up. The current Campaign route is
accepted only within its tested day scope. Refill-prompt rejection and no-duplicate guards remain
part of the contract.

This contract description does not itself authorize a live attempt. Runtime registration and
scheduler eligibility remain disabled.
