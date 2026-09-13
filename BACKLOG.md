# Canonical execution backlog

## Current recovery track — offline planning only

This file is a small entry point for the 74 inactive recovery tickets. The canonical planning records
are linked below; they are not a queue, registry, scheduler, runtime control plane, or authorization
source. `READY` means that a later, separately authorized offline assignment may be considered. It
does not enable a flow, authorize transport, mutate production state, or approve native evidence.

Read the [recovery execution guide](docs/backlog/execution-guide.md) before assigning work, then read
the complete linked ticket and the [proportionate planning contract](docs/backlog-task-contract.md).

- [Foundation tickets REC-F01–REC-F17](docs/backlog/foundation.md)
- [Daily tickets REC-D01–REC-D12](docs/backlog/daily.md)
- [Resource and policy tickets REC-R01–REC-R19 and REC-P01–REC-P12](docs/backlog/resources.md)
- [Operations tickets REC-O01–REC-O14](docs/backlog/operations.md)

The linked records are current planning scope only. They distinguish code merged, native evidence,
scheduler acceptance, and explicit enablement. BlueStacks remains the development environment;
final production is NAS/Unraid-hosted. No current live readiness is claimed here. Runtime launchers,
controls, `ResourceEffectAuthority`, leases/fencing, manual-only states, and live gates remain
unchanged and authoritative where they already apply.

## Historical boundary

The [legacy backlog archive](docs/archive/backlog-legacy.md) preserves the original 148 third-level
records and IDs byte-for-byte from the pre-cleanup root backlog. It is historical, not a second
current planning authority. Existing legacy queue/context tooling reads that explicit archive path;
its derived index remains a 32-record compatibility subset and is not discovery for these 74 tickets.
Historical statuses, evidence, and no-retry conclusions are not promoted by this index.

See [`docs/archive/README.md`](docs/archive/README.md) for archive scope and [`governance-simplification-plan.md`](governance-simplification-plan.md)
for the current architecture/governance direction. `CURRENT_HANDOFF.md` remains the volatile
operational handoff; it does not activate a linked recovery ticket.
