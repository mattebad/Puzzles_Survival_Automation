# Praise resume startup correction

Recorded: 2026-07-13, America/Chicago

Attempted command: `pnsctl run-task --task praise`

## Result

Current screen was the already validated Personal Might leaderboard. Startup classifier omitted
that valid resume state and incorrectly defaulted to Home. Three bounded Home-to-More source
recognition attempts failed before transport.

- Praise inputs: zero.
- Claim inputs: zero.
- Navigation inputs: zero.
- Nonterminal/unresolved actions: zero in fresh run database.

Fix: startup now positively recognizes Personal Might leaderboard, Rankings, More, or Home and
returns `UNKNOWN` for every other screen. It never defaults to Home. Resume directly at
Personal Might leaderboard skips prior navigation and reaches fresh Praise authorization.
