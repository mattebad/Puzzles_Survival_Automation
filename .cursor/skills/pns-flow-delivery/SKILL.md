---
name: pns-flow-delivery
description: Integrate one existing personal-bot flow with focused verification.
disable-model-invocation: true
---

# Lean PnS flow delivery

Read `AGENTS.md`, `CURRENT_HANDOFF.md`, only the active portion of `BACKLOG.md`
above `<!-- ACTIVE_BACKLOG_END -->`, and `docs/backlog-task-contract.md`.
Implement only the selected slice, reusing existing Python flows and storage.

## Development

- Ground callers before editing. Prefer small, complete changes over new frameworks.
- Work directly; delegate only if requested. No mandatory model assignments,
  manifests, development leases, receipt gates, or historical queue transitions.
- Exercise actual changed behavior and relevant existing tests. Report exact
  verification and remaining limits; offline results are not live gameplay proof.
- Update the active backlog and handoff briefly. Do not automatically commit,
  push, or begin another slice. Preserve unrelated work and protected evidence.

## Runtime safety

- Keep one bot process, one controlled emulator, and one active flow.
- Preserve explicit approvals in `tasks/flow_delivery_product_policy.json`.
- Live input and registration/scheduler enablement need explicit authorization.
  Use the supported `scripts/pnsctl.py` interface for authorized live operation.
- Bound transport, recognition, retries, and recovery. Transport success and
  selection are not gameplay completion; do not blindly retry uncertain consumption.
- Stop on login, account selection, CAPTCHA, credentials, or other manual-only
  states. Reject real-money confirmation.
- Development paperwork, Git state, and agent receipts are not runtime dependencies.
