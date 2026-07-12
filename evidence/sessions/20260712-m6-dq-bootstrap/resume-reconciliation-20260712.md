# M6-DQ-BOOTSTRAP — Resume reconciliation attempt

Recorded: 2026-07-12, America/Chicago

The required first action after the reported SSH restoration was a read-only Unraid/Bliss
reconciliation. The process-only credential variables were loaded without printing or retaining
their values. The pinned `plink` probe again ended with `FATAL ERROR: Remote side unexpectedly
closed network connection` before any remote command output was returned.

Independent TCP checks then failed for both `nas.local:22` and `192.168.50.92:22`.

No worker was launched, no ADB command was sent, no screenshot was captured, and no game or OS
input was sent during this resumed attempt. The prior Daily-tab input remains unreconciled; it
was not retried. The prior blocker evidence and retained Daily Quest frames remain authoritative.

Required next action: restore stable private SSH connectivity, then begin with read-only
reconciliation of the VM, device, existing task-scoped worker, ADB, listeners, and backup.
