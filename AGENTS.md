# Agent execution rules

## Authoritative state

- The repository, Git history, current working tree, retained evidence, and runtime journals are
  authoritative.
- BACKLOG.md is the sole authority for task status, dependencies, blockers, and task ordering.
- CURRENT_HANDOFF.md is the primary entry point for the current execution state.
- The canonical service plan defines architecture and milestone intent, but unrelated plan sections
  do not need to be read during routine atomic execution.
- Conversation transcripts are historical context only and may contain superseded conclusions.

## Initial context loading

Begin every execution iteration with:

1. `git status --short --branch`
2. `git diff --stat`
3. `CURRENT_HANDOFF.md`
4. the exact current backlog item identified by CURRENT_HANDOFF.md
5. the directly relevant implementation files, tests, journals, and evidence referenced by that item

Do not read BACKLOG.md or the canonical service plan in full during routine execution.

Locate and read only:

- the current backlog task;
- its direct dependencies;
- its explicit acceptance criteria;
- its blocker or completion entry;
- any exact plan section referenced by the current task.

BACKLOG.md remains authoritative without requiring unrelated historical sections to be loaded.

If CURRENT_HANDOFF.md does not clearly identify the current atomic task, inspect targeted backlog
headings or identifiers until the next unblocked task is established. Do not perform a broad
repository reconstruction first.

## Atomic execution

- Complete exactly one atomic backlog task per execution iteration.
- Do not combine unrelated implementation, generalized research, historical cleanup, evidence
  compaction, or downstream task preparation into the same iteration.
- Continue within the same iteration only through the implementation, verification, evidence,
  documentation, and commit work required to close that one task.
- Preserve all previously passed tasks and retained evidence.
- Never repeat a passed experiment without contradictory evidence.
- Do not restart completed research or reconstruct already-proven state.
- Do not discard or overwrite valid uncommitted work.
- Update only the evidence and canonical state files directly affected by the current task.
- Commit each passed atomic task separately.
- Do not amend, squash, reset, rebase, or rewrite prior history unless the user explicitly directs
  it.
- Do not push unless the user explicitly directs it.

## Context discipline

- Do not recursively explore the repository before identifying the current atomic task.
- Do not reread unchanged files already inspected during the current iteration.
- Prefer targeted searches within directly relevant files and directories.
- Avoid repository-wide searches when the current task names the relevant module, symbol, action
  ID, evidence session, or test.
- Stop gathering context once all of the following are known:
  - current authoritative state;
  - current atomic task;
  - permitted actions;
  - prohibited actions;
  - directly relevant implementation;
  - acceptance criteria;
  - required verification.

- Do not load historical conversation transcripts during routine execution.
- Read a transcript only when current canonical files identify a specific unresolved contradiction
  that cannot be resolved from repository state, evidence, journals, or Git history.

## Evidence access

- Do not recursively search `evidence/`.
- Read only exact evidence sessions, transaction IDs, action IDs, or artifact paths referenced by:
  - CURRENT_HANDOFF.md;
  - the current backlog item;
  - the active journal record;
  - a directly relevant test or status file.

- Begin evidence inspection with the smallest authoritative artifact available, such as:
  - summary JSON;
  - result JSON;
  - manifest;
  - journal query output;
  - reconciliation report.

- Open individual screenshots only when visual verification is required for:
  - control geometry;
  - screen identity;
  - source or destination recognition;
  - input placement;
  - semantic postconditions;
  - contradictory evidence.

- Do not inspect historical evidence sessions merely for background or comparison.
- Do not enumerate all evidence files unless the current atomic task is specifically evidence
  reconciliation or evidence hygiene.
- Do not perform duplicate detection, evidence compaction, archive analysis, or broad evidence
  classification during ordinary implementation tasks.
- Preserve unique and decisive evidence.
- Never delete evidence unless a separately authorized evidence-hygiene task requires it.

## Live and runtime operations

- Use the checked-in operator interface and established runtime workflow.
- Do not bypass established runtime controls with ad hoc direct commands when a supported operator
  command exists.
- Before live input, verify:
  - the expected source state;
  - the exact local target;
  - target geometry in the correct coordinate space;
  - applicable authorization gates;
  - absence of unresolved consequential actions;
  - required immediate-before evidence.

- Transport success alone never proves semantic success.
- Polling and frame reacquisition are not transport retries.
- Unknown consequential outcome means stop and reconcile, never retry blindly.
- Navigation-only ambiguity must remain distinct from consequential ambiguity.
- Do not infer completion from a function return, command exit code, screen change, or full-screen
  hash alone.

## Verification

- Run focused tests first.
- Run only the validators required by the current backlog item.
- Run the authoritative full suite once when required by the task.
- Do not repeatedly run the full suite unless:
  - it failed because of a defect introduced by the current task; and
  - a specific correction has been made.

- Classify failures as:
  - newly introduced regression;
  - unchanged known baseline;
  - fixed baseline failure;
  - environment-specific blocker.

- Any new failure in touched components is blocking.
- Review the final diff before live input and before commit.
- Verify protected and unrelated files are not staged.

## Documentation and handoff

After the current task reaches a terminal result:

- update the exact backlog item;
- update CURRENT_HANDOFF.md;
- update directly affected status, plan, matrix, or runbook sections only when their state changed;
- reference the canonical evidence and journal result;
- record the next atomic task;
- avoid rewriting unrelated historical sections.

Keep CURRENT_HANDOFF.md focused on:

- current HEAD and branch;
- working-tree state;
- most recent proven result;
- unresolved actions;
- exact active blocker;
- exact current evidence paths;
- next atomic task;
- immediate permitted and prohibited actions.

Do not turn CURRENT_HANDOFF.md into a complete project history.

## Stop conditions

Stop and report the exact blocker when:

- a product or architecture decision is required;
- credentials or unsafe permissions are required;
- live interaction would violate the current authorization policy;
- a consequential action remains unresolved;
- journal or evidence integrity is uncertain;
- verification repeatedly fails without a new diagnosis;
- the runtime enters an unsafe or unknown state;
- a destructive operation would be required;
- usage limits prevent completion.

Do not broaden scope to unrelated work after reaching a valid blocked outcome.

## Hard boundaries

- Production remains entirely on Unraid.
- Never reboot or shut down the Unraid host autonomously.
- Never delete or overwrite the Bliss qcow2.
- Never modify unrelated VMs, containers, storage, or services.
- Never expose ADB or a viewer publicly.
- Never store credentials in files, scripts, logs, evidence, or command history.
- Never automate login, tutorial, account switching, credentials, or CAPTCHA handling.
- Never perform gameplay input before the relevant promotion and authorization gates.
- Unknown consequential outcome means stop and reconcile, never retry blindly.