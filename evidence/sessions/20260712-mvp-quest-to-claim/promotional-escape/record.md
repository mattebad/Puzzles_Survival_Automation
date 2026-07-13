# Promotional escape-only offline review

Recorded: 2026-07-12, America/Chicago

## Scope

The retained blocker frame was reviewed offline. No Unraid, VM, ADB, game, container, tunnel, or
runtime-network access occurred. No game or OS input occurred.

Source frame: `../reset-reconcile-current.png` (retained SHA-256
`71a4134084acf0deb3516dfc25e6f6e2ba38bb55989b084b61cbf0298963b1a8`, 800x1280).
Arrow reference: `../../20260711-rt-012-observe-soak/cash-mall-startup-reference.png`.

## Detector result

The frame is recognized as `UNKNOWN_PROMOTIONAL_WITH_VERIFIED_BACK`. The page title, product,
price, offer tabs, and reward content are intentionally not required for authorization. The
standard game Back arrow passed the locked isolated ROI `(45, 5, 130, 60)`, similarity `0.898225`,
component `(13, 5, 60, 38, 812)` within the ROI, and foreground/background contrast `160.974`.

The target is isolated from the explicit forbidden regions for offer tabs, reward tiles,
confirmation controls, price/purchase controls, and premium-currency controls. The retained frame
therefore produces only a `SAFE_PROMOTIONAL_BACK` proposal; no purchase, reward, Claim, quantity,
or offer control is proposed.

## Contract

The central policy requires the exact source state, semantic arrow identity, geometry, target ROI,
explicit forbidden-region metadata, zero-cost navigation consequence, bounded expected successor,
fresh RT-019-compatible frame, exclusive lease, and no unresolved action. It permits at most three
independently journaled promotional Back actions. Each action still uses the existing prepared,
immediate-before, one transport call, input-sent, and positive-successor lifecycle. An unexpected
successor or unresolved result stops the sequence.

## Offline validation

- `safe_action_core` and the promotional extension: 78 tests passed.
- RT-019 profile validation passed with profile ID
  `pns-blissos-poc-virgl-800x1280-v1` and the locked profile hash.
- M6 six-asset validation passed; no M6 asset was changed or promoted.
- Offline classifier output: `promo-classification.json`.
- Review annotation: `promo-annotated.png`.

This analysis does not pass `MVP-QUEST-TO-CLAIM`, does not create a Claim-positive asset, and does
not authorize live input by itself.
