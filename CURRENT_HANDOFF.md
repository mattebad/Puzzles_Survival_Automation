<!-- CURRENT_HANDOFF_STATE_BEGIN -->
{
  "schema_version": 3,
  "branch": "feature/runtime-reliability-convergence",
  "head_binding": "commit-containing-this-handoff",
  "last_product_candidate_head": "commit-containing-this-handoff",
  "ahead_behind": {"source": "compute_from_git"},
  "attributable_dirty_paths": ["scripts/flow_delivery_campaign_bluestacks.py", "scripts/pnsctl.py", "tasks/flow_delivery_validation_profiles.json", "tests/test_flow_delivery_campaign_bluestacks.py", "CURRENT_HANDOFF.md", "docs/runtime-reliability-convergence-status.md"],

  "task_start_worktree": {"tracked_dirty_paths": ["AGENTS.md", "docs/flow-delivery-validation-policy.md", "tests/test_flow_delivery_workflow_policy.py"], "protected_untracked_paths": [".omp/", "Start-PnS-OMP.ps1", "Stop-PnS-OMP.ps1", ".local-captures/", ".local-orchestrator/"]},
  "protected_user_owned_paths": [".local-reference/", ".local-captures/", ".local-tools/", "evidence/"],
  "current_task_id": "campaign-ap-continuous-session-migration",
  "current_task_state": "completed_offline",
  "next_task_id": "troop-training-product-authority-migration",
  "next_task_activation_status": "awaiting_explicit_selection",
  "active_task_or_flow": "none",
  "active_delivery_stage": "campaign_ap_continuous_session_accepted_offline",

  "active_execution_manifest_path": null,
  "development_lease_state": "absent",
  "runtime_ownership_state": "none",
  "writable_agent_state": "none",
  "unresolved_action_state": "clear",
  "latest_focused_validation_result": "Campaign AP continuous-session adapter and affected Campaign suites passed 50 focused-profile tests; receipt 2d6453eae4a4837edae3a7197a4b1b5c978fde0727045f34caac19373727f9f3; no runtime input.",
  "latest_architecture_validation_result": "Campaign AP architecture profile passed 44 tests with receipt 15ba02c6907b3ed2c1580a128d749b83a52882b5887b5782fac0602e6e5f7387; no runtime input.",
  "latest_full_suite_result": "Manual opt-in only; not run.",
  "current_live_attempt_state": "not authorized and not attempted; Campaign AP session migration used zero emulator/ADB/BlueStacks observation and zero runtime input",
  "current_evidence_or_session_reference": "No current Campaign AP production-controller continuous proof is being claimed; retained mechanics remain non-authorizing",
  "last_safe_completed_step": "Bound the unchanged Campaign AP controller to one flow-owned DevelopmentSession with typed initial observation, retained transport accounting, exact AP/result/Home gates, one read-only trace, and sessionless dispatch denial.",
  "exact_next_permitted_action": "Perform Troop Training product authority migration only; do not combine Troop Training session behavior or any runtime action.",
  "current_blocker": "Native production-controller Campaign AP proof remains required; registration and scheduling stay disabled.",
  "prohibited_repeated_action": "Do not dispatch Campaign AP, use emulator/ADB/BlueStacks, combine Troop Training product and session migrations, begin Stage 8, registration/scheduler work, or select World work before Troop Training product and session tasks.",

  "stage_revision": "campaign-ap-continuous-session-migration-r1",
  "stage_type": "medium_continuous_session_migration",
  "product_precondition": "Campaign AP r9 product authority and direct contract binding are current; unchanged controller was available.",
  "failure_class": "evidence_required for native production-controller proof; no offline local defect",
  "budgets": {"stage_revisions_used": 1, "managed_turns_used": 1, "live_attempts_used": 0, "runtime_inputs_used": 0},
  "registration_and_scheduler": {"production_registration": "NOT_REGISTERED", "scheduler_enabled": false, "active_runtime": "local BlueStacks only"},
  "journals_and_lease": {"development_lease_status": "absent", "active_prepared_input_sent_unresolved_action_ids": [], "historical_journals": "immutable and non-authorizing"},
  "evidence": {"evidence_requirement": "Native Campaign AP positive stage/cost/result/AP-delta/Home proof remains required before live admission; current continuous proof is evidence_required", "monitoring_issue": "MONITOR-UNOBSERVED-EFFECT-RECONCILIATION", "do_not_recursively_inspect_parent_evidence_tree": true},
  "control_owner": "sol_parent",
  "control_parent_conversation_id": "current-task",
  "deferred_independent_review": "Sol 5.6 PR review pending; self-review only; no independent review claimed.",
  "stage_7_ordered_plan": [
    "1 Daily Milestone Claim continuous-session migration or evidence-blocked disposition",
    "2 Campaign AP product authority",
    "3 Campaign AP continuous-session migration",
    "4 Troop Training product authority",
    "5 Troop Training continuous-session migration",
    "6 World product authority without rebuilding accepted Stage 6 session",
    "7 Gathering product authority",
    "8 Gathering route/session migration",
    "9 Zombie Lair product authority and offline disposition",
    "10 Nano Material product authority and maintenance/session migration",
    "11 Nanoweapon product authority and adapter/session repair",
    "12 Ruins Shop product authority and route/session disposition",
    "13 Rare Earth Shop product authority and route disposition",
    "14 Alliance Shop product authority and route disposition",
    "15 Box purchase product decision, block, or retirement",
    "16 Hero Upgrade product authority and route disposition",
    "17 Hero Duel product authority and offline/combat-blocked disposition",
    "18 VIP popup helper authority and route disposition",
    "19 Ruins Challenge ownership selection or retirement",
    "20 Personal Might Praise/legacy Claim migration or retirement",
    "21 Remaining catalog and active-plan tickets with one durable disposition each",
    "22 Legacy retirement and final Stage 7 closure"
  ],
  "next_three_atomic_tasks": [
    "Troop Training product authority: add typed record, revision-bound contract, catalog/generated authority mapping, and focused tests only.",
    "Troop Training continuous-session migration: bind existing queue/slot controller to one session only after product authority is current.",
    "World product authority: add typed record and revision-bound authority without rebuilding the accepted Stage 6 session."
  ]
}
<!-- CURRENT_HANDOFF_STATE_END -->

