# Noah's Tavern Daily Free Recruit

This is a separate workflow with an executable local BlueStacks route. It does not import the
legacy free-recruit or daily-recruit contracts and it has no production registration, scheduler,
purchase, ticket, or Claim path.

## Native observations

All interaction targets were bound from fresh Computer Use frames for BlueStacks window `2102310`
with the 800x1280 game profile. The visible enabled control was the purple `Free Recruit 1x`
button. The orange `Recruit 10x` and result-screen `Recruit 1x` controls were never selected.

| Tier | Daily Free maximum | Observed cooldown text | Duration used by controller |
| --- | ---: | --- | ---: |
| Basic Recruit | 5 | `Free in 00:09:52` | 600 seconds (10 minutes nominal) |
| Int. Recruit | 1 | `Free in 23:59:51` | 86,400 seconds (24 hours nominal) |
| Adv. Recruit | 1 | `Free in 1d23:59:52` | 172,800 seconds (2 days nominal) |

The displayed values are remaining timers captured immediately after the successful recruit; the
nominal duration is therefore rounded up to the tier's full cooldown period.

## Runtime safety

`tasks/noahs_tavern_recruit.py` contains the semantic contract, `tasks/noahs_tavern_recruit_vision.py`
contains native OCR/color recognition, `tasks/noahs_tavern_recruit_runtime.py` contains the
one-command-at-a-time controller, and `scripts/noahs_tavern_recruit_bluestacks.py` is the
dry-run-by-default executable route. With explicit `--execute --yes`, it captures each native frame
through the local BlueStacks ADB endpoint, drives Home → Tavern → free single recruit → result →
postcondition → Home, and retains every frame and transport event under `.local-captures/`.

The controller stores independent tier state, hashes and action keys, requires a fresh result and
post-close frame, rejects stale/unknown/overlay/premium states, yields one scheduler-ready wait
command during cooldown, and returns Home/Base when the aggregate reaches 5. Claim is deliberately
not an action in this workflow.

The bounded command is:

```text
python scripts/noahs_tavern_recruit_bluestacks.py --adb <BlueStacks-ADB> --serial <local-serial> --max-recruits 1 --execute --yes
```

Omitting `--execute` performs capture/connection setup but issues no input. The local route remains
unregistered and scheduler-disabled; a later Bliss transport can implement the same runtime port
without changing the semantic controller.

The 2026-07-16 integrated execution proved Home → Tavern → Basic free recruit → explicit `Bard
Frag` result → cooldown → Home. The live UI displayed `Daily free attempts: 2` before dispatch and
hides that counter while cooldown is active; the verified successor displayed `Free in 00:06:47`.
The controller permits the hidden 2 → 1 successor only after both the explicit reward and new
cooldown are proven. Retained recovery is keyed to the original action and cannot dispatch a second
recruit.
