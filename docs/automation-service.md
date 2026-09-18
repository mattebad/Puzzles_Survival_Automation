# Automation service

`automation_service/` composes the existing Python flows with canonical SQLite service state.
The Windows/BlueStacks recruitment slice uses `UtcPulseCoordinator` for eligibility, claims,
and terminal projection, then calls `run_noahs_tavern_unified_recruitment` and the existing
`NoahTavernIntegratedRoute`. Other canonical handlers remain selectors, not gameplay runners.

## Boundaries

- Context classification is read-only. Flow handlers own action semantics.
- The service scheduler uses UTC epoch `next_eligible_at` values. It never interprets
  `tasks.scheduler.TaskState.next_due_monotonic` and does not compose two schedulers.
- Fake and replay adapters have zero transport.
- The semantic BlueStacks adapter retains its `SafeActionExecutor` contract. Recruitment
  instead uses its existing ordinary native runner under the shared `RuntimeInputLock`.
  No arbitrary shell, coordinate, or remote-command endpoint is added.
- Canonical registration is static code; service/flow enablement remains in `BotStateManager`
  and defaults off. The historical JSON registry and development queue are not runtime authority.
- Campaign composition delegates destination policy and atlas navigation to existing
  `tasks.campaign_auto_battle` / `tasks.campaign_atlas` contracts. It never authorizes AP,
  Challenge, Auto Battle, Sweep, Blitz, Auto Complete, or AP refill.
- Retention operations classify records only; deletion remains in the dedicated evidence workflow.

## Local checks

Run focused checks from the repository root:

```text
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_automation_service_contracts \
  tests.test_automation_service_adapters \
  tests.test_automation_service_temporal \
  tests.test_automation_service_scheduler \
  tests.test_automation_service_handlers \
  tests.test_automation_service_campaign \
  tests.test_automation_service_operations
```

Status and replay remain non-authorizing:

```text
PYTHONDONTWRITEBYTECODE=1 python -m automation_service --mode disabled status
PYTHONDONTWRITEBYTECODE=1 python -m automation_service --adapter replay observe
```

## Windows recruitment service

Live execution requires separate permission, existing service/Recruitment enablement, and
explicit local serial/account/server configuration. Merely invoking `serve` does not enable
anything. After authorization, the invocation shape is:

```text
python -m automation_service --mode supervised --adapter bluestacks serve --live --serial <private-local-serial> --account-id <account> --server-id <server>
```

Use the existing Python environment with OpenCV, NumPy, Pillow, and pytesseract/Tesseract
available for the native runner. `--state-path` is a global option; `serve` also accepts
`--adb` and `--output-directory`. A sibling `<state-stem>.recruitment.sqlite3` uses the existing
maintenance repository for Basic counts and independent tier cooldowns. No old session or
operational state is automatically imported.

- One process owns the shared runtime input lock for its lifetime; only recruitment executes.
- Selection cannot report recruitment completion. Verified native results and Home return
  determine the next UTC due time. Frame freshness remains monotonic.
- Basic is capped at five free singles per UTC game day; Int./Advanced cooldowns survive reset.
  Paid, premium, item-backed and 10x recruitment remain prohibited.
- Successful passes return Home. The service waits outside the flow until due, checking stop
  and enablement at most every 30 seconds while idle.
- Ctrl+C/SIGTERM stop the loop. `service-disable`/`emergency-stop` prevent further native inputs
  at capture/dispatch checkpoints. An in-flight bounded transport call may finish first.
- An interrupted, unknown, or failed pass leaves a persistent Recruitment-only inspection block.
  Do not clear it and retry blindly; inspect the retained session and consuming outcome first.
  The block is cleared automatically only after verified canonical terminal projection.
- Results are emitted as JSON. Development manifests, Git state, handoffs and agent receipts
  are not runtime dependencies.

Focused guarded integration: `python -m unittest tests.test_service_recruitment`.
Its scripted recognition/transport exercises the real runner and controller, not live gameplay.

## Packaging and eventual deployment

`docker/automation-service.Dockerfile` and `compose.automation-service.yml` provide a reproducible
Linux packaging shape with disabled/fake defaults, bounded resources, a read-only code/root
filesystem, and explicit writable state/evidence mounts. The compose file makes no Docker-socket,
libvirt, public-ADB, or runtime-host assumption.

