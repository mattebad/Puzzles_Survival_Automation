# DQ-FOUNDATION-DAILY-INVENTORY

Repository authority: catalog owns observed identity; matrix owns current state; `BACKLOG.md`
owns this task. Preserve validated selected Daily-tab recognition. Exclude Main Quest Claim.

Scope: selected Daily tab and complete inventory binding for retained inventory rows only.
Do not promote Main Quest rows, documentation candidates, or synthetic fixture names. Reusable
components: `tasks/daily_quest.py`, profile anchors, safe navigation, catalog loader. Route:
home → quest → selected Daily tab.

Source recognizer: profile-backed home/quest anchors and Daily tab; target recognizer: selected
Daily tab plus row identity; successor recognizer: stable inventory frame and game-day identity.
Bind source, target, successor to one current frame before any future action. Policy: zero-cost
read-only recognition; transaction none; postcondition is complete, current Daily inventory.
Recovery: bounded read-only retry, then unresolved inventory state.

Daily admission: require raw/lossless Bliss evidence or inventory derived from it, positive Quest
screen, positive selected Daily tab, visible objective-list row, non-Main classification, and exact
source path. Unknown tab, OCR-only text, prose, GnBots definitions, and synthetic fixtures fail
closed. Map admitted rows through catalog aliases without merging semantics. Claim behavior:
none; inventory never claims. Persistence/scheduler: dormant, no task rows or eligibility.
Tests: fixture replay, alias/key coverage, selected-tab negative recognition, game-day binding,
and deterministic duplicate rejection. Bliss evidence: retain current screenshots/metadata;
GnBots geometry only provenance.

Permitted future navigation is read-only. Prohibit ADB, worker/VM lifecycle, leases, journal
migration, live evidence capture, gameplay/consequential input, registrations, and scheduler
eligibility during planning. Update status/matrix docs. Commit:
`docs(tasks): map every Daily objective to an execution task`. Preserve validated behavior and
continue offline work autonomously.
