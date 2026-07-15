# BlueStacks flow capture

`bluestacks_flow_collector.py` is a manual recorder for building a translation corpus. It records
clean portrait screenshots, selected coordinates, labels, notes, and user-observed successors. It
does not discover routes, decide what to tap, retry actions, or execute quests autonomously.

## Setup and safety

Use a local Windows BlueStacks instance with the game displayed in portrait at `800x1280`. Set
approximately `160 DPI` when BlueStacks exposes that setting. Enable BlueStacks local ADB and note
the exact loopback serial, normally something like `127.0.0.1:5555` or `localhost:5555`.

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

## Demonstrate a flow

1. Confirm the displayed serial and safety state.
2. Use **Capture current frame** whenever the current screen needs a fresh observation.
3. Label the current screen, selected target, and expected successor before recording the step.
4. Use **Tap**, **Swipe**, **Android Back**, or **Wait**. Tap and swipe selections show display and
   raw coordinates before confirmation. Dispatch mode requires a separate confirmation and sends
   one input. Record-only mode prompts the user to perform the action manually and captures the
   after frame only after the user confirms readiness.
5. Add notes and set objective progress before/after as observed. Keep the final row-control state
   explicit. Stop when the Daily row becomes Claim-ready; do not tap Claim unless the session is
   specifically capturing Claim behavior.
6. Mark the flow complete and choose **Export ZIP**. The exporter refreshes the deterministic
   manifest, creates a sorted ZIP, parses the archived manifest, and verifies every archived
   artifact hash. An aborted or interrupted session is retained for diagnosis.

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
