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
| Ultimate | Four inputs reached battle, but generic popup geometry rejected the gem grid. No Exit or Flee was sent. The controller stopped and restored every control OFF. | Repair `e8419c0` passes the native regression and focused checks; the existing active-battle continuation and a fresh full Home-entry pass still require live proof. |
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
the two reported cases passed three repetitions each. Windows Python 3.11 CI on
repair `e8419c0` is still pending; a prior green run does not override run 57.

The Ultimate repair passed 17 focused native/visual/lineup checks with normal
temporary-directory access. A separate baseline using the original committed
popup function reproduces two stale Home-fixture failures; they were not
weakened or counted as passes. The sandbox's earlier temporary-directory
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
