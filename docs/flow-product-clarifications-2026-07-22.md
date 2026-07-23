# Flow product policy (approved 2026-07-22; reconciled 2026-07-23)

Status: APPROVED PRODUCT POLICY. This document retains the human-readable approved decisions
reconciled into product policy, backlog, queue, contracts, and coverage by the 2026-07-23 offline
atomic task. Machine-readable authorities remain the product-policy registry and gameplay
contracts. Implementation and evidence states remain independently gated; this policy does not
authorize runtime input, registration, or scheduler eligibility.

Reference pattern: the just-repaired Nova Praise flow (implementation, tests,
evidence, handoff) is the reference. Do not reopen or regress Nova unless a
shared contract dependency requires it.

## Guiding principle: stage separation
Flow delivery must keep three stages explicitly separate. Do NOT bundle live
execution authorization into implementation or unit tests.
1. Product contracts (what the flow is allowed to do).
2. Offline implementation + tests + replay contracts.
3. Live execution + fresh native evidence (separate later stage, its own
   authorization, action budgets, immediate-before/post evidence, journal
   reconciliation, terminal Home proof).

A flow is NOT live-ready merely because its product policy is now explicit.
Live readiness still requires focused validation and fresh flow-specific evidence.

## Read-first for later implementation or evidence work
- AGENTS.md
- CURRENT_HANDOFF.md
- BACKLOG.md (only the relevant flow sections)
- tasks/flow_delivery_queue.json
- tasks/flow_delivery_product_policy.json
- tasks/gameplay_flow_contracts/*.json for the affected flows
- the existing Nova Praise implementation/tests/contracts

---

## 1. Nanoweapon
- Route: Home/Base -> Gear Factory -> Gear Factory radial -> Gear Factory screen
  -> Nanoweapon -> Normal Craft.
- Use Normal Craft only. Exclusive Craft is prohibited; Inherit is outside this flow.
- The rotating weapon display is random and is NOT a selector.
- Normal Craft is available only when nano parts are at least 100 out of 100 AND the enabled Craft
  control proves readiness. One craft requires exactly 100 nano parts.
- One normal Nano Weapon craft maximum per reset.
- Exactly one craft may be active at a time and each craft duration is exactly 12 hours.
- Claim a completed weapon when entering the Nanoweapon screen.
- Starting another craft in the same reset has no Daily benefit and is prohibited.
- Insufficient parts or a disabled Craft control produces a deferred/no-op result without resource
  consumption.
- Material Production is a SEPARATE independent maintenance flow (see below).
- Return through the safe return path to canonical Home/Base.

### Nano Material Production (independent maintenance flow)
- Enter the Nanoweapon screen and select Material Production.
- Consumes NO base resources, resource boxes, currency, or items.
- Only one Material Production batch may be active at a time.
- Exact six-hour timer.
- When complete: claim it, then start exactly one new batch.
- When active: record or refresh its due time and defer.
- When available and idle: start it.
- Does NOT require a Daily Quest row.
- Deferred/no-op while active is normal, not a failure.
- Return to canonical Home/Base.

## 2. Recruitment
- Check and track all three tabs.
- Basic: five free single attempts per reset; each refreshes after ten minutes
  until the five are used.
- Int: one free attempt per 24 hours.
- Advanced: one free attempt per 48 hours.
- The five Basic attempts fulfill the Daily recruitment objective.
- Daily completion requires five Basic free recruits, one per availability window; Int and
  Advanced do not own Daily completion. Already-complete Daily behavior is idempotent.
- Int and Advanced are INDEPENDENT free-attempt maintenance actions; inspect all three tabs and use
  every currently available free single whenever maintenance runs.
- Never use 10x, premium, paid, item-backed, or ambiguous recruitment.
- Never substitute a paid recruit when a free recruit is unavailable.
- Track per-tab next-eligible timestamps; do NOT wait inside one execution
  attempt for a cooldown.
- Cooling-down and exhausted tabs produce explicit deferred/no-op outcomes.
- Return to canonical Home/Base after the maintenance pass.

## 3. Campaign AP
- Keep the approved Story destinations exactly:
  - 1-15-9 costs 14 AP
  - 1-20-9 costs 16 AP
  - 2-2-9 costs 20 AP
- The configured stage must be navigated to again each time Campaign is entered;
  do NOT assume the prior stage remains selected.
- Use Auto Battle ONLY. Sweep, Blitz, and Auto Complete are prohibited for this
  route.
- Maximum AP is 120.
- AP regenerates at exactly one AP per 360 seconds.
- Before each run, bind the configured stage and the current displayed AP/cost.
- Expected AP after each run equals current AP minus the static stage cost; track that expectation
  and re-capture current AP after every run.
- Run as many configured-stage Auto Battles as current AP safely permits.
- Home scheduling may estimate recovery, but displayed AP and cost remain mandatory before input.
- No AP refills, purchases, premium resources, or unknown-cost actions.
- Keep Home Atlas navigation SEPARATE from AP-consuming execution.
- Deferred/no-op until calculated recovery when AP is insufficient (normal).
- Return to canonical Home/Base.

## 4. Ultimate Challenge
- Keep Ultimate Challenge SEPARATE from Campaign AP farming.
- Route: Home/Base -> Campaign -> Ultimate Challenge -> Challenge -> Hero Lineup
  Challenge -> top-right Exit -> Flee -> return to canonical Home/Base.
- No AP, stamina, ticket, currency, item, or other resource use.
- Do not Auto Battle this flow.
- Flee counts as the successful daily Ultimate Challenge action.
- Already-completed in the current reset is a valid terminal no-op.
- Return to canonical Home/Base is mandatory before terminal success.
- Ambiguous Flee/result/Home recovery is UNRESOLVED and must not be retried.

## 5. Zombie Lair
- Replace the static Daily-row-first assumption with a Home/Base maintenance pulse.
- Source is the in-game Lair notification panel visible from canonical Home/Base.
- If no eligible Lair notification exists, return DEFERRED / NO_LAIR_AVAILABLE.
  This is NOT a failure and consumes no attempt.
- Eligible levels are 30 through 55 inclusive. Level 60 is prohibited.
- Each eligible Lair costs 28 stamina.
- If multiple eligible Lairs are present, join as many as current stamina allows.
- Planning bound is `min(eligible_lair_count, floor(current stamina / 28))`; if stamina permits only
  one of multiple eligible Lairs, join one. Every individual join still requires fresh
  current-frame validation.
- If stamina is below 28, do NOT pulse continuously; defer until a later normal
  Home/maintenance pulse after tracked recovery predicts at least 28 stamina.
- Never use a stamina refill. Cancel or leave a refill prompt safely without consuming anything.
- Quick Join uses the player's existing unit configuration; automation must NOT
  alter unit composition.
- The first successful join fulfills the Daily Quest objective.
- Additional eligible joins are general maintenance.
- Track each distinct Lair join and stamina delta separately.
- Do NOT retain a standalone generic stamina-consuming flow; Zombie Lair owns
  this stamina use.
- Return to canonical Home/Base or an explicitly recognized safe Home-equivalent terminal.

## 6. Troop Training
- Leave current training implementation and policy UNCHANGED.
- Do NOT enable Train dispatch in this task.
- Preserve the existing entry-only/navigation flow and prohibition.
- Future (separate) work: Talent Memory -> Training talent route and per-type
  once_daily/continuous configuration.

---

## Reconciliation disposition and remaining work

The approved decisions are closed in policy. Daily and maintenance identities are distinct for
Nanoweapon, Recruitment, and Zombie Lair; Campaign AP and Ultimate Challenge remain distinct.
Offline implementation and evidence status must remain truthful per coverage and queue.

Later atomic implementation/replay tasks must:

- update only the narrow implementations and focused replay tests needed for the activated flow;
- preserve and reuse retained Recruitment and Campaign work;
- preserve explicit deferred/no-op outcomes where nothing is available:
  - no Nano Material Production ready
  - no free recruitment attempt ready
  - insufficient AP
  - no Lair notification
  - insufficient stamina
- keep live execution as a separate later stage with fresh native evidence,
  explicit action budgets, immediate-before/post evidence, journal reconciliation,
  and terminal Home proof.

## Safety and scope for later tasks
- Do NOT issue BlueStacks, Bliss, ADB, scheduler, registration, or production
  input in the contract/implementation/test phase.
- Do NOT change scheduler eligibility or production registration.
- Do NOT modify protected evidence or unrelated dirty Nova work.
- Do NOT broaden scope to Gathering, purchases, upgrades, PvP, donations,
  speedups, or other policy-disabled flows.
- Use existing schemas and patterns before proposing new infrastructure.
- A flow is not live-ready merely because its product policy is explicit.
- Preserve one active flow and one writable implementation owner at a time.

## Validation for later tasks
- Run focused tests for each touched flow first.
- Run governance/JSON/schema validation and diff checks.
- Report baseline failures separately.
- Do NOT rewrite tests to manufacture a pass.
- Finish with a concise report of: (1) files changed, (2) contract/policy changes,
  (3) implementation/test changes, (4) remaining evidence gates, (5) queue status
  changes, (6) exact next permitted live-execution action, (7) prohibited repeats.
