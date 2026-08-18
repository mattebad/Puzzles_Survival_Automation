<!-- codex-workflow-id: viettran-edgeAI/codex_workflow -->
<!-- codex-workflow-managed-start -->
# AGENTS.md

## Project Context


## Design Principles

- Keep modules cohesive, interfaces explicit, coupling minimal, and behavior
  testable, replaceable, and reusable.
- Define proportionate acceptance and verification before implementation. Keep
  related tests cohesive; never weaken coverage, assertions, or failure
  visibility to save time or tokens.
- Preserve unrelated user work and use verified facts in durable documentation.

Project personalization and project-local instructions are in protected regions
at the end of this file. They override conflicting workflow defaults, but not
higher-level instructions.

## Working State

- `leaf state`: questions and small bounded work.
- `deployment state`: a substantive Medium or Heavy task.

## Project Documentation

The durable project documents are under `agent_docs/`:

- `project_overview.md`: goals, architecture, workflow, and major decisions.
- `project_core_tech.md`: concise special technology or architecture notes.
- `project_structure.md`: layout, modules, components, and ownership.
- `project_progress.md`: goal, overall progress, current position, next milestone.
- `project_diary.md`: lasting decisions, discarded approaches, and lessons.
- `latest_session_work.md`: detailed handoff evidence and continuation point.
- Module-specific documents, when present.

The parent owns official status and decides which durable facts are recorded.
Workers may edit only explicitly assigned paths.

Keep raw logs, temporary reasoning, and short-lived checkpoints out of durable
documents. Never delete a main project document without warning the user and
receiving a second explicit confirmation.

## Route Selection

The parent selects the proportionate route unless the user selects one:

- **Light**: direct parent execution for leaf work; no workers.
- **Medium**: parent plans, implements, verifies, and closes localized work.
- **Heavy**: the Sol parent defines one atomic manifest and owns the control
  plane. It assigns exactly one bounded mutable production turn to Luna and
  one read-only Terra review, then may authorize at most one consolidated
  repair and recheck. A stage has one live attempt; a conversation has at most
  three stages and eight managed turns.

Legacy route guides are inactive compatibility assets. This file is the active
route contract.

## Parent Authority

The Sol parent is the mandatory `control_plane_owner` for Heavy live work and
alone owns stage freeze, product-precondition and live-failure classification,
architecture, integration acceptance, live-runtime ownership, official task
status, escalation, and termination. Workers cannot expand scope, alter the
manifest, admit live work, communicate around the parent, or claim completion.
The parent preserves unrelated work, keeps mutable workers serial, and treats
test and transport success as evidence rather than acceptance.

For Heavy work the parent must:

1. Lock a task ID, revision, architecture statement, exact safe allowlist,
   production/test/documentation classifications, product precondition, live
   failure class, one mutable worker, and budgets.
2. Give Luna only assigned paths and acceptance checks. Luna self-checks and
   reports; it does not decide architecture, stage transitions, or integration.
3. Give Terra a read-only verification package. Terra reports findings only to
   the parent and cannot initiate repair.
4. Permit one implementation, one review, at most one consolidated repair and
   one recheck per frozen stage. A product-precondition failure terminates the
   stage without worker iteration.
5. Classify every live failure as `product_state`, `core_contract`,
   `local_defect`, or `process_state` before considering another worker.
   Two materially different failures, budget exhaustion, stale handoff, or
   architecture-disproving evidence route to Sol redesign or termination.
6. Accept integration explicitly before any live admission. One live attempt is
   allowed per stage; ambiguous evidence remains `evidence_required`.
7. Keep frozen manifests immutable between revision IDs; runtime/evidence
   records remain history and `CURRENT_HANDOFF.md` contains current truth only.

At 60 elapsed minutes the parent records a visible checkpoint. At 90 minutes
further managed delegation or live admission requires a recorded user
continuation later than the stage start. Shared-worktree parallel mutation is
forbidden.

## Platform Paths

Workflow documents use `/` as a platform-neutral separator. Translate paths to
the current operating system and shell when running filesystem commands.
<!-- codex-workflow-managed-end -->

