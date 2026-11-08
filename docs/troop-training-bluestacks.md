# Daily troop training — local BlueStacks route

This canonical service route owns the four fixed Training variants: Fighter T8/current numeric
maximum/continuous, Vehicle T1/current numeric maximum/continuous, Shooter T8/fixed 250/daily,
and Rider T1/fixed 250/daily. The saved Training preset is required. The fixed product and
recurrence bindings are `troop_training-v3` and timer/reset-scoped; the route is registered but
both flow and service controls remain disabled by default. Registration does not enable execution.
Locked tiers, unresolved maxima, mismatched queues, unknown costs, and uncertain successors fail
closed. Fighter/Vehicle box continuations require exact current inventory and effect authority;
without it the branch stays `evidence_required` and dispatches no boxes or blind warehouse Train.
Shooter/Rider boxes are prohibited; boxes are never selected as a separate action. Daily Quest Claim
remains separate. Every Commander preset use requires fresh exact `Applied` recognition; cached
readiness is not proof, and an already-Applied preset is not switched again. Any real switch needs
a recognized saved-preset Apply branch and known cost/confirmation. Talent-tree edits and Reset are
never part of this flow. No standalone Commander-talents scheduled flow is introduced.

Example configuration:

```json
{
  "fighter": {"enabled": true, "target_tier": 8, "quantity_mode": "current_max", "training_policy": "continuous", "allow_resource_boxes": true},
  "shooter": {"enabled": true, "target_tier": 8, "quantity_mode": "fixed", "quantity": 250, "training_policy": "once_daily", "allow_resource_boxes": false},
  "rider": {"enabled": true, "target_tier": 1, "quantity_mode": "fixed", "quantity": 250, "training_policy": "once_daily", "allow_resource_boxes": false},
  "vehicle": {"enabled": true, "target_tier": 1, "quantity_mode": "current_max", "training_policy": "continuous", "allow_resource_boxes": true}
}
```

The route is served only by the canonical automation service. The previous direct Training CLI and
flow-delivery runner are retired; ordinary Training execution must not use a development-session
runner or a parallel operator registry.

## Canonical service route

The service binding uses the existing native Training factory, handler, account/server/reset
identity, singleton runtime lock, occurrence claim, checkpoints, and bounded route budget. The
route is capped at 96 inputs and 12 consequential actions. Its configured profile is fixed to:

- Fighter: T8, current numeric maximum, continuous; boxes only with exact current inventory and effect authority.
- Vehicle: T1, current numeric maximum, continuous; boxes only with exact current inventory and effect authority.
- Shooter: T8, 250, once per daily reset; boxes forbidden.
- Rider: T1, 250, once per daily reset; boxes forbidden.

Before an independently authorized live run, inspect the persisted controls:

```text
python scripts/pnsctl.py automation-service status
```

The supervised serving boundary is `pnsctl automation-service ... serve --flow troop-training`.
The flow and service gates are currently disabled; this integration does not enable either gate or
authorize live execution. The service requires a saved `Training` preset and a fresh canonical Home
Atlas proof. Each accepted queue transition is bound to the exact variant, tier, numeric quantity,
resources, timer, account/server, and reset identity. Unknown screens, costs, quantities, or
successors fail closed; an unresolved Training action is never retried or inferred successful.

## Manual Home recovery

`python scripts/pnsctl.py bluestacks recover-home` is a manual, navigation-only operation. Its
admission is the canonical SQLite Training action/resource history, not a flow-delivery queue,
lease, retained receipt, artifact, or event text: the history must name a pending or
confirmed-queue Training candidate and prove no unrelated unresolved effect or blocking Resource
effect. The command acquires the existing singleton runtime input lock itself (an executing service
pass or any other owner blocks it) and rereads the unchanged history under that lock before
connecting. It runs only the retained native `TroopTrainingReturnHomeRoute` within the canonical
Training input ceiling, requires exact current queue recognition and canonical Home Atlas proof, and
preserves startup-source evidence. It never runs the Training service runner, confirms or clears an
action, retries a dispatch, changes counters, claims a reward, or enables a control. A Home
recovery result is navigation evidence only, not Training completion.

## Historical manual observations — not native acceptance

The following notes preserve prior manual BlueStacks exploration only. They are not current
native-route evidence, end-to-end acceptance, scheduler enablement, or proof that the service is
safe to enable.

Manual frames showed Fighter Camp, Shooter Camp, Rider Camp, and Vehicle Depot on Home/Base. The
facility radial menu exposed Details, Upgrade, and Train. The training view had four tabs; selecting
a tab navigated to that troop type, and a completed banner could indicate automatic claim behavior,
so an unproven completed pre-state must never be silently accepted as a claim.

The manual account displayed T1–T8 as trainable and T9+ as question-mark locked tiers. Quantity was
edited through a numeric control. Normal Train displayed a duration; Train Now displayed a
premium-currency cost and was not targeted. The owner-authorized #54 observation was exactly one
manual chest tap at zero spend; `glowing` to `Claimed` is its recognition basis. Preserve the raw
`UNKNOWN` record unchanged; the observation is historical context, not combined native route
acceptance (`evidence_required`).

The historical shortage successor observed on 2026-07-16 was titled `Auto Use`, displayed selected
food resource boxes, and explicitly offered `Auto-use Resource Boxes`. It was an inventory-item
popup, not a warehouse-only confirmation. Fighter/Vehicle box continuations require exact current
inventory and effect authority; absent proof the branch remains `evidence_required`, with no box
dispatch, no expected-warehouse assumption, and no blind Train. Shooter/Rider never use boxes.
A successful Home recovery is navigation-only and does not resolve or complete a Training action.
