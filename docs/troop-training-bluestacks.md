# Daily troop training — local BlueStacks route

This workflow owns four per-type configurations: `fighter`, `shooter`, `rider`, and
`vehicle`. Each configuration has `enabled`, an explicit `target_tier` (T1–T13), `quantity` or
`quantity_mode` (`fixed` or `current_max`), `training_policy` (`once_daily`, `continuous`, or
`disabled`), and resource-box policy. The named default is Fighter T8/current maximum/continuous
with boxes, Vehicle T1/current maximum/continuous with boxes, Shooter T8/fixed 250/once_daily
without boxes, and Rider T1/fixed 250/once_daily without boxes. Every override is retained exactly;
locked tiers, unresolved maxima, and mismatched queues fail closed. Daily Quest Claim remains
separate; registration and scheduler eligibility remain disabled.

Example configuration:

```json
{
  "fighter": {"enabled": true, "target_tier": 8, "quantity_mode": "current_max", "training_policy": "continuous", "allow_resource_boxes": true},
  "shooter": {"enabled": true, "target_tier": 8, "quantity_mode": "fixed", "quantity": 250, "training_policy": "once_daily", "allow_resource_boxes": false},
  "rider": {"enabled": true, "target_tier": 1, "quantity_mode": "fixed", "quantity": 250, "training_policy": "once_daily", "allow_resource_boxes": false},
  "vehicle": {"enabled": true, "target_tier": 1, "quantity_mode": "current_max", "training_policy": "continuous", "allow_resource_boxes": true}
}
```

The equivalent CLI toggles are `--<troop>-allow-resource-boxes` and
`--no-<troop>-allow-resource-boxes`.

## Native route

The executable route is dry-run by default and uses the shared native 800×1280 capture/transport
boundary:

```powershell
python scripts\troop_training_bluestacks.py `
  --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" `
  --serial emulator-5554 `
  --reset-identity <recognized-reset> `
  --fighter-tier 8 --fighter-quantity-mode current_max `
  --shooter-tier 8 --shooter-quantity-mode fixed --shooter-quantity 250 `
  --rider-tier 1 --rider-quantity-mode fixed --rider-quantity 250 `
  --vehicle-tier 1 --vehicle-quantity-mode current_max `
  --execute --yes
```

The canonical consolidation route recognizes canonical Home Atlas state, opens one configured
training facility, and uses the four verified top tabs to process each enabled troop type. Each tab
freshly proves troop identity, tier, quantity, resources, and queue state. The route returns to
canonical Home once after the configured tab pass. Every dispatch has
fresh source/immediate-before/immediate-post evidence and an exact successor queue label/tier/
quantity/timer; no Train Now or premium control is authorized.

`--reconcile-unresolved-session <session>` is a recovery-only route. It requires the prior
immediate-post evidence and a fresh live queue matching troop type, tier, quantity, and timer. It
records the reconciliation and may navigate Home, but it has no consequential dispatch path.

## Live BlueStacks observations

Fresh native frames showed Fighter Camp, Shooter Camp, Rider Camp, and Vehicle Depot on Home/Base.
The facility radial menu exposes Details, Upgrade, and Train. The training view has four tabs;
selecting a tab navigates to that troop type, and a completed banner can indicate automatic claim
behavior, so an unproven completed pre-state is never silently accepted as a claim.

The live account displayed T1–T8 as trainable and T9+ as question-mark locked tiers. Quantity is
edited through the numeric control and verified after entry. Normal Train displayed a live duration;
Train Now displayed a premium-currency cost and was never targeted. The default profile uses
current maximums for Fighter/Vehicle and fixed 250 for Shooter/Rider at their configured tiers.
No warehouse continuation was required in the validated run.

## Safety boundary

The adapter rejects non-native frames, unknown screens/facilities/tabs/tiers, question-mark tiers,
wrong quantities, active queues, overlays, ambiguous resource popups, and forbidden premium,
purchase, speedup, ticket, resource-item, AP, or stamina controls. Every live capture and dispatch
is retained under `.local-captures/troop-training-*`; these are BlueStacks validation artifacts,
not production evidence or registration.

The live shortage successor observed on 2026-07-16 was titled `Auto Use`, displayed selected food
resource boxes, and explicitly offered `Auto-use Resource Boxes`. It is an inventory-item popup,
not a warehouse-only confirmation. The route binds Cancel and Confirm independently. Confirm is
available only when the corresponding troop configuration explicitly enables resource boxes, the
popup's four required resource amounts match the exact pre-dispatch training transaction, and the
immediate postcondition proves either the configured active queue or the exact projected resource
holdings. The live UI applies boxes first, returns queue-empty, and may change the slider quantity;
the route terminally reconciles that acquisition, restores the configured quantity, and creates a
new separately keyed normal Train transaction. It never treats the second Train as a retry of an
unresolved action. When disabled, the route presses only Cancel, proves the queue remained empty,
terminally rejects the Train, and returns Home. The
recovery-only `--reconcile-forbidden-resource-popup-session` remains available for older unresolved
sessions and never retries Train.
