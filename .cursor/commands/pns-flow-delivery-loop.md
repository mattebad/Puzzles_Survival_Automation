Implement one selected PnS flow slice.

1. Read `AGENTS.md`, `CURRENT_HANDOFF.md`, only the active portion of `BACKLOG.md`
   above `<!-- ACTIVE_BACKLOG_END -->`, and `docs/backlog-task-contract.md`.
2. Ground the existing caller chain and reuse its implementation and storage.
   Work directly; no mandatory roles, manifests, leases, reviews, or queue ceremony.
3. Make the smallest complete change. Preserve approved gameplay policy and
   actual runtime safety; development paperwork is not a runtime prerequisite.
4. Exercise the changed behavior and relevant existing tests. Offline verification
   is not live gameplay proof. Live input and scheduler enablement require permission.
5. For authorized live work use the supported `scripts/pnsctl.py` interface,
   preserving one bot, one emulator, one active flow and bounded input/recovery.
   Stop on manual-only screens and do not blindly retry uncertain consumption.
6. Briefly update the active backlog and handoff with observed results and remaining
   limits. Preserve unrelated work and evidence. Do not commit, push, or start
   another backlog slice without the user's instruction.
