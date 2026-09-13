# Project conventions

## Scope and truth

- This repository contains an implemented offline/runtime kernel and a smaller
  accepted live portfolio. Documentation MUST distinguish implemented code from
  live-accepted behavior.
- `CURRENT_HANDOFF.md` records volatile current state; `BACKLOG.md` and `docs/`
  hold durable plans and history. Git state and retained evidence are authoritative.
- Describe readiness, blockers, and current state from present facts. Mark missing,
  stale, or contradictory proof as `evidence_required`; never infer readiness from
  an old receipt. Legacy receipts remain historical records and do not imply a
  runtime bypass today.

## Canonical architecture and safety

- Extend the existing kernel and contracts. `safe_action_core/` retains existing
  safety, policy, leases, fencing, and resource-effect authority; `scripts/pnsctl.py`
  is the supported operational boundary when a command exists.
- `automation_service/` is the canonical runtime composition and state boundary. It
  reuses `safe_action_core` and existing task contracts; legacy `scripts/` and
  `tasks/` remain under their existing safety boundaries, and evidence never
  authorizes execution.
- Preserve runtime launchers and controllers, `ResourceEffectAuthority`, lease
  and fencing checks, registration/scheduler-disabled posture, and manual-only
  state handling. Do not create a parallel authority or compatibility bypass.
- Exactly one live runtime operator may exist. Development chats, agents, tests,
  collectors, and automation MUST NOT share or overlap a live operator.
- Every live attempt requires explicit current authorization recorded by the controller/operator; documentation, receipts, and retained evidence never grant live authority.
- The `begin-delegation` command/API requires an explicit non-empty free-form attribution; it has no default persona, provider, or model.
- Do not use ad-hoc ADB, SSH, remote shells, device access, VM access, or live
  input in offline development. Login, account switching, credentials, tutorial,
  CAPTCHA, and other explicitly manual-only states stop for a human.
- Transport success is intermediate evidence, not semantic success. Unknown or
  ambiguous consequential results fail closed; do not issue identical retries.
- Evidence and source captures are immutable historical records. Preserve the
  source, immediate-before, transport, immediate-after, semantic, and terminal
  evidence required by the applicable contract; never fabricate, rewrite, or
  delete evidence as a shortcut.

## Changes and ownership

- Make the smallest complete change for the active task. Keep edits narrow,
  cohesive, reviewable, and attributable; do not mix unrelated refactors or
  speculative abstractions.
- Use separate worktrees for independent branches. Coordinate overlapping edits;
  within a shared worktree, assign disjoint writable paths and serialize Git operations.
- Workers edit only explicitly assigned paths. Preserve unrelated user changes,
  untracked files, retained evidence, and Git history.
- Reuse existing interfaces, naming, error handling, and test patterns before
  introducing new ones. Remove obsolete callers and entrypoints during a clean
  cutover; do not leave stale discoverable tools.

## Python and tests

- Support Python 3.11 and newer. Use the standard library and existing project
  dependencies; prefer clear typed functions, explicit boundaries, and small
  deterministic units. Avoid import-time side effects and hidden global state.
- Keep production and test changes focused on the changed behavior. Tests MUST
  assert consumer-visible behavior, safety boundaries, transitions, invariants,
  and real error handling—not wording, implementation details, or ceremony.
- Run focused checks for touched components first. Full repository discovery is
  manual opt-in, not a routine gate; report baseline failures separately and
  never weaken a test to manufacture a pass.

## Documentation and Git

- Public docs must state whether a capability is implemented, offline-proven,
  or live-accepted, and must preserve current blockers and uncertainty.
- Current instructions are model/provider/persona-neutral. Historical model-specific policies and manifests belong under `docs/archive/` and are non-authoritative.
- Keep durable history separate from volatile state. Never discard unrelated
  changes or rewrite shared history without explicit authorization.
- Stage only explicitly attributable paths when authorized. Do not mutate runtime
  state, protected evidence, registration, scheduling, or deployment posture as
  part of documentation or development cleanup.
