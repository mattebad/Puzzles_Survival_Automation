# Cash Mall overlay guard review

Recorded: 2026-07-11, America/Chicago

- Fresh 30-second launch frame reached the expected Cash Mall layout but displayed an unexpected
  light `Ending Soon` banner over the offer header.
- The initial Cash Mall classifier would have recognized the underlying layout; no input was sent.
- The guard was tightened with a fixed-profile bright rectangular-header overlay detector. The
  retained frame now returns `UNKNOWN`, `unknown_overlay=true`, and `no_unknown_overlay=false`.
- The clean retained Cash Mall reference remains `CASH_MALL` with `unknown_overlay=false`.
- Revised hypothesis: routine banner/toast overlays must be explicitly recognized or absent before
  the no-spend back-arrow target can be authorized. This overlay is currently not allowlisted.
