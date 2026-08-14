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
- **Heavy**: the parent defines one atomic manifest and assigns exactly one
  bounded mutable production turn to Luna. A read-only tester then reports
  findings to the parent. After classifying those findings, the parent may
  authorize at most one consolidated Luna repair turn. The parent may finally
  provide verified terminal facts to one documentation-only End-of-Session
  pass.

Legacy route guides are inactive compatibility assets. This file is the active
route contract.

## Parent Authority

The parent alone owns architecture, integration acceptance, defect
classification, live-runtime ownership, official task status, and termination.
Workers cannot expand scope, alter the manifest, admit live work, communicate
around the parent, or claim completion. The parent preserves unrelated work,
keeps mutable workers serial, and treats test and transport success as evidence
rather than acceptance.

For Heavy work the parent must:

1. Lock a task ID, architecture statement, exact safe allowlist,
   production/test/documentation classifications, one mutable worker, and
   optional file and line budgets.
2. Give Luna only assigned paths and acceptance checks. Luna self-checks and
   reports; it does not decide architecture or integration.
3. Give the tester a read-only verification package. The tester reports defects
   only to the parent and cannot initiate repair.
4. Classify findings and either reject, accept, or authorize one consolidated
   repair batch. Re-freeze changed production and require fresh receipts.
5. Accept integration explicitly before any live admission. One live attempt is
   allowed per iteration; ambiguous evidence remains `evidence_required`.
6. After termination, optionally assign one documentation-only pass using only
   parent-provided terminal facts and exact durable-document paths.

At 60 elapsed minutes the parent warns the user. At 90 minutes further live
admission requires an explicit parent checkpoint. Shared-worktree parallel
mutation is forbidden.

## Platform Paths

Workflow documents use `/` as a platform-neutral separator. Translate paths to
the current operating system and shell when running filesystem commands.
<!-- codex-workflow-managed-end -->

<!-- codex-workflow-project-personalization-start -->
P&S project workflow constraints:
- For substantive behavior changes, run the existing deterministic validation hierarchy—focused and flow-specific checks followed by any required architecture or integration gate—before any live emulator canary. Use the Bliss OS / P&S emulator only when actual runtime behavior requires live verification.
- For cross-cutting changes involving state recognition, navigation, recovery or retry behavior, ADB contracts, or multiple interacting production packages, the parent performs the integration review and owns the final integration decision; do not automatically spawn a child `executor_sol`.
- Never use `git add .`. Never automatically commit unrelated working-tree changes. Stage only explicitly enumerated active-task paths and preserve all pre-existing user modifications; this overrides automatic closure Git defaults.
- Unless the user explicitly selects a route, the main agent must automatically choose the proportionate route for each new task and may change routes between tasks: Light for trivial or leaf work, Medium for localized substantive changes handled primarily by the main agent, and Heavy only for genuinely multi-module or independently parallelizable work. Briefly state an automatic Medium or Heavy selection before substantive execution. An explicit user route selection overrides automatic selection and remains active until the user changes it or the session ends.
- Route the work using this project-local matrix (an explicit user route still wins):
| Scope | Default route and owner | Promotion rule |
| --- | --- | --- |
| Trivial or leaf | Light direct fast path | No delegation required |
| Localized/offline, including one-file fixes | Medium; main-agent owned | Promote when a trigger in the Heavy row appears |
| Substantive live gameplay-flow development | Heavy; parent orchestration with `executor_luna` bounded production ownership | Promote Medium to Heavy for cross-cutting recognizer, navigation, recovery, retry, or ADB behavior, multiple interacting production packages, or a second materially distinct live failure |
One initial live failure alone does not require promotion or an extra review.
- The parent owns architecture and one coherent pre-canary integration acceptance after the Luna executor self-check and the named tester package are complete. Do not request incremental patch reviews unless a new cross-contract decision appears; no child Sol review is automatic.
- Use the compact ladder in [`docs/flow-delivery-validation-policy.md`](docs/flow-delivery-validation-policy.md): exact regression during repair; each affected package suite once; the focused profile once before canary; shared-navigation only when navigation is touched; one parent integration gate; zero-input `pnsctl development-session observe`; live execution; semantic verification. Full repository discovery is manual-only (`full --manual`). Reuse the checked-in runner's compact output and receipts; do not create a second validation framework.
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
- This project is in active development. `pnsctl development-session` automatically acquires and
  releases singleton runtime ownership and writes one compact terminal record.

## Fixed runtime and manual-only states

- Production runtime is the Unraid-hosted Bliss OS VM, package `com.global.ztmslg`, logical profile
  800×1280 at 160 dpi. Live coordinates use raw full-frame 800×1280 evidence only.
