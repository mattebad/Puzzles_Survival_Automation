# Flow product clarifications (captured 2026-07-22)

Status: CAPTURED CONTEXT ONLY. Not yet implemented. No product-policy, backlog,
contract, queue, implementation, test, or live changes have been made from this
document. This is the authoritative source of user-approved product behavior to
draw from when the corresponding atomic tasks are later activated.

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

## Read-first when activating this work
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
  -> Nanoweapon -> Craft Weapon -> Normal Craft.
- Exclusive Craft and Inherit are prohibited.
- The rotating weapon display is random and is NOT a selector.
- Normal Craft is available only when the current nano-parts state AND the
  enabled Craft control prove readiness.
- One normal Nano Weapon craft maximum per reset.
- Each craft has a static 12-hour timer.
- Completed crafts must be claimed through the normal Nano Weapon screen.
- Do NOT invent a numeric parts threshold if the enabled Craft control is the
  authoritative readiness signal.
- Material Production is a SEPARATE independent maintenance flow (see below).
- Return through the safe return path to canonical Home/Base.

### Nano Material Production (independent maintenance flow)
- Consumes NO base resources or resource boxes.
- Only one Material Production batch may be active at a time.
- Exact six-hour timer.
- When complete: claim it, then start exactly one new batch.
- Does NOT require a Daily Quest row.
- Deferred/no-op when no Material Production is ready (normal, not a failure).

## 2. Recruitment
- Check and track all three tabs.
- Basic: five free single attempts per reset; each refreshes after ten minutes
  until the five are used.
- Int: one free attempt per 24 hours.
- Advanced: one free attempt per 48 hours.
- The five Basic attempts fulfill the Daily recruitment objective.
- Int and Advanced are INDEPENDENT free-attempt maintenance actions; use whenever
  available.
- Never use 10x, premium, paid, item-backed, or ambiguous recruitment.
- Track per-tab next-eligible timestamps; do NOT wait inside one execution
  attempt for a cooldown.
- Deferred/no-op when no free recruitment attempt is ready (normal).

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
- Before each run, bind the configured stage and the current displayed AP/cost.
- Expected AP after a run = current AP minus the static stage cost; re-capture
  current AP after every run.
- Continue only while AP is sufficient for another run.
- No AP refills, purchases, premium resources, or unknown-cost actions.
- Keep Home Atlas navigation SEPARATE from AP-consuming execution.
- Deferred/no-op when AP is insufficient (normal).

## 4. Ultimate Challenge
- Keep Ultimate Challenge SEPARATE from Campaign AP farming.
- Route: Home/Base -> Campaign -> Ultimate Challenge -> Challenge -> Hero Lineup
  Challenge -> top-right Exit -> Flee -> return to canonical Home/Base.
- No AP, ticket, currency, or other resource use.
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
- Planning bound = floor(current stamina / 28), but every individual join still
  requires fresh current-frame validation.
- If stamina is below 28, do NOT pulse continuously; defer until a later normal
  Home/maintenance pulse.
- Never accept or interact with a stamina-refill prompt.
- Quick Join uses the player's existing unit configuration; automation must NOT
  alter unit composition.
- The first successful join fulfills the Daily Quest objective.
- Additional eligible joins are general maintenance.
- Track each distinct Lair join and stamina delta separately.
- Do NOT retain a standalone generic stamina-consuming flow; Zombie Lair owns
  this stamina use.

## 6. Troop Training
- Leave current training implementation and policy UNCHANGED.
- Do NOT enable Train dispatch in this task.
- Preserve the existing entry-only/navigation flow and prohibition.
- Future (separate) work: Talent Memory -> Training talent route and per-type
  once_daily/continuous configuration.

---

## Required work (for the future activation task)
- A. Update product policy records for the approved behavior.
- B. Update the relevant BACKLOG sections and flow-delivery queue metadata.
- C. Update or add per-flow gameplay contract JSONs.
- D. Separate independent maintenance flows from Daily Quest flows where required:
  - Nano Material Production maintenance
  - Recruitment free-attempt maintenance
  - Zombie Lair Home/Base maintenance
- E. Update implementations and focused tests/replay contracts for the affected flows.
- F. Add explicit deferred/no-op outcomes where "nothing available" is normal:
  - no Nano Material Production ready
  - no free recruitment attempt ready
  - insufficient AP
  - no Lair notification
  - insufficient stamina
- G. Keep live execution as a separate later stage with fresh native evidence,
  explicit action budgets, immediate-before/post evidence, journal reconciliation,
  and terminal Home proof.

## Safety and scope (for the future activation task)
- Do NOT issue BlueStacks, Bliss, ADB, scheduler, registration, or production
  input in the contract/implementation/test phase.
- Do NOT change scheduler eligibility or production registration.
- Do NOT modify protected evidence or unrelated dirty Nova work.
- Do NOT broaden scope to Gathering, purchases, upgrades, PvP, donations,
  speedups, or other policy-disabled flows.
- Use existing schemas and patterns before proposing new infrastructure.
- A flow is not live-ready merely because its product policy is explicit.
- Preserve one active flow and one writable implementation owner at a time.

## Validation (for the future activation task)
- Run focused tests for each touched flow first.
- Run governance/JSON/schema validation and diff checks.
- Report baseline failures separately.
- Do NOT rewrite tests to manufacture a pass.
- Finish with a concise report of: (1) files changed, (2) contract/policy changes,
  (3) implementation/test changes, (4) remaining evidence gates, (5) queue status
  changes, (6) exact next permitted live-execution action, (7) prohibited repeats.
