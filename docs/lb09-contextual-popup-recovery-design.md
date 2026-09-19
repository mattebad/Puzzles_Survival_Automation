# LB-09 contextual VIP popup recovery

## Status and scope

This document freezes the LB-09 contract and records its offline verification checkpoint. The
store-free helper and existing Noah's Tavern Recruitment integration are implemented in the
checkpoint committed at `36e7af0`. Live canary and natural-popup proof remain pending and are not
authorized. This work does not start live gameplay, enable a scheduler, change popup
recognition thresholds, or generalize recovery to unknown surfaces.

The first implementation supports only the exact `VIP_POINTS_GET_PTS` modal already recognized
by `recognize_reset_popup`. Startup Scarlett/commercial recovery and the existing startup VIP
ledger remain unchanged.

## Problem

The existing VIP recovery path is startup-only. It owns a separate `SafetyStore` action record
and requires a Home successor. That is unsuitable after Recruitment has started:

- a popup may cover either Home, Tavern, a recruit result, or a post-result cooldown;
- the popup invalidates any target selected from the covered frame;
- a free recruit may already have been transported and must not be repeated;
- dismissing the popup does not prove that the route is ready to continue.

LB-09 therefore separates exact-popup dismissal, exact-popup absence, and route readiness.
The active route, not the popup helper, decides which successor is valid.

## Ownership boundaries

`scripts/bluestacks_popup_recognition.py`

- remains recognition-only;
- supplies `recognize_reset_popup` and `classify_popup_recovery`;
- grants dismissal classification only for exact VIP title/body, literal `Close`, retained
  native geometry, and the allowlisted target identity;
- never grants generic Confirm, Close, or Back authority.

`scripts/startup_recovery.py`

- owns the new store-free contextual helper;
- recaptures and rebinds the exact Close target immediately before transport;
- performs at most one navigation-class Close for one invocation;
- reports facts but does not decide Recruitment progress.

`scripts/noahs_tavern_recruit_bluestacks.py`

- supplies the expected source context and successor callback;
- abandons commands derived before a dismissal;
- preserves pending recruit and maintenance state;
- blocks when the helper cannot prove a fresh route-specific successor.

`LocalBlueStacksRuntime`

- retains captures, dispatches, input count, duplicate action keys, the session ceiling, and
  reconciliation events;
- remains transport-only and gains no popup semantics.

`automation_service/recruitment.py` and
`scripts/flow_delivery_recruitment_bluestacks.py`

- continue consuming the unified Recruitment result and retained native events;
- do not gain popup authority;
- count a popup Close as route/navigation input, never as a completed recruit.

## Shared helper contract

The helper and result type live in `scripts/startup_recovery.py`:

```python
@dataclass(frozen=True)
class ContextualPopupRecoveryResult:
    settled_frame: CapturedNativeFrame | None
    dismissed: bool | None
    popup_absent: bool | None
    resume_ready: bool
    input_count: int
    reason: str


def recover_contextual_vip_popup(
    runtime: LocalBlueStacksRuntime,
    captured: CapturedNativeFrame,
    *,
    source_context: str,
    recognize_successor: Callable[[np.ndarray], bool],
    action_key: str,
    settle_seconds: float = 0.8,
    sleep: Callable[[float], None] = time.sleep,
) -> ContextualPopupRecoveryResult:
    ...
```

The supplied `captured` frame is a current native frame retained by the same runtime. The
helper validates a non-empty source context and the caller-supplied action key. It does not
capture an initial replacement unless an exact popup is present.

### Result semantics

- `dismissed=True`: exactly one exact Close transport returned successfully.
- `dismissed=False`: no Close transport was attempted.
- `dismissed=None`: runtime authorization began and transport completion is uncertain.
- `popup_absent=True`: a trustworthy current frame was checked and no exact VIP popup remains.
- `popup_absent=False`: a fresh post-transport frame still recognizes the exact popup.
- `popup_absent=None`: no trustworthy absence decision is available.
- `resume_ready=True`: `recognize_successor` accepted the same frame returned in
  `settled_frame`.
- `input_count`: the runtime input-count delta for this helper call; it is always zero or one.

`dismissed`, `popup_absent`, and `resume_ready` are deliberately independent. In particular,
a successful Close may leave a persistent popup or reveal an unexpected screen.

### Decision table

