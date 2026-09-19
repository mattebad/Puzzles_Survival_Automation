# Offline validation and live-admission boundaries

Current development conventions are in [AGENTS.md](../AGENTS.md); setup and the selected
offline check command are in [README.md](../README.md). There is no model-routing matrix,
mandatory agent sequence, fixed review/repair cycle, or participant-attribution registry.
Offline work does not require queue activation, a delivery receipt, a frozen execution
manifest, or a manual flow ledger.

## Offline validation

- Reproduce the reported defect where practical, then run its focused regression and the
  directly affected modules. Tests use checked-in replay inputs or isolated temporary state.
- Run `python scripts/check.py` for the explicitly selected offline suite. It is not
  comprehensive coverage or native gameplay acceptance.
- Report exact commands, results, scope, and remaining failures. Do not suppress a failure,
  weaken a safety assertion, or imply that old evidence proves a current implementation.
- Use normal change review appropriate to the affected behavior. Review does not authorize
  runtime input, expand the task, or grant permission to alter protected state.
- Full-suite discovery is manual opt-in, not a routine development gate.

## Separate live authorization and existing controls

No test result, review, document, receipt, or retained capture grants live authorization.
Every live attempt needs explicit current authorization and must satisfy the applicable
existing controller/flow contract. Retiring development choreography does not remove any
code-enforced admission check, receipt requirement, candidate binding, or input budget.

- Use the supported `pnsctl` interface for the applicable runtime path; never bypass it
  through ad-hoc ADB, SSH, VM/device access, or direct transport.
- Keep one runtime operator, singleton ownership, leases, and fencing. Parallel offline
  work must not interfere with that operator or mutate runtime state or retained evidence.
- Require fresh source/target binding, supported actions, explicit budgets, and clear
  unresolved-action state before admission. Do not enable registration or scheduling as
  a side effect of validation.
- Unknown or ambiguous consequential results fail closed. Transport success is not semantic
  success. Do not retry an uncertain consequential action or repeat an input to force teardown.
- Login, tutorial, CAPTCHA, account switching, credentials, and other manual-only states
  require a human. Premium, real-money, unsupported, or unapproved actions are prohibited.
- Preserve original evidence and the source, before/action/after, semantic, and terminal
  records required by the existing contract. Do not rewrite historical proof.
- Release ownership only through the existing safe terminal path. If an unresolved action,
  unknown modal, or unsafe release remains, record the blocker and escalate without input.

See [runtime input safety](runtime-input-safety-policy.md) and
[execution ownership](chat-execution-ownership-policy.md). Existing focused, shared-navigation,
and explicitly requested full validation profiles remain available through
`scripts/run_flow_delivery_validation.py`; using them neither admits live input nor promotes
any flow. [Archived workflow records](archive/README.md) are historical, not current instructions.
