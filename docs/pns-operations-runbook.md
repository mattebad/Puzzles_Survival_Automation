# Puzzles & Survival operator runbook

Routine Unraid and private-ADB operations use `scripts/pnsctl.py`. Run commands from the project
root with the approved `UNRAID_TEMP_USERNAME` and `UNRAID_TEMP_PASSWORD` values available in the
project `.env` or process environment. The CLI never prints or writes those values.

The CLI owns the pinned `nas.local` host key, cache-backed workspace, worker image, UID 65534
worker, read-only root, writable in-memory `/tmp`, task ADB socket `127.0.0.1:5042`, guest serial
`192.168.122.79:5555`, package/activity, RT-019/M6 validation, evidence synchronization, and
task cleanup. The approved pre-existing host ADB at `127.0.0.1:5037` is never stopped.

```text
python3 scripts/pnsctl.py preflight
python3 scripts/pnsctl.py worker-start
python3 scripts/pnsctl.py worker-status
python3 scripts/pnsctl.py adb-start
python3 scripts/pnsctl.py launch
python3 scripts/pnsctl.py capture --name current
python3 scripts/pnsctl.py observe --name current
python3 scripts/pnsctl.py navigate --step cash-home
python3 scripts/pnsctl.py navigate --step home-quest
python3 scripts/pnsctl.py navigate --step quest-daily
python3 scripts/pnsctl.py navigate --step daily-scroll-up
python3 scripts/pnsctl.py navigate --step daily-scroll-down
python3 scripts/pnsctl.py navigate --step daily-bioenhancer-go
python3 scripts/pnsctl.py run-task --task alliance-help
python3 scripts/pnsctl.py run-task --task praise
python3 scripts/pnsctl.py test-focused --pattern test_task_module.py
python3 scripts/pnsctl.py test-full
python3 scripts/pnsctl.py validate
python3 scripts/pnsctl.py preserve-evidence \
  --destination evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/remote-complete \
  --name alliance-help-1783981635-source.png \
  --name alliance-help-1783981635-immediate-before-1.png \
  --name alliance-help-1783981635-post-1.png \
  --name alliance-help-result.json
python3 scripts/pnsctl.py cleanup
```

`navigate` accepts only the checked-in route names and uses the existing safe-action executor.
`preserve-evidence` requires one or more exact `--name` values. An omitted name fails before
creating the destination; cumulative `remote_evidence/*` downloads are intentionally disabled.
The Daily scroll routes are bounded navigation-only swipes; each captures and revalidates the
selected Daily source before dispatch, then requires a fresh selected-Daily successor.
`daily-bioenhancer-go` is a bounded navigation-only tap on the freshly observed selected-Daily
Bioenhancer row; it requires a positively recognized direct Bioenhancer Research successor and
never presses Free Research or Research 10x.
`bioenhancer-daily-back` is the bounded navigation-only return from the exact Bioenhancer
Research back control to Home/Base; continue through `home-quest` and `quest-daily` to rebind
selected Daily.
`daily-supply-depot-go` is a bounded navigation-only tap on the current selected-Daily Supply
Depot row; it requires a positively recognized Supply Depot successor and never collects.
`supply-depot-daily-back` is the bounded navigation-only return from Supply Depot to Home/Base;
continue through `home-quest` and `quest-daily` to rebind selected Daily.
`observe` records capture start/completion epochs and UTC completion time beside foreground
identity so retained raw frames have explicit capture timing.
`run-task` exposes bounded task adapters only. `praise` first recognizes and attempts one
task-scoped dismissal of the reset-time `Get Pts` modal through its local Close ROI, then uses
the named Personal Might route. It is not a general remote shell or arbitrary tap endpoint.

## Canonical governance references

This runbook is an operational entry point, not a duplicate authority. Permanent invariants are in
[`../AGENTS.md`](../AGENTS.md); detailed procedures are in:

- [`runtime-input-safety-policy.md`](runtime-input-safety-policy.md) for raw-frame recognition,
  coordinate translation, rebinding, input limits, and semantic postconditions;
- [`journal-lease-policy.md`](journal-lease-policy.md) for operational versus historical journals,
  lifecycle, leases, unresolved gates, and reconciliation;
- [`chat-execution-ownership-policy.md`](chat-execution-ownership-policy.md) for singleton
  ownership and safe handoffs;
- [`evidence-retention-policy.md`](evidence-retention-policy.md) for exact manifests, hashes,
  indexing exclusion, and archive-before-removal.

The current task and exact next action are authoritative only in `CURRENT_HANDOFF.md` and
`BACKLOG.md`. Offline contracts do not authorize registration or scheduler eligibility.

The retained mistarget is reconciled by copying the closed historical database and recording a
terminal no-effect cancellation in the copy. The original unresolved journal remains immutable:

```text
python3 scripts/pnsctl.py reconcile \
  --source evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/actions-after-release.sqlite3 \
  --output evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/reconciled-actions-20260713.sqlite3 \
  --action-id alliance-help-20260713-001 \
  --evidence remote-complete/alliance-help-source-001.png remote-complete/alliance-help-immediate-before-1.png remote-complete/alliance-help-post-001.png
```

Do not use ad hoc `plink`, Docker, ADB, inline Python, or arbitrary remote commands for routine
operations. Stop on an account/session hard stop, public ADB exposure, unresolved consequential
outcome, profile mismatch, or destructive runtime requirement.
