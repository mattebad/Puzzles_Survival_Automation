# Current handoff

Updated 2026-11-07. This file is volatile session state.
Current owner direction and route planning live in [tracker #53](https://github.com/mattebad/Puzzles_Survival_Automation/issues/53) and its tickets.

- **Verified starting point:** `origin/main` and original workspace HEAD were
  `c6f0e2fba509dacde136226a7519568550f6b066` at task startup; do not reuse merged branches.
- **Review branch:** `impl/base-route-batch-a-20261107`, in a separate worktree.
  Batch A integrates #54/#66 through the canonical service, not their retired operator wrappers.
- **Offline checks:** 208 focused route/integration tests and the device-free `scripts/check.py`
  set (394 tests) pass. A temporary-SQLite fake service run demonstrated restart persistence
  and a later distinct Daily ready batch in the same reset.
- **Daily evidence gap:** the owner-supplied raw image recognizes all five chests, with only the
  first glowing. No same-chest claimed/opened successor is admitted; chest input remains blocked.
  Complete zero-ready scans, including after a confirmed aggregate Claim, can close at verified
  Home. A fake replay exercised the native zero-Claim path with one bounded navigation input.
- **Resource Item:** exactly one positively identified owned 1K Food item, with owned decrement
  by one; no Food-balance OCR or Daily ownership. Current native acceptance is `evidence_required`.
- **Current live authorization:** the owner now explicitly permits live validation. The parent
  alone is the operator, initially scoped to #54. A supported zero-input observation and a
  bounded Home-to-Daily navigation probe acquired and released controller ownership; both
  issued zero inputs. The navigation probe exposed a current Home-footer template mismatch.
- **Home repair:** a source-derived compact-footer template recognizes an independent current
  Home capture at 0.9993 correlation while retaining the 0.90 threshold and existing mapped
  Quest point. World and Daily screens remain rejected. This is recognition proof, not a claim
  or completed-route acceptance. The corrected native navigation attempt is pending.
  Focused Home/Daily/Resource/Ultimate consumer checks passed 150 tests (three optional
  capture-dependent skips); the device-free repository gate passed 394 tests.
- **Runtime posture:** no gameplay effect, native route acceptance, deployment, PR merge or
  runtime enablement has occurred. Current status still reports service OFF, generation 282,
  and all nine original flows OFF. Original raw evidence and unrelated user files are preserved.
- **Historical handoff:** the [November 2 pre-merge snapshot](../archive/current-handoff-astra-premerge-20261102.md)
  remains historical; its PR #16 publication/CI instructions are complete or obsolete.

This file grants no live authority.
