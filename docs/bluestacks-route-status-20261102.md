# BlueStacks acceptance, November 2 UTC

The accepted runtime is `3c222af`. PR [#16](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16)
remains draft and unmerged; permanent scheduling is disabled. Actual current-head
CI is authoritative in [PR checks](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16/checks)
and `.local-validation/pr16-final-current-head-ci-20261102.json`. Historical green
runs do not validate a newer head.

## Live results

| Check | Observed result |
| --- | --- |
| Final two-hour cadence | 7,200.333 seconds, 29 completed reports, 100 inputs and 15 confirmed actions. Every terminal Home frame was independently replayed. Five remaining Nova Praises, four remaining Basic recruits, uninterrupted Enhancement, Personal Might and two Campaign wins completed. Already-completed Bioenhancer, Supply and Ultimate stayed future-due. |
| Campaign cadence | 18 reports: two wins/28 AP/29 inputs and 16 zero-input low-AP checks. Every next due time is exactly 300 seconds after the entire drain or low-AP Home completion. Actual stage/Lineup/Core links were checked. |
| Consuming real reset | The same continuing drain entered three stages before November 2 00:00 UTC and five after it: eight wins/112 AP/48 inputs/Home, AP120 + one regenerated -112 = AP9. No launch, clock, quota or due-date changes manufactured the boundary. |
| Fresh Supply | Home â†’ Depot â†’ one Hold, free attempts 9â†’0 â†’ Home; four inputs. This was a fresh full route after the two retained zero-Hold recognition failures. Its final recognition code and execution path remain unchanged in the accepted runtime. |
| Tavern Basic | Five actual free recruits, each source/result/cooldown/Home verified. The first accepted run recorded count one; four later runs advanced it 2â†’3â†’4â†’5. The first native counter displayed zero while Free Recruit 1x was enabled. Tickets stayed 91â†’91 for that first verified free action. The earlier zero-recruit Home-only report is not acceptance. |
| Independent recruitment timers | Intermediate deadline `1793594260.4039137` (November 2 04:37 UTC) and Advanced deadline `1793672002.075106` (November 3 02:13 UTC) stayed unchanged across the reset and all Basic recruits. These are separate 24-hour/48-hour timers, not claims that every tier is exhausted. |
| Nova | The final cohort consumed the five remaining Praises, 5â†’4â†’3â†’2â†’1â†’0, each Home. Together with the two earlier new-day passes, all seven actual new-day Praises completed. |
| Enhancement | Uninterrupted Gear â†’ Chip â†’ Module in one Profile visit, 22 inputs/three Confirms/Home. Each category consumed one one-star material and gained 10 EXP, 60â†’70. Gear9557â†’9556, Chip11530â†’11529, Module8294â†’8293. Source/quantity/equipped-item witnesses and committed effects were independently replayed; no retained category composition was used. |
| Personal Might | Six inputs, one actual Praise, one confirmed committed action and Home. Independent replay checked the gold source, used/disabled successor, inability to bind a second Praise and terminal Home. |
| Ultimate / Bioenhancer | Earlier new-day ordinary runs completed eight inputs/one Flee/Home and four inputs/one Free Research/Home respectively. Their relevant implementations remain unchanged. Ultimate Defeat/Continue was not naturally encountered and remains offline-proven. No repeat Flee or research was forced. |
| Fresh bot process | Seven genuinely future-due completed daily routes, zero attempts/native startup/inputs/effects. Every due time, ordinal and last completion stayed unchanged; the entire unselected Campaign row was identical. This checks the bot process skip guard. |
| Current guarded cold restart | Two consecutive successful stop/verified-exit/one-launch tests reached the recognized Scarlett surface. Bootstrap game inputs were zero; shared recovery used one Back per test and independently verified Home. All nine flow/due rows remained unchanged. |

The final cadence audit checks 438 unchanged frozen source files, 430 PNGs,
366 capture references, 58 startup observations, all 29 independent Home terminals,
actual effect links and released cleanup:
`.local-orchestrator/logs/current-ea02-full-acceptance-independent-audit-20261102T043743891350Z.json`.
All nine flow/service controls were OFF, with no active/orphan run, input/effect
owner or unreleased Core/service lease. No permanent enablement occurred.

The actual midnight drain retains its original frozen-source scope; its cohort
stopped later at Supply and was not a full two-hour pass. The supplemental audit
rechecks eight real Core inputs and confirms that 63 relevant Campaign, scheduler,
state, Core, startup and Atlas source files are byte-identical in the final runtime:
`.local-orchestrator/logs/final-runtime-reset-path-equivalence-and-native-utc-stage-audit-20261102.json`.
It binds dispatch to the freshly authorized pre-input frame; preparation and
pre-input pixels legitimately differ in three entries. The later two-hour run
adds separate current-runtime cadence proof, not a relabeled midnight rerun.

The fresh-process audit is
`.local-orchestrator/logs/ea02-completed-daily-fresh-process-final-audit-20261102.json`.
It sent no game input or launch. The guarded cold tests and shared recovery are
separate, consuming no game resources. Native app restarts occurred only after
the continuous-client midnight and five-Basic-recruit acceptance had finished.

## Fixes and retained failures

Supply's real failures were a caption mixed with the neighboring HUD and an
absent circle proposal despite strong actual edge support. The tight caption
fallback keeps the complete Claim label; the second circle proposal is used only
when the original is absent, with tighter glyph centering and unchanged final
edge, safe-interior and HUD exclusions. Actual missing/clipped/ambiguous controls
remain denied. Fresh full-route audit:
`.local-orchestrator/logs/supply-fresh-full-home-caption-circle-live-audit-20261102T0058Z.json`.

Tavern now uses the visibly enabled zero-cost Free Recruit 1x control when the
native counter is stale at zero. Zero alone cannot invent five prior uses;
only the verified result/cooldown transition commits one action. Confirmed-use
limits, unknown-result stops and independent deadlines remain enforced. First
live audit:
`.local-orchestrator/logs/tavern-enabled-free-stale-zero-live-final-audit-20261102.json`.

The user-paused Enhancement attempt stopped after five navigation inputs and
zero Confirms. A later attempt stopped after four navigation inputs and zero
Confirms because sparse OCR/cubic scaling lost the `/9557` denominator. Line OCR
and linear scaling for that field corrected it while retaining confidence,
exact Total/value agreement, material/star, quantity-one and button checks.
Both failed receipts and every original reservation were preserved. Canonical
inspection acknowledgment changed no schedules, quotas or limits. The subsequent
22-input family above is the fresh uninterrupted consuming proof.

One cold-start attempt failed with a native Unity SIGSEGV; its stack includes
`libtcb.so` and `libil2cpp.so`. The game returned to the BlueStacks launcher before
readiness, with zero game inputs. This was retained as a failure, not Home or a
Play Games prompt. A separately guarded relaunch and shared Scarlett recovery
returned Home; two subsequent guarded cold starts then passed consecutively.
The native crash's underlying cause remains unproved. No automatic repeated-
launch policy or emulator setting change was introduced. Evidence:
`.local-captures/development-sessions/launch-game-20261102T035300225603Z/result.json`
and `.local-captures/development-sessions/launch-intent-20261102T035905459129Z/crash-log.txt`.
Historical Play Games causality remains unproved; account/login states remain
manual-only.

## Offline and CI coverage

107 focused Tavern cases, 47 Supply cases and 29 native quantity/selection-context
cases passed locally. Both new real Supply failure frames then passed eight
fresh-process repetitions (16 cases), including missing-caption/template denials.
The failed invocation using the wrong test class name is retained separately.

CI77 passed both complete Windows/Linux jobs on `ea02fa2`. Its explicit list
omitted the two new Supply failure frames and native quantity modules. The final
workflow adds those frames to the eight-iteration repeated binding step, includes
the full Supply button module and its negatives, and runs the Gear/Chip/Module
quantity modules alongside existing selection-context coverage on both systems.
The actual final-head receipt and PR checks determine whether this expanded CI
has completed successfully.

The [November 1 report](bluestacks-route-status-20261101.md) and older audits retain
their historical source scope. The consumed November 1 extra-run request is not
reused. Broader unaccepted backlog items are not promoted by this portfolio's
acceptance; the PR remains unmerged and runtime controls remain OFF.

## Post-acceptance quantity OCR compatibility

CI78 on `8162e6b` completed successfully on Windows but failed the newly included
Gear denominator screenshot on Linux. CI79/80 retained diagnostics showed identical
scaled pixels, Tesseract5.5.0 and byte-identical English models: color input produced
`1/9557` at zero confidence on Linux, while explicit grayscale produced `/9557` at
91 confidence. The model-drift and resize-difference hypotheses were disproved.

The candidate now converts only that denominator crop to grayscale before OCR.
All 29 existing native quantity/selection-context cases passed locally; confidence20,
exact stock/Total agreement, material/star, quantity-one and action gates are unchanged.
Diagnostic-only test code and its temporary duplicate workflow step were removed.
The final current-head Windows/Linux jobs must validate this correction. CI speed
optimization is deferred to [issue17](https://github.com/mattebad/Puzzles_Survival_Automation/issues/17),
explicitly outside this goal.

The two-hour cadence and consuming family above remain live proof at `3c222af`.
Fresh live acceptance of the changed denominator path is `evidence_required`, not
inferred from those receipts. The consumed November1 manual extra-run request cannot
be reused; further same-day manual consumption requires a distinct current request,
or this path can be exercised at its ordinary next-reset eligibility. No due dates,
quotas or controls were changed to manufacture eligibility.