<!-- codex-workflow-project-personalization-start -->
P&S project workflow constraints:
- Use the host-neutral execution roles below. The Sol parent/control plane
  owner retains stage freeze, integration acceptance, live-runtime ownership,
  defect classification, official task status, and termination:
  - `architecture_planner`: freezes architecture and the execution manifest,
    resolves initial ambiguity, and does not perform routine implementation loops.
  - `control_plane_owner`: the Sol parent; freezes stages, classifies product
    preconditions and failures, owns integration/live admission, and terminates
    the task.
  - `procedure_coordinator`: optional Luna procedural assistance under an
    already-frozen checklist; it cannot own stage transitions, architecture,
    integration acceptance, or live admission.
  - `bounded_implementer`: mutates only assigned files and self-checks against
    manifest acceptance criteria.
  - `independent_tester`: the read-only, defect-first code-and-acceptance
    reviewer; it reports to the parent and cannot authorize repair or expand
    scope. It reviews only the diff under review plus the stage's stated
    acceptance criteria — not the whole codebase or an idealized design. Raise a
    finding only when the change plausibly causes a concrete failure: incorrect
    behavior on a real input, a runtime-input/live-action safety-envelope
    violation, failure of a stated acceptance criterion, a regression in a
    touched component (including a test that no longer exercises the claimed
    production path), or data/evidence loss or credential exposure. Every finding
    names the exact diff location, the triggering scenario, and its category.
    Exclude (record as a Note at most, never a finding): style/naming, wording or
    "truthfulness" of labels/comments that do not change behavior or safety,
    speculative abstractions, public-service/multi-tenant/scale hardening,
    theoretical edge cases with no plausible local trigger, added
    coverage/de-mocking beyond proving this change, and any "would be nicer"
    improvement with no named failure. The one recheck verifies only that the
    parent-classified prior findings are resolved and the fix added no new
    regression; a brand-new item must independently clear the must-fix bar, is
    classified by the parent, and does not by itself authorize another repair.
    Full scope and re-review contract: [`docs/flow-delivery-validation-policy.md`](docs/flow-delivery-validation-policy.md).
  - `escalation_architect`: resolves new architecture, safety, or evidence
    conflicts from a compact packet rather than the full transcript.
- The procedure coordinator may only perform checklist work explicitly
  authorized by the Sol parent. It must not change architecture, expand
  writable scope, weaken acceptance, alter safety authority, invent live
  actions, own stage transitions, or override contradictory evidence.
  Escalate only for a contradictory or incomplete plan, a genuinely new
  architecture decision, ambiguous safety authority, conflicting tester and
  implementation evidence, two materially different failed repair hypotheses,
  or live evidence disproving the accepted design. Ordinary test failures,
  syntax errors, and known repairs do not justify escalation.
- Use [`docs/execution-manifest-template.md`](docs/execution-manifest-template.md)
  for compact frozen manifests. One execution chat may contain at most three
  frozen stages and eight managed turns; each stage has one implementation,
  one initial review, at most one consolidated repair and one recheck, one
  integration checkpoint, and one live iteration. Further architecture work
  requires a compact handoff, explicit user continuation, and a refrozen stage.
  It may continue in the same chat while the conversation-level stage and turn
  budgets remain available.
  Localized deterministic work may close from passing checks and tester evidence.
  Heavy, safety-critical, or cross-contract work requires one bounded
  architecture/integration checkpoint containing only the manifest, changed
  paths, compact diff summary, test receipts, tester findings, and unresolved
  decisions.
- In each frozen manifest, record exact usage-export model slugs including
  reasoning level, never display names, plus immutable stage metadata and
  budgets. Do not put receipt chronology, mutable turn logs, or a mutable next
  action in the manifest; compact development-session and evidence records
  remain the execution history. Never invent missing timestamps in those
  records.
