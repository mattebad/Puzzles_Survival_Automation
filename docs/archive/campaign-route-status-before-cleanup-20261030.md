# Campaign Auto Battle route contract

The normal Campaign route is one whole AP-drain claim. A single native invocation enters from
Home, repeats every affordable Auto Battle, and returns to Home only after the fresh displayed AP
is below the selected stage cost. There is no five-minute wait between battles. After the whole
drain completes, the service schedules the next observation for `completed_at + 300` seconds.

The service/controller implementation is proven offline by 57 focused checks, including
observed-regeneration continuation, cumulative entry/battle/effect accounting, exact terminal Home
AP admission, and post-drain cadence. Current native code has one accepted full-drain run: six
consecutive Victories, six unique entries/battles/effects, 37 inputs, AP `83 - 84 + 2 = 1`, and
verified terminal Home. Its before-due restart performed zero work and preserved `completed_at +
300s`. The first real due-boundary test reached admission on time but produced zero executions/reports
because explicit Campaign execution inherited a 14-AP minimum from the non-consuming selector.
That boundary is now fixed: explicit execution uses minimum 0 while the registered selector remains
at 14 with its fences, and 47 focused actual-serve/real-runner checks plus review pass. Native
below-cost no-work completion then passed at AP 3→3 with zero inputs/actions/battles and verified
Home, creating a new exact 300-second due. The repaired due recheck then passed naturally at Home
AP 4→4 with zero inputs/actions/battles, exactly two capture/event hashes, no dispatches, and a
new exact `completed_at + 300s` due. Cleanup left service and all flows OFF with no active/orphan
runs. The Campaign route is accepted for this within-day contract; it is not registered for
production or scheduler execution. The prior 74093 pre-reset session stopped between completed checks after four zero-input/zero-action
AP no-work reports (`8→8`, `8→8`, `9→9`, `10→10`) and a terminal `SERVICE_DISABLED` record. It was
a controlled stop for the calendar-scope fix; the 7200-second soak did not complete. The fix is
now frozen and offline-proven: `automation_service/service.py` SHA-256
`f060218359d8466489dcef165802b7e58b17bd9341bf6a1401eb4766bc73cc95` and
`automation_service/campaign.py` SHA-256
`8d5c059da04bf410db1cd4c7347eb176b4be1e3cc67f8d398b65aec0e6cacae1`. Seventy focused checks,
review, and compile pass. Virtual actual-serve/real-runner checks cover two wins across virtual
00:00, late Home 13→14 continuation, preserved claim identity, new-day-before-due zero captures,
new-day-due zero input, and preclaim old-observation discard; other seven route guards remain
unchanged.

Session 84447 completed its bounded 4800-second run at 22:43:35 UTC. It produced 15 reports: an initial AP 14→1 full affordable drain with one Victory and 12 inputs, followed by 14 due zero-work Home checks at AP 1,2,3,4,5,6,7,8,9,9,10,11,12,13. Every report scheduled exactly 300 seconds after completion and its first capture was at or after the preceding due. The independent audit verified all 52 capture hashes, 12 dispatch-source bindings, one reconcile post-hash, and the canonical 12-input/1-action record. Only Campaign ran; the other seven routes were not invoked early. Cleanup confirmed controls OFF with no active/orphan runs or surviving operator before the next launch. This is bounded serial Campaign cadence evidence; it does not establish the native cross-midnight bridge or portfolio acceptance.

The AP HUD parser now crops strictly beyond the measured badge edge; retained 12/120 parser/ledger regression passes. Explicit pending-AP admission uses an input-free observation-pending projection, executor opt-in from the registry descriptor, canonical due/generation binding, and leaves the pure selector at 14 AP with legacy rejection unchanged. Claimed VIP-popup recovery normalizes through Home under the same runtime claim with exact journal accounting and returns the actual terminal frame. Offline verification: 53 focused core checks (52 pass, one unchanged legacy RegistryClosureMissingMight baseline), 87 native checks pass, compile and independent review pass.

A claimed native VIP-popup affordable drain is accepted: exact VIP dismissal, Chapter return and Home, then one Victory; AP `22 + 1 - 14 = 9`, terminal Home, 15 inputs/1 effect, and exact `completed_at + 300s` due. Audit verified 42 capture hashes, 15 dispatch sources, two reconcile posts, terminal Home hash and canonical 15/1. A before-due restart completed with zero reports, native directories and attempts, preserving due. This does not establish low-AP or terminal-popup native acceptance. The earlier 2026-10-29 cross-midnight failure remains immutable; separate source reconciliation proved AP 26→12, one win, 14 spent, zero new input, without rewriting its failed report.

Root-only handle 3298 is currently running the all-eight fresh-reset soak; latest snapshot had zero reports and only a Nova native directory with a RUNNING reset-day-30 claim. Its aggregate, cleanup, fresh seven-route resource effects, Enhancement one-Profile Gear→Chip→Module visit, and full new-code midnight route proof remain pending. Monitor only the sole operator. This active run is not yet portfolio acceptance.

The supported canonical live entrypoint is the existing `pnsctl` facade, for example:

```text
python scripts/pnsctl.py automation-service --mode supervised --adapter bluestacks --state-path .local-orchestrator/bot-state.sqlite3 serve --live --flow campaign --campaign-stage 1-15-9 --campaign-cadence-seconds 300 --adb "C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe" --serial emulator-5554 --account-id primary-account --server-id primary-server --output-directory .local-captures/automation-service-live
```

The facade forwards arguments unchanged to the existing canonical service CLI, checks the standard
mode/adapter/state path before serving, and respects existing disabled controls. It does not
auto-enable registration, scheduling, or flow gates. Ordinary legacy one-battle live entrypoints
are historical/recovery interfaces; navigation, preparation, explicit Victory recovery and receipt
audit remain preserved through the canonical path.

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