Build and test locally before any future artifact deployment. No deployment is performed by this
roadmap slice; Codex/Cursor is not a NAS production dependency.

## Readiness versus admission

Offline tests do not establish live recognition, transport reliability, or unattended gameplay.
LB-02's first authorized live service attempt temporarily enabled the gates but blocked on
ADB readiness before any game input; gates were restored disabled and the inspection block
retained. See `CURRENT_HANDOFF.md` for the preflight recognition/allocation failure and evidence.
The subsequent offline repair changed only independent Home navigation OCR to sparse-text mode:
the retained frame passes that classifier and Atlas, while Tavern semantic recognition remains
UNKNOWN. The actual recruitment preflight gates on that Tavern recognizer, not the repaired
classifier, so its `current_source_not_recognized` failure remains unresolved on this frame.
Existing-server inspection found the device available again, but neither the original
allocation cause nor device stability is established. `OPENCV_FOR_THREADS_NUM=1` still reported
24 OpenCV threads in the available build; it is not a verified memory/thread bound.
The separately authorized attempt 2 connected and navigated to the Advanced Tavern page,
but its next-frame recognition failed before any recruitment. Three navigation inputs occurred;
no Home return was performed. Gates were restored disabled and the new inspection block retained.
The header/title crop geometry correction is now applied and verified with real retained-frame
OCR/controller replay and 44 focused tests. No new spelling alias or grayscale workaround.
Authorized attempt 3 made one camera pan, then blocked at building-label binding before Tavern
entry; the corrected Tavern recognizer was not reached. Gates were restored disabled (generation
6), ownership released, and the new inspection block retained. No recruit or cooldown transition.
Exact-frame offline replay shows strong Atlas localization but failed label OCR from noisy/
clipped crops; complete isolated label-line OCR succeeds. Independent Home OCR is not this final
binder's veto. The shared label extractor is now repaired and verified offline against five
Tavern frames plus Bank/Fighter Camp; 185 affected tests pass. Binding failures now distinguish
`home_atlas_localization_failed`, `home_atlas_label_not_read`, and `home_atlas_target_unsafe`,
with frame-linked bounds, raw OCR and crop artifacts. The real unified failure path was checked
using input-forbidden replay. No post-repair live proof yet: preserve the existing inspection
block, gates and state until a separately authorized bounded run. Do not retry automatically.
Authorized attempt 4 used the existing shared VIP startup recovery before the service. One
exact Close removed the popup, but Home-nav template correlation 0.336 missed the 0.90 floor;
recovery recorded `unresolved:unexpected_successor`. Main visually confirmed Home afterward,
not runtime admission. The service never started and the repaired binding was not exercised.
The canonical service does not automatically invoke the `pnsctl` shared startup recovery path.
Preserve the startup action record and existing Recruitment block; diagnose the retained
successor offline rather than repeating Close. All gates remain disabled at generation 6.
Shared popup interruption and context-aware resumption are tracked in active backlog LB-09,
not yet implemented. Authorized attempt 5 used fresh normal Home admission and one real service
pass: repaired Tavern binding passed, one free Advanced recruit visibly produced Griffin Frag x1,
and the post-Close screen showed Free in 1d 23:59:54. Automatic verification nevertheless stopped
at `recruit_postcondition_not_proven`; maintenance state remained empty and Home return failed.
Native events prove the recruit dispatch despite zero-dispatch result flags/canonical counters.
Treat it as consumed, retain the inspection block, and investigate offline before any retry.
The inspected failure budget was re-armed via state API; final failures=1 and gates disabled at
generation 8. Operator cleanup required a finalizer after a closed-database error; ownership is
released. No consuming action was repeated.
The cooldown/control interpretation bug is now repaired offline: “Free in…” plus Recruit 1x
does not qualify as a free button, and a parsed positive timer remains an active cooldown.
Real retained before/result/after replay passes the unchanged controller, persists/restores
the Advanced cooldown in temporary SQLite and prevents duplicate recruitment; 72 tests pass.
Operational maintenance was not backfilled, the inspection block remains, and there is no
post-fix live/Home-return proof. Existing persistence still uses the full tier cooldown policy
interval. Zero-dispatch failure flags, operator cleanup and LB-09 remain separate work.
Authorized attempt6 reached a free Intermediate result showing 5K Nova EXP x1, then stopped at
`recruit_result_not_recognized` before Close. OCR read that reward correctly, but the then-current
predicate admitted only “frag” or “antiserum” text. Four captures retained the same result.
No new cooldown/count persistence or Home return was established, and Advanced cooldown was
not observed in this pass. Both consumed free attempts remain non-repeatable without inspection.
Gates are disabled at generation10; failures2/max3, new block retained, ownership released,
process exited0 cleanly. End-to-end completion remains unverified.
Reward-independent completion is now repaired offline. Only pending authorized free context
permits one Close, identified by literal label OCR within the existing red control. Success is
a fresh same-tier Free-in cooldown with free disabled; one consumed count comes from the
pre-action count, independent of reward text, quest progress or post-screen count OCR.
Native Nova/blank-reward Close and complete Advanced replay pass; temporary SQLite persistence,
restart and synthetic Basic4->3/Int1->0 are verified. 78 affected tests pass.
No operational backfill, live Close/retry, Home-return proof or block clearance followed.
Evidence: `.local-captures/lb02-cooldown-success-contract-20260916T025512Z/delivery-result.json`.
Attempt7 now establishes one completed live pass: Basic free recruit, one Close, positive cooldown,
Int/Advanced cooldown deferral without repeats, and verified safe Home return. Six native inputs.
Basic count1/remaining4 and all tier deadlines persisted; next due2026-09-16T04:11:47.161664Z.
Main verified generation12 disabled gates, failures0, released ownership and clean service exit.
The initial launcher failed before service import; only one actual service pass ran.
Generic scheduler Home/action-count fields still do not prove gameplay completion; native
route/events do. Later-due/unattended execution was not exercised live. VIP record unchanged.
Evidence: `.local-captures/lb02-live/attempt7-20260916T035700Z/attempt7-result.json`
and adjacent `parent-verification.json`.
A subsequent authorized30-minute soak stopped on its first pass after27.328s:
`home_atlas_label_not_read`, before any input. Main sees Home/Tavern label in the retained frame.
Two captures, zero recruits; scheduler state and VIP ledger unchanged. Gates disabled at
generation14, failures1/max3, new block retained, ownership released and process exited0.
This does not establish prolonged or repeated-cycle reliability.
Evidence: `.local-captures/lb02-live/soak-20260916T042200Z/soak-result.json`
and adjacent `parent-verification.json`.