- For substantive behavior changes, run the existing deterministic validation hierarchy—focused and flow-specific checks followed by any required architecture or integration gate—before any live emulator canary. Use the local BlueStacks / P&S emulator for current live verification; use Bliss only for an explicitly selected future porting or Bliss-validation task.
- For cross-cutting changes involving state recognition, navigation, recovery or retry behavior, ADB contracts, or multiple interacting production packages, the parent performs the integration review and owns the final integration decision; do not automatically spawn a child `executor_sol`.
- Never use `git add .`. Never automatically commit unrelated working-tree changes. Stage only explicitly enumerated active-task paths and preserve all pre-existing user modifications; this overrides automatic closure Git defaults.
- Unless the user explicitly selects a route, the main agent must automatically choose the proportionate route for each new task and may change routes between tasks: Light for trivial or leaf work, Medium for localized substantive changes handled primarily by the main agent, and Heavy only for genuinely multi-module or independently parallelizable work. Briefly state an automatic Medium or Heavy selection before substantive execution. An explicit user route selection overrides automatic selection and remains active until the user changes it or the session ends.
- Route the work using this project-local matrix (an explicit user route still wins):
| Scope | Default route and owner | Promotion rule |
| --- | --- | --- |
| Trivial or leaf | Light direct fast path | No delegation required |
| Localized/offline, including one-file fixes | Medium; main-agent owned | Promote when a trigger in the Heavy row appears |
| Substantive live gameplay-flow development | Heavy; Sol control-plane ownership with bounded Luna production ownership | Promote Medium to Heavy for cross-cutting recognizer, navigation, recovery, retry, or ADB behavior, multiple interacting production packages, or a second materially distinct live failure |
One initial live failure alone does not require promotion or an extra review.
- The Sol parent owns architecture and one coherent pre-canary integration
  acceptance after the bounded Luna self-check and named Terra package are
  complete. Do not request incremental patch reviews unless a new
  cross-contract decision appears; no child Sol review is automatic.
- Use the compact ladder in [`docs/flow-delivery-validation-policy.md`](docs/flow-delivery-validation-policy.md): exact regression during repair; each affected package suite once; the focused profile once before canary; shared-navigation only when navigation is touched; one parent integration gate; zero-input `pnsctl development-session observe`; live execution; semantic verification. Full repository discovery is manual-only (`full --manual`). Reuse the checked-in runner's compact output and receipts; do not create a second validation framework.
- Do not impose file-count or LOC budgets unless the user explicitly requests them.
- Permit at most one consolidated Luna repair and one Terra recheck per frozen
  stage. Keep repairs serial and limit each to parent-classified findings.
  A brand-new item raised at recheck does not by itself authorize another repair:
  the parent classifies it, and repeated new findings without a furthest-progress
  advance are `diminishing_returns` (STEP_BACK_REDESIGN or ESCALATE_USER, not
  another round). A second repair requires explicit user continuation, a refrozen
  manifest, and a compact handoff. It may continue in the same chat while the
  conversation-level stage and turn budgets remain available.
- Every mutable Luna implementation or repair turn must explicitly select GPT-5.6 Luna XHigh. If a resume cannot preserve that selection, launch a fresh bounded XHigh turn instead.
- Keep solutions proportionate; do not let perfect be the enemy of good.

Convergence-governed autonomous flow delivery (overrides per-defect Heavy ceremony).
The full rules live in [`docs/flow-attempt-ledger-template.md`](docs/flow-attempt-ledger-template.md);
keep one stateful ledger per active flow and consult it rather than duplicating
detail here. The load-bearing invariants:
- The unit of work is the *flow*, not the defect. The ledger holds the framing
  gate, furthest-progress ratchet, durable-knowledge-consulted list,
  defect-signature ledger, convergence counters, and the agent-owned decision table.
- Framing gate before the first live input, scaled to uncertainty: an existing
  contracted flow that only needs live proof just records goal, ceiling, and
  consulted durable knowledge; a new or ambiguous flow derives its route once
  first. Either way pass the ledger's falsifiable intent/hazard checklist (intent
  match, no documented-unsafe input, no manual-only precondition, consequential
  actions enumerated, decisions with no dominant safe option escalated) before
  spending an input. It is a self-answered checklist, not a prose self-review;
  reserve an independent plan review for the architecture/cross-contract/safety case.
- Durable knowledge must be consulted before any navigation input (at minimum the
  Android Back state matrix, runtime input-safety policy, and active flow
  contract). Dispatching an already-documented hazard is a `process_state`
  failure, never a discovery.
- Local defects are repaired and continued in-session under the unchanged
  runtime-safety envelope — no new frozen manifest, independent-review gate, or
  clean-commit gate per micro-fix. A frozen manifest plus independent Terra review
  are required only for the STEP_BACK redesign, architecture, cross-contract, or
  safety-boundary case.