| Condition | dismissed | popup_absent | resume_ready | inputs | Reason |
| --- | --- | --- | --- | --- | --- |
| Supplied frame has no exact VIP popup | `False` | `True` | successor result | 0 | `exact_vip_popup_absent` |
| Exact popup classification does not allow dismissal | `False` | `None` | `False` | 0 | `vip_popup_dismissal_not_allowed` |
| Pre-dispatch recapture fails or popup/target identity changes | `False` | `None` | `False` | 0 | `vip_popup_revalidation_failed` |
| Runtime rejects the action key or input ceiling before transport | `False` | `None` | `False` | 0 | `vip_popup_dispatch_not_authorized` |
| Transport completion is uncertain | `None` | `None` | `False` | 1 | `vip_popup_transport_uncertain` |
| Close transport completes but no post frame can be captured | `True` | `None` | `False` | 1 | `vip_popup_post_capture_failed` |
| Fresh post frame still has exact VIP | `True` | `False` | `False` | 1 | `vip_popup_persisted` |
| Popup is absent but expected context is not ready | `True` | `True` | `False` | 1 | `popup_dismissed_context_not_ready` |
| Popup is absent and expected context is ready | `True` | `True` | `True` | 1 | `popup_dismissed_resume_ready` |

A successor callback exception is not treated as readiness. If the frame itself is trustworthy,
popup absence may still be `True`, but `resume_ready` remains `False` and the route blocks.

## Exact recovery sequence

1. Run `recognize_reset_popup` on `captured`.
2. If no exact popup is recognized, run the successor callback on that same frame and return
   without input.
3. Project the exact recognition through `classify_popup_recovery` using `source_context`.
   Continue only when `allows_dismissal` is true.
4. Check the route/session one-dismissal bound and the runtime input ceiling.
5. Capture one fresh pre-dispatch frame.
6. Recognize the same popup identity again and require a freshly detected literal-Close ROI
   and target identity. Never reuse the ROI from `captured`.
7. Call `runtime.tap` once with:
   - `target_identity="reset-popup-close"`;
   - the freshly rebound target ROI;
   - the caller's route-scoped action key;
   - `action_class="navigation"`;
   - `consequential=False`.
8. Sleep for the bounded settle interval and capture one post frame.
9. Recognize exact-popup presence and route-specific successor readiness independently.
10. Call `runtime.reconcile` as confirmed when a valid post frame proves popup absence, even
    if the route-specific successor is not ready. Dismissal and route admission are separate
    outcomes. Use unresolved when the exact popup persists. If no post frame exists, do not
    fabricate one merely to write a reconciliation event.
11. Return the structured result. Any uncertain or non-ready result causes the caller to stop
    or retain its existing inspection outcome.

The helper catches only expected recognition, capture, and transport failures needed to return
the structured outcome. Stop/checkpoint exceptions must continue to abort the route immediately.

## Action identity and recurrence bound

Recruitment uses:

```text
noah:popup-close:<source-context>:<source-sha256>
```

`source-context` is one of the route-owned values below and contains only lowercase letters,
digits, and hyphens. `source-sha256` is the supplied retained frame digest. It is evidence
identity, not permission to reuse an old ROI.

The unified Recruitment invocation permits at most one contextual VIP Close across Home
normalization, Tavern work, result reconciliation, and safe return. A second recognized popup
in the same runtime session blocks without input, even if its frame digest differs. This bound
is enforced in route-owned in-memory state/runtime action keys; it creates no database or global
gate.

The contextual namespace cannot collide with
`startup-recovery:vip-reset-close:<scope-digest>`. The contextual helper neither reads nor clears
the startup `SafetyStore`, so the unresolved startup VIP record remains untouched.

The contextual Close consumes the existing route input ceiling. LB-09 does not add an input
allowance. An externally completed startup recovery keeps its existing separately accounted
allowance.

## Recruitment integration

### Home normalization and Atlas entry

Every Home-normalization source frame and the final Atlas-entry probe first pass through the
contextual helper.

The Home successor callback accepts either:

- `recognize_home_zoom_source(frame)` success; or
- fresh canonical Atlas Home localization: recognized, fully zoomed out, current-frame digest,
  no overlay, and no ambiguity.

Source contexts are `home-normalization` and `home-atlas-entry`.

When no popup is present and the context is ready, the existing normalization or binding logic
uses the same current frame. When a popup is dismissed, every localization, planned gesture,
binding, and ROI derived before dismissal is discarded. The normal loop restarts from
`settled_frame` and recomputes the decision.

### Tavern route observations

`NoahTavernIntegratedRoute._observe` becomes the single popup-aware observation seam. Its
expected successor depends on existing route state:

| Existing state | Source context | Only resumable successor |
| --- | --- | --- |
| No pending recruit | `home-or-tavern` | recognized Home/canonical Atlas Home or recognized Tavern |
| `pending_action_key` set, no `pending_result` | `recruit-result-<tier>` | recognized recruit-result screen |
| `pending_result` set, result Close not dispatched | `recruit-result-close-<tier>` | the same recognized recruit-result screen |
| Result Close dispatched | `recruit-postcondition-<tier>` | recognized same-tier Tavern cooldown/postcondition |

