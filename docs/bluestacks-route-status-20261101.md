# BlueStacks acceptance, November 1 UTC

This supplements the [October 31 report](bluestacks-route-status-20261031.md).
Implemented code, offline checks and live acceptance are different evidence.
PR [#16](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16) remains
draft and unmerged. Permanent scheduling remains disabled. Only explicitly
authorized bounded controllers temporarily enable selected routes.

## Current acceptance

| Check | Observed result | Remaining limit |
| --- | --- | --- |
| Supply Depot | Source `d41af83`: recognized radial to facility, 9 free attempts to 0 through exactly one Hold, 3 inputs, verified Home and disabled cleanup. | Earlier Home entry and drawer recovery stopped across repairs. A fresh uninterrupted Home-entry pass on the final crop source requires the next actual reset. |
| Personal Might | Source `122ff13`: uninterrupted 6 inputs, one committed Praise, 3 independently replayed disabled/gray captures, Home. | The first immediate post-input frame still showed ready; the route waited for the actual successor without a second Praise. |
| Enhancement | Gear, Chip and Module each consumed once in one physical Profile visit, with final Home and independent family replay. Original attempt: 13 inputs/1 Gear Confirm. Resume: 15 inputs/2 Confirms, retaining Gear. | This is composite acceptance. An uninterrupted all-three run remains `evidence_required` at the next actual reset. |
| Cold restart | Source `122ff13`: one guarded stop, process-exit check passed, one checked MAIN/LAUNCHER/NEW_TASK launch, Home, zero game inputs and no human intervention. | All nine flow rows and their due facts were unchanged. This proves this cached account state, not historical Play Games prompt causality. |
| Campaign and other due routes | Cohort `fd5b6482`: Campaign 120 + 1 regenerated - 112 spent = 9 AP, 8 wins/8 committed AP effects, 50 inputs and Home; next due exactly completion + 300 seconds. Nova used one free Praise, Tavern used one Advanced and one Basic free recruit, and Bioenhancer used one free Research; each returned Home. | This is not a completed two-hour cadence. The cohort stopped after 1,030.094 seconds on Ultimate. Nova has 6 free Praises and Tavern has 4 Basic recruits remaining. |
| Ultimate | Four inputs reached battle, then a separate continuation sent one Exit and exactly one Flee without repeating Challenge. The warning closed to a native Defeat overlay. | Current Home is now verified by zero-input adoption after the user restart and one Scarlett Back. This is composite acceptance; fresh full Home entry and native Defeat/Continue remain unproved. No repeated Flee is allowed. |
| Native reset crossing | Pending November 2 at 00:00 UTC. | Requires a consuming Campaign route across the real boundary and continuous-client Tavern refresh. The earlier zero-input admission defer does not satisfy this. |

Supply's current-source consuming leg and Personal Might both completed through
the canonical service, with native accounting, resource-effect authority, claims,
leases and dispatch fences intact. No exhausted quota, cooldown, daily completion
or retained capture was edited to obtain another attempt.

## Repairs and the failures that exposed them

Supply's intermittent fixture failures were reproduced with `OCR_DEADLINE` on
large scene crops. Reordering the bands and defaulting the owned Tesseract worker
to one thread improved the checks but did not eliminate failures: CI run 54 still
failed on both operating systems. These failed runs remain evidence.

The final optimization locates a stable Details glyph to propose a smaller,
translation-relative OCR region. The glyph supplies no menu identity or click
target. Exact menu context, unique complete Claim text, the independent suitcase
and circle checks, and every target pixel's HUD clearance remain required.
The five-second OCR deadline is unchanged; the broad fallback remains for an
absent or unproven proposal.

A separate live stop was caused by an expanded Home event badge covering the
radial. The route now binds its down-chevron from current Home, sends one
navigation input and requires the collapsed up-chevron before continuing.
The collapsed rail is narrower. Other HUD icons remain visible after collapse.
They can obscure the lower Supply caption while the actual button is still
provable. That second caption no longer supplies navigation authority; facility
identity and the free Hold are independently checked afterward. Unknown or
covered button bodies still block. The failure reason now distinguishes an
unrecognized menu from a recognized menu with no actionable control.

Enhancement previously omitted the shared startup recovery entirely. It now
replays the bounded observed VIP → Scarlett → Home sequence in the same input
journal before entering Profile. A later Chip stop was a real OCR disagreement:
one mode read `1/11532`, while two read the slash as `4`. Measuring the complete
current glyph bounds and equal padding restores three-mode agreement without
changing the selection quantity or inventory checks. A resumed selected panel
unwinds through measured exits and rebuilds fresh equipped-item and quantity
witnesses; completed Gear is retained rather than repeated.

Windows CI also exposed a test that measured final executor/SQLite cleanup
against the OCR callback deadline. The strict deadline assertion now measures
the actual recognition return. Dead worker/descendant, zero transport, blocked
run and released-lease assertions remain. Eight focused repetitions passed;
the runtime deadline and cleanup reserve were not changed.

The next live cohort exposed an unrelated Ultimate recognition failure. The
generic Hough detector paired unrelated gem-grid lines into fictional popup
rectangles. Battle recognition now requires real horizontal panel borders and
also checks closed panel contours, so the grid alone does not block Exit.
Actual panels, the Flee warning, missing board and missing Exit still deny a
target. Home and other actionable states retain their previous popup policy.
The exact failed native frame and provenance accompany four regression tests.
Ten retained successors independently prove that the original Lineup Challenge
reached battle; no retained evidence grants input authority or rewrites the
failed receipt. Continuation must freshly recognize the current battle.

The subsequent live continuation sent one Exit and reached the exact Flee
warning. Its OCR, colors and modal checks passed, but Hough combined canvas
edges with unrelated scene lines. A canvas-specific correction passed its
limited offline cases, then a zero-input live attempt exposed the defeat page
underneath the still-open dialog. That failure is preserved.

The final warning recognizer checks the foreground dialog directly: its modal
geometry, high-confidence Warning title, failure text, unique red/gold controls
and literal Fight/Flee labels. The native battle and defeat backgrounds produce
the same Flee target. Roughly 150 lines of scene-rectangle filtering/clustering
and the associated shape-only assertions were retired. Tests now reject an
actual unknown popup covering the dialog, missing title/text/controls and a gold
Buy button. All 12 focused cases passed. Claims, reset guard, source freshness,
resource authority and successor verification are unchanged. This remains
live-proven only for the single Flee dismissal: its successor is Defeat, and terminal Home remains pending. The failed receipt is retained. A known Defeat Continue selector and post-Flee Home-only recovery were added; the new binder never supplies Buy Now or another Flee. Twenty focused cases passed. The user then restarted BlueStacks. Recovery-only stopped with zero game inputs before and after an owned warm launch, first because P&S was not foreground and then because Scarlett lacked a shared recovery owner.

## Validation and retained evidence

The crop revision passed 48 focused Supply checks and eight consecutive groups
of three native tests locally. CI repeats those three tests eight times on both
Linux and Windows. On `122ff136eb551d9dc6df6ab43f8e529edeff086f`, both full
operating-system jobs passed, including the repetition steps.
[CI run 56](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41262958608)
is the source of those claims, not the earlier passing runs.

Latest documentation-head [CI run 57](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41264115871)
passed Linux and both Supply repetition steps, but Windows exposed two service
proof errors in instant fake-device tests. A frozen native clock reproduced
the missing Campaign camera-only proof and Ultimate startup chronology failure.
The test harnesses now advance native timestamps while keeping the remaining
real freshness consumers in the same time window. Production chronology and
freshness checks are unchanged. The two affected modules passed 44 cases, and
the two reported cases passed three repetitions each. Both full operating-system
jobs, including Windows Python 3.11, passed on repair `e8419c0` in
[CI run 58](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41266335664).
The foreground warning correction also passed both full jobs in [CI run 61](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41268509505). The later Defeat recovery revision has its own CI pending; run 57 remains a retained failure rather than being overwritten by a passing rerun.

The Ultimate repair passed 17 focused native/visual/lineup checks with normal
temporary-directory access. A separate baseline using the original committed
popup function reproduces two real larger-HUD Home recognition failures. The sidebar crops missed their visible labels; these fixtures were kept. A second bounded label layout now passes focused offline checks, preserving exact tokens, two labels within one layout and independent header/footer/popup gates. Eight Home and existing post-Flee wrapper checks passed; current-source live proof remains pending. The sandbox's earlier temporary-directory
permission errors are retained separately from the passing rerun.

Enhancement startup checks passed 29 focused cases. Native selection/material
checks and causal/family/service replay checks passed their focused reruns.
Packages overlap and are not an aggregate unique-test count. The pre-existing
legacy `tests.test_flow_delivery_enhancement` baseline still has 5 failures and
7 errors in 48 cases; its old fake facts/reset identities were not weakened to
manufacture a pass. Its baseline log is retained separately.

Raw evidence is retained locally, outside the published source tree:

| Receipt | Local reference |
| --- | --- |
| Enhancement composite audit | `.local-orchestrator/logs/enhancement-composite-resume-live-audit-20261101.json` |
| Supply free-Hold audit | `.local-orchestrator/logs/supply-safe-button-free-hold-live-audit-20261101.json` |
| Personal Might uninterrupted audit | `.local-orchestrator/logs/personal-might-uninterrupted-live-audit-20261101.json` |
| Cold restart/due-state audit | `.local-orchestrator/logs/current-source-cold-restart-live-audit-20261101.json` |
| First current-cohort Campaign drain audit | `.local-orchestrator/logs/current-cohort-first-campaign-drain-audit-20261101.json` |
| Failed cohort/disabled cleanup audit | `.local-orchestrator/logs/all8-cohort-stopped-ultimate-live-audit-20261101.json` |
| Ultimate successor inspection | `.local-orchestrator/logs/ultimate-failed-lineup-successor-inspection-20261101.json` |
| One-Exit warning stop audit | `.local-orchestrator/logs/ultimate-exit-warning-stop-live-audit-20261101.json` |
| Warning successor inspection | `.local-orchestrator/logs/ultimate-exit-warning-successor-inspection-20261101.json` |
| Zero-input defeat-background warning stop | `.local-orchestrator/logs/ultimate-warning-over-defeat-zero-input-stop-audit-20261101.json` |
| Single-Flee/Defeat stop audit | `.local-orchestrator/logs/ultimate-flee-defeat-successor-stop-audit-20261101.json` |
| Post-user-restart cleanup/source audit | `.local-orchestrator/logs/ultimate-post-user-restart-pre-repair-audit-20261101.json` |
| Old Enhancement baseline | `.local-validation/remaining-enhancement-baseline-20261101.log` |
| Supply local repetitions | `.local-validation/supply-tight-crop-eight-repeats-20261101.log` |

The Enhancement audit verified 347 unchanged runtime-source hashes and 53 current
capture hashes. Personal Might verified 349 source hashes, including the new
Details assets, and 21 captures. Restart verified the same 349 sources and retained
10 captures. Supply verified 12 captures and its frozen source bindings; its audit
ran after a post-terminal offline edit began, so it explicitly records the frozen
committed blob and timestamps rather than falsely calling that working file
unchanged. The other 346 working source files still matched. There was no source
edit during that live attempt.

The failed eight-route cohort retained 298 PNGs, verified 275 event-capture
hashes and all 349 frozen source hashes, and released every owner/control.
Its first Campaign drain additionally cross-checks all 191 native captures and
eight confirmed 14-AP actions. The failed Ultimate report remains blocked with
zero Flee transports; it does not count as daily completion.

The actual failed UI frames and their provenance accompany the focused native
regressions. Historical failed receipts are not rewritten as successful ones.
Retry-breaker acknowledgment after inspected code repair used canonical state
APIs and retained the failed outcomes. It did not rearm resource quotas or alter
due dates.

Remaining scope is explicit: uninterrupted Enhancement and fresh Supply Home
entry after reset, Ultimate continuation and a fresh full Home-entry pass,
consuming native UTC crossing, continuous Tavern refresh, current-source cadence,
and any camera recovery branch not actually exercised.
Ultimate's accepted participation path is entry/Flee/Home; victory and independent
quest-credit attribution remain outside that proof.

The user explicitly requested that both Scarlett and VIP recovery apply across
routes. Both now have shared startup ownership, without flow allowlists. The
supported recovery workflow handles two distinct known surfaces within its input
budget, retains each result/action separately and recaptures before handing
control to the active route. Popup dismissal is not reported as Home proof. The
existing policy admits the retained successor only under the exact zero-cost VIP
Close contract; arbitrary successor contracts still deny input. Noah now calls
the shared contextual helper. At that revision native contextual helpers handled either single
surface and stopped if another followed; the later native cutover is recorded below.
This cutover is offline-proven and awaits its live retry.

The full shared startup suite passed 49 checks, session/service startup passed 16,
contextual safety passed 4 and the focused Noah group passed 12. Seven shared
executor and route-handoff checks passed in the root review. Two old integrated
Noah tests still fail with fake-runtime navigation `continuation mismatch`; both
failures were independently reproduced with committed original modules in memory.
They remain baseline failures, not passes. Logs are
`.local-validation/noah-integrated-original-baseline-20261101.log` and
`.local-validation/noah-return-original-baseline-20261101.log`.
Both full operating-system jobs passed on `eb0fce9` in
[CI run62](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41271866463).
The new shared-recovery/Home revision requires its own hosted CI.

The `d35f8a0` live recovery dismissed Scarlett with one safe Back and captured a
native Home source. It then stopped before child runtime startup: Ultimate's CLI
incorrectly required exactly 16 inputs rather than accepting the 15 remaining after
startup recovery. The CLI now accepts budgets 1 through 16; the upper ceiling and
runtime input fence remain unchanged. Two offline CLI boundary checks passed.
The adapter-error path also omitted that startup input from its outer failed
summary; its separate startup journal correctly retained 1. That failed receipt
was preserved, and the summary path now keeps each startup action/count before
re-raising the original error; four focused session checks passed. The audit
`.local-orchestrator/logs/ultimate-shared-scarlett-child-budget-stop-audit-20261101.json`
verifies 351 unchanged sources, 8 captures and disabled/released cleanup. No new Flee
or Challenge was sent. Current Home adoption subsequently completed on `8c36b5b` with zero new inputs.

The subsequent recovery-only run independently verified current Home and completed
for the reset, with zero new inputs and no Flee or Challenge. Its audit is
`.local-orchestrator/logs/ultimate-after-user-restart-composite-home-audit-20261101.json`:
351 unchanged sources, five current captures and the unchanged original failed
Flee receipt hash. All controls were OFF and owners released. Canonical Ultimate
was then unblocked through its state API with generation, failure count, due date
and reset unchanged; the separate unblock audit is retained. This is composite
acceptance after a human BlueStacks restart. It does not establish uninterrupted
native Defeat/Continue recovery or a completed two-hour cadence.

## Later cadence stop and repairs

The next requested two-hour cohort, `0feb88d6` on `69a3c51`, stopped after
421.137 seconds. Nova used one free Praise (6 inputs/Home), and Noah used one
free Intermediate plus one free Basic recruit (9 inputs/Home). Intermediate's
next eligibility is now 24 hours after this recruit, Advanced's existing 48-hour
deadline is unchanged, and Basic has three daily recruits remaining. Campaign
sent seven navigation inputs and no AP action, then stopped because Chapter 15's
projected center was exactly at x=700 while its visible medallion crossed into the
right HUD. Template/current text could not authorize a tap. This was not a
successful cadence. The audit
`.local-orchestrator/logs/current-cohort-campaign-before-ap-stop-audit-20261101.json`
verifies 351 unchanged runtime-source hashes, 71 captures and disabled/released
cleanup with no resource-effect blocks.

Repair `1ba790b` requests a bounded HUD-safe atlas pan when an unbound target is
near an edge and localization has supported anchors/residual. It grants no target
from projection alone. Existing fresh-source, progress and subsequent binding
checks remain. The native frame and its exact retained landmark geometry are
packaged for CI; three portable geometry/OCR/progress cases pass without skips.
ORB unavailability and the already observed template failure are isolated in that
portable case, so it is not full-atlas binding proof. The old full-atlas local
regressions remain separate.

[CI run65](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41273611877)
failed on a claimed service-startup fixture that supplied text bytes as a PNG.
The stricter shared helper correctly rejected it. The fixture now emits encoded
PNGs with matching digests and unique temporary paths; visual absence is stubbed
at the same semantic test seam as the existing VIP and route recognizers. Six
focused service checks passed. Production image validation was preserved.

Native shared two-popup sequencing and its consumer accounting/replay are now
implemented and offline-proven. No live operator overlapped these edits or tests.
Current-source live multi-surface behavior is not yet accepted.

## Shared native sequence cutover

All eight native route callers now use the common bounded sequence for two
distinct exact Scarlett/VIP surfaces. Each navigation input retains its proposal,
immediate-before, settled frame, target, key and reconciliation. A different known
popup can verify the preceding dismissal; only the final clear screen and the
active route's recognition permit onward action. Repeated identities, unknown
intermediates, exhausted budgets, stale captures and uncertain transports stop.
No global input budget or resource-action limit was increased. Enhancement's
separate VIP-to-Scarlett loop was removed.

Ultimate, Campaign and Enhancement independently replay the sequence. Review
closed reconciliation-order gaps, requires Enhancement startup to precede every
route/resource input, and verifies Campaign's actual point matches its measured
Close/Back target. New regressions reorder only journal events or mutate only the
point and require rejection. Noah preserves the failed-attempt lock while leaving
a zero-input unknown observation's slot unused. Identical intact-frame recognition
is reused only within one helper invocation; independent proof replay stays separate.

Focused consumer groups passed 58 and 44 cases; helper 16, Noah 12, terminal stack/drain
and Noah 14, and the corrected Campaign tamper case passed. Final Ultimate and
Enhancement reorder negatives passed. One newly added test initially tried to
capture after its lease store closed; production rejected it. Replay now runs
inside the existing held-lease seam, and the corrected case passed. The root review
passed 29 helper, Noah and claimed-startup cases in 14.246 seconds. Groups overlap
and do not form a unique total. The independent reviewer confirmed the reported
gaps closed. These remain offline results; live acceptance and final cadence are
pending. The inspected Campaign block was cleared through the state API with its
failure, generation, due and resource facts preserved.

## Current Campaign recovery and Windows path repair

The first all-eight attempt on 076c07e stopped after 12 seconds with zero inputs:
Nova refused the Campaign map left by the earlier failed run. Its startup context
fence was preserved. Campaign alone then recovered through Home, captured fresh
AP and completed 38+1-28=11AP with two victories,18 inputs and verified Home. The
audit `.local-orchestrator/logs/campaign-current-source-recovery-drain-home-audit-20261101.json`
checks 416 unchanged code/asset/local-atlas hashes, 75 captures, both confirmed
14-AP canonical action rows and their exact stage-entry/lineup continuation links,
independently reread Home/AP 11, and completion+300 scheduling. All controls and
owners were released. Nova's zero-input context block was then unblocked through
the state API without changing due, failure or quota facts.

This proves current-source Campaign recovery and a full affordable drain. It
used three existing atlas-directed pans and a fresh target binding; the new
unbound HUD-edge branch did not execute and remains offline-proven. This bounded
single route is not a completed two-hour cadence.

[CI68](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41276240130)
failed 11 Windows service cases out of 205 because equivalent 8.3 and long path
spellings compared as different captures, or could not be made relative to the
same session. Actual `GetShortPathNameW` aliases reproduced four pre-fix defects,
including the exact Ultimate/Enhancement failures and a same-file alias wrongly
accepted as a fresh capture. The narrow production fix resolves both identity
operands and relative-path roots. It retains image, digest, chronology, foreign
path and in-session symlink checks; trusted parents above the session remain
allowed. No clock/freshness threshold was weakened. The failure excerpt is
`.local-validation/ci68-windows-path-alias-failure-20261101.log`.

The alias/affected-module suite passed 61 checks, followed by 20 helper checks after
final boundary narrowing; real alias cases did not skip locally. Both full jobs
had passed on 1ba790b in [CI67](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41274799852).
The path repair needs its own latest-head CI and current-source cadence.
