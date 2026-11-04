# Runtime input safety policy

This project is in active development. Planned gameplay is ordinary development interaction and is
run through `scripts/pnsctl.py development-session`; there is no per-action consequential lifecycle.
Real-money Cash Mall confirmation is unsupported.

## Session boundary

- `pnsctl` automatically validates the expected package and native 800×1280 runtime, acquires the
  singleton runtime lock, creates one compact local session record, applies bounded input limits,
  writes a terminal summary, and releases ownership on normal or exceptional exit.
- A session may contain navigation, taps, swipes, zoom, Back, dialogs, claims, rewards, recruitment,
  resource collection or spending, Zombie Lairs, zombie attacks, other combat, challenges,
  maintenance, recovery, and complete end-to-end flow execution.
- No ordinary action requires queue activation, a per-action lease, a prepared/input-sent/reconciled
  journal, a global unresolved record, zero-transport replay, production preflight, manual attempt
  increments, or persistent-artifact mutation.

## Fixed paths and retained evidence

`safe_action_core.path_safety` inspects every existing path component with `lstat`;
dangling links are not treated as missing files. Fixed orchestrator paths still
must equal their configured lexical path, and evidence paths remain constrained
to the caller's evidence root.

Only Darwin's exact `/var` → `/private/var` and `/tmp` → `/private/tmp` OS aliases
are eligible for substitution. The alias must be root-owned, its target text must
match, and `/`, `/private`, and the target must be real root-owned directories
protected from group/other writes. Only the exact `/private/tmp` target permits
the normal sticky, writable temporary-directory mode. User-owned descendant
directories are valid, but every descendant symlink is rejected, even if that
link is root-owned. Other platforms do not inherit the Darwin exception.

The orchestrator, startup-recovery references, Campaign recovery, and Ruins and
Bioenhancer evidence guards reuse this check; their containment and error
boundaries remain authoritative. Evidence consumers canonicalize only after raw
component validation, preserving Windows short-path aliases without hiding links.
Parent steps cannot erase prior link checks, and a missing component does not
hide later components reached after a parent step.
These are path checks, not an atomic defense
against filesystem changes between validation and use. Darwin alias policy has
deterministic offline boundary coverage; native macOS runtime proof remains
`evidence_required`. No filesystem receipt authorizes live input.

## Action-specific checks

- Use a fresh raw 800×1280 frame when the action requires visual binding. Bind visible targets from
  that frame, translate crop-local geometry to full-frame coordinates, and reject out-of-bounds or
  unsafe overlay intersections.
- Home zoom requires the expected package, sufficient current native Home context, and bounded
  gesture geometry. It does not require canonical Atlas localization or an off-screen building.
- A target tap needs current-frame evidence sufficient to bind that target. A tested fixed-screen
  control may use its action-specific binding without unrelated whole-flow source gates.
- Transport success alone is not semantic success. Capture useful immediate-post evidence and
  recognize the successor. Unknown results trigger bounded recognition or recovery inside the same
  session.
- Do not repeat an identical ineffective input. Continue only after a concrete diagnosis and a
  materially changed implementation or condition.

## Android Back

- Android Back is not a generic return-Home operation. On top-level Base/Home, World, and Campaign
  surfaces it is prohibited unless a future state-specific experiment proves otherwise; current
  Base/Home-radial and Campaign evidence shows that it can open `Exit the game?`.
- A Back dispatch from a nested menu or overlay is authorized only when the exact source state has
  retained native immediate-before and successor frames proving that transition. Similar-looking
  screens, semantic fixtures, synthetic tests, and successor-only Home recognition are not proof.
- Unproven Back transitions are `evidence_required` and dispatch zero input. Prefer a freshly bound
  visible in-game back or exit control.
- If `Exit the game?` appears, Confirm is forbidden. Only an exact current-frame Cancel binding may
  recover, followed by fresh state recognition.
- Track state-specific evidence and active call-site status in
  [`android-back-state-matrix.md`](android-back-state-matrix.md).

## Cash Mall stop

If a path reaches a real-money Cash Mall payment surface, it may observe or safely leave the surface
but must reject the payment confirmation before transport. Do not create approval or journal
infrastructure for real-money purchasing.

## Delegated receipts and reservations

Reconnaissance receipts permit only zero-input observation or an explicitly enumerated bounded
navigation manifest. Purchases, claims, crafts, donations, upgrades, item or resource use,
marches, combat dispatch or confirmation, premium currency, and real-money confirmation are
forbidden; reconnaissance resource and combat budgets are always zero.

Canary receipts are exact, non-widenable manifests. Before a canary session, the controller must
bind the clean candidate fingerprint and all three pre-canary gates: implementation self-check,
independent read-only tester evidence, and parent integration acceptance. The receipt is consumed
before runtime acquisition and cannot be reused.

Before every delegated input transport, the controller durably reserves the ordinal, action
identity and class, consequence class, source-frame hash when available, and budgets. Dispatch
exceptions, crashes, timeouts, unknown successors, and missing post evidence leave the reservation
unresolved and require `evidence_required`; budgets are never refunded and an identical retry is
denied. A delegated dry-run consumes its receipt without runtime access. A delegated zero-input
observation acquires the normal singleton, retains native evidence, writes a receipt-bound result,
and releases ownership normally or exceptionally.
