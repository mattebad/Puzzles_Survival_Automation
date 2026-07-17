# DQ-FLOW-CAMPAIGN-AUTO-BATTLE

## Repository authority

`BACKLOG.md`, `CURRENT_HANDOFF.md`, the working tree, and retained evidence are authoritative.

## Scope

Maintain the dormant configurable Campaign Auto Battle contract. Route configuration binds an
exact tier, chapter, stage, AP cost, AP budget, and run cap.

## Route and evidence

Source recognition, the exact target, and every successor must be fresh and semantic. Policy
forbids refills, premium currency, ambiguous gameplay input, and a second dispatch after an
unresolved result.

## Postcondition and recovery

Postcondition success requires a recognized battle terminal plus exact AP reconciliation. Recovery
unwinds loss, insufficient AP, or timeout through chapter, tier, and Home without another battle.

## Daily, Claim, and persistence

Daily progress is state output only. Claim remains separate and dormant. Persistence records the
configured route and AP ledger; production registration, scheduler eligibility, and promotion stay
disabled.

## Tests and Bliss boundary

Tests cover route parsing, budgeting, win/loss/timeout behavior, AP regeneration, and Claim
separation. BlueStacks validation does not authorize Bliss input.

Commit: `feat(tasks): model Campaign Auto Battle route`.
