# Working instructions

## Goal and current scope

Build a reliable personal game bot on Windows/BlueStacks first. Reuse existing flows and
integrate one useful end-to-end slice at a time. NAS/Bliss deployment is deferred.

Read `CURRENT_HANDOFF.md`, then only the relevant active section of `BACKLOG.md` above
`<!-- ACTIVE_BACKLOG_END -->`. Historical tasks, delivery queues, plans, and receipts are
reference material, not an alternate active queue. Do not read the full historical backlog
or recursively explore evidence during ordinary work.

These instructions and the approved active backlog replace the previous development workflow.
Other documents remain useful technical references; their model-role choreography, task-field
ceremony, receipt gates, and historical execution order are not mandatory development steps.
Existing gameplay approvals and concrete runtime safety limits are not revoked by this cleanup.

## Work with the user

- Work only on the selected task. Backlog approval is not permission to execute every task or
  start live gameplay. Do not resume the abandoned Supply branch or carry its changes forward.
- Do not spawn or contact subagents unless the user explicitly requests delegation for the task.
- Ask about materially different product choices or genuinely missing permissions. Use code,
  configuration, and existing decisions for facts already available; do not reopen settled policy.
- State the concrete problem, proposed correction, and observed result. Distinguish a code bug
  from missing evidence. Report uncertainty where it matters; never invent proof or completion.
- Stop repetitive attempts without progress. Show the failing assumption or relevant UI evidence
  instead of adding more gates, retries, or background investigation.

## Engineering and verification

- Prefer existing implementations and storage. Fix the smallest complete behavior, not a symptom.
  Avoid speculative abstractions, universal authority migrations, and duplicated state systems.
- For Home-building entry, follow `docs/atlas-home-entry-design.md`: use fresh Atlas
  localization, the mapped building's interaction anchor, `bind_visible_building`, and
  route-owned successor recognition. Do not add an OCR-gated or flow-specific building binder.
- For known popups, reuse the shared recognition/recovery seams in
  `scripts/bluestacks_popup_recognition.py` and `scripts/startup_recovery.py`. Do not add
  per-flow coordinate dismissers or a generic Close/Back fallback. After dismissal, recapture
  and let the active route verify its expected context; LB-09 is the canonical contextual
  mid-flow recovery contract.
- Keep the bot serial: one process controls one emulator and executes one flow at a time.
  Development paperwork, Git state, and agent orchestration do not belong in the bot runtime.
- Change shared helpers only for demonstrated needs. Retire duplicate code when its replacement
  works; do not require a portfolio-wide migration before an individual flow becomes useful.
- Bound capture, OCR, transport, recovery, and retries. A timeout must not leave accumulating work.
  Preserve useful cooldown/reset/limit state; never blindly repeat uncertain resource consumption.
- For OCR failures, inspect the exact native crops and raw OCR output before changing aliases
  or preprocessing. Check complete glyphs and crop boundaries against the image; fix geometry first.
  Validate shared extractors across multiple target labels and camera positions, not only the
  original failing frame; a new narrow crop assumption is not a general repair.
- Exercise the changed behavior and run the affected existing tests. Keep regression tests for
  plausible behavioral failures, not wording, internal wiring, or paperwork. Full-suite execution
  is explicit opt-in, not a routine edit, live-input, commit, or handoff prerequisite.
- For UI changes, inspect the actual surface and exercise the changed route when authorized.
  Offline success is not live proof; transport success is not proof of the gameplay outcome.
- Documentation-only changes need content/link/consumer checks, not game operation or a test suite.
- Use the short ticket guidance in `docs/backlog-task-contract.md`. Update backlog/handoff at
  meaningful completion or scope/blocker changes, not between ordinary inputs or debugging steps.

## Gameplay and live operation

- Preserve explicit decisions in `tasks/flow_delivery_product_policy.json`, including approved
  Lair behavior and the limited Hero Upgrade diamond exception. Resolve actual contradictions
  with the user; do not impose a new blanket zero-spend policy or enable unfinished features.
- Do not change registration, scheduler enablement, or start a live session without authorization
  for that scope. Once authorized, ordinary inputs within the scope do not need repeated approval.
- Use the existing supported BlueStacks interface (`scripts/pnsctl.py` where a command exists).
  Do not bypass resource policy or singleton ownership using ad hoc transport commands.
- The current profile is native 800x1280, package `com.global.ztmslg`, on the configured private
  local serial. Do not derive live coordinates from scaled previews, stale frames, or vendor data.
- Recognize the current target and expected successor. Carry established context through expected
  transitions; do not demand a building label hidden by its opened menu. Reacquire context after
  an unexpected transition. Use stable controls/ROIs, not exact whole-frame pixel equality.
- Ordinary claims, rewards, recruitment, maintenance, and approved in-game spending use session
  ownership, not per-action leases or a global unresolved-action lock. Keep uncertain outcomes
  local where safe; never blindly retry a consuming action.
- Real combat must remain within explicit approved scope. Real-money confirmation is unsupported
  and must be rejected. Stop at unexpected login, CAPTCHA, tutorial, credential, or account-switch
  screens instead of automating them. Unknown reset identity blocks only reset-dependent work.

## Protect work and infrastructure

- Preserve unrelated work, retained evidence, and Git history. No destructive reset, clean,
  restore, history rewrite, force-push, or evidence deletion without explicit authorization.
  Stage only attributable work; do not commit or push merely because a task is complete.
- Keep `.local-reference/`, `.local-captures/`, and protected evidence untouched unless explicitly
  in scope. Vendor material is read-only research, never runtime authority or shipped assets/code.
- Keep ADB private. Do not put secrets in source, logs, evidence, prompts, or shell history.
- Do not reboot/shut down the host or change unrelated VMs, storage, networking, containers, or
  services. Windows-first work must not mutate the deferred NAS/Bliss environment.
