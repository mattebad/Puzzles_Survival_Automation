# Canonical execution backlog

## Implemented BlueStacks route portfolio

Reconciled November2 against the code and retained native evidence. All eight
routes below are **implemented** in the canonical service on the MR16 branch.
`IMPLEMENTED_LOCAL` in the detailed records means implemented repository/PR code,
including committed/pushed code; it does not mean uncommitted, merged or enabled.

| Route | Implementation | Proven BlueStacks behavior | Detailed backlog |
| --- | --- | --- | --- |
| Campaign AP | IMPLEMENTED_LOCAL | Configured1-15-9 drains affordable AP, returns Home, next check whole-completion+300seconds; actual consuming reset crossing proved. | [REC-R10/R11](docs/backlog/resources.md#rec-r11--campaign-ap-auto-battle-at-exact-configured-destinations) |
| Ultimate | IMPLEMENTED_LOCAL | One Flee and verified Home; DefeatContinue remains offline-proven. | [REC-D05](docs/backlog/daily.md#rec-d05--migrate-ultimate-daily-join-to-the-zero-resource-flee-route) |
| Nova | IMPLEMENTED_LOCAL | One free Praise per due pulse; seven new-day Praises, cooldown/attempt gating and Home. | [REC-D11](docs/backlog/daily.md#rec-d11--canonicalize-nova-to-one-free-praise-pulse) |
| Noah's Tavern | IMPLEMENTED_LOCAL | Independent Basic/Intermediate/Advanced maintenance; five actual Basic free recruits across reset with result/cooldown/Home. | [REC-D07](docs/backlog/daily.md#rec-d07--unify-daily-recruitment-and-three-tier-maintenance) |
| Supply Depot | IMPLEMENTED_LOCAL | Fresh Home to Depot, one free Hold exhausts9to0, then Home. | [REC-D10](docs/backlog/daily.md#rec-d10--exhaust-only-free-supply-depot-collections-and-reconcile-daily-progress) |
| Gear/Chip/Module enhancement | IMPLEMENTED_LOCAL | All three once in ONE Profile visit/Home; fresh23inputs/3Confirms, all EXP100to110 and stock minus1. | [REC-R03 through R05](docs/backlog/resources.md#rec-r03--gear-one-star-single-material-enhancement) |
| Bioenhancer | IMPLEMENTED_LOCAL | One Free Research, positive cooldown/result and Home. | [REC-D06](docs/backlog/daily.md#rec-d06--migrate-bioenhancer-to-one-free-research-action) |
| Personal Might | IMPLEMENTED_LOCAL | One rank-one Praise, positive used-control/effect and Home, distinct from Nova. | [REC-D09](docs/backlog/daily.md#rec-d09--implement-personal-might-praise-separately-from-nova) |

Native acceptance is scoped to the actual recorded sources in the
[November2 report](docs/bluestacks-route-status-20261102.md): fresh Enhancement at
`cfe449c`, full two-hour cadence at `3c222af`, and separately recorded reset/cold/
other-route receipts. Later shared OCR timeouts have their own offline and affected-
family/Home proof; this table does not assert a new whole-head rerun of every route.
The reviewed code head `7d75b05` passed both complete CI87 jobs. Any later publication
head still requires its own CI; old green is not new-head validation.

Several broader tickets remain `PARTIAL_LOCAL` because their selected-Daily point/
completion attribution, other Campaign destinations, fresh Advanced recruitment
acceptance or hosted/NAS scope is unfinished. Each now names **Route implementation**
and **Remaining ticket scope** separately. Gear/Chip/Module and standalone Nova
implementation records are `IMPLEMENTED_LOCAL`. The [O10 development ledger](docs/backlog/operations.md#implemented-bluestacks-development-portfolio-november-2)
records this portfolio separately from future hosted acceptance. All nine controls
stay OFF; none of these records authorizes a live run or closes the broader backlog.

## Astra pre-merge corrections, November 2

Implemented and offline-proven: bound Enhancement OCR calls and whole observations, atomically replace
mutable family progress, explicitly run the five omitted route/recovery modules in
Windows/Linux CI, and reconcile the service guide. Fault tests exercise a real hung
child process, timeout accounting before/after confirmation, cancellation, failed
flush/replace and process termination before publication.

Live accepted at `cfe449c`: fresh continuous Gear/Chip/Module in one Profile visit,
23 inputs/three Confirms/Home. Each EXP100 to110; stocks9553 to9552,11526 to11525,
8290 to8289. Independent audit checks453 unchanged sources,34 prior family files,
117 historical evidence files,87 PNGs/83 capture links, every due/ordinal and the
other eight flow rows. Audit:
`.local-orchestrator/logs/astra-corrections-fresh-continuous-independent-audit-20261102.json`.

The first attempt stopped13inputs/one Gear Confirm at Chip1/11527 OCR confidence0.
Original evidence remains. A bounded luminance-preserving corroboration requires
three independent modes to agree with the original complete line; any competing
valid fraction still denies. Existing negatives and the actual failure fixture pass.
Independent Gear proof, two-navigation/zero-Confirm Home and exact inspection
preceded SAME-request15input/two-Confirm Chip/Module completion, explicitly composite.
That request is consumed and separate from the fresh continuous proof.

Local checks:104 route/recovery,113 shared Home/VIP/Nova,81 native/service cases,
then21 final context/fault and6 Module-context cases plus the new conflict negatives.
Counts overlap; full discovery was not run. Actual new-head CI remains
`evidence_required` until BOTH complete Windows/Linux jobs match the PR head in
`.local-validation/pr16-astra-corrections-current-head-ci-20261102.json` and
[PR16 checks](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16/checks).

CI84 failed on both platforms because one retained replay OCR stub lacked the new
`timeout` argument. The stub now requires a positive timeout at most five seconds;
crop/configuration/modal assertions are preserved. All10 replay cases and the exact
327-case deterministic check selection passed locally after repair. Runtime code
and the accepted `cfe449c` live scope are unchanged. Completed-job logs/receipt:
`.local-validation/pr16-ci84-failure-20261102.json`; a new-head CI pass is still required.

CI85 completed Linux successfully; Windows exposed raw-versus-resolved temporary
path matching in the newly selected category-resume fixture. Its lookup now uses
canonical session paths on both sides. A verifier-level equivalent-path regression
fails with the old lookup and passes with the repair; the exact94-case boundary
group passes locally, preserving source/effect/fence negatives. Runtime is unchanged.
Receipt: `.local-validation/pr16-ci85-final-jobs-20261102.json`. New-head CI is required.

CI86 again passed Linux; Windows then exposed the shared fixture still emitting
`RUNNER~1` paths while captures resolve to `runneradmin`. Normalize the fixture root
once at creation, retaining exact path/hash assertions. The real Windows8.3 alias
failure reproduces locally before this change; all108 replay/boundary cases pass
with actual short-alias temporary paths afterward. No runtime change or game input.
Receipt: `.local-validation/pr16-ci86-final-jobs-20261102.json`.

Deferred: repeated historical Enhancement replay/admission optimization; preserve
native replay, claims and effect fences when designing that change. CI duration and
ordinary duplicate invocations remain under
[issue 17](https://github.com/mattebad/Puzzles_Survival_Automation/issues/17).
The inherited synthetic test
`DirectCommanderRouteTests.test_unknown_use_successor_stays_evidence_required_and_reconciles`
fails at `CURRENT_RUN_MODAL_WITNESS_UNPROVEN` on unchanged `f96fc4b` as well as the
correction branch. Rebuild its causal fixture in a separate test-maintenance pass;
do not weaken current native witness requirements. Baseline log:
`.local-validation/astra-corrections-inherited-fixture-baseline-f96-20261102.log`.

## BlueStacks reliability validation

The [November 2 report](docs/bluestacks-route-status-20261102.md) records the
accepted portfolio, exact source scopes and retained failures. Earlier Enhancement
runtime `044ecb9` passed fresh continuous Gear â†’ Chip â†’ Module in one Profile visit:
23 inputs/three Confirms/Home, each stockâˆ’1 and EXP80â†’90. Independent replay checked
443 unchanged source files, 32 unchanged prior family records, 87 screenshots and
82 native capture links plus the initial source. An extra Gear tab selection was
needed because Profile reopened on Module. No retained composition was used.

The earlier recovered request remains separate composite proof: Gear completed
before a Chip selected-fraction stop, then safe two-input/zero-Confirm Home recovery
and exact canonical inspection preceded same-request Chip/Module completion.
Gear was retained, not repeated. The failed run and every original receipt remain.
The final OCR changes normalize the denominator to grayscale and permit a confident
complete selected-fraction line only when word modes offer no competing valid
fraction; original agreement and all quantity/stock/checkmark/causal gates remain.

The `3c222af` two-hour cadence retains its exact source: 7,200.333 seconds, 29 reports,
100 inputs/15 confirmed actions, every terminal Home independently replayed. It
completed five remaining Nova Praises, four remaining Basic recruits, the earlier
22-input family, one Personal Might Praise and two Campaign wins. Campaign's 18
reports comprise two wins/28 AP/29 inputs and 16 zero-input low-AP checks; every due
is exactly whole-completion +300 seconds. Already-completed Supply/Bio/Ultimate
stayed due-gated. The later shared OCR time limits and Enhancement persistence/
recognition changes have the affected-route proof above; no new whole-head two-hour
rerun is inferred.

Five actual Basic free recruits completed in the continuing reset client, each
result/cooldown/Home verified. Enabled Free Recruit 1x overrode a stale zero counter;
only actual transitions committed uses. Independent Intermediate24h/Advanced48h
deadlines were preserved; a timer becoming due later does not imply every tier is
exhausted or extend the bounded window. Fresh Supply completed Home â†’ Depot â†’ one
Hold, attempts9â†’0 â†’ Home, four inputs, on the final unchanged Supply recognition path.

The actual continuous Campaign reset drain entered three native stages before
November2 00UTC and five after: eight wins/112 AP/48 inputs/Home. Its supplement
checks63 unchanged critical code paths at the earlier recorded revision,239 preserved PNG hashes and actual Core
policy-authorized immediate-input/Stage/Lineup links. Fresh process/restart tests
proved zero-work daily guards and two consecutive guarded cold/sharedScarlett/Home
passes with unchanged flow/due rows. The first cold launch had a genuine native
Unity SIGSEGV; its cause remains unproved, no automatic retry policy was added.
Historical Play Games causality is unproved; account states remain manual-only.
Ultimate Defeat/Continue was not naturally encountered and remains offline-proven.

107 Tavern,47 Supply and29 original native quantity/context cases passed locally;
the new actual Chip positive/negative case passed separately. The two new Supply
failure frames passed eight fresh-process repetitions (16 cases). CI78 passed
Windows but caught the actual Linux denominator failure; diagnostic CI79/80 failures
are retained. Temporary diagnostics were removed. Actual final-head Windows/Linux
CI is authoritative in [PR16 checks](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16/checks)
and the matching new receipt above. The historical CI83/f96fc4b receipt remains
`.local-validation/pr16-final-current-head-ci-20261102.json`. Older green is not
final-head validation. CI speed optimization is deferred to [issue17](https://github.com/mattebad/Puzzles_Survival_Automation/issues/17)
and excluded from this goal.
CI82 Windows caught Supply OCR deadlines before text; parentOMP1 now matches
live/local validation. Five native fixtures passed eight fresh processes/40cases
without changing runtime,deadlines or assertions. Exact hosted contention cause
is unproved; final-head CI remains authoritative.

All nine flow/service controls remain OFF, no active/orphan/input/effect owner and
leases released. Every daily due/ordinal and all other flow rows were preserved
through the manual goal iterations. The consumed November1 extra request was not
reused; current standing iterative-testing authorization was explicitly recorded
by the canonical controller. PR16 remains draft/unmerged; no permanent scheduling.
This portfolio does not close the74 broader records below. `CURRENT_HANDOFF.md`
records volatile operator state; historical receipts never grant live authority.

## Historical acceptance, October31 and earlier

These dated rows preserve what remained at that time; they are not the current
implementation backlog. The current portfolio and November2 report above supersede
their pending reset/family labels without rewriting the historical receipts.

| Route | Retained acceptance | October31 reset status / remaining work |
| --- | --- | --- |
| Nova | October 31: all 7 free Praises confirmed, with Home after each run. | Complete for reset; no repeated daily actions. |
| Campaign AP | October31 current numeric-agreement reader: uninterrupted46+1-42=5,3wins/24inputs/Home. Latest repaired-source drain19+1-14=6,1win/13inputs/Home; all entry actions confirmed. | Full affordable drain, then300seconds after completion. Lost-localization camera fix passes25focused checks; latest live pass used existing chapter anchors, so the new fallback remains offline-proven. Fresh120-AP uninterrupted drain is additional coverage. |
| Ultimate Challenge | October 31: one Flee, 9 inputs and Home; complete for reset. | Next real 00 UTC reset; same-reset completion is preserved. |
| Supply Depot | October 31: 9 to 0 free attempts through one Hold, 7 inputs and Home. | Next real 00 UTC reset; no paid follow-up. |
| Noah's Tavern | October 31: all 5 Basic free recruits, each result/cooldown and Home verified; persisted count 5, remaining 0. Intermediate and Advanced deadlines preserved. | Basic resets at 00 UTC; Intermediate and Advanced retain their independent 24-hour and 48-hour timers. Client refresh across the next reset remains evidence_required. Earlier zero observations did not persist five uses; no timer or quota edits. |
| Enhancement | October31: Gear,Chip,Module eachonce in one physical Profile visit,22inputs/3Confirms and Home. All3source/stock/EXP/action proofs independently replayed; canonical completion used0newinputs/effects. | Proof is composite across a repaired Chip-modal stop. A fully uninterrupted native all-three attempt remains additional coverage at the next real reset; do not repeat accepted categories. |
| Bioenhancer | October31:1actual Free Research,5inputs including1known startup Back, observed20:00:53cooldown and Home; canonical due preserved at November1 00UTC. Actual prior00UTC admission rollover safely deferred0/0. | Full free-button label and ready-screen/Home recovery are live-accepted. Additional calibrated camera waypoint passed27focused checks; latest live entry needed only one ordinary pan, so that extra waypoint remains offline-proven. |
| Personal Might | October 31: one actual Praise reconciled from the original gold-to-gray transition and fresh disabled state, then 2 Back actions/Home. Canonical open-More resume used 4 navigation inputs, zero Praise and returned Home. | Complete for reset. Initial 57 focused checks and later 23 caption/resume checks passed. The original wrapper failed on a root handoff update mid-session; that failure remains separate from native proof and the successful canonical run. |

The latest October 31 frozen source completed 1,200.057 seconds of serial operation:
8 completed reports, 22 inputs, 2 remaining Nova Praises, 2 remaining Basic recruits and
4 zero-input Campaign checks, every terminal Home. Already completed daily routes
stayed reset-gated; all controls were restored OFF with no active/orphan run or
Core/resource block. See the [full status report](docs/bluestacks-route-status-20261031.md)
and `.local-orchestrator/logs/current-source-all8-1200-cadence-final-audit-20261031.json`.

The October30 source completed a7200.337-second serial cadence:21reports,2Campaign
wins,19low-AP checks,24inputs,159verified capture hashes and exact completion+300.
That is retained acceptance for its frozen source, not a full-duration acceptance
for subsequent October31 repairs. See
`.local-orchestrator/logs/current-source-full-7200-cadence-audit-20261030.json`.
The new Campaign drain is audited in
`.local-orchestrator/logs/current-ap-agreement-full-drain-live-audit-20261031.json`.

Cold process restart was observed twice with verified process exit, one launch,
known startup recovery and Home. The corrected command matches the measured icon's
MAIN/LAUNCHER/0x10000000 intent fields. It still originates from Android shell;
the manual icon originates from `com.uncube.launcher3`. The successful restart
followed the user's manual Play Games cancellation, so it does not establish why
that prompt appeared. A second cold restart reached Home without a new manual Cancel. Launcher causality remains `evidence_required`. Normal
service startup preserves a foreground game. Login, Play Games setup, CAPTCHA
and unknown manual-only states stop for the user.

On October31, the observed crossing was only the pre-native Bio admission boundary,20.758ms before
00UTC. The runner was not entered, no effect was attempted, and a new due reset was
projected. At that time a consuming native crossing remained unproved. The actual November2
Campaign crossing above supplies that later live evidence; synthetic tests do not.

## Reconciled recovery records and remaining work

The 74 stable ticket IDs have been reviewed against the local kernel and retained route evidence.
Overlapping records state `IMPLEMENTED_LOCAL` or `PARTIAL_LOCAL`, with a dated
explanation of what exists and what their broader acceptance still requires. The remaining records
keep their explicit future dependency, policy or native gates. No ticket was marked fully closed,
merged, deployed or enabled merely because a standalone route passed.

Generic due scheduling is implemented. Aggregate Daily claims, milestone chests, observed Daily
point attribution, Alliance Help, training, gathering, shops, broader World work and hosted
acceptance remain separate work. The code snapshot is committed locally on
`codex/bluestacks-route-reliability`; [draft PR #16](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16)
is published. For the agreed BlueStacks scope, actual latest-head CI and formal review precede merge;
this does not require closing unrelated Daily/World/hosted tickets.
These Markdown records are not a runtime queue or authority.

Read the [recovery execution guide](docs/backlog/execution-guide.md) before assigning work, then read
the complete linked ticket and the [proportionate planning contract](docs/backlog-task-contract.md).

- [Foundation tickets REC-F01ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“REC-F17](docs/backlog/foundation.md)
- [Daily tickets REC-D01ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“REC-D12](docs/backlog/daily.md)
- [Resource and policy tickets REC-R01ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“REC-R19 and REC-P01ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“REC-P12](docs/backlog/resources.md)
- [Operations tickets REC-O01ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã¢â‚¬Å“REC-O14](docs/backlog/operations.md)

The linked records distinguish local implementation, code merged, native evidence,
scheduler acceptance, and explicit enablement. BlueStacks remains the development environment;
final production is NAS/Unraid-hosted. No live readiness is claimed for these future records. Runtime launchers,
controls, `ResourceEffectAuthority`, leases/fencing, manual-only states, and live gates remain
unchanged and authoritative where they already apply.

## Historical Atlas and Recruitment integration baseline

This subsection describes the earlier branch baseline. Current implementation and
acceptance are recorded in the portfolio and detailed November2 ticket notes above.

The `refactor/lean-bot-backlog` implementation adds Atlas-defined Home building entry and the
executor-bound Windows/BlueStacks Recruitment slice. Atlas Tavern entry, repeated free-recruit
operation, cooldown persistence, and verified Home return have live evidence. One naturally
occurring exact VIP points popup was dismissed and resumed from Home; Tavern/non-Home and
post-consumption popup interruption remain `evidence_required`.

This implementation does not register or enable Recruitment in production. The canonical
Recruitment selector remains non-consuming unless the explicitly configured supervised service
installs `RecruitmentExecutionHandler` behind the existing claim and dispatch fences. Legacy
LB-04 through LB-08 are not implied complete by this integration.

## Historical boundary

The [legacy backlog archive](docs/archive/backlog-legacy.md) preserves the original 148 third-level
records and IDs byte-for-byte from the pre-cleanup root backlog. It is historical, not a second
current planning authority. Existing legacy queue/context tooling reads that explicit archive path;
its derived index remains a 32-record compatibility subset and is not discovery for these 74 tickets.
Historical statuses, evidence, and no-retry conclusions are not promoted by this index.

See [`docs/archive/README.md`](docs/archive/README.md) for archive scope and [`docs/archive/governance-simplification-plan.md`](docs/archive/governance-simplification-plan.md)
for the historical migration proposal. Current architecture is in [the service guide](docs/automation-service.md). `CURRENT_HANDOFF.md` remains the volatile
operational handoff; it does not activate a linked recovery ticket.
