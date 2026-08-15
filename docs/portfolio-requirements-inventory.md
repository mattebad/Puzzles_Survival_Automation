# Portfolio requirements inventory

This inventory is a non-authorizing planning index. It does not register a handler, enable a
scheduler, promote a flow, authorize input, or replace a gameplay contract.

## Separate identities

Keep these identities separate in code, persistence, evidence, and policy:

- observation and navigation;
- claims and rewards;
- cooldown and reset maintenance;
- queue and facility maintenance;
- resources and progression;
- AP and stamina;
- marches and world-map actions;
- combat and challenges;
- shops and purchases;
- manual-only account/runtime states.

Evidence from one identity cannot promote another identity.

## Requirement families

| Family | Offline requirement | Current authority |
| --- | --- | --- |
| Observation/navigation | Fresh native provenance, profile/freshness, Home/Atlas localization, target binding, safe exit, successor proof | Shared perception and existing Home/Campaign semantics; no production registration |
| Claims | Identify the exact local claim and receipt/result; never confuse Go, reward, or purchase controls | Disabled progression family |
| Cooldown/reset | Bind reset identity once per session; use UTC epoch deadlines at the service boundary | Scheduler state is disabled |
| Queue maintenance | Track queue identity, timer, capacity, and completion without inventing a dispatch | Disabled progression family |
| Resources/progression | Record resource/material deltas and reserve/cap effects independently | Product decisions remain flow-specific |
| AP/stamina | Keep AP and stamina ledgers separate; no refill fallback | Campaign AP policy forbids refill; stamina family disabled |
| Marches | Track slot, target, return estimate, and occupancy separately from world navigation | Gathering and lair policy remain unresolved/disabled |
| Combat/challenges | Separate challenge setup, combat dispatch, result reconciliation, and chest/reward claims | No automatic production authority |
| Shops | Treat Cash Mall, Exchange, and paid offers as unsupported/manual-only | No purchase handler |
| Manual-only | Login, tutorial, CAPTCHA, account selection, credentials, and ambiguous identity stop automation | Permanently manual-only |

## Known stale or unresolved requirements

- Zombie level evidence has a stale `20 → 28` conflict; it is not a scheduler or action
  authorization.
- Nanoweapon requires `100` parts and a `43200` second production cadence; maintenance and
  daily collection remain separate identities.
- Material Production uses a `21600` second cadence.
- Gathering target/resource-node/march policy is unresolved and remains disabled.
- Conflicting proof states remain `evidence_required` until independently reconciled.
- Progression families (purchases, donations, speedups, upgrades, and unsupported resource
  transactions) remain disabled pending their own policy and evidence.

## Authority boundaries

The queue and gameplay contracts remain authoritative for flow semantics and historical evidence.
The disabled production registry owns only handler/profile/mode/registration/scheduler eligibility.
The automation service composes those authorities; it does not copy queue history, contract policy,
evidence state, or runner definitions.

