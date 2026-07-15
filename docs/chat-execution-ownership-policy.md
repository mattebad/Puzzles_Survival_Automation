# Chat and execution ownership policy

This policy governs handoffs between chats, agents, editors, and operators. It does not create a
runtime worker or authorize live input.

## Singleton ownership

- Exactly one chat or agent may own live runtime preparation, dispatch, recovery, or reconciliation
  at a time.
- Parallel live-runtime chats, recovery chats, collectors, workers, schedulers, and automations are
  prohibited, even when they appear to be observing the same task.
- An editor may work on documentation or offline tests only when it cannot mutate the runtime and
  does not overlap an active working-tree owner.

## Working-tree ownership

Overlapping editors must not modify the same files. Planning-only work may coexist when it is
read-only, cannot touch the same working tree, and cannot change runtime state. A task owner must
list staged paths, relevant unstaged paths, and protected untracked categories before handoff.

## Persistence boundary

A chat may hand off only after all of the following are true:

- no action is between `prepared` and terminal state;
- generated evidence is flushed and each artifact is referenced;
- authoritative journal state and lease state are recorded;
- staged, unstaged, and protected untracked ownership is listed;
- exact next permitted action is written to `CURRENT_HANDOFF.md`;
- actions that must not be repeated are explicit;
- runtime, if involved, is left in a recognized task-authorized state.

If any condition is unverifiable without prohibited runtime or remote operations, record
`UNKNOWN` or `NOT_VERIFIED_THIS_RUN` and stop the handoff.

## Recovery handoff fields

A recovery handoff must include:

- exact failed operation and action class;
- whether transport occurred or did not occur;
- action ID and authoritative journal record;
- current frame or exact reason it is unavailable;
- latest diagnosis;
- retry eligibility;
- prohibited repeated input;
- lease owner/status/expiry and unresolved classification.

The receiving chat must not infer a successful or failed consequential outcome from transport,
process exit, screen change, or stale prose. It must read the exact current handoff, active task, and
referenced journal/evidence artifacts first.

## Planning-only coexistence

Multiple planning conversations may coexist only when all are read-only with respect to the runtime
and each has separate working-tree ownership. A planning conversation must not register tasks,
change scheduler eligibility, mutate journals or leases, start workers, collect evidence, or issue
runtime input.
