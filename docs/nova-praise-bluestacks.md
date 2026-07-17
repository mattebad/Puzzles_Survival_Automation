# Nova Praise — local BlueStacks workflow

Nova Praise is a separate local-BlueStacks workflow with an executable integrated route. It does not reuse the
Personal Might leaderboard route, the left-side Research overlay, Research Queue, or the
free Bioenhancer contract.

## Route and safety boundary

1. Recognize Home/Base and zoom the map out with Ctrl held while scrolling down.
2. Bind the Research Lab building from the current native 800×1280 frame.
3. Open the building menu; if clipped, drag the map until the complete menu is visible.
4. Bind the menu's distinct Nova control and recognize the Nova screen.
5. Bind one enabled Praise control and read the remaining Interaction attempts count.
6. Dispatch one zero-cost Praise at most once, then require a fresh frame.
7. Require an exact one-attempt decrement and a visible `CD: HH:MM:SS`/equivalent cooldown.
8. Persist the next-eligible timestamp and yield a scheduler-ready waiting state.
9. Re-enter Nova only after eligibility; stop at zero and return Home/Base.

Unknown screen, missing or disabled Praise, stale frame, overlay, cooldown mismatch, duplicate
frame, or ambiguous postcondition is fail-closed. Production registration and scheduler eligibility
remain disabled.

## Local BlueStacks inspection

Computer Use inspection on 2026-07-16 established and retained in the task session:

- Home/Base with the Research Lab building identity;
- Research Lab menu with separate Nova and Bioenhancer controls;
- Nova screen with Praise enabled and 7 attempts;
- delayed post-Praise Nova screen with disabled controls, `CD: 00:01:44`, and 6 attempts.

The first cooldown was five minutes; the delayed frame is the settled postcondition after elapsed
time. No zero-attempt terminal frame was produced in this bounded validation because the workflow
correctly yielded during cooldown rather than busy-looping or consuming additional attempts.

The live Praise action was positively reconciled from the settled frame. No live action remains
unresolved.

`scripts/nova_praise_bluestacks.py` now performs the complete Home → Research Lab → Nova → one
Praise → exact decrement/cooldown postcondition → Home route. It is dry-run by default and requires
both `--execute` and `--yes` before any local input:

```text
python scripts/nova_praise_bluestacks.py --adb <BlueStacks-ADB> --serial <local-serial> --execute --yes
```

Each consequential Praise remains single-flight until its semantic postcondition is reconciled.
Frames and transport events are retained under `.local-captures/`. Production registration and
scheduler eligibility remain unchanged and disabled.

The 2026-07-16 integrated execution proved Home → Research Lab radial menu → Nova → Praise → Home.
The exact successor was `Interaction attempts left: 6` to `5` with `CD: 00:04:38`. The retained
reconciliation command can complete only that original unresolved action key from its source and
current cooldown evidence; it cannot dispatch another Praise.
