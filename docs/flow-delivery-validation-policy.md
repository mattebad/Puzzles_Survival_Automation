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

## Continuous-integration coverage

Routine PR checks inventory the complete suite but execute the declared baseline
and affected selection in `scripts/offline_selection.py`. Windows retains shared
consequential contracts and representative supported-route integrations. Linux
retains distinct process/worker, filesystem, SQLite and tooling protection. A changed
test module runs in full; route dependencies expand the relevant family and static
import consumers. Shared surfaces use their owning tests plus consumer boundaries,
rather than every historical variant through every route. Uncertain impact requests
explicit full-fallback execution.

Each existing per-OS required job executes and verifies its own receipt. Verification
recomputes discovery and the selection independently and rejects missing/repeated or
unexecuted intended cases, failures, foreign policy/revision/attempts, undisclosed
omissions and new skip IDs. A partial selection cannot claim full execution. Timing
weights remain scheduling estimates, never selection allowlists.

After merge, the workflow schedules full regression daily at 08:23 UTC and makes it
available explicitly through workflow dispatch or `ci:full`. It is not another default pre-merge bottleneck. Deferred
portability/fixture/rare-branch failures may survive an unrelated merge until the
next successful full run (normally within 24 hours plus queue/runtime; longer if a
schedule fails). Extra fresh-process Supply stress is manual diagnostic coverage;
there is no automatic detection bound for failures unique to repeated startup.

The developer command remains usable. Its environment helper is shared by the CI
runner; CI sets hash/user-site flags before interpreter startup and scrubs runtime
selectors before discovery. Focused entrypoint tests cover its real child launch
and errors, replacing the duplicate controlled semantic rerun. Hygiene checks remain.
Local full execution is opt-in. See the [issue #51 implementation ledger](validation/issue-51/README.md).


## Static debt ratchets

`python -B scripts/check_static.py` runs the pinned Ruff/Vulture checks on active
Python sources and mypy on all of `safe_action_core/` and `automation_service/`.
The committed baseline is existing debt, not suppression or a clean type-check
claim. Every file/error-code allowance must stay equal or shrink; new files and
rules start at zero. When a finding disappears, run the command with
`--refresh-baseline` and commit the lower allowance. Refresh refuses increases.

Routine CI enforces these gates on Linux; full validation also runs them on Windows.
It compares the committed allowances with the base revision so a baseline increase
cannot conceal a regression. Windows-specific analyzer differences may be detected
by the next full run. The initial counts, explicit
shrinking type-debt list and scope are in
[the issue #39 validation record](validation/ticket-39/README.md).
Import-direction policy remains issue #22, not a second rule set in this checker.

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
[execution ownership](chat-execution-ownership-policy.md). Run the focused unittest modules for
the changed component directly; validation neither admits live input nor promotes any flow.
[Archived workflow records](archive/README.md) are historical, not current instructions.
