# Noah's Tavern Recruitment

Recruitment has two distinct product identities that reuse one retained Noah's Tavern route and
one set of tier, free-control, result-overlay, and Home-return primitives:

- **Recruitment Daily objective:** complete the current reset with five **Basic** free single
  recruits, one per availability window. Int. and Advanced never own Daily completion.
- **Free-attempt maintenance:** inspect Basic, Int., and Advanced independently and use every
  currently available free single. This maintenance continues after Daily completion.

Neither identity is registered for production or eligible for scheduling. Recruitment Claim,
paid recruitment, premium recruitment, item-backed recruitment, ambiguous prices, and all 10x
controls remain outside both flows.

## Retained gameplay and mechanics evidence

The retained session
`evidence/sessions/20260716-noahs-tavern-daily-free/record.md` is valid gameplay/mechanics and
semantic navigation evidence. Through Computer Use it demonstrated Home → Noah's Tavern, enabled
free controls on all three tiers, three Basic free singles, one Int. free single, one Advanced free
single, safe result-overlay closure, Daily progress reaching 5/5, and return to Home. No Daily Claim
control was selected.

The record retains semantic frame identifiers because the Computer Use workflow did not copy its
screenshots into the repository. It is therefore not raw hash-bound screenshot evidence, a
consequential journal, a manifest, or a production-controller attempt record. It proves the
observed gameplay mechanics without proving a production-grade automated replay or authorizing
registration, scheduling, or another consequential attempt.

| Tier | Free availability policy | Retained post-action timer | Exact cooldown policy |
| --- | --- | --- | ---: |
| Basic Recruit | Five free singles per game-day/reset, one per window | `Free in 00:09:52` | 600 seconds |
| Int. Recruit | One free single when independently available | `Free in 23:59:51` | 86,400 seconds |
| Adv. Recruit | One free single when independently available | `Free in 1d23:59:52` | 172,800 seconds |

The displayed values were remaining timers captured after successful recruits. The exact policy
durations are 600, 86,400, and 172,800 seconds; due-time persistence must use those tier-specific
durations while current displayed availability is still verified before any action.

## Daily objective contract

The Daily identity starts from canonical Home, enters Noah's Tavern, selects Basic, and authorizes
only a visibly enabled, explicitly zero-cost single. One Basic recruit may be initiated per
availability window until five Basic recruits are confirmed for the current reset. A cooling Basic
tab returns an explicit deferred outcome with its next due time; an exhausted tab defers without
substituting a paid recruit. An already-complete reset is idempotent. Every pass must finish at
canonical Home, and ordinary Daily Claim remains separate.

The retained session's mixed three-Basic/one-Int./one-Advanced 5/5 result proves that free recruits
advance the objective, but it does not prove the final five-Basic production replay. That proof
remains evidence-gated.

## Free-attempt maintenance contract

Maintenance always inspects all three tabs. Basic, Int., and Advanced availability and due times
are persisted independently. Every currently available free single is used once; cooling or
exhausted tabs produce explicit deferred/no-op outcomes. Daily completion does not stop Int. or
Advanced maintenance, and those tiers never substitute for Basic Daily ownership. The pass returns
to canonical Home after all three tabs are handled.

## Existing implementation to reuse

`tasks/free_recruitment.py` and `tasks/daily_recruitment.py` provide the retained pure free-single
and five-count offline contracts. `tasks/noahs_tavern_recruit.py` provides tier identities, exact
zero-cost authorization, result postconditions, and independent tier state;
`tasks/noahs_tavern_recruit_vision.py` provides native OCR/color recognition;
`tasks/noahs_tavern_recruit_runtime.py` provides the dormant one-command-at-a-time controller; and
`scripts/noahs_tavern_recruit_bluestacks.py` provides the dry-run-by-default integrated route and
the navigation-only Home → Tavern → Home adapter.

The integrated route already supports Home entry, tier selection, one or more free recruits, safe
result closure, cooldown observation, duplicate guards, unresolved-result reconciliation, and Home
return. The separate navigation route has scripted offline replay coverage and excludes the
consequential recruit target. These primitives must be extended, not rebuilt.

Remaining integration work is narrow but consequential: make the Daily adapter Basic-only and
availability-window aware; keep maintenance active after Daily completion; treat the controller's
due-time signal as deferred persistence rather than scheduler promotion; and produce explicit
cooldown/exhausted no-op outcomes. The exact cooldown constants must be enforced by policy while
retained timer OCR continues to verify current availability.

## Promotion boundary

Offline synthetic fixtures exercise free-only authorization and five-count semantics, and scripted
tests exercise the navigation route. They are not substitutes for native evidence. Production
promotion still requires hash-bound source/immediate-before/transport/immediate-post/result/Home
evidence, a consequential journal and attempt record, and a positive replay through the production
recognizer, controller, policy, persistence, and postcondition path. A later separately authorized
supervised consequential canary remains required.

The executable local adapter remains dry-run by default. Even with its explicit execution flags,
its existence does not constitute production registration or scheduler eligibility. Ambiguous
results are persisted unresolved, never retried identically, and permit only bounded recovery from
a positively recognized safe state.
