# RT-012 observe-only soak — authentication block

Recorded: 2026-07-11, America/Chicago

## Status

RT-012 execution is externally blocked before runtime mutation.

The observe-only harness is implemented at:

`scripts/test-observe-soak.ps1`

The harness was parsed with the PowerShell language parser and passed linter diagnostics.
It performs only:

- transient private ADB tunnel setup
- read-only Android profile/health inspection
- approved non-game startup keyguard dismissal when required
- optional package launch for observation
- lossless PNG capture and local freshness/dimension/black-frame checks
- read-only host/QEMU/NAS metric collection
- cleanup of the transient tunnel

It sends no gameplay input, credentials, tutorial input, purchases, or account operations.

## Blocker evidence

A read-only SSH probe to `root@nas.local` using strict host-key checking and batch mode
returned:

`Permission denied (publickey,password,keyboard-interactive).`

Exit code: `255`.

No password was supplied. No authentication secret was written to the repository or evidence.
The existing transient password is intentionally not reproduced here.

## Exact resume action

From a fresh PowerShell process, retrieve the temporary password from the password manager into
process-only environment state, or configure the dedicated pinned SSH key, then run:

```powershell
$env:UNRAID_TEMP_PASSWORD = '<set from password manager; do not commit or log>'
.\scripts\test-observe-soak.ps1 `
  -OutputDirectory .\evidence\sessions\20260711-rt-012-soak `
  -AdbPath C:\Users\burni\adb\adb.exe `
  -AuthenticationMode PlinkPassword `
  -LaunchGame
```

Do not place the password in this script, repository, command history, or an evidence file.
Use `OpenSshKey` instead after the pinned key is available.

## Runtime state

No VM, host, network, storage, game, or account state changed during the auth probe or harness
validation. RT-011 cleanup state remains authoritative: selected Mesa VirGL profile, VM
autostart disabled, game force-stopped, no active ADB tunnel, and no gameplay input enabled.

RT-012 acceptance remains unmeasured. Runtime selection now requires the 4-hour target; a
2-hour run is diagnostic only. Do not mark it passed until the target duration, captures,
host/QEMU/NAS metrics, disk growth, network observations, error review, and manual
visual/authentication-state review are complete. Longer 12–24 hour endurance is deferred to
M10 operations hardening.
