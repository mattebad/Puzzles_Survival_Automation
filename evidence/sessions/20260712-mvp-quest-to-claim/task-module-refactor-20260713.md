# Daily Quest task-module refactor — 2026-07-13

## Scope

This repository-only boundary introduced the smallest typed task-module layer needed before
resuming the supervised MVP. It does not enable automatic scheduling, begin transition-corpus
promotion, or send game input. Vendor/GnBots code, assets, selectors, and profiles were not
inspected or executed.

## Stable contracts

- `TaskOutcome` distinguishes `PROGRESS`, `DONE`, `RETRY`, `BLOCKED`, and `FAILED_SAFE`. A
  function return never marks the Daily Quest task complete; completion requires a verified
  postcondition and matching completion key.
- `AnchorSpec` stores Bliss `800x1280` absolute ROI, anchor-specific threshold, confirmation
  count, polling/timeout budget, optional tap offset, and independent Bliss asset provenance.
- Navigation uses typed `NavigationStep` and local source/target contracts. `NavigationResult`
  exposes a typed task result; reaching a successor is `PROGRESS`, not `DONE`. Existing local-ROI
  navigation does not use full-frame equality or unrelated OCR.
- Popup handling distinguishes navigation cleanup from `ACTION_TRANSACTION`: navigation may handle
  one known benign popup per bounded round; action transactions allow only explicit dialogs and
  reject unknown/cost/purchase surfaces.
- `RouteDispatcher` recognizes Daily Quest, direct task screens, highlighted-building/base-search
  routes, Alliance, World, Cash Mall, bounded promotional escape, hard stops, and unknown unsafe
  destinations. World remains unsupported for this zero-cost MVP.
- Existing `safe_action_core` remains the sole injected transport/journal boundary. Action intent
  audit records now carry explicit action kind, subject, resource/currency, maximum cost, free-only
  rule, dialog whitelist, and semantic pre/postcondition fields.

## Validation

- Full dependency-complete offline suite: **96 tests passed**.
- RT-019 validator: passed for profile
  `pns-blissos-poc-virgl-800x1280-v1`, content hash
  `195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.
- M6 bootstrap validator: six promoted assets passed.
- No Unraid, VM, ADB, worker, tunnel, or game input occurred during the validation run.

## Live preflight before this boundary

The approved remote path was reconciled read-only. The selected Bliss VM was `running`; RT-017
backup remained mode `0600`, size `13522501632` bytes; the task worker was exited and no 5037/5042
listener remained. The retained live SQLite journal was schema version 1 with terminal actions
only, including the prior cancelled Home→Quest attempt; no lease or unresolved action remained.