The LB-03 offline candidate now removes building-name OCR from Home-entry authority. A fresh
canonical Atlas localization projects a distinct interaction anchor and an anchor-centred hit
region that must remain inside the building footprint and HUD-safe geometry. Route-owned
successor recognition still gates Tavern, Supply, Nova and other destinations. The duplicate
Supply Home-building binder is removed; Claim Supply/radial OCR remains destination semantics.
The settled affected command passed 369 tests with 4 skipped. Five retained positives include
the exact failed-soak frame, two other Tavern camera positions, native Bank, and a label-erased
Tavern frame with OCR forbidden; 16 geometry/state negatives produced no input. Read-only
inspection preserved generation14 disabled gates, the original block/failure count, cooldowns,
counts, released ownership and unresolved startup VIP ledger. Evidence:
`.local-captures/lb03-atlas-entry-20260918T185758Z/`.
That offline evidence alone did not prove live navigation or service behavior. Retained Tavern
evidence still does not prove real lighting transitions, Supply/Nova live entry, or other
buildings. Earlier Campaign/Supply results do not qualify this branch's service integration.

The admitted LB-03 continuation passed a zero-input Tavern binding preflight and a two-input
navigation-only Tavern round trip. Its supervised service soak then completed two eligible
Recruitment cycles with natural cooldown waiting. Native events record 15 inputs and exactly
four free recruits; each cycle persisted verified cooldown/count state and returned to Home.
No paid input, duplicate recruit, popup recovery, or unrelated flow ran.

The four-recruit safety ceiling stopped the soak after 772.8 seconds, before the requested
1,800-second deadline. The user accepted this repeated-cycle proof as LB-03 live closure;
it is not a completed 1,800-second prolonged soak. Cleanup left service and Recruitment disabled at generation 16, cleared the inspected LB-03
block through successful terminal projection, released service/runtime ownership, and preserved
the unresolved startup VIP record. Evidence:
`.local-captures/lb03-live-admission-20260918T224056406651Z/`.

