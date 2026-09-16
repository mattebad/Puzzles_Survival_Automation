# Backlog task guidance

The active backlog is the section of `../BACKLOG.md` above `<!-- ACTIVE_BACKLOG_END -->`.
It describes user outcomes, not a runtime authorization system or a development ceremony.

## A useful ticket

Give the task a clear title and status, then record:

- **Problem:** What is wrong or missing?
- **Outcome:** What should the user or bot be able to do when this is finished?
- **Code/docs:** Relevant files or existing implementation, when known.
- **Check:** The observable result that will establish completion.

Split an implementation ticket when it combines independently selectable work. The active
backlog's gameplay groups are a feature inventory, not a requirement to implement them all
at once. Preserve distinct behavior when sharing an implementation across variants.

Add dependencies, unresolved choices, or concrete spending/live-input limits only when they
matter to that task. Reuse approved policy; do not copy it into dozens of fields or ask the
user to approve it again. Backlog approval alone does not start a live session.

## Completion and history

Record what changed, what was actually exercised, and any remaining relevant limitation.
A selected handler, transport success, passing mock, receipt, or old completed status does
not establish successful gameplay. Keep tests for real behavioral risks; avoid test-count
requirements and project-wide qualification ladders.

The historical backlog is reference material. It does not need migration to this format.
There is no required agent-role sequence, evidence manifest for a documentation task,
per-commit allowlist, standalone activation transition, or mandatory 19-field-plus contract.

Existing governance utilities still encode the former workflow; they are not acceptance gates
for this active backlog. Do not rewrite them merely to make the new prose pass an obsolete
schema. Remove or adapt a real dependency when the selected implementation encounters it.