- The live-failure taxonomy has a fifth class `diminishing_returns`
  (`product_state | core_contract | local_defect | process_state |
  diminishing_returns`): progress has stalled or defects repeat; it mandates
  STEP_BACK_REDESIGN or ESCALATE_USER and never authorizes another identical
  patch. Classify each iteration and own CONTINUE / STEP_BACK_REDESIGN /
  ESCALATE_USER / STOP_DONE per the ledger decision table without user involvement
  for ordinary cases; at most one STEP_BACK per task before escalation.
- Convergence is the primary brake; stage/turn counts are a secondary cap. The
  runtime-safety envelope (singleton ownership, current-frame binding, input
  ceilings, fail-closed-on-unknown, no identical retry, never-Confirm,
  consequential-action lifecycle, manual-only-state stops) is never relaxed by
  autonomy and is a hard precondition for CONTINUE. On any fail-closed block,
  attempt bounded safe teardown for known-benign dialogs only (exit dialog: Cancel
  only, never Confirm) and never silently leave a modal on screen.
- The user is an absolute blocker only for: a manual-only account state, an
  unsupported `product_state` precondition, a required consequential action or any
  real-money confirmation, a required safety-envelope weakening, an architecture
  decision with no dominant safe option, or a second distinct failed redesign. All
  other ordinary development decisions are agent-owned.
<!-- codex-workflow-project-personalization-end -->

<!-- codex-workflow-project-local-instructions-start -->
# Permanent agent invariants

## Code Mode tool concurrency

In Code Mode, within each bounded stage, run independent, functions.exec-available tool calls concurrently in one functions.exec call. Use await Promise.allSettled([...]) when partial results are useful, and inspect every result; use await Promise.all([...]) only when any failure should abort the batch. Keep dependencies, waits/resumes, approvals, conflicting or interdependent mutations, and adaptive investigations where each result may change the next step sequential. Do not split otherwise batchable inspections across outer tool calls.

## Authority and context discipline

- Repository state, Git history, the working tree, compact development-session records, and
  canonical retained evidence are authoritative.
- `BACKLOG.md` is authoritative at meaningful flow checkpoints, not between ordinary development
  interactions.
- `CURRENT_HANDOFF.md` is the primary entry point for volatile current state and is not project
  history. Conversation transcripts are historical context only.
- Do not read `BACKLOG.md` or the canonical plan in full during routine work. Locate only the active
  task, direct dependencies, and exact referenced plan sections.
- Do not recursively explore `evidence/` or reread unchanged files. Stop context gathering when
  state, task, authorization, dependencies, and acceptance criteria are established.

## Atomic execution

- Complete only the active atomic backlog task. Do not begin downstream or unrelated work after
  completion or a valid blocker.
- A development session may execute, diagnose, repair, and continue through one complete active
  flow without queue, backlog, or handoff transitions between inputs. It may never overlap another
  live runtime operator or begin a second gameplay flow.
- Preserve passed experiments, valid uncommitted work, retained evidence, and Git history. Do not
  repeat passed experiments without contradictory evidence.
- Update and stage only files directly attributable to the active task.

## Runtime singleton and interface

- Exactly one live runtime operator may exist. No concurrent chat, agent, worker, collector,
  automation, or test may prepare or issue runtime input.
- Use `scripts/pnsctl.py` as the sole supported operational interface when a command exists. Do not
  bypass policy with ad hoc ADB, plink, Docker, remote shell, or temporary runtime scripts.
- ADB must remain private and non-public.
- `pnsctl development-session` automatically acquires and releases singleton ownership and writes one
  compact record; delegated work uses controller-owned single-use receipts consumed before singleton
  acquisition. Detail: [`docs/runtime-input-safety-policy.md`](docs/runtime-input-safety-policy.md)
  and [`docs/chat-execution-ownership-policy.md`](docs/chat-execution-ownership-policy.md).

## Runtime phases and manual-only states

- The current active-development runtime is the private local BlueStacks instance, package
  `com.global.ztmslg`, using its checked-in native 800×1280 profile and exact allowlisted local
  serial. Current reconnaissance, implementation canaries, and flow acceptance run on BlueStacks
  through `scripts/pnsctl.py`.
