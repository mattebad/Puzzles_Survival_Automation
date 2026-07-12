# RT-021 retained orchestration failures and corrections

These are retained execution failures, not filtered runtime results.

1. Bridge attempt wrapper: the container ran and its evidence was preserved, but the outer SSH
   wrapper escaped the final numeric exit incorrectly. The container log is retained; direct ADB
   connection was refused and the captured frame was zero bytes. The container was removed.
   Revised hypothesis: Docker bridge forwarding to libvirt `virbr0` is blocked.

2. Host-network attempt 2: the container was correctly unprivileged, but setting
   `ADB_SERVER_SOCKET=tcp:127.0.0.1:5038` made this ADB build treat the server as remote; it could
   not start its own local server and produced a zero-byte frame. The container was removed.
   Revised hypothesis: use the ADB-supported local server port variable instead.

3. First reconnect wrapper: nested shell escaping caused `done` syntax failure before the ADB
   loop ran. No evidence of a transport failure was inferred and the VM remained running.
   Correction: use one natural 20-second boot interval with the same host-network configuration.

4. First final-reconcile command: local PowerShell parsed nested `grep` quotes before SSH; no
   remote action occurred. Correction: retain full window-policy output without nested quotes.

The passing host-network attempt, corrected reconnect, and final reconciliation evidence remain
under `remote-cache/`; no more materially different network attempts were made.