The tier comes from the controller's awaiting tier/pending result, never from the popup-covered
frame. A route-local `result_close_dispatched` flag distinguishes a popup covering the result's
Close control from a popup revealed after that Close transport. The flag is set immediately
after the Close transport returns and cleared only after the existing postcondition succeeds;
it is not persisted or added to the native runtime. `_observe` recognizes the helper's
`settled_frame` again and returns that fresh recognition. It never returns a recognition or
target from the original covered frame.

### Pre-dispatch checks

The exact contextual check runs on the current frame immediately before:

- Home zoom/pan and Tavern building entry;
- tier selection;
- free-recruit transport;
- result Close;
- Tavern safe return.

These checks use `home-normalization`, `home-atlas-entry`, `home-or-tavern`,
`recruit-result-<tier>`, `recruit-result-close-<tier>`,
`recruit-postcondition-<tier>`, and `tavern-safe-return` as their closed set of
source-context values.

If no popup is present, the current command may proceed only when its expected source still
matches. If a popup is dismissed, the pending command is abandoned and the route continues its
normal loop from the fresh settled frame. No target selected before the dismissal may dispatch.

The navigation safe-return helper receives the same popup-aware pre-dispatch seam rather than
adding its own recognizer or coordinates.

### Post-consumption interruption

Immediately after a free-recruit tap returns, the existing `pending_action_key`, controller
awaiting-postcondition state, awaiting tier, and before-observation remain authoritative.

If VIP appears while waiting for the result:

1. dismiss VIP at most once;
2. require a fresh recognized recruit-result screen;
3. continue observing the same pending recruit;
4. never issue another `RECRUIT_FREE`.

If VIP appears after result Close:

1. preserve `pending_result`, `result_close_dispatched`, and the pending recruit key;
2. dismiss VIP at most once;
3. require the fresh same-tier cooldown/postcondition;
4. let the existing controller verify and persist the transition.

Popup recovery never calls the recruit controller's completion method and never reconciles the
pending recruit by itself.

## Accounting and persistence invariants

- The popup Close increments `LocalBlueStacksRuntime.input_count` and retained native transport
  count by one.
- It does not increment `actions_completed`, `recruitment_dispatch_count`, basic daily count,
  tier attempts, or maintenance revision.
- A free recruit remains counted only from its exact retained transport and normal semantic
  postcondition.
- Cooldown/count state advances only through existing controller verification.
- `next_due` advances only after the unified route returns verified terminal Home.
- `pending_action_key`, `pending_result`, `result_close_dispatched`, controller awaiting state,
  input ceiling, checkpoint, stop callback, runtime ownership, and singleton lock survive the
  interruption unchanged.
- Persistent, uncertain, or unexpected recovery returns blocked/unresolved and retains the
  Recruitment inspection block.
- Startup VIP action records are neither read nor mutated.

The unified result includes bounded contextual-recovery records containing source/settled
digests, source context, the five result fields, and the reason. Flow-delivery verification
continues deriving total and recruitment-specific counts from retained events; it must accept
one extra navigation transport without treating it as Recruitment completion.

## Failure and stop behavior

- Wrong title/body, generic orange controls, old Close coordinates, scaled frames, ambiguous
  geometry, unknown overlays, commercial/login/tutorial/CAPTCHA/credential/account-switch
  surfaces: no input and normal route block.
- Changed popup identity or target between recognition and dispatch: no input.
- Existing contextual action key, exhausted input ceiling, or exhausted one-dismissal bound:
  no input.
- Transport uncertainty: no retry; return unresolved and preserve the consumed input slot/key.
- Post-capture failure: no retry; dismissal may be known, but popup absence/readiness are not.
- Persistent exact popup: no second Close.
- Popup absent with unexpected successor: dismissal remains recorded, but resumption blocks.

The frozen contract's offline checkpoint is satisfied in the committed `36e7af0` candidate:

- Exact `VIP_POINTS_GET_PTS` title/body recognition, literal `Close`, retained native geometry,
  and the dismissal/absence/readiness tri-state outcomes are covered offline.
- The helper performs one fresh pre-dispatch rebind and one contextual Close at most; Recruitment
  preserves phase-aware pending recruit/result state, invalidates stale commands, re-observes after
  dismissal, and counts the Close as navigation input rather than recruitment completion.
- Focused verification passed: 135 tests passed with 1 skipped; the additional changed-route
  command passed 50 tests. Python compilation and `git diff --check` passed. Python LSP was
  unavailable. These are focused checks, not a full-suite result.
- Independent helper, accounting, integration, and route reviews passed after the safe-return
  stale-Back finding was repaired.
- No live canary or natural-popup proof was run. This checkpoint does not claim live popup
  recovery, production registration, scheduler enablement, or natural-popup proof.