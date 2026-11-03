"""Shared navigation-session fixtures for offline tests."""

from __future__ import annotations

from pathlib import Path
import tempfile

from tasks.home_atlas import AmbiguityState, BuildingBinding, LocalizationResult, ZoomIdentity
from tasks.navigation_session import (
    AuthorizationScope,
    compute_pan_gesture_fingerprint,
    create_session,
    load_session,
    make_pan_action_key,
    record_pan_prepared,
    record_plan,
    record_source_home_verified,
    save_session,
)
from tasks.perception_bundle import (
    ContextualClass,
    FrameValidityState,
    ImmutableFrameValidationObservation,
    ImmutableRadialObservation,
    NativeFrameIdentity,
    binding_from_result,
    bundle_from_identity,
    classify_and_attach,
    localization_from_result,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


PROFILE = ACTIVE_RUNTIME_PROFILE_ID
PLATFORM = "BlueStacks 5 / Android"
BUILDING = "home.building.supply_depot"


def digest(tag: str) -> str:
    nibble = tag[:1].lower()
    if nibble not in "0123456789abcdef":
        raise AssertionError("digest tag must be a hex nibble")
    return nibble * 64


def scope(**overrides) -> AuthorizationScope:
    values = dict(
        task_id="RUNTIME-RESUMABLE-NAVIGATION-SESSIONS",
        owner_operator="test-operator",
        action_class="navigation_only",
        platform=PLATFORM,
        profile=PROFILE,
        environment="fixture",
        target_building_id=BUILDING,
    )
    values.update(overrides)
    return AuthorizationScope(**values)


def identity(
    *,
    session: str = "runtime-session-a",
    ordinal: int = 1,
    monotonic: float = 1000.0,
    transport: str = "a",
    semantic: str = "b",
    label: str = "fixture",
    profile_id: str = PROFILE,
) -> NativeFrameIdentity:
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=session,
        capture_ordinal=ordinal,
        capture_completed_monotonic=monotonic,
        transport_sha256=digest(transport),
        semantic_sha256=digest(semantic),
        runtime_profile_id=profile_id,
        width=800,
        height=1280,
        label=label,
    )


def localization_result(frame: NativeFrameIdentity, **overrides) -> LocalizationResult:
    values = dict(
        recognized=True,
        platform=PLATFORM,
        profile_id=PROFILE,
        zoom_identity=ZoomIdentity.FULLY_ZOOMED_OUT,
        screen_to_atlas=((1.0, 0.0, 100.0), (0.0, 1.0, 200.0), (0.0, 0.0, 1.0)),
        viewport_polygon=((100.0, 200.0), (900.0, 200.0), (900.0, 1480.0), (100.0, 1480.0)),
        confidence=0.95,
        supporting_landmarks=("v1",),
        residual_px=0.2,
        ambiguity_state=AmbiguityState.NONE,
        map_edge_state="interior",
        frame_sha256=frame.semantic_sha256,
        timestamp="2026-07-19T00:00:00+00:00",
        stale=False,
        overlay=False,
    )
    values.update(overrides)
    return LocalizationResult(**values)


def binding_result(frame: NativeFrameIdentity, **overrides) -> BuildingBinding:
    values = dict(
        building_id=BUILDING,
        target_roi=(320, 420, 420, 520),
        frame_sha256=frame.semantic_sha256,
        confidence=0.94,
        semantic_evidence=("current-frame OCR: Supply Depot",),
        overlay_intersects=False,
        ambiguous_overlap=False,
    )
    values.update(overrides)
    return BuildingBinding(**values)


def frame_validation(frame: NativeFrameIdentity) -> ImmutableFrameValidationObservation:
    return ImmutableFrameValidationObservation(
        source_frame=frame,
        validity=FrameValidityState.VALID_NATIVE,
        expected_profile_id=PROFILE,
        expected_width=800,
        expected_height=1280,
        expected_platform=PLATFORM,
        package_ok=True,
        orientation_ok=True,
        supporting_evidence=("fixture",),
    )


def home_bundle(
    frame: NativeFrameIdentity,
    *,
    with_binding: bool = False,
    localization_overrides: dict | None = None,
    binding_overrides: dict | None = None,
):
    loc = localization_result(frame, **(localization_overrides or {}))
    bundle = (
        bundle_from_identity(frame)
        .with_frame_validation(frame_validation(frame))
        .with_localization(localization_from_result(frame, loc))
    )
    if with_binding:
        bundle = bundle.with_building_binding(
            binding_from_result(frame, binding_result(frame, **(binding_overrides or {})))
        )
    return classify_and_attach(bundle)


def radial_home_bundle(
    frame: NativeFrameIdentity,
    *,
    facility_identity: str = BUILDING,
    localization_overrides: dict | None = None,
):
    loc = localization_result(frame, **(localization_overrides or {}))
    bundle = (
        bundle_from_identity(frame)
        .with_frame_validation(frame_validation(frame))
        .with_localization(localization_from_result(frame, loc))
        .with_radial(ImmutableRadialObservation(frame, facility_identity, 0.91, ("fixture-radial",)))
    )
    classified = classify_and_attach(bundle)
    assert classified.context is not None
    assert classified.context.contextual_class is ContextualClass.HOME_WITH_KNOWN_RADIAL
    return classified


def prepared_uncertain_session(requested=(10.0, 0.0), predicted=(9.0, 0.0)):
    session, frame = verified_session()
    record_plan(session, requested=requested, predicted=predicted)
    next_pan = session.pan_ordinal + 1
    fingerprint = compute_pan_gesture_fingerprint(
        session, pan_ordinal=next_pan, requested=requested, predicted=predicted, source_frame=frame
    )
    action_key = make_pan_action_key(session, fingerprint, next_pan)
    record_pan_prepared(
        session,
        action_key=action_key,
        source_frame=frame,
        requested=requested,
        predicted=predicted,
        gesture_fingerprint=fingerprint,
    )
    return session, frame, action_key, fingerprint


def save_reload(session):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session.json"
        save_session(session, path)
        return load_session(path)


def verified_session(*, runtime: str = "runtime-session-a"):
    session = create_session(scope(), runtime_capture_session_id=runtime, maximum_pans=4)
    frame = identity(session=runtime, ordinal=1, transport="1", semantic="2")
    record_source_home_verified(session, frame=frame, localization_confidence=0.95)
    return session, frame
