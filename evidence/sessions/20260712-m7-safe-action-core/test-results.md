# M7-SAFE-ACTION-CORE test results

Recorded: 2026-07-12, America/Chicago

## Final verification

- `python -m unittest discover -s tests -v`: **44 passed, 0 failures, 0 errors**.
- `python scripts/daily_quest_bootstrap.py validate-assets ...`: **6 assets valid**, locked
  profile matched, `input_lock=false`.
- `python scripts/validate-runtime-profile.py`: manifest valid for
  `pns-blissos-poc-virgl-800x1280-v1`, canonical hash matched.
- `python -m compileall -q safe_action_core tests`: passed.
- `git diff --check`: passed before documentation finalization.

The tests cover schema creation/version rejection, transactions, durable reload, lifecycle
transitions, duplicate keys, lease contention/release/expiry/restart, unresolved takeover blocks,
all required policy denials, exactly-one mocked dispatch, pre-input drift, transport ambiguity,
verification timeout/unexpected successor, process and durable global blocks, and all required
crash boundaries. Synthetic Claim success observations are test-only.

## Preserved implementation failure

The first run executed 59 tests: 14 policy/M6 tests passed and 45 store-dependent tests errored
because Python SQLite `executescript` committed outside the surrounding transaction context.
Migration was corrected to own an explicit `BEGIN IMMEDIATE`/`COMMIT` script. The full suite then
passed. The harness was then corrected to avoid inherited duplicate store tests, and two
additional fail-closed policy/lease and post-dispatch evidence-persistence reviews brought the
final unique total to 44.

The post-dispatch review initially caused 8 executor tests to fail because the new global
nonterminal guard treated the current action's own `prepared` record as a competing block during
immediate pre-input revalidation. The guard was corrected to exclude only that current action at
that internal step; every other `prepared`, `input_sent`, or `unresolved` consequential record
continues to block. All 44 tests then passed.