# Current handoff

## Stage 7 Recruitment product-record migration

Heavy revision `recruitment-product-record-migration-r1`, manifest SHA-256
`64aeef2aa09cc3a9113bcdd5585749e7e04b0f0c4e357c71e0b3b2890dc60a25`,
adds r8 record `noahs_tavern_recruitment-v1`, digest
`dfdf98ff9705882aa163450668b8c513d19fcf89904f45778d97ac63e085717e`;
authority digest is
`3b64ef5caf8755449bed680c4555117f658db1cf2c50c9df1d17c3019d5bf5c2`.
It separates Basic five/reset Daily ownership (600-second windows) from
independent zero-cost Basic/Int./Advanced maintenance (600/86400/172800
seconds). Every action is one current-tier free single; paid, premium,
item-backed, 10x, ambiguous, unknown, contradictory, stale, and identical
retry paths remain forbidden. Dispatch is not success, a same-tier result and
attempt successor is required, tier state is persisted, and canonical Home is
separate.

Both Recruitment schema-2 contracts bind the same r8 record and native
BlueStacks profile while remaining `evidence_required`, not production eligible,
and registration-disabled. The eight prior contracts changed only their global
r8 authority fields and retained their record digests/semantics. Catalog
ownership maps only the Basic-five objective and keeps selected Daily out of the
direct route. Luna and Terra each passed 96 focused tests; Terra found no defect,
verified the mechanical rebinds, and all 29 bindings validated. Thirty-eight
current orchestrator/handoff tests also passed. Architecture
passed 92, receipt
`48f2096081c7f982eca877e1cd2d9cb9f8810a4ce0a125753ae8712a2481d6fd`.