- Never derive coordinates from scaled previews, stale captures, untranslated crops, or vendor
  coordinates.
- Login, tutorial, CAPTCHA, account selection/switching, credential entry, and other explicitly
  manual-only account states are not routine preconditions and must not be checked before normal
  development work. If one unexpectedly becomes the current screen, stop there rather than
  automating it.

## Live target and action safety

- Positively recognize the source, bind the exact local target from a current raw frame, capture and
  revalidate immediately before dispatch, and require full-frame bounds/overlay checks.
- Rebind a moved target only through a narrow evidence-supported policy; generic rebinding is
  forbidden. Transport success never proves semantic success.
- Actual combat dispatch and real-money Cash Mall purchase confirmation are the only consequential
  action classes. Navigation, entering Zombie Lairs, targeting zombies, challenge setup, claims,
  rewards, recruitment, maintenance, and in-game-currency spending are ordinary development
  interactions and do not use a per-action consequential lifecycle. Cash Mall confirmation remains
  unsupported.
- Do not issue identical retries. Continue diagnosis only with a concrete new hypothesis, corrected
  logic, or materially different conditions. An unknown result is session-local diagnostic state:
  capture it, recognize or recover, repair, and continue when materially changed.
- Real-money Cash Mall confirmation is unsupported and must be rejected. Navigating to or closing a
  payment surface must never confirm payment.
- See [`docs/runtime-input-safety-policy.md`](docs/runtime-input-safety-policy.md) for the complete
  procedure.

## Development sessions and game-day binding

- Ordinary development interactions do not acquire per-action leases, create
  `prepared/input_sent/reconciled` rows, or consult a global unresolved-action gate.
- One development session owns singleton runtime access, applies bounded per-command and per-session
  input limits, retains useful before/after evidence, appends compact action results, writes one
  terminal summary, and releases ownership automatically.
- Legacy journals remain immutable historical evidence. They do not gate an ordinary development
  session and must not be rewritten to represent new actions.
- Establish the game-day/reset identity automatically once per development session and reuse it for
  that session. Do not re-gate every action on repeated identity checks. An initially unknown or
  stale cycle blocks only reset-bound Daily work until the session identity is established.
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
- Preserve useful native evidence: source or immediate-before, transport result, immediate-post,
  and semantic result. One compact session record replaces per-action journal ceremony.
- Do not delete or compact evidence during ordinary work. Evidence hygiene requires dry-run
  classification, archive-before-removal, and verification through its dedicated workflow. See
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

- Never trust a visual asset's filename, label, metadata, or passing tests as proof of identity.
  Visually inspect every new or changed template before it can authorize live input.
- Retain independent target ground truth: native source frame, source hash, crop coordinates,
  template hash, runtime profile, and an annotated source showing the selected ROI and nearby
  semantic label.
- Tests must not derive expected identity, ROI, geometry, or provenance from the same constants,
  metadata, or asset used by production recognition. Circular agreement is not validation.
- OCR validates a target only when the text is spatially associated with that target. Text elsewhere
  in the frame is context, not proof that the matched control has that identity.
- Before the first live dispatch for a changed visual selector, inspect the fresh immediate-before
  native frame with the bound ROI overlaid and positively confirm the intended control.
- Bind from the current native frame. Retained coordinates describe retained evidence, not a live
  target; use bounded visual matching plus independently measured current-frame geometry.
- Keep Home semantics distinct. `HOME_READY`, positive Home registration, safe atlas localization,
  and `HOME_CANONICAL` are different claims. A strong wrong-zoom registration may prove Home context
  but must not authorize atlas coordinates, panning, or building binding until the supported zoom
  and localization requirements are met.
- After any dispatched input, assume runtime state changed. Recovery requires exact successor
  recognition and immediate-before revalidation; never reuse the prior state's authority.
- Prove supported intermediate-state continuation and the canonical end-to-end route. Success from
  an already-open radial does not prove Home-to-target navigation.
- Contradictory visual evidence invalidates passing tests. Surface any asset, label, ROI, geometry,
  or semantic mismatch immediately and prohibit live input until corrected.

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

- Production remains on Unraid. Never autonomously reboot/shut down the host, replace the Bliss
  qcow2, or modify unrelated VMs, containers, storage, networking, or services.
- Never expose ADB/viewers publicly or place credentials in files, code, logs, evidence, prompts, or
  shell history.
- Do not create generic execution, live-action, or recovery prompt templates.
<!-- codex-workflow-project-local-instructions-end -->
