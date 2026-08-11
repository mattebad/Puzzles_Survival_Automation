# Chat and execution ownership policy

Exactly one chat, agent, worker, collector, or automation may prepare or issue runtime input. Every
live path uses `pnsctl development-session`, which owns the singleton lock for the whole bounded
flow and releases it automatically.

Parallel live-runtime work is prohibited. Offline planning may coexist only when it cannot mutate
the runtime or overlap working-tree ownership.

A handoff occurs only after the session has terminated, native evidence and the compact summary are
flushed, runtime ownership is released, and attributable staged/unstaged paths are known. Routine
inputs, recognition failures, repairs, tests, zoom attempts, combat, claims, rewards, and recovery
do not trigger `CURRENT_HANDOFF.md`, queue, or backlog rewrites. Update those artifacts only at a
flow checkpoint or genuine external blocker.
