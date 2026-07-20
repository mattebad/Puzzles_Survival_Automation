# Permanent agent invariants

## Authority and context discipline

- Repository state, Git history, the working tree, authoritative operational journals, and canonical
  retained evidence are authoritative.
- `BACKLOG.md` is authoritative for task status, ordering, dependencies, blockers, authorization,
  verification, and completion criteria.
- `CURRENT_HANDOFF.md` is the primary entry point for volatile current state and is not project
  history. Conversation transcripts are historical context only.
- Do not read `BACKLOG.md` or the canonical plan in full during routine work. Locate only the active
  task, direct dependencies, and exact referenced plan sections.
- Do not recursively explore `evidence/` or reread unchanged files. Stop context gathering when
  state, task, authorization, dependencies, and acceptance criteria are established.

## Atomic execution

- Complete only the active atomic backlog task. Do not begin downstream or unrelated work after
  completion or a valid blocker.
- Exception: the named development flow-delivery orchestrator may advance from one completed
  atomic flow to the next only after the prior flow has a terminal runtime state, reconciled
  evidence, passing required tests, a focused commit, a clean attributable tree, and an atomic
  queue transition. It may never have two active flows, two writable agents, or concurrent
  BlueStacks operators.
- Preserve passed experiments, valid uncommitted work, retained evidence, and Git history. Do not
  repeat passed experiments without contradictory evidence.
- Update and stage only files directly attributable to the active task.

## Runtime singleton and interface

- Exactly one live runtime operator may exist. No concurrent chat, agent, worker, collector,
  automation, or test may prepare or issue runtime input.
- Use `scripts/pnsctl.py` as the sole supported operational interface when a command exists. Do not
  bypass policy with ad hoc ADB, plink, Docker, remote shell, or temporary runtime scripts.
- ADB must remain private and non-public.

## Fixed runtime and manual-only states

- Production runtime is the Unraid-hosted Bliss OS VM, package `com.global.ztmslg`, logical profile
  800×1280 at 160 dpi. Live coordinates use raw full-frame 800×1280 evidence only.
- Never derive coordinates from scaled previews, stale captures, untranslated crops, or vendor
  coordinates.
- Login, tutorial, CAPTCHA, account selection/switching, credential entry, and other explicitly
  manual-only account states must never be automated.

## Live target and action safety

- Positively recognize the source, bind the exact local target from a current raw frame, capture and
  revalidate immediately before dispatch, and require full-frame bounds/overlay checks.
- Rebind a moved target only through a narrow evidence-supported policy; generic rebinding is
  forbidden. Transport success never proves semantic success.
- Navigation-only and consequential actions are distinct. Consequential actions normally allow one
  authorized transport input; ambiguous results become unresolved and are never blindly retried.
- Do not issue identical retries. Continue diagnosis only with a concrete new hypothesis, corrected
  logic, or materially different conditions. Disable generic popup cleanup during consequential
  preparation and dispatch.
- See [`docs/runtime-input-safety-policy.md`](docs/runtime-input-safety-policy.md) for the complete
  procedure.

## Journals, leases, and game-day binding

- Preserve the established journal lifecycle and lease policy. Check the global active-unresolved
  gate before consequential dispatch.
- Keep operational journal authority distinct from immutable historical/source evidence. Reconcile
  navigation-only records without changing consequential records; historical unresolved snapshots
  do not permanently block a properly reconciled operational copy.
- Bind Daily tasks, state, evidence, and authorization to a positively established game-day/reset
  identity. Unknown or stale cycles do not authorize work.
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
- Preserve the minimum evidence sequence: source, immediate-before, transport, immediate-post,
  semantic result, journal reference, and unresolved proof when applicable.
- Do not delete or compact evidence during ordinary work. Evidence hygiene requires dry-run
  classification, archive-before-removal, and verification through its dedicated workflow. See
  [`docs/evidence-retention-policy.md`](docs/evidence-retention-policy.md).

## Chat ownership and handoff

- Hand off only after no action is between prepared and terminal state, evidence is flushed and
  referenced, journal and lease state are recorded, staged/uncommitted ownership is listed, the
  exact next permitted action and prohibited repeats are in `CURRENT_HANDOFF.md`, and runtime is
  left recognized and task-authorized.
- Recovery handoffs record the failed operation, whether transport occurred, action class/id,
  journal record, current frame, diagnosis, retry eligibility, and prohibited repeated input.
- Parallel live-runtime chats are prohibited. Planning-only work may coexist only when it cannot
  touch the same working tree or runtime. See
  [`docs/chat-execution-ownership-policy.md`](docs/chat-execution-ownership-policy.md).

## Hard infrastructure boundaries

- Production remains on Unraid. Never autonomously reboot/shut down the host, replace the Bliss
  qcow2, or modify unrelated VMs, containers, storage, networking, or services.
- Never expose ADB/viewers publicly or place credentials in files, code, logs, evidence, prompts, or
  shell history.
- Do not create generic execution, live-action, or recovery prompt templates.
