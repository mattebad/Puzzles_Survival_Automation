# BlueStacks flow capture

`bluestacks_flow_collector.py` is a manual recorder for building a translation corpus. It records
clean portrait screenshots, selected coordinates, labels, notes, and user-observed successors. It
does not discover routes, decide what to tap, retry actions, or execute quests autonomously.

## Setup and safety

Use a local Windows BlueStacks instance with the game displayed in portrait at `800x1280`. Set
approximately `160 DPI` when BlueStacks exposes that setting. Enable BlueStacks local ADB and note
the exact local serial, normally something like `127.0.0.1:5555`, `localhost:5555`, or the
local emulator transport reported by BlueStacks HD-Adb such as `emulator-5554`.

Keep the Bliss runtime, Unraid worker, other automation, and any second recorder isolated. Do not
use the same game account concurrently from BlueStacks and Bliss. The collector never runs `adb
connect`; it requires the exact serial to be selected and confirmed. A wrong package, wrong
orientation or resolution, non-loopback serial, offline device, known Bliss serial, or failed
foreground check disables dispatch. Record-only mode remains available for diagnosis.

## Start a session

From the repository on Windows, run:

```powershell
python scripts\bluestacks_flow_collector.py --serial 127.0.0.1:5555 --flow-id consume-ap-campaign --daily-objective "Consume AP"
```

For a synthetic image or a headless smoke session, use mock mode. Mock mode invokes no ADB code:

```powershell
python scripts\bluestacks_flow_collector.py --mock-image path\to\800x1280.png --flow-id collector-smoke-test --daily-objective "Collector smoke test"
```

Add `--record-only` to live sessions when the user will perform every action manually. Add
`--no-gui` only for a temporary mock manifest/ZIP check. Sessions are written beneath
`.local-captures\bluestacks\<flow-id>\<UTC-session-id>\` and are intentionally ignored by Git.

### Passive recording (recommended for route capture)

For chronological route capture, select the BlueStacks window or process and run passive mode. The
collector observes only while that selected window is foreground, records normal mouse taps and
drags/swipes without blocking or replaying them, and keeps a rolling clean-frame buffer for the
pre-action image. Press `F8` to start and `F9` to stop by default; `--start-hotkey`,
`--stop-hotkey`, and `--back-hotkey` are configurable. Screen labels, target names, successors,
notes, and semantic results remain optional metadata.

```powershell
python scripts\bluestacks_flow_collector.py --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial emulator-5554 --passive --window-title "BlueStacks" --flow-id consume-ap-campaign --daily-objective "Consume AP"
```

Run the terminal at the same Windows integrity level as BlueStacks. If BlueStacks is elevated, open
PowerShell with **Run as administrator**. The collector checks both process integrity levels and fails
before installing hooks when it cannot safely observe the selected player.

Use `--window-handle 0x...` or `--process-id <pid>` when title matching is ambiguous. The passive
mode captures client coordinates, maps them through the portrait 800x1280 letterboxed frame,
classifies movement using configurable distance and duration thresholds, captures the delayed
after frame, and exports the ordered manifest and verified ZIP when stopped. It never sends ADB
input. The existing collector GUI remains available as an optional manual annotation/fallback
workflow.

## Demonstrate a flow

1. Confirm the displayed serial and safety state.
2. For passive capture, bring the selected BlueStacks window forward, press the start hotkey, and
   demonstrate the route directly in the normal game window. No collector Tap or Swipe button is
   required, and the collector does not interrupt or replay the action.
3. For the manual fallback, use **Capture current frame**, then optionally label the current screen,
   target, and successor before using **Tap**, **Swipe**, **Android Back**, or **Wait**.
4. Add notes and set objective progress before/after as observed. These annotations are optional and
   can be added after the route is captured.
5. Stop when the Daily row becomes Claim-ready; do not tap Claim unless the session is specifically
   capturing Claim behavior.
6. Press the passive stop hotkey or use **Mark flow complete** in the manual GUI, then choose
   **Export ZIP** if the GUI path was used. Passive mode acknowledges the stop immediately, but final
   output can take several seconds while queued delayed after-frames finish and the manifest and ZIP
   hashes are verified. An aborted or interrupted session is retained for diagnosis.

## Consume AP example

Daily starts at `0/20`. Label the Daily screen and record the user-driven route to **Campaign**,
then perform **Auto Complete**. Return to Daily and label the observed result: Daily shows `20/20`
with **Claim**. Leave Claim untapped and record the final row-control state as Claim-ready,
Claim untapped. Export the ZIP for the later Bliss implementation; the ZIP is a translation source,
not production authorization.

## Recommended first-pass capture order

1. AP through Campaign Auto Complete
2. AP through Challenge fallback
3. zombie lair and stamina
4. Quick Join lair
5. gathering each resource type
6. one-unit 1-star Gear enhancement
7. one-unit 1-star Chip enhancement
8. one-unit 1-star Module enhancement
9. nano-weapon build or craft
10. free recruitment
11. Supply Depot five free collections
12. remaining training, donation, research, and consumption objectives

Provide the exported ZIP to the Bliss implementation work only after reviewing its labels, clean
before/after frames, annotated selections, semantic notes, and unresolved or canceled steps.