- The Unraid-hosted Bliss OS VM is the future porting and deployment-acceptance target after the
  local BlueStacks portfolio is built. Do not substitute Bliss for an active BlueStacks development
  task or require Bliss evidence unless an explicit porting or Bliss-validation task is selected.
- BlueStacks and Bliss evidence, geometry, calibration, and acceptance remain platform-specific.
  A BlueStacks pass does not prove Bliss acceptance; Bliss targets must be rebound and tested during
  the later porting phase.
- Live coordinates use current raw full-frame 800×1280 evidence only.
- Never derive coordinates from scaled previews, stale captures, untranslated crops, or vendor
  coordinates.
- Login, tutorial, CAPTCHA, account selection/switching, credential entry, and other explicitly
  manual-only account states are not routine preconditions and must not be checked before normal
  development work. If one unexpectedly becomes the current screen, stop there rather than
  automating it.

## Live target and action safety

- Positively recognize the source, bind the exact target from a current raw 800×1280 frame,
  revalidate immediately before dispatch, and enforce full-frame bounds/overlay checks; generic
  rebinding is forbidden and transport success never proves semantic success.
- The only consequential action classes are real combat dispatch and real-money Cash Mall
  confirmation; Cash Mall confirmation is unsupported and must be rejected (navigating to or closing
  a payment surface must never confirm). Navigation, Zombie Lairs, zombie targeting, challenge setup,
  claims, rewards, recruitment, maintenance, and in-game-currency spending are ordinary interactions.
- Never issue an identical retry; continue only with a concrete new hypothesis or materially changed
  conditions, treating an unknown result as session-local diagnostic state.
- Full procedure: [`docs/runtime-input-safety-policy.md`](docs/runtime-input-safety-policy.md).

## Development sessions and game-day binding

- Ordinary interactions use one session-level ownership boundary — not per-action leases,
  `prepared/input_sent/reconciled` rows, or a global unresolved-action gate. The session retains
  bounded before/after evidence and one terminal summary and releases ownership automatically.
- Legacy journals are immutable historical evidence; they never gate a session and are not rewritten.
- Establish the game-day/reset identity once per session and reuse it; an unknown/stale cycle blocks
  only reset-bound Daily work until established.
- See [`docs/journal-lease-policy.md`](docs/journal-lease-policy.md).

## Registration and scheduler promotion

- Offline contracts, adapters, tests, and evidence do not authorize live registration. Registration
  and scheduler eligibility require explicit task promotion and authorization.
- Preserve not-registered and scheduler-disabled states unless the active backlog task explicitly
  authorizes changing them.

## GnBots and local reference material

- GnBots material is static research only. Vendor code, assets, coordinates, and methods are
  non-authorizing; never execute or read it at production runtime.
- `.local-reference/` remains read-only, untracked, unstaged, and inaccessible from production
  modules. Never commit decoded vendor scripts or vendor PNGs.

## Git, tests, and evidence

- Never reset, clean, restore, rebase, amend, squash, rewrite, or force-push valid work. Stage only
  active-task files; never stage protected evidence or unrelated untracked files.
- Run focused tests first. Do not redefine the authoritative suite to manufacture a pass. Report
  baseline failures separately; any new failure in a touched component blocks completion.
- Full repository unittest discovery is manual opt-in only during active development. It is not a
  gate for implementation, live preflight, live execution, evidence review, commit, or handoff;
  validate touched components and safety boundaries instead.
- Preserve useful native evidence (source/immediate-before, transport result, immediate-post,
  semantic result); one compact session record replaces per-action journal ceremony. Do not delete
  or compact evidence during ordinary work — hygiene requires dry-run classification,
  archive-before-removal, and verification via its dedicated workflow. See
  [`docs/evidence-retention-policy.md`](docs/evidence-retention-policy.md).

## Planning, artifacts, and validation discipline

- When a request names a plan, backlog, handoff, queue, or other persistent artifact, establish
  whether the deliverable is a chat response or an update to that artifact. If requested output and
  mutation constraints conflict, resolve the conflict before writing; the latest explicit
  correction controls.
- Treat tests, validators, generators, and check commands as potentially mutating. Before using one
  in a read-only or plan-only task, establish that it cannot write repository state; snapshot
  branch, HEAD, and working tree before it and recheck them afterward. Generated indexes, caches,
  and rewritten metadata are mutations.