Retained semantic mechanics record
`cc5d306033c559d014947ee48449b794e0e3e8c7175cff2011d2336d6ad896c4`
and synthetic fixtures remain non-accepting; current uninterrupted Basic-five,
three-tier maintenance, successors, and Home proof remain `evidence_required`.
Zero emulator/ADB/BlueStacks observation, runtime input, or recruit occurred.
Registration/scheduling remain disabled and runtime ownership is absent. Next
is only the Recruitment continuous-session migration.

## Stage 7 Supply Depot continuous-session migration

The current r7 record `supply_depot-v1` and exact schema-2 contract proved the
product precondition. The separate parent-owned Medium lane binds the unchanged
controller to one active flow-owned session and the identical typed,
hash/invocation-bound initial observation; `conduct` creates no pre-run session.
It recounts all native transports and the one bounded Free hold, emits exactly
one read-only/non-authoritative trace, and labels only uninterrupted proof
`continuous`. Paid/diamond/unknown controls remain denied.

Completion requires Free attempts at zero, every Free control absent, and
canonical Home. A hold-bearing unknown becomes `effect_reconciliation_required`,
denies identical retry, and vetoes `DONE`; checked-in verification is mandatory.
No Daily `5/5` or action attribution is inferred from retained navigation proof.
Validation passed 8 adapter, 32 conductor, and 75 Supply/session tests. Focused
receipt `21d2184ba75969cdd7e1f75101eddde3f1edf69d1344255eb9564a236b0ca036`;
architecture receipt
`ff47b92baf60b59dcc859bf0fca1232ad0047717aab8fb25fb6f501ea4f06a0d`.
Zero live input/hold; current uninterrupted proof remains `evidence_required`.
Registration/scheduling remain disabled. Next is Recruitment dependency audit.

## Stage 7 Daily Milestone Claim product-record migration

Heavy revision `daily-milestone-claim-product-record-migration-r1`, manifest
SHA-256 `f84c62b5608acc33fedeaff9220eed1e94557e88d216512aeda24677f5e9fbdb`,
adds r7 record `activity_milestone_claim-v1`, digest
`fc39004cd8e4727fc5fed56cc656d2b1790908a1e57e0b82bc65493b1bf5a638`;
authority digest is
`7ecac59c562120d3babb1a65455afcd15f30402f0ba0251c1835ac754a5a2c03`.
It owns one current ready, fully visible, zero-cost Activity Milestone chest,
separate from ordinary row Claim and Daily point ownership. Dispatch is not
success; same-milestone opened/claimed or positive bound-points successor is
required, unknown effect denies identical retry, and canonical Home is separate.

The schema-2 BlueStacks contract remains `contract_only`, `evidence_required`,
not production eligible, and registration-disabled. The Phase E Bliss/synthetic
fixture is diagnostic only; current ready/successor/Home evidence is missing.
Luna and Terra each passed 66 focused tests; Terra found no defect and verified
all seven prior contracts changed only global r7 binding fields. Architecture
passed 92, receipt
`34c5b6c32f3b08e82b3a548f21caded14b83fa62f4e05afbd87c613a089146a5`.
Zero live input or Claim occurred. Next is only the Supply Depot dependency audit.

## Stage 7 Bioenhancer product and continuous-session migrations

Heavy revision `bioenhancer-product-record-migration-r1`, manifest SHA-256
`b3cce031eb1b0d6426a69990f1d27525aa02b229993ca1a5d0d242889af7a57f`,
added typed record `bioenhancer_research-v1` digest
`5f36370751b2ff5071c0f42fbe15a28a3c628b28aa1ecf588337f5d32cb61207`.
Authority r6 digest is
`369d85615d30e1776b0fa719f11b8fbc85da7a0978342494f2d9deb37d9b951d`.
It preserves direct Home routing, one zero-cost Free Research 1x, cooldown
successor, dispatch/success separation, retry denial, no paid/10x fallback,
null Daily/Claim ownership, and canonical Home. Historical Bliss evidence stays
non-accepting; current BlueStacks proof is `evidence_required`.

