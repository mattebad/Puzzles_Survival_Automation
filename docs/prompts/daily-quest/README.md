# Daily Quest implementation prompt pack

`index.json` maps every DQ backlog task to one standalone prompt. Prompts are future
implementation instructions, not runtime authorization.

Repository authority:

- `tasks/daily_quest_catalog.json`: reconciled identity, aliases, variants, observations, and
  provenance.
- `tasks/daily_quest_execution_matrix.json`: current status, policy, evidence, promotion,
  registration, persistence, and scheduler authority.
- `BACKLOG.md`: task ownership and dependencies.
- `docs/daily-quest-execution-matrix.md`: human-readable matrix.

Every prompt preserves these boundaries:

- Daily Quest only; Main Quest Claim excluded.
- Objective execution never implies ordinary row Claim or milestone Claim.
- Current-frame source/target/successor binding required for consequential work.
- GnBots coordinates and calibration are research provenance, never authorization.
- No new runtime registration, scheduler eligibility, worker wiring, live task-state row, lease,
  journal migration, ADB, evidence capture, or gameplay input during this planning boundary.
- Offline contracts, replay, mocks, and documentation continue independently.

Terminal or validated tasks use preservation/verification language. Policy-disabled tasks explicitly
remain offline-only, unregistered, scheduler-ineligible, and live-input prohibited.
