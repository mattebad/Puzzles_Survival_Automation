# RT-008 ADB containment — passed by strict private boundary

Date: 2026-07-11 (America/Chicago)

## Scope

Prove that ADB is reachable only through an approved private path and is not exposed on the
Unraid LAN or Internet-facing host interfaces. No firewall, routing, VM XML, or guest network
mutation was performed.

## Observed topology

- VM interface: libvirt `default` network, VirtIO, bridge `virbr0`.
- Guest address: private `192.168.122.79/24`.
- Libvirt network: NAT mode, `virbr0`, host address `192.168.122.1/24`.
- Host LAN: `192.168.50.92/24` on `br0`.
- Guest ADB: `*:5555` inside the guest.
- Host listener inventory: no host `:5555` listener.
- Guest properties: `ro.adb.secure=0`, `ro.debuggable=0`, `sys.boot_completed=1`.

ADB authentication is not enabled by this Bliss image. The result therefore relies on strict
network containment rather than an ADB authorization prompt. The production worker must remain
on the private host/libvirt path or use a pinned SSH tunnel; it must never connect through LAN
or Internet routing.

## Verification

Evidence files:

- `host-network.txt`
- `host-to-guest-allowed-corrected.txt`
- `guest-adb-properties.txt`
- `guest-listeners.txt`
- `guest-addresses.txt`
- `guest-routes.txt`
- `tunnel-connect.txt`
- `windows-direct-guest-probe.json`
- `windows-nas-5555-probe.json`
- `windows-local-tunnel-probe.json`

Results:

1. Host-to-guest private probe succeeded: `/dev/tcp/192.168.122.79/5555` exit `0`.
2. Existing pinned SSH tunnel connected ADB through `127.0.0.1:15555`.
3. Windows direct probe to `192.168.122.79:5555` failed; ping also failed and the selected
   route remained the LAN gateway, not the libvirt network.
4. Windows probe to reachable `nas.local:5555` failed, proving no host LAN listener/forward.
5. Windows probe to local tunnel `127.0.0.1:15555` succeeded.
6. Libvirt XML showed NAT `default`/`virbr0`, with no port-forward declaration.
7. Host firewall snapshot showed libvirt ingress rules rejecting new traffic toward `virbr0`;
   only established/related traffic is accepted. No `5555` DNAT/redirect or host listener was
   found in the captured rules/listeners.
8. Guest ADB reconnect remained usable through the approved tunnel. RT-007 restart evidence
   separately records reconnect after each guest reboot.

## Acceptance

Passed by strict isolation. Endpoint is private to the libvirt network, unreachable from the
tested LAN path, absent from host LAN listeners, and reachable only through the approved host
path or pinned transient SSH tunnel. ADB remains unauthenticated at the guest protocol layer;
this is an explicit limitation, not hidden.

## Rollback and next work

Observation-only; no runtime or host network state changed. Tunnel was closed after testing.
Game remained force-stopped. RT-009 non-game input fidelity is next independent task; RT-011
restart matrix follows after RT-009.