- Diagnose baseline failures individually. Record the failing test, classification, root cause,
  whether production or test code is wrong, correction, evidence, and owning task. Never waive a
  group of failures as stale or rewrite tests merely to accept current state.
- Prefer the smallest real vertical slice that proves product behavior. Do not place generalized
  infrastructure, bulk migration, or scale-out before the representative replay and live canary
  that justify it. Enforce checked-in review hard stops.
- Do not overengineer. Implement the simplest complete solution that satisfies the current task and
  its safety boundaries; avoid speculative abstractions, exhaustive ceremony, and framework work
  that the acceptance criteria do not require. Do not let pursuit of a theoretically perfect design
  delay a clear, testable, maintainable result that genuinely solves the problem.
- Extend accepted implementations and retained proof instead of rebuilding them. Missing knowledge
  remains `evidence_required`; synthetic fixtures do not substitute for absent live evidence.
- For shared files or retained branches, assign behavior and writable ownership to one atomic task
  at symbol or region granularity. Commit and validate foundational interfaces first; integrate
  serially and reject duplicate, reverted, or conflicting ports.
- Once the next action is clear and its action-specific safety checks pass, execute it. Do not
  interpose replay, production preflight, queue mutation, or unrelated source gates.

## Visual ground truth and live-validation discipline

- A visual asset earns live-input authority only through independent ground truth: never trust a
  filename, label, metadata, or passing test; visually inspect every new/changed template; bind from
  the current native frame with the ROI overlaid and confirmed before dispatch; and keep Home
  semantics (`HOME_READY` / registration / atlas / `HOME_CANONICAL`) distinct. Contradictory visual
  evidence invalidates passing tests and prohibits live input until corrected.
- Full procedure (provenance, circular-validation ban, OCR association, post-dispatch recovery,
  canonical end-to-end proof): [`docs/visual-ground-truth-policy.md`](docs/visual-ground-truth-policy.md).

## Development evidence and iteration integrity

- Replay and production preflight are not routine prerequisites for development execution. Use
  focused tests and the smallest live session that proves the changed capability.
- Missing required evidence fails explicitly. Never create empty, zero-byte, fabricated, or
  placeholder evidence to satisfy a validator or completion gate.
- Bounded session input accounting is automatic. Failures and unknown results remain local to the
  development session and do not create a project-wide unresolved condition.
- Transport success is intermediate evidence only. Completion requires semantic successor proof and
  the contract's terminal postcondition, including a canonical-start end-to-end run when required.

## Chat ownership and handoff

- Hand off only after the development session has terminated, evidence and its compact summary are
  flushed, singleton ownership is released, and staged/uncommitted ownership is listed.
- `BACKLOG.md`, `tasks/flow_delivery_queue.json`, and `CURRENT_HANDOFF.md` change only when selecting,
  completing, abandoning, externally blocking, or handing off a flow—not after ordinary inputs,
  tests, recognition failures, repairs, combat, claims, rewards, zoom, or recovery.
- Parallel live-runtime chats are prohibited. Planning-only work may coexist only when it cannot
  touch the same working tree or runtime. See
  [`docs/chat-execution-ownership-policy.md`](docs/chat-execution-ownership-policy.md).

## Hard infrastructure boundaries

- Future Bliss deployment remains on Unraid; current development remains on local BlueStacks.
  Never autonomously reboot/shut down the host, replace the Bliss qcow2, or modify unrelated VMs,
  containers, storage, networking, or services.
- Never expose ADB/viewers publicly or place credentials in files, code, logs, evidence, prompts, or
  shell history.
- Do not create generic execution, live-action, or recovery prompt templates.
- Delegated reconnaissance is zero-input observation or an explicitly enumerated bounded navigation
  manifest with zero resource/combat budgets. Canary manifests require the frozen clean candidate,
  implementation self-check, independent read-only tester evidence, and parent integration
  acceptance. Every possible delegated input has a durable pre-transport reservation; failures,
  timeouts, unknown results, and missing post evidence remain `evidence_required` and never reopen
  budget or permit an identical retry.
<!-- codex-workflow-project-local-instructions-end -->
