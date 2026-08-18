# Android Back state matrix

Android Back is state-specific transport, never a generic return-Home operation. Unknown or
unproven transitions dispatch zero input. A transition becomes `safe` only after retaining a native
800×1280 immediate-before frame, exact source recognition, immediate-post/settled successor frames,
their hashes, and the session/action key.

| Source state | Expected successor | Status | Evidence or required action |
| --- | --- | --- | --- |
| Base/Home | none | `unsafe` | Top-level Back may request app exit. Use a visible in-game control or remain Home. |
| Base/Home with Research Lab radial | close radial/Home | `unsafe` | Nova fixture `stale-radial-translated-dff2386b.png` followed by Android Back produced `post-stale-radial-back-f15b73cc.png`, the exact exit dialog. |
| Campaign tier map | Home | `unsafe` | Ultimate session `daily-20260818T003817175329Z/nav-20260818T003817641599Z`: action `campaign-back-20260818T003851589541Z` transformed frame SHA-256 `376980f53ded2a493b1f6c5caa9daac0184d74258ce8aea2c3b0b2a4a5ae6833` into exit-dialog SHA-256 `c8f001e235eeb7964a51af285e8cae12614dfe9dcc1675e735d18b84c99dc295`. Use measured `campaign-exit-base`. |
| World top level | Base/Home | `evidence_required` and prohibited | No retained native transition proof. Use a visible World/Base toggle. |
| World search overlay | World ready | `evidence_required` | `world_map_navigation_bluestacks.py` is source/successor-gated, but no independently inspectable native before/after pair is retained. |
| Ultimate Challenge main | Campaign | `evidence_required` | The current route is source/successor-gated, but the transition needs a retained hash-bound visual pair before being classified safe. |
| Selected Daily | Home | `evidence_required` | Daily Claim is source/successor-gated, but its claimed live transition lacks accessible retained source/post PNG hashes. |
| Noah's Tavern | Home | `evidence_required` | Source/successor-gated; native before/after proof remains missing. |
| Troop Training surfaces | parent/Home | `evidence_required` | Multiple source-gated Back calls exist; retain and classify each exact surface separately. |
| Ruins Chat/detail/list surfaces | parent/Home | `evidence_required` | Multiple source-gated Back calls exist; retain and classify each exact surface separately. |
| Commander enhancement terminal | selected Daily | `evidence_required` | Current implementation assumes generic Back; no native before/after proof. |
| Bioenhancer/radial surfaces | Home | `evidence_required`; generic helper unsafe | Current helper allows two generic Back attempts without exact source binding. Disable or replace before another live run. |
| Nova screen (`NOVA_SCREEN`) | canonical Home | `safe` for one exact transition only | Retained native transition `be223f...` → immediate post `2405e1...` → settled Home `abb002...` authorizes at most one revalidated Nova-screen Back. |
| Research Lab radial menu | Home | `unsafe` | The retained radial counterexample produced the exact exit dialog; never issue Android Back from `RESEARCH_LAB_MENU` or an unknown successor. |

## Exit-dialog recovery

The exact `Exit the game?` dialog is recoverable only by freshly binding and tapping Cancel. Confirm
is always forbidden. After Cancel, recapture and classify the actual successor; never retry Back.

## Promotion procedure

1. Select one exact source state and one expected successor.
2. Start from a current native frame with positive source recognition.
3. Reserve one bounded non-consequential input and retain the immediate-before frame/hash.
4. Dispatch Android Back once.
5. Retain immediate-post and settled frames/hashes.
6. If the exit dialog appears, classify the source as `unsafe`, tap only exact Cancel under a
   separately bounded recovery, and retain the recovered state.
7. Mark `safe` only when the expected successor is independently recognized. Any ambiguity remains
   `evidence_required`.