Luna passed 57 affected and 6 adapter tests; Terra found no must-fix defect.
Focused 6 receipt `760f7d1174e66a78c6a8f89f6c98721f9e71482cc45a50c1f891040a2b6762fc`;
architecture 92 receipt `ef5d6befbea493a0edd560e91e77803e2d23775de8d2151bf77389ecbf84d038`.
Commit `dff36cf` closed the product-only predecessor. The separate Medium lane
now requires one exact active flow-owned session and the identical typed,
hash/invocation-bound initial observation before runtime connection. `conduct`
does not pre-observe. The unchanged controller retains current-frame binding,
paid/10x denial, one Free Research ceiling, cooldown successor, and Home.

The adapter recounts every native transport and the one Free Research dispatch,
writes exactly one read-only/non-authoritative causal trace, and labels proof
`continuous` only for one uninterrupted session. A dispatch without verified
cooldown plus terminal Home is `effect_reconciliation_required`, denies an
identical retry, and vetoes conductor `DONE`; the checked-in verifier is the
final gate.

Validation passed 9 adapter, 32 conductor, 16 session, 11 Bioenhancer safety,
and 57 authority/contract/catalog tests. Focused 9 receipt
`7d247c8e4f36bafeccaa3d53b5bc7218ff3f073731889f652c7d3b5013291513`;
architecture 92 receipt
`7c934a3fff7f2f4a2a242eb50d8c4c4765d6292c1da6628cad31355541da6d8f`.
One route-local causal-trace artifact declaration `local_defect` was repaired.
Zero live input/research; historical Bliss proof remains non-accepting and a
current uninterrupted BlueStacks session stays `evidence_required`. Registration
and scheduling remain disabled, ownership absent. Next is only the Daily
Milestone Claim dependency audit.

## Stage 7 Ultimate product and terminal-session migrations

Commit `ac4e334` accepted typed record `ultimate_challenge-v1` and r5 authority.
The separate Medium terminal lane now runs only the existing post-Flee
Ultimate→Campaign→measured-exit→Home seam inside one exact flow-owned session,
with typed/hash/invocation-bound initial evidence and no pre-observe session.
It recounts nested native transports, emits one read-only trace, requires zero
new Flee, and gates `DONE` through the checked-in verifier. Attempts 13/14 stay
truthful `composite`; only terminal reconciliation is `continuous`.

Validation passed 106 Ultimate, 31 conductor, and 16 session tests. Final
focused 27 receipt `a3ef27b1b7644611cadefc291e58ad74bd6064f640d6e070b1496e8bcc935a92`;
architecture 27 receipt `7e7876f9adfd47a9f8ab37c547c71e1089f5ed3c874ad72c6887137458c2c01f`.
One nested-transport accounting `local_defect` was repaired. Zero runtime input
or Flee; native uninterrupted terminal proof remains `evidence_required`.

## Stage 7 Enhancement continuous-session migration

Prior commit `1db306e` accepted Enhancement's exact one-session family adapter.
Focused 59 receipt `a856aa24...3944a`; architecture 92 receipt
`72494ec31...be5e1`. Retained proof remains non-accepting `composite`.

## Stage 7 Nova Praise continuous-session migration

Prior commit `2886c1d` accepted Nova’s one-session adapter offline: exact typed
observation, one Praise, transport recount, successor, one trace, and Home gate.
Focused 172 receipt `74cdb810d0859a8c4f060ba3fcc1bee48cb37117e34a79242dcab224cf20f63b`;
architecture 92 receipt
`33229ace42cf1ddc8ac2d988890f0a787f13e7aa9471cfa732b14286afd25265`.
Native proof remains `evidence_required`; zero live input and registration stays
disabled.

