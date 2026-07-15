# Journal and lease policy

This document defines authority and recovery boundaries for action journals. It does not authorize
runtime input or migrate existing production databases.

## Journal authority

- The authoritative operational journal is the current task's mutable operational copy used for
  lease and unresolved-action gates.
- Historical/source journals are immutable records of what an earlier run recorded. They remain
  evidence and are never edited or deleted.
- A reconciled operational copy may record a terminal classification while retaining a reference to
  the immutable source journal. Reconciliation must not rewrite source rows or imply that a later
  action happened.
- Historical unresolved snapshots do not permanently block runtime after their authoritative
  operational copy has been properly reconciled. The reconciliation record must name the source,
  action, evidence, terminal outcome, and reason.

## Action lifecycle

Consequential action records use the established lifecycle:

`prepared → input_sent → confirmed`

An action may instead become `unresolved` after transport or when a terminal positive
postcondition cannot be proven. `confirmed` and proven no-effect terminal diagnostics are terminal.
`prepared` and `input_sent` are nonterminal and require recovery before a chat or operator handoff.

Navigation-only records may use the same transport lifecycle but their reconciliation is separate.
Navigation-only reconciliation must never clear, downgrade, modify, or reinterpret a consequential
action record.

## Global unresolved gate

Before preparing any consequential action, check the authoritative operational journal for every
active `prepared`, `input_sent`, or `unresolved` consequential action. Any such record blocks new
consequential input until it is positively confirmed, manually reconciled, or classified as proven
no-effect under a recorded policy. A navigation-only diagnostic is not a consequential
unresolved-action clearance.

## Lease ownership

A lease record names the owner, acquisition time, expiry policy, current status, and release or
handoff event. Only the owner may prepare or dispatch the action while the lease is valid. Expiry
does not prove success or failure; it requires journal inspection and reconciliation. A released or
expired lease must not be silently reused for a nonterminal action.

Lease transfer requires:

- no action between `prepared` and terminal state, or an explicit recovery record;
- the exact action ID and journal path;
- current unresolved classification;
- evidence references and hash/integrity state;
- old owner release and new owner acquisition recorded in order.

## Safe chat transfer and recovery

The persistence boundary must flush evidence, record journal and lease state, list staged and
uncommitted paths, and write the exact next permitted action and prohibited repeats to
`CURRENT_HANDOFF.md`. A recovery handoff additionally records the failed operation, whether
transport occurred, action class, action ID, journal record, current frame, latest diagnosis,
retry eligibility, and the prohibited repeated input.

## Proven no-effect handling

Proven no-effect requires the action class to be navigation-only or a separately authorized
no-effect policy, preserved source/immediate-before/post evidence, an unchanged or explicitly
negative semantic state, and a terminal journal record naming the reason. It never authorizes a
consequential retry and never changes a consequential action's state.

## Consequential preparation boundary

No generic popup cleanup, account navigation, scheduler mutation, task-row migration, or
navigation reconciliation may occur while a consequential action is being prepared or dispatched.
If journal or lease authority cannot be determined from exact local records, record
`UNKNOWN`/`NOT_VERIFIED_THIS_RUN` and stop rather than probing the runtime.
