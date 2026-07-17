# Daily troop training — local BlueStacks route

This workflow owns four independent configurations: `fighter`, `shooter`, `rider`, and
`vehicle`. Each configuration has `enabled`, an explicit `target_tier` (T1–T13), `quantity`, and
`training_policy` (`once_daily`, `continuous`, or `disabled`), and `allow_resource_boxes`. The
resource-box toggle is independent per troop type and defaults to `false`. The default quantity is
250 and a tier is never substituted when it is locked or ambiguous. Daily Quest Claim is not part
of this route; registration and scheduler eligibility remain disabled.

Example configuration:

```json
{
  "fighter": {"enabled": true, "target_tier": 8, "quantity": 250, "training_policy": "continuous", "allow_resource_boxes": false},
  "shooter": {"enabled": true, "target_tier": 8, "quantity": 250, "training_policy": "continuous", "allow_resource_boxes": false},
  "rider": {"enabled": true, "target_tier": 8, "quantity": 250, "training_policy": "continuous", "allow_resource_boxes": true},
  "vehicle": {"enabled": true, "target_tier": 8, "quantity": 250, "training_policy": "continuous", "allow_resource_boxes": false}
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
  --fighter-tier 8 --shooter-tier 8 --rider-tier 8 --vehicle-tier 8 `
  --execute --yes
```

The normal route recognizes Home/Base, opens one configured facility, enters its training view,
and processes the enabled types by the four in-view tabs. It does not return Home or reopen a
facility between troop types. Every Train dispatch is one consequential action with an immediate
postcondition capture; the normal timed Train is the only training control authorized.

`--reconcile-unresolved-session <session>` is a recovery-only route. It requires the prior
immediate-post evidence and a fresh live queue matching troop type, tier, quantity, and timer. It
records the reconciliation and may navigate Home, but it has no consequential dispatch path.

`--continue-from-training --training-troop-type <type>` is a bounded continuation for a live
training view already reached by the route. It uses tabs only. `--continue-from-radial` is the
corresponding navigation recovery for a positively recognized radial menu; neither mode opens
another facility.

## Live BlueStacks observations

Fresh native frames showed Fighter Camp, Shooter Camp, Rider Camp, and Vehicle Depot on Home/Base.
The facility radial menu exposes Details, Upgrade, and Train. The training view has four tabs;
selecting a tab navigates to that troop type, and a completed banner can indicate automatic claim
behavior, so an unproven completed pre-state is never silently accepted as a claim.

The live account displayed T1–T8 as trainable and T9+ as question-mark locked tiers. Quantity is
edited through the numeric control and verified after entry. Normal Train displayed a live duration;
Train Now displayed a premium-currency cost and was never targeted. The validated default live
quantity was 250 at T8 for all four types. No warehouse continuation was required in the validated
run.

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
