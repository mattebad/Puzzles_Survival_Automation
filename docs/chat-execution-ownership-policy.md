# Runtime execution ownership

Exactly one runtime operator may prepare or issue input. Planning chats, workers, tests,
collectors, and automation must not overlap that operator. Explicit current authorization
and the existing runtime ownership, lease, and fencing checks are required; documentation,
participant labels, review results, and historical evidence grant no authority.

Use the supported `pnsctl` boundary for the applicable runtime path. Do not use ad-hoc ADB,
SSH, VM/device access, or direct transport to bypass admission. Offline development does not
require a runtime owner, queue activation, delivery receipt, or prescribed agent choreography.

## Existing delegated runtime controls

Where a retained legacy runtime path uses delegated receipts, its existing checks remain in
force. The controller binds the exact task/flow, operator identity, candidate, command,
scenario, capability, budgets, expiry, and result. It enforces single-use admission and
singleton ownership; descriptive attribution is not a bearer credential or permission grant.
Retiring editor/model workflow instructions does not waive candidate, review, receipt,
authorization, or other safety checks enforced by that controller.

The separate legacy `begin-delegation` development command/API requires an explicit non-empty
free-form `--agent` value. This records attribution only, selects no model or persona, and does
not authorize runtime input. Ordinary offline work need not use this command.

## Unresolved actions and handoff

- Preserve fresh source/target binding, input budgets, unresolved-action handling, and the
  existing safe terminal/release path. Never bypass a stale lease or fencing failure.
- Unknown or ambiguous consequential results fail closed. Do not issue an uncertain retry,
  repeat an input to force teardown, or infer semantic success from a transport return.
- Login, tutorial, CAPTCHA, account/credential work, and other manual-only states stop for a
  human. Premium, real-money, unsupported, and unapproved consequential actions are prohibited.
- Before a runtime handoff, retain the required native evidence and summary, classify any
  unresolved state, and complete the existing safe ownership release. If safe release is
  impossible, report the blocker rather than releasing or taking over by force.
- Keep evidence immutable. Record a consequential or unknown terminal surface honestly;
  historical records are not permission to repair, retry, or enable a flow.

See [runtime input safety](runtime-input-safety-policy.md) and
[validation boundaries](flow-delivery-validation-policy.md). Archived model-specific workflow
records under [archive/](archive/README.md) are non-authoritative historical context.