## Stage 7 Nova Praise product-record migration

Prior commit `5451b2c` accepted typed record `nova_praise-v1`; its exact
authority, review, evidence, and receipt history is retained in durable status.

## Prior Stage 6 closure

Accepted offline revision `continuous-development-session-thin-conduct-r6` has
manifest SHA-256
`68c94af7113a8c506e603384dfdf2149ed4cee8a3f1215d71bbf43e7e2692356`.
Resource and World prove the shared one-session contract, exact typed initial
observation, transport accounting, one non-authoritative trace, thin checked
conduct, exact external-blocker authority, and bounded reconciliation
`CONTINUE → STEP_BACK → ESCALATE`. Detailed revision history and receipts remain
in durable status. No Stage 6 live input occurred; registration and scheduling
remain disabled.

## Prior Stage 3 closure

Runtime Reliability Stage 3 control primitives (umbrella Stage 5) is complete
in the commit containing this handoff. The accepted frozen revision is
`runtime-reliability-stage-3-control-primitives-r3`, recorded in
`docs/runtime-reliability-stage-3-control-primitives-execution-manifest-r3.md`
(SHA-256
`bdf221ee636af73e7dcd21748ac0e9df99ff3d5b573295c9fb519fb973242f36`).
The candidate adds pure stable-transition, list-search, and source-context
modal/recovery primitives plus a read-only causal trace projection. Production
flow adapters, SafetyStore, current-frame authority, runtime ownership, Home
Atlas behavior, registration, and scheduling are unchanged.

The integrated candidate passes 9 exact trace/replay tests, 16 primitive/replay
tests, 66 affected-package tests with one existing skip, 20 shared-navigation
tests (receipt
`d26b941e771229b19d6e4600d461dd377cae587cbc4661e21716b26a34745c95`).
The post-closure architecture profile passed 92 tests with receipt
`1b062eceb783b6f932e49ac0076a3cc07b1019ba1698614fb2a449a1d8bfe3c6`.

Independent review initially found missing provenance-bound cross-consumer
replay and a mixed-action causal-trace merge. The one consolidated repair fixed
the causal merge. After explicit user continuation, r3 bound the retained
Enhancement result, event log, BlueStacks profile, native dimensions, and exact
immediate-post/settled hashes into executable replay. Nova + Enhancement now
provide the two required transition consumers. Final review found one
test-proof gap for missing or duplicate phases; the exact unique four-phase
repair passed all focused checks. The parent integration decision is accepted
for Stage 3 offline scope.

The Resource sessions used the unchanged standard BlueStacks profile; their
legacy record merely omits repeating that field. Existing Ultimate sessions
already prove Flee, the false-Home Resource Shop frame, the Campaign Back exit
dialog, measured Campaign exit, and terminal Home recovery; they are not yet
indexed by the new replay corpus. Neither requires a fresh run. Incomplete
retained causal traces remain diagnostic/unknown and never authorize runtime
behavior.

Deferred decisions are recorded: Alliance Shop is its own flow, checking the
already-selected Weekly Offers tab for Joy Coins or Bioenhance Scheme before
falling back to Shop → Other → 1★ Gear Enhance Material → Buy → quantity 1 →
Buy → Home. Gathering reuses the proven World/Search-menu foundation and may
continue through category, level 5, Gas reveal, and current-frame node binding,
but march dispatch remains forbidden. No runtime input occurred in Stage 3.

## Retained baseline

Runtime Reliability Stage 2, Resource Effect Authority Integration, is complete
in commit `dde9b1c`. The production path
now loads the checked-in typed product authority and derives Resource identity
from the fixed BlueStacks slot plus the exact `00:00 UTC` / `86400`-second
product rule. It has no Quest navigation, Daily timer OCR, or prior
identity-observation receipt authority.

Retained accepted canary:
`.local-captures/development-sessions/DAILY-RESOURCE-ITEM-BLUESTACKS-INTEGRATION-20260820T212159603189Z`

