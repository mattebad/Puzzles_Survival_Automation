# Alliance Help semantic correction and lower Help All attempt — 2026-07-13

- Historical `(641,302)` action: `ALLIANCE_HELP_ONE`, upper label Help, one request processed.
- Actual lower target: `ALLIANCE_HELP_ALL`, ROI `(277,1188)-(523,1268)`, center `(400,1228)`.
- Pre-dispatch artifact: literal `Help All`, valid lower geometry, no individual-region overlap, interior tap.
- Dispatch: exactly one `input tap 400 1228`; no retry.
- Postcondition: the first post-tap frame positively contains the transient exact message `No help request currently`; later frames returned to Speedup Help. This confirms the actual lower Help All control was activated and that no request was available.
- Journal: the immutable source remains retained; the schema-1 reconciled copy records action `alliance-help-1783986842` as `confirmed` with `positive_postcondition`, zero unresolved/nonterminal actions, and a released lease.
- Tests: focused 7 visual + 14 task-contract + 9 CLI/catalog passed; one authoritative pinned full suite passed 119 tests.
- RT-019 passed; all six M6 assets passed.
- Cleanup: scoped worker/task ADB removed, no public listener or tunnel, VM running, RT-017 intact.
- Outcome: `BLOCKED` with `NO_HELP_REQUEST_CURRENTLY`; the actual lower Help All control is live-validated, but the Daily Quest objective remains incomplete and no Claim is authorized.
