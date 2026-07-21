# Flow-delivery coverage

Machine-readable companion: `tasks/flow_delivery_coverage.json`.

This matrix tracks development-flow coverage contracts. It does not authorize runtime input,
production registration, or gameplay scheduling.

## Campaign AP farming

Flow: `CAMPAIGN-AP-HOME-ATLAS-AND-DESTINATION-NAVIGATION`

| Coverage field | State |
| --- | --- |
| `home_navigation_state` | contracted, not implemented |
| `story_destination_navigation_state` | contracted, not implemented |
| `ap_execution_state` | preserved existing behavior; separate from destination verification |
| `supported_story_destinations` | `1-20-9`, `1-15-9`, `2-2-9` |

Product tuple format:

```text
<story difficulty>-<stage>-<chapter>
```

Examples:

- `1-20-9` = difficulty 1, Stage 20, Chapter 9
- `1-15-9` = difficulty 1, Stage 15, Chapter 9
- `2-2-9` = difficulty 2, Stage 2, Chapter 9

Removed from the Campaign AP destination contract and not retained as aliases:

- `1-2-9`
- `ultimate-challenge`

All other Story destination tuples fail closed unless a future explicit product decision adds them.
Ultimate Challenge coverage is not part of this flow.

## Ultimate Challenge daily

Flow: `ULTIMATE-CHALLENGE-DAILY-BLUESTACKS-INTEGRATION`

| Coverage field | State |
| --- | --- |
| `campaign_entry_state` | offline navigation contract implemented (Home Atlas Campaign door reuse) |
| `ultimate_challenge_navigation_state` | offline navigation contract implemented (entry bind; no challenge action) |
| `daily_execution_state` | contracted, not implemented |
| `already_completed_detection_state` | offline contract implemented |
| `reset_idempotency_state` | offline contract implemented (one-success-per-reset) |

This flow is separate from ordinary Campaign AP expenditure. Completing Campaign AP does not
complete Ultimate Challenge, and completing Ultimate Challenge does not complete Campaign AP.
Navigation-only validation opens Campaign via Home Atlas `home.building.campaign` and verifies
the Ultimate Challenge entry control; it never routes UC through Campaign story destination
parsing.
