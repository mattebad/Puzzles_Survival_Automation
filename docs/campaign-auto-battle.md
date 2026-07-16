# Campaign Auto Battle route contract

This dormant offline contract extends the existing one-pulse Campaign AP model. It does not
register a task, select coordinates, or dispatch input.

## Configured route

A stage uses `tier-chapter-stage`, for example `1-20-9`. A future runtime adapter must positively
recognize all three components before Challenge:

- the selected tier (`1` or `2` at the top of the Campaign map);
- the chapter header, such as `Ch.3 Teton Ranch`;
- the exact stage dialog, such as `[3-1] Teton Ranch`.

AP cost, current AP, an explicit AP budget, and a maximum run count are mandatory. Whole runs are
planned as the minimum of available AP, budget, and run cap. Refills and unknown costs fail closed.

## Captured route

The local BlueStacks session
`.local-captures/bluestacks/consume-ap-campaign/20260716T014118395232Z/` established this sequence:

1. Home/Base to Campaign.
2. Campaign tier/chapter map.
3. Exact stage selection (`[3-1] Teton Ranch`, 20 AP).
4. Hero Lineup and Challenge.
5. Active battle and explicit Auto enablement.
6. Screenshot polling while battle remains active.
7. Success only when `WINNER`, `Loot`, and `Tap to continue` are jointly recognized.
8. Continue, verify the exact AP delta, and repeat only while the bounded plan permits.
9. Finish at Home/Base. An explicit loss returns home and disables repeats.

Battle duration is deliberately not modeled as a fixed sleep. Polling timeout or an unknown result
is unresolved/blocked, never success.

## Promotion gaps

Before a live Bliss adapter can be promoted, capture and validate:

- exact tier 1 to chapter 20 navigation;
- stage 20-9 visibility/selection and its current AP cost;
- the defeat screen and its safe return control;
- insufficient-AP behavior without opening a refill flow;
- Bliss-native 800x1280 source, target, immediate-before, and successor evidence for each input.

BlueStacks frames are route-translation sources only. Runtime registration and scheduler eligibility
remain disabled.
