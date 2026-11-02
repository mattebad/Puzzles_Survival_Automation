# Stage 6 follow-on Medium migration packets

These packets are the bounded follow-on work produced by the accepted
continuous-session architecture. They do not activate a flow, authorize live
input, change product policy, or permit shared-primitives edits. Each packet is
a separate future Medium task selected explicitly after Stage 6 closure.

## Daily Claim

- Flow: `DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION`.
- Goal: bind the existing row-local Claim route to the parent-owned continuous
  `DevelopmentSession`, including typed initial observation, one transport
  count, one causal trace, semantic points/control successor, and Home terminal.
- Writable production scope: `scripts/pnsctl.py` Daily Claim dispatch seam and
  `scripts/flow_delivery_daily_row_claim_bluestacks.py` only.
- Writable tests: existing Daily Claim adapter tests plus
  `tests/test_development_session.py` and `tests/test_flow_conductor.py` only
  when a shared accepted contract needs a regression.
- Safety: Claim remains row-local; clipped, cost-bearing, non-claimable, unknown,
  or contradictory rows dispatch zero input. A dispatch-bearing unknown becomes
  reconciliation-required and cannot authorize another Claim.
- Acceptance: no pre-observe session, one active parent session, exact Claim
  ceiling, verified points/control successor, route verifier before `DONE`,
  truthful continuous/composite topology, terminal Home, registration disabled.

## Nova Praise

- Flow: `NOVA-PRAISE-SUPERVISED-ONE-FREE-PULSE`.
- Goal: carry Home Atlas navigation, delayed transition state, one Praise intent,
  semantic successor, and Home recovery through one parent-owned session.
- Writable production scope: `scripts/pnsctl.py` Nova dispatch seam and
  `scripts/flow_delivery_nova_praise_bluestacks.py`; existing Nova controller
  files only if retained evidence disproves their adapter contract and the
  Medium task is explicitly widened before mutation.
- Writable tests: `tests/test_pnsctl_nova_praise.py`, existing Nova flow tests,
  and shared session/conductor regressions only when required.
- Safety: exactly one free Praise maximum; wrong-building and false-Home
  observations fail closed; a dispatched unknown is reconciliation-required and
  never authorizes another Praise.
- Acceptance: no pre-observe session, retained delayed settling in the same
  session, exact one-Praise accounting, verified Praise successor and safe Home
  return before `DONE`, registration disabled.

## Enhancement family

- Flow: `ENHANCEMENT-FAMILY-BLUESTACKS-INTEGRATION`, variants Gear, Chip, and
  Module.
- Goal: integrate the existing adapter and retained evidence with the continuous
  session contract without consuming material merely to relabel proof.
- Writable production scope: `scripts/pnsctl.py` Enhancement dispatch seam and
  `scripts/flow_delivery_enhancement_bluestacks.py` only. Product quantities,
  exact targets, Use/Confirm semantics, and reservations remain adapter-owned.
- Writable tests: existing Enhancement delivery/session tests and shared
  session/conductor regressions only when required.
- Safety: exact target and quantity binding; Use remains selection and Confirm
  remains the consuming action; unresolved dispatch state persists outside
  process memory and blocks identical continuation.
- Acceptance: retained evidence remains `composite` unless one uninterrupted
  future session proves all three members; no additional consumption is needed
  for migration; route verifier gates `DONE`; terminal Home and registration
  disabled.

## Ultimate terminal reconciliation

- Flow: `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`.
- Goal: bind only the existing post-Flee terminal reconciliation and measured
  Campaign exit to one continuous session.
- Writable production scope: `scripts/pnsctl.py` Ultimate dispatch seam and
  `scripts/flow_delivery_ultimate_challenge_bluestacks.py` terminal-
  reconciliation seam only.
- Writable tests: existing Ultimate delivery and terminal-recovery tests plus
  shared session/conductor regressions only when required.
- Safety: retained Flee is immutable proof and is never repeated; Resource Shop
  remains false Home; Android Back from Campaign remains prohibited; an exact
  exit-dialog Cancel is the only dialog recovery; use the measured visible exit.
- Acceptance: start from retained effect state, perform zero new Flee actions,
  distinguish semantic effect from terminal completion, verify canonical Home
  before `DONE`, label prior composite evidence truthfully, registration
  disabled.

## Cross-packet monitor

`MONITOR-UNOBSERVED-EFFECT-RECONCILIATION` applies to every effect-bearing
packet. A real action may occur while the visual or semantic recognizer misses
its successor. Such an attempt must remain reconciliation-required rather than
being declared success or failure. Each migration records the observed
false-unknown signature and improves only its flow-specific observe-only
reconciliation; it must never weaken retry denial or infer an effect from
transport alone.