The retained canary row intentionally remains
`FIXED_RUNTIME_BINDING_RESET_OBSERVED` with historical Quest/OCR evidence.
Only exact fixed-slot/reset core equality (account, server, runtime scope,
reset start, and reset deadline) permits reuse; historical identity evidence
is not rewritten.

Proof: one settled list scroll → one exact `1K Food` Use → owned
`129679 → 129678` → `HOME_CANONICAL` in 3 inputs. The retained
`result.json` uses adapter state `HOME`; the canonical terminal
observation/projection explicitly stores `HOME_CANONICAL`. The canonical
SafetyStore remains v4 with zero foreign-key violations, the occurrence is
`COMPLETED`, the effect and linked action are confirmed, and no controller or
runtime-input ownership is held.

Prospective terminal reconciliation releases `ACTIVE` and
`RECONCILIATION_ONLY` claims transactionally and appends a claim transition;
`RELEASED` and `EXPIRED` claims remain unchanged. The existing canonical
historical claim row's literal durable state column remains `ACTIVE`; its
`expires_at` has elapsed, so it is expired by lease semantics and
non-authorizing. It was not rewritten by this candidate. No extra live canary
was run.
At the retained Stage 2 baseline, registration was `NOT_REGISTERED`, scheduler
eligibility was disabled, and Stage 3 was not started. The Stage 2 closure is
commit `dde9b1c` on branch
`feature/runtime-reliability-convergence`; its parent is
`8c73b932dc09ca4569f6e1082b3680ead876c18c`.

Final focused Resource validation passed 65 tests. The offline baseline repair
normalized the Resource queue record and current workflow assertions; the
architecture profile now passes all 92 tests with receipt digest
`102bac590580861dba3fe972e1217fec7c6e3e0692f46f836ac91f1d996ffe1e`.
The next execution-stage task at that baseline was Stage 3 control primitives, corresponding to
“Shared control primitives through offline replay” (Stage 5 in the expanded
umbrella plan). That historical selection is now complete.
## Stage 7 Recruitment continuous-session migration

The separate offline session lane registers `RECRUITMENT-BLUESTACKS-INTEGRATION`
with `pnsctl conduct` and binds the unchanged Noah controller/native route to
one active flow-owned `DevelopmentSession`. Conduct no longer creates a
pre-observation session for Recruitment. The adapter requires the real active
session, exact typed initial-observation identity, invocation/hash binding, and
the existing 12-input full-pass ceiling; the existing direct continuation
route retains its separate 4-input ceiling.

The adapter recounts every retained native transport and exact
`noahs-tavern-daily-free` recruit transport, preserves the controller's
current-frame tier/free-control binding and persisted tier state, emits one
read-only non-authoritative causal trace, and requires result/decrement/
cooldown successors plus canonical Home. A dispatch-bearing unresolved result
is `effect_reconciliation_required`, denies identical retry, and cannot pass
the checked-in verifier. Product authority, selectors, route semantics,
registration, and scheduler state were not broadened.

Focused adapter validation passed 5 tests, the affected Recruitment/conductor
suite passed 77 tests, and the architecture profile passed 92 tests. Receipt
digests are recorded in the state JSON above. `git diff --check` passed.
Zero emulator/ADB/BlueStacks observation, runtime input, and recruit actions
occurred. Retained native proof remains `evidence_required`. Sol 5.6 PR review
is pending and was not claimed.

## Stage 7 ordered remainder and next-three detail

The machine-readable state above is the persistent ordered plan. Next:
Daily Milestone Claim route integration or truthful evidence-blocked
disposition; Campaign AP product authority; Campaign AP continuous-session
migration. Product authority and session migrations remain separate atomic
tasks. All remaining canonical-plan/catalog entries require one durable
migrated, blocked-with-owner, disabled-with-owner, or retired disposition
before Stage 7 closure.
