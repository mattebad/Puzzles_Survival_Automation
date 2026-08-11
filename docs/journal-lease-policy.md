# Development session ownership and records

Ordinary gameplay development uses one session-level ownership boundary, not per-action leases or
journals.

- `pnsctl development-session` acquires the fixed cross-process runtime lock once and releases it
  automatically at terminal exit.
- The session retains compact action results and one terminal summary. It does not create
  `prepared`, `input_sent`, `confirmed`, or `unresolved` lifecycle rows.
- A failed, ineffective, or unknown interaction is development evidence. Capture the current state,
  recognize or recover, repair materially, and continue within the bounded session.
- Historical action journals remain immutable evidence but do not globally block ordinary
  development interactions.
- Daily/reset-sensitive behavior still binds to a positively established game-day identity where
  the action itself depends on that identity.
- `BACKLOG.md`, `tasks/flow_delivery_queue.json`, and `CURRENT_HANDOFF.md` are checkpoint artifacts.
  They change only for flow selection, completion, abandonment, a genuine external blocker, or a
  handoff—not for individual actions, tests, repairs, or routine recovery.
