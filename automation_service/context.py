"""Common read-only runtime and screen context classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from tasks.perception_bundle import (
    ContextualClass,
    FramePerceptionBundle,
    classify_frame_context,
)

from .contracts import PerceptionEnvelope


class RuntimeContext(str, Enum):
    STOPPED = "stopped"
    FOREGROUND = "foreground"
    LOADING = "loading"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class ScreenContext(str, Enum):
    HOME = "home"
    QUEST = "quest"
    KNOWN_SURFACE = "known_surface"
    UNKNOWN = "unknown"


class SafetyContext(str, Enum):
    NONE = "none"
    KNOWN_OVERLAY = "known_overlay"
    MANUAL_ONLY = "manual_only"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommonContextClassification:
    runtime: RuntimeContext
    screen: ScreenContext
    safety: SafetyContext
    recognized: bool
    interaction_allowed: bool
    reason_code: str
    supporting_evidence: tuple[str, ...] = ()


MANUAL_ONLY_IDENTITIES = frozenset(
    {"login", "captcha", "tutorial", "account_selection", "credential_entry", "manual_only"}
)


def classify_common_context(
    observation: FramePerceptionBundle | PerceptionEnvelope | None,
) -> CommonContextClassification:
    """Classify shared context only; gameplay handlers own all action transitions."""

    if observation is None:
        return CommonContextClassification(
            RuntimeContext.UNKNOWN,
            ScreenContext.UNKNOWN,
            SafetyContext.UNKNOWN,
            False,
            False,
            "NO_OBSERVATION",
        )
    if isinstance(observation, FramePerceptionBundle):
        context = classify_frame_context(observation)
        if context.contextual_class is ContextualClass.KNOWN_MODAL:
            return CommonContextClassification(
                RuntimeContext.FOREGROUND,
                ScreenContext.KNOWN_SURFACE,
                SafetyContext.KNOWN_OVERLAY,
                True,
                False,
                context.reason_code,
                context.supporting_observations,
            )
        if context.contextual_class is ContextualClass.CANONICAL_HOME:
            return CommonContextClassification(
                RuntimeContext.FOREGROUND,
                ScreenContext.HOME,
                SafetyContext.NONE,
                True,
                context.context_allows_interaction,
                context.reason_code,
                context.supporting_observations,
            )
        if context.contextual_class is ContextualClass.HOME_WITH_KNOWN_RADIAL:
            return CommonContextClassification(
                RuntimeContext.FOREGROUND,
                ScreenContext.HOME,
                SafetyContext.NONE,
                True,
                context.context_allows_interaction,
                context.reason_code,
                context.supporting_observations,
            )
        if context.contextual_class is ContextualClass.KNOWN_FULLSCREEN_SURFACE:
            return CommonContextClassification(
                RuntimeContext.FOREGROUND,
                ScreenContext.KNOWN_SURFACE,
                SafetyContext.NONE,
                context.context_recognized,
                context.context_allows_interaction,
                context.reason_code,
                context.supporting_observations,
            )
        return CommonContextClassification(
            RuntimeContext.FOREGROUND,
            ScreenContext.UNKNOWN,
            SafetyContext.UNKNOWN,
            False,
            False,
            context.reason_code,
            context.supporting_observations,
        )

    runtime_value = observation.runtime_state.strip().casefold()
    if runtime_value in {"loading", "animation"}:
        runtime = RuntimeContext.LOADING
    elif runtime_value in {"foreground", "ready"}:
        runtime = RuntimeContext.FOREGROUND
    elif runtime_value in {"disconnected", "stopped"}:
        runtime = RuntimeContext.DISCONNECTED if runtime_value == "disconnected" else RuntimeContext.STOPPED
    else:
        runtime = RuntimeContext.UNKNOWN

    context_value = observation.context.strip().casefold()
    screen = (
        ScreenContext.HOME
        if "home" in context_value
        else ScreenContext.QUEST
        if "quest" in context_value
        else ScreenContext.KNOWN_SURFACE
        if context_value in {"known_surface", "campaign", "ruins"}
        else ScreenContext.UNKNOWN
    )
    safety = (
        SafetyContext.MANUAL_ONLY
        if any(identity in context_value for identity in MANUAL_ONLY_IDENTITIES)
        else SafetyContext.UNKNOWN
        if context_value in {"unknown", ""}
        else SafetyContext.NONE
    )
    recognized = runtime is RuntimeContext.FOREGROUND and safety is SafetyContext.NONE and screen is not ScreenContext.UNKNOWN
    return CommonContextClassification(
        runtime,
        screen,
        safety,
        recognized,
        recognized and not observation.invalidated_after_input,
        "ENVELOPE_CONTEXT_CLASSIFIED" if recognized else "CONTEXT_NOT_ACTIONABLE",
        observation.negative_evidence,
    )


def classify_runtime_envelope(envelope: PerceptionEnvelope) -> CommonContextClassification:
    return classify_common_context(envelope)

