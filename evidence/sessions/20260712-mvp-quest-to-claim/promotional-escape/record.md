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

This offline analysis did not pass `MVP-QUEST-TO-CLAIM` and did not create a Claim-positive asset.

## Live bounded attempt after implementation commit

After commit `5cec210`, the fresh post-launch frame independently matched this detector. One
`SAFE_PROMOTIONAL_BACK` tap at `(87, 32)` was authorized and dispatched through M7. The initial
post-observation result was `unexpected_successor`, so the action was durably marked unresolved and
no retry was sent. Three retained post frames independently recognized Home/Base, a bounded safe
successor. After commit `d6fd1c7` corrected the adapter to accept the bounded successor set, the
existing action was reconciled to confirmed from those positive frames and the lease was released.
This was reconciliation, not another input.

A subsequent Home→Quest proposal was cancelled before dispatch because its immediate-before frame
changed to an unknown/non-Home surface; transport calls were zero and no retry was sent. The game
was force-stopped afterward. No Quest, Daily Quest, Go, Claim, prerequisite, spend, combat, account,
or OS input occurred. The final combined journal is retained at the task `actions.sqlite3`, and
`live-actions.sqlite3` preserves the fetched cleanup copy.
