# Agent execution rules

- Read the canonical service plan and BACKLOG.md before selecting work.
- BACKLOG.md is the sole authority for task status, dependencies, and blockers.
- Complete exactly one backlog task per execution iteration.
- Preserve passed tasks and retained evidence.
- Never repeat passed experiments without contradictory evidence.
- Update evidence and BACKLOG.md after each task.
- Commit each passed task separately.

## Hard boundaries

- Production remains entirely on Unraid.
- Never reboot or shut down the Unraid host autonomously.
- Never delete or overwrite the Bliss qcow2.
- Never modify unrelated VMs, containers, storage, or services.
- Never expose ADB or a viewer publicly.
- Never store credentials in files, scripts, logs, evidence, or command history.
- Never automate login, tutorial, account switching, credentials, or CAPTCHA handling.
- Never perform gameplay input before the relevant promotion and authorization gates.
- Unknown consequential outcome means stop and reconcile, never retry blindly.