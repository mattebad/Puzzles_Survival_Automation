# DQ-FLOW-ALLIANCE-HELP

Repository authority: catalog owns `help_allies`; matrix owns current status,
Policy, registration, and scheduler eligibility; `BACKLOG.md` owns the task.
Historical Bliss Help All and individual Help evidence remains immutable but
does not authorize current gameplay.

Scope: selected-Daily completion attribution only. Route: none; the provider
must not navigate to Alliance Help. Source: the positively selected Daily
`help_allies` progress row. Target: none. Successor: selected-Daily progress
reaches the completion target after independently performed gameplay.

Postcondition: objective completion is attributed from current Daily progress.
Recovery: fail closed as incomplete when progress or objective identity is
unreadable; never navigate, bind a Help control, dispatch, or retry gameplay.
Daily Claim remains the separate aggregate one-tap action. Persistence is
offline-only. Registration is `NOT_REGISTERED`; scheduler eligibility is
disabled.

Tests: verify progress parsing/completion attribution and absence of route,
target, action, Claim, registration, and scheduler authority. Prohibit live
input, ADB, worker/VM changes, lease/journal changes, and new registration.
Commit: `docs(tasks): map every Daily objective to an execution task`.
