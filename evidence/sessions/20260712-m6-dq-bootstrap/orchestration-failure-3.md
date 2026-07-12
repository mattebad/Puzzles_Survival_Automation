# M6-DQ-BOOTSTRAP — Navigation worker expiry

Recorded: 2026-07-12, America/Chicago

## Observation

The sequential worker `m6-dq-bootstrap-home-quest-20260712` was started with a bounded 600-second
hold so local source/target gates could be completed between ADB commands. Before the immediate
pre-input Quest recapture for the Daily Quest tab, the container exited and the next `docker exec`
returned `container ... is not running`.

## Impact

No Daily Quest tab input was sent. No Go, Claim, quest, purchase, resource, or other gameplay
input occurred. The prior Home/Base-to-Quest tap and its positive settled Quest evidence remain
valid. The game was not force-stopped by this failed follow-up operation.

## Revised hypothesis and correction

The worker hold duration was too short for the sequential review cadence. The smallest correction
is to remove only this exited temporary container and start a new unprivileged observer with a
fresh bounded hold, reconnecting to the already-recognized Quest screen without relaunching or
sending additional navigation until the immediate source/target gate passes.
