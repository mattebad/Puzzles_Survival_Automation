"""Flow-agnostic navigation-development boundary for direct BlueStacks work.

Owns the fixed cross-process runtime input lock, route-declaration validation,
navigation-only gesture firewall, current-frame
safety checks, and shared terminal evidence finalization.

This module is intentionally flow-agnostic: adapters supply route declarations and
source-state safety facts. It never reads flow-delivery queue, lease, context,
receipts, governance, architecture, handoff, or backlog metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from contextvars import ContextVar
from typing import Any, Callable, Mapping, Sequence

from scripts.bluestacks_flow_collector import EXPECTED_PACKAGE
from scripts.bluestacks_native_runtime import (
    CapturedNativeFrame,
    NATIVE_HEIGHT,
    NATIVE_RUNTIME_PROFILE_ID,
    NATIVE_WIDTH,
    NativeBox,
    NativeRuntimePort,
    reject_real_money_confirmation,
)
from safe_action_core import SafetyStore


REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = REPO_ROOT / ".local-orchestrator"
RUNTIME_INPUT_LOCK_PATH = ORCHESTRATOR_DIR / "bluestacks-runtime-input-lock.sqlite3"
CANONICAL_ACTION_STORE_PATH = ORCHESTRATOR_DIR / "bluestacks-actions.sqlite3"

DEFAULT_FRAME_MAX_AGE_SECONDS = 30.0

ALLOWED_GESTURE_CLASSES = frozenset({"tap", "swipe", "back", "zoom_out"})
FORBIDDEN_GESTURE_CLASSES = frozenset(
    {"long_press", "type_text", "clear_numeric_text", "press_key", "quantity_input"}
)
TERMINAL_RESULT_STATUSES = frozenset(
    {"completed", "blocked", "manual_required", "unresolved", "failed"}
)
SAFE_OVERLAY_STATES = frozenset({"none", "none_observed", ""})


class NavigationBoundaryError(RuntimeError):
    """Fail-closed navigation-development boundary denial."""


def require_fixed_orchestrator_path(path: Path | None, expected: Path, label: str) -> Path:
    """Reject path escape and symlinks; only the fixed orchestrator path is legal."""

    expected_path = Path(expected)
    candidate = Path(expected_path if path is None else path)
    cand_abs = Path(os.path.abspath(os.path.normpath(str(candidate))))
    exp_abs = Path(os.path.abspath(os.path.normpath(str(expected_path))))
    if cand_abs != exp_abs:
        raise NavigationBoundaryError(f"{label} must be exactly {expected_path}")
    probes = [cand_abs, exp_abs, *list(cand_abs.parents), *list(exp_abs.parents)]
    seen: set[str] = set()
    for probe in probes:
        key = str(probe)
        if key in seen:
            continue
        seen.add(key)
        if probe.exists() and os.path.islink(probe):
            raise NavigationBoundaryError(f"{label} must not be a symlink")
    return exp_abs


@dataclass(frozen=True)
class NavigationRouteDeclaration:
    """Adapter-supplied navigation route contract (flow-agnostic)."""

    allowed_source_states: frozenset[str]
    allowed_target_identities: frozenset[str]
    allowed_gesture_classes: frozenset[str]
    consequence_class: str = "navigation_only"
    frame_max_age_seconds: float = DEFAULT_FRAME_MAX_AGE_SECONDS
    expected_package: str = EXPECTED_PACKAGE
    expected_device_state: str = "device"
    expected_runtime_profile_id: str = NATIVE_RUNTIME_PROFILE_ID

    def validate(self) -> None:
        if not self.allowed_source_states:
            raise NavigationBoundaryError("route declaration requires allowed_source_states")
        if not self.allowed_target_identities:
            raise NavigationBoundaryError("route declaration requires allowed_target_identities")
        if not self.allowed_gesture_classes:
            raise NavigationBoundaryError("route declaration requires allowed_gesture_classes")
        if self.consequence_class != "navigation_only":
            raise NavigationBoundaryError("route declaration consequence_class must be navigation_only")
        unknown = set(self.allowed_gesture_classes) - ALLOWED_GESTURE_CLASSES
        forbidden = set(self.allowed_gesture_classes) & FORBIDDEN_GESTURE_CLASSES
        if forbidden:
            raise NavigationBoundaryError(f"forbidden gesture classes in route: {sorted(forbidden)}")
        if unknown:
            raise NavigationBoundaryError(f"undeclared gesture classes in route: {sorted(unknown)}")
        if self.frame_max_age_seconds <= 0:
            raise NavigationBoundaryError("frame_max_age_seconds must be positive")
        if self.expected_package != EXPECTED_PACKAGE:
            raise NavigationBoundaryError("expected_package must match production package")
        if self.expected_device_state != "device":
            raise NavigationBoundaryError("expected_device_state must be device")
        if self.expected_runtime_profile_id != NATIVE_RUNTIME_PROFILE_ID:
            raise NavigationBoundaryError("expected_runtime_profile_id must be native BlueStacks profile")


@dataclass(frozen=True)
class SourceStateSafetyFacts:
    """Adapter recognition/safety facts. Runtime package/device/profile/dims are bound live."""

    recognized: bool
    source_state: str
    overlay_state: str
    manual_required: bool
    hard_stop: bool
    unknown_state: bool
    runtime_profile_id: str
    foreground_package: str
    device_state: str
    frame_width: int
    frame_height: int
    frame_sha256: str
    captured_monotonic: float
    now_monotonic: float | None = None
    target_roi: NativeBox | None = None


@dataclass(frozen=True)
class DevelopmentInitialObservation:
    """Typed, hash-bound first observation owned by one development session.

    The observation is evidence/state only.  It never supplies input authority;
    every dispatch still binds a fresh current frame through ``run_action``.
    """

    observation: Mapping[str, Any]
    frame_sha256: str
    frame_path: str = ""
    invocation_id: str = ""

    def __post_init__(self) -> None:
        digest = str(self.frame_sha256 or "")
        if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise DevelopmentSessionError("initial observation frame hash is invalid")
        declared = self.observation.get("frame_sha256")
        if declared is not None and str(declared) != digest:
            raise DevelopmentSessionError("initial observation hash binding is inconsistent")

    def to_mapping(self) -> dict[str, Any]:
        payload = dict(self.observation)
        payload["frame_sha256"] = self.frame_sha256
        if self.frame_path:
            payload["frame_path"] = self.frame_path
        if self.invocation_id:
            payload["invocation_id"] = self.invocation_id
        return payload

    @property
    def frame_hash(self) -> str:
        return self.frame_sha256


# Stable descriptive aliases for adapters/tests that refer to the session's
# first observation without coupling to the concrete class name.
InitialObservation = DevelopmentInitialObservation
SessionInitialObservation = DevelopmentInitialObservation


@dataclass(frozen=True)
class NavigationSessionResult:
    status: str
    reason: str
    flow_id: str | None = None
    scenario_id: str | None = None
    navigation_input_count: int = 0
    session_directory: str = ""
    extra: Mapping[str, Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "reason": self.reason,
            "navigation_input_count": self.navigation_input_count,
            "session_directory": self.session_directory,
        }
        if self.flow_id is not None:
            payload["flow_id"] = self.flow_id
        if self.scenario_id is not None:
            payload["scenario_id"] = self.scenario_id
        if self.extra:
            payload.update(dict(self.extra))
        return payload


class RuntimeInputLock:
    """Cross-process exclusive lock held via an open SQLite BEGIN IMMEDIATE transaction."""

    def __init__(self, *, owner: str, invocation_id: str) -> None:
        if not owner or not str(owner).strip():
            raise NavigationBoundaryError("runtime input lock requires owner")
        if not invocation_id or not str(invocation_id).strip():
            raise NavigationBoundaryError("runtime input lock requires invocation_id")
        self.path = require_fixed_orchestrator_path(
            None,
            RUNTIME_INPUT_LOCK_PATH,
            "runtime input lock",
        )
        self.owner = str(owner)
        self.invocation_id = str(invocation_id)
        self._connection: sqlite3.Connection | None = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> "RuntimeInputLock":
        if self._held:
            raise NavigationBoundaryError("runtime input lock already held in this process")
        self.path = require_fixed_orchestrator_path(
            self.path,
            RUNTIME_INPUT_LOCK_PATH,
            "runtime input lock",
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=0, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=0")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_input_lock (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    owner TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                )
                """
            )
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                connection.close()
                raise NavigationBoundaryError(
                    "runtime input lock is held by another owner"
                ) from exc
            acquired_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            connection.execute(
                """
                INSERT INTO runtime_input_lock(singleton, owner, invocation_id, acquired_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    owner=excluded.owner,
                    invocation_id=excluded.invocation_id,
                    acquired_at=excluded.acquired_at
                """,
                (self.owner, self.invocation_id, acquired_at),
            )
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            connection.close()
            raise
        self._connection = connection
        self._held = True
        return self

    def release(self) -> None:
        connection = self._connection
        self._connection = None
        held = self._held
        self._held = False
        if connection is None:
            return
        try:
            if held:
                try:
                    connection.execute("DELETE FROM runtime_input_lock WHERE singleton=1")
                    connection.execute("COMMIT")
                except sqlite3.Error:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
        finally:
            connection.close()

    def assert_held(self, owner: str, invocation_id: str) -> None:
        """Assert ownership through the same live SQLite connection/transaction."""

        if not self._held or self._connection is None:
            raise NavigationBoundaryError("runtime input lock is not held")
        if owner != self.owner or invocation_id != self.invocation_id:
            raise NavigationBoundaryError("runtime input lock owner or invocation mismatch")
        try:
            row = self._connection.execute(
                "SELECT owner, invocation_id FROM runtime_input_lock WHERE singleton=1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise NavigationBoundaryError("runtime input lock connection is stale") from exc
        if row is None or row["owner"] != owner or row["invocation_id"] != invocation_id:
            raise NavigationBoundaryError("runtime input lock ownership was lost")

    def __enter__(self) -> "RuntimeInputLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def open_canonical_action_store() -> SafetyStore:
    store_path = require_fixed_orchestrator_path(
        None,
        CANONICAL_ACTION_STORE_PATH,
        "canonical action store",
    )
    store_path.parent.mkdir(parents=True, exist_ok=True)
    return SafetyStore(store_path)


def require_canonical_unresolved_clear() -> None:
    """Fail closed when the canonical SafetyStore has a blocking action."""

    store = open_canonical_action_store()
    try:
        if store.has_action_block():
            raise NavigationBoundaryError(
                "canonical unresolved or nonterminal action blocks BlueStacks input"
            )
    finally:
        store.close()


def validate_source_state_safety(
    facts: SourceStateSafetyFacts,
    declaration: NavigationRouteDeclaration,
) -> None:
    declaration.validate()
    if facts.unknown_state:
        raise NavigationBoundaryError("unknown source state is denied")
    if facts.manual_required:
        raise NavigationBoundaryError("manual_required source state is denied")
    if facts.hard_stop:
        raise NavigationBoundaryError("hard_stop source state is denied")
    if not facts.recognized:
        raise NavigationBoundaryError("unrecognized source state is denied")
    overlay = str(facts.overlay_state or "").strip().lower()
    if overlay not in SAFE_OVERLAY_STATES:
        raise NavigationBoundaryError("overlay source state is denied")
    if facts.source_state not in declaration.allowed_source_states:
        raise NavigationBoundaryError(
            f"undeclared source state denied: {facts.source_state!r}"
        )
    if facts.runtime_profile_id != declaration.expected_runtime_profile_id:
        raise NavigationBoundaryError("runtime profile mismatch is denied")
    if (facts.frame_width, facts.frame_height) != (NATIVE_WIDTH, NATIVE_HEIGHT):
        raise NavigationBoundaryError("native 800x1280 profile is required")
    if facts.foreground_package != declaration.expected_package:
        raise NavigationBoundaryError("foreground package mismatch is denied")
    if facts.device_state != declaration.expected_device_state:
        raise NavigationBoundaryError("device state mismatch is denied")
    now = facts.now_monotonic if facts.now_monotonic is not None else time.monotonic()
    age = now - facts.captured_monotonic
    if age < 0 or age > declaration.frame_max_age_seconds:
        raise NavigationBoundaryError("stale source frame is denied")
    if facts.target_roi is not None:
        x0, y0, x1, y1 = facts.target_roi
        if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
            raise NavigationBoundaryError("target bounds outside native frame are denied")


def authorize_navigation_gesture(
    *,
    declaration: NavigationRouteDeclaration,
    facts: SourceStateSafetyFacts,
    gesture_class: str,
    target_identity: str,
    consequential: bool = False,
) -> None:
    """Validate one navigation-only gesture before transport."""

    declaration.validate()
    if consequential:
        raise NavigationBoundaryError("consequential gestures are denied by navigation firewall")
    if gesture_class in FORBIDDEN_GESTURE_CLASSES:
        raise NavigationBoundaryError(f"forbidden gesture class denied: {gesture_class}")
    if gesture_class not in declaration.allowed_gesture_classes:
        raise NavigationBoundaryError(f"undeclared gesture class denied: {gesture_class}")
    if target_identity not in declaration.allowed_target_identities:
        raise NavigationBoundaryError(f"undeclared target identity denied: {target_identity}")
    validate_source_state_safety(facts, declaration)


class NavigationGuardedRuntime:
    """NativeRuntimePort wrapper that enforces declaration + live source-safety before transport."""

    def __init__(
        self,
        inner: NativeRuntimePort,
        declaration: NavigationRouteDeclaration,
    ) -> None:
        declaration.validate()
        self._inner = inner
        self.declaration = declaration
        self._pending_facts: SourceStateSafetyFacts | None = None
        self.authorized_gestures: list[dict[str, Any]] = []

    @property
    def execute(self) -> bool:
        return self._inner.execute

    @property
    def session(self) -> Path:
        return self._inner.session

    @property
    def in_flight_action(self) -> str | None:
        return self._inner.in_flight_action

    @in_flight_action.setter
    def in_flight_action(self, value: str | None) -> None:
        self._inner.in_flight_action = value

    def prepare_source_safety(self, facts: SourceStateSafetyFacts) -> None:
        self._pending_facts = facts

    def _consume_facts(self) -> SourceStateSafetyFacts:
        facts = self._pending_facts
        self._pending_facts = None
        if facts is None:
            raise NavigationBoundaryError("source safety facts required before navigation input")
        return facts

    def _measure_device_state(self) -> str:
        measure = getattr(self._inner, "measure_device_state", None)
        if not callable(measure):
            raise NavigationBoundaryError("device state measurement unavailable")
        return str(measure())

    def _measure_foreground_package(self) -> str:
        measure = getattr(self._inner, "measure_foreground_package", None)
        if not callable(measure):
            raise NavigationBoundaryError("foreground package measurement unavailable")
        return str(measure())

    def _bind_live_runtime_facts(
        self,
        source: CapturedNativeFrame,
        adapter_facts: SourceStateSafetyFacts,
        *,
        target_roi: NativeBox | None = None,
    ) -> SourceStateSafetyFacts:
        """Overwrite package/device/profile/dims from live runtime + current frame."""

        height = int(source.frame.shape[0])
        width = int(source.frame.shape[1])
        profile = (
            NATIVE_RUNTIME_PROFILE_ID
            if (width, height) == (NATIVE_WIDTH, NATIVE_HEIGHT)
            else f"non-native-{width}x{height}"
        )
        wall = time.monotonic()
        return SourceStateSafetyFacts(
            recognized=adapter_facts.recognized,
            source_state=adapter_facts.source_state,
            overlay_state=adapter_facts.overlay_state,
            manual_required=adapter_facts.manual_required,
            hard_stop=adapter_facts.hard_stop,
            unknown_state=adapter_facts.unknown_state,
            runtime_profile_id=profile,
            foreground_package=self._measure_foreground_package(),
            device_state=self._measure_device_state(),
            frame_width=width,
            frame_height=height,
            frame_sha256=source.sha256,
            captured_monotonic=source.captured_monotonic,
            now_monotonic=wall,
            target_roi=target_roi if target_roi is not None else adapter_facts.target_roi,
        )

    def _authorize(
        self,
        source: CapturedNativeFrame,
        *,
        gesture_class: str,
        target_identity: str,
        consequential: bool,
        target_roi: NativeBox | None = None,
    ) -> tuple[SourceStateSafetyFacts, dict[str, Any]]:
        adapter_facts = self._consume_facts()
        facts = self._bind_live_runtime_facts(source, adapter_facts, target_roi=target_roi)
        authorize_navigation_gesture(
            declaration=self.declaration,
            facts=facts,
            gesture_class=gesture_class,
            target_identity=target_identity,
            consequential=consequential,
        )
        entry = {
            "gesture_class": gesture_class,
            "target_identity": target_identity,
            "source_state": facts.source_state,
            "frame_sha256": facts.frame_sha256,
            "consequential": False,
            "authorized": True,
            "transport_observed": False,
        }
        self.authorized_gestures.append(entry)
        return facts, entry

    def _mark_transported(self, entry: dict[str, Any]) -> None:
        entry["transport_observed"] = True

    def capture(self, label: str) -> CapturedNativeFrame:
        return self._inner.capture(label)

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        _facts, entry = self._authorize(
            source,
            gesture_class="tap",
            target_identity=target_identity,
            consequential=consequential,
            target_roi=target_roi,
        )
        self._inner.tap(
            source,
            target_identity=target_identity,
            target_roi=target_roi,
            action_key=action_key,
            consequential=False,
            continuation_of=continuation_of,
        )
        self._mark_transported(entry)

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str = "tier-carousel-swipe",
    ) -> None:
        roi = (
            min(start[0], end[0]),
            min(start[1], end[1]),
            min(NATIVE_WIDTH, max(start[0], end[0]) + 1),
            min(NATIVE_HEIGHT, max(start[1], end[1]) + 1),
        )
        _facts, entry = self._authorize(
            source,
            gesture_class="swipe",
            target_identity=target_identity,
            consequential=False,
            target_roi=roi,
        )
        self._inner.swipe(
            source,
            start=start,
            end=end,
            action_key=action_key,
            target_identity=target_identity,
        )
        self._mark_transported(entry)

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        continuation_of: str | None = None,
        target_identity: str = "system-back",
    ) -> None:
        _facts, entry = self._authorize(
            source,
            gesture_class="back",
            target_identity=target_identity,
            consequential=False,
        )
        self._inner.back(
            source,
            action_key=action_key,
            continuation_of=continuation_of,
        )
        self._mark_transported(entry)

    def dispatch_zoom_out(
        self,
        source: CapturedNativeFrame,
        facts: SourceStateSafetyFacts,
        *,
        transport: Callable[[], None] | None = None,
        target_identity: str = "home-zoom-out",
    ) -> None:
        """Authorize then invoke native or injected zoom transport."""

        self.prepare_source_safety(facts)
        _bound, entry = self._authorize(
            source,
            gesture_class="zoom_out",
            target_identity=target_identity,
            consequential=False,
        )
        try:
            if transport is None:
                self._inner.zoom_out(
                    source,
                    action_key=f"home-zoom-out:{source.sha256}",
                )
            else:
                accounted = getattr(self._inner, "dispatch_external_zoom", None)
                if callable(accounted):
                    accounted(
                        source,
                        action_key=f"home-zoom-out:{source.sha256}",
                        transport=transport,
                    )
                else:
                    transport()
        except Exception:
            entry["transport_observed"] = False
            raise
        self._mark_transported(entry)

    def long_press(self, *args: Any, **kwargs: Any) -> None:
        raise NavigationBoundaryError("long_press is denied by navigation firewall")

    def type_text(self, *args: Any, **kwargs: Any) -> None:
        raise NavigationBoundaryError("type_text is denied by navigation firewall")

    def clear_numeric_text(self, *args: Any, **kwargs: Any) -> None:
        raise NavigationBoundaryError("clear_numeric_text is denied by navigation firewall")

    def press_key(self, *args: Any, **kwargs: Any) -> None:
        raise NavigationBoundaryError("press_key is denied by navigation firewall")

    def reconcile(self, action_key: str, status: str, post: CapturedNativeFrame, reason: str) -> None:
        return self._inner.reconcile(action_key, status, post, reason)

    def record_recovery(self, **kwargs: Any) -> None:
        return self._inner.record_recovery(**kwargs)


class NavigationDevelopmentSession:
    """Acquire and automatically release shared development runtime ownership.

    Ordinary development sessions deliberately do not consult the legacy canonical
    action journal.  Singleton ownership is the only session-level admission gate;
    action-specific safety remains in current-frame validation and bounded transport.
    """

    def __init__(self, *, owner: str, invocation_id: str) -> None:
        self.lock = RuntimeInputLock(owner=owner, invocation_id=invocation_id)
        self.owner = owner
        self.invocation_id = invocation_id

    def __enter__(self) -> "NavigationDevelopmentSession":
        self.lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.lock.release()


ORDINARY_DEVELOPMENT_ACTION = "ordinary_development"
ORDINARY_DEVELOPMENT_CAPABILITIES = frozenset(
    {
        "navigation",
        "combat",
        "claim",
        "reward",
        "free_action",
        "recruitment",
        "resource_collection",
        "resource_spending",
        "zombie_lair",
        "zombie_attack",
        "challenge_confirmation",
        "healing",
        "training",
        "upgrade",
        "research",
        "in_game_currency",
        "maintenance",
        "recovery",
        "complete_flow",
    }
)
REAL_MONEY_CASH_MALL_CONFIRMATION = "real_money_cash_mall_confirmation"


class DevelopmentSessionError(NavigationBoundaryError):
    """A bounded development-session safeguard rejected an operation."""


_DELEGATED_RUNTIME_CONTEXT: ContextVar[Any | None] = ContextVar(
    "pns_delegated_runtime_context", default=None
)
_ACTIVE_DEVELOPMENT_SESSION: ContextVar[Any | None] = ContextVar(
    "pns_active_development_session", default=None
)


def current_delegated_runtime_context() -> Any | None:
    return _DELEGATED_RUNTIME_CONTEXT.get()


class delegated_runtime_context:
    """Install controller-owned receipt authority for one bounded session."""

    def __init__(self, context: Any) -> None:
        self.context = context
        self._token = None

    def __enter__(self) -> Any:
        if current_delegated_runtime_context() is not None:
            raise DevelopmentSessionError("nested delegated runtime context is denied")
        self._token = _DELEGATED_RUNTIME_CONTEXT.set(self.context)
        return self.context

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _DELEGATED_RUNTIME_CONTEXT.reset(self._token)
            self._token = None


def validate_development_action(action_class: str) -> str:
    normalized = str(action_class).strip().lower()
    if not normalized:
        raise DevelopmentSessionError("development action description is required")
    try:
        reject_real_money_confirmation(normalized)
    except RuntimeError as exc:
        raise DevelopmentSessionError(str(exc)) from exc
    if normalized == REAL_MONEY_CASH_MALL_CONFIRMATION:
        raise DevelopmentSessionError("real-money Cash Mall confirmation is unsupported")
    return ORDINARY_DEVELOPMENT_ACTION


def settle_successor(
    capture: Callable[[str], Any],
    recognize: Callable[[Any], Any],
    *,
    label: str = "settled-successor",
    stable_polls: int = 2,
    timeout_polls: int | None = None,
) -> Any:
    """Capture and classify a settled successor without dispatching input.

    This is a reusable observation seam for adapters.  It deliberately accepts
    no transport callback and delegates deterministic state comparison to the
    pure transition primitive; the caller remains responsible for any runtime
    capture ownership and semantic policy.
    """

    from tasks.transition_stability import TransitionObservation, poll_stable_transition

    if not callable(capture) or not callable(recognize):
        raise DevelopmentSessionError("settled successor requires capture and recognize callbacks")
    observations: list[Any] = []
    ceiling = int(timeout_polls) if timeout_polls is not None else None
    if ceiling is not None and ceiling < 1:
        raise DevelopmentSessionError("settled successor timeout_polls must be positive")
    for ordinal in range(1, (ceiling or stable_polls * 2) + 1):
        frame = capture(f"{label}-{ordinal}")
        observations.append(TransitionObservation(recognize(frame), evidence_ref=f"{label}-{ordinal}"))
        result = poll_stable_transition(
            observations,
            stable_polls=stable_polls,
            timeout_polls=ceiling,
        )
        if result.status.value in {"stable", "contradictory", "timeout"}:
            return result
    return poll_stable_transition(observations, stable_polls=stable_polls, timeout_polls=ceiling)


# Name used by callers that treat the seam as a callback factory.
poll_settled_successor = settle_successor


def _validate_development_native_frame(frame: CapturedNativeFrame) -> None:
    height = int(frame.frame.shape[0])
    width = int(frame.frame.shape[1])
    if (width, height) != (NATIVE_WIDTH, NATIVE_HEIGHT):
        raise DevelopmentSessionError("development input requires a native 800x1280 frame")


def _validate_development_roi(roi: NativeBox | None) -> None:
    if roi is None:
        return
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        raise DevelopmentSessionError("development target is outside native-frame bounds")


@dataclass(frozen=True)
class DevelopmentActionResult:
    status: str
    reason: str
    state: str
    before_sha256: str
    after_sha256: str
    recovery_used: bool = False


class DevelopmentSession:
    """Run multiple ordinary interactions through the existing navigation boundary."""

    def __init__(
        self,
        *,
        owner: str,
        invocation_id: str,
        session_directory: Path,
        max_inputs: int = 12,
        allow_zero_inputs: bool = False,
        initial_observation: DevelopmentInitialObservation | Mapping[str, Any] | None = None,
    ) -> None:
        if not 0 <= int(max_inputs) <= 100 or (int(max_inputs) == 0 and not allow_zero_inputs):
            raise DevelopmentSessionError("max_inputs must be between 1 and 100")
        self.owner = owner
        self.invocation_id = invocation_id
        self.session_directory = Path(session_directory)
        self.max_inputs = int(max_inputs)
        self.allow_zero_inputs = bool(allow_zero_inputs)
        self.input_count = 0
        self.actions: list[dict[str, Any]] = []
        self.control_memory: dict[str, Any] = {}
        self.causal_trace: dict[str, Any] | None = None
        self._initial_observation: DevelopmentInitialObservation | None = None
        self._transport_count_adopted = False
        self.terminal_status: str | None = None
        self.blocker: str | None = None
        self.next_action: str | None = None
        self._ownership = NavigationDevelopmentSession(owner=owner, invocation_id=invocation_id)
        self._entered = False
        self._context_token = None
        if initial_observation is not None:
            self.set_initial_observation(initial_observation)

    def __enter__(self) -> "DevelopmentSession":
        if _ACTIVE_DEVELOPMENT_SESSION.get() is not None:
            raise DevelopmentSessionError("nested DevelopmentSession ownership is denied")
        self._ownership.__enter__()
        try:
            self.session_directory.mkdir(parents=True, exist_ok=False)
        except Exception:
            self._ownership.__exit__(None, None, None)
            raise
        self._context_token = _ACTIVE_DEVELOPMENT_SESSION.set(self)
        self._entered = True
        return self

    @property
    def runtime_input_lock(self) -> RuntimeInputLock:
        """Return this session's already-held lock without permitting replacement."""

        lock = self._ownership.lock
        if not self._entered or not lock.held:
            raise DevelopmentSessionError("development session runtime input lock is not held")
        return lock

    @property
    def is_active(self) -> bool:
        return bool(self._entered and self._ownership.lock.held)

    @property
    def initial_observation(self) -> DevelopmentInitialObservation | None:
        return self._initial_observation

    def set_initial_observation(
        self,
        observation: DevelopmentInitialObservation | Mapping[str, Any],
        *,
        frame_path: str = "",
    ) -> DevelopmentInitialObservation:
        """Bind exactly one typed first observation to this session."""

        if self._initial_observation is not None:
            raise DevelopmentSessionError("initial observation is already bound")
        if isinstance(observation, DevelopmentInitialObservation):
            typed = observation
        elif isinstance(observation, Mapping):
            digest = str(observation.get("frame_sha256") or "")
            typed = DevelopmentInitialObservation(
                observation=dict(observation),
                frame_sha256=digest,
                frame_path=frame_path,
                invocation_id=self.invocation_id,
            )
        else:
            raise DevelopmentSessionError("initial observation must be typed evidence")
        if typed.invocation_id and typed.invocation_id != self.invocation_id:
            raise DevelopmentSessionError("initial observation invocation binding mismatch")
        self._initial_observation = typed
        return typed

    def remember_control(self, key: str, value: Any) -> None:
        """Persist observability/control memory without granting input authority."""

        if not str(key).strip():
            raise DevelopmentSessionError("control memory key is required")
        self.control_memory[str(key)] = value

    bind_initial_observation = set_initial_observation

    def set_causal_trace(self, trace: Mapping[str, Any]) -> None:
        """Retain one read-only causal trace for this attempt."""

        if self.causal_trace is not None:
            raise DevelopmentSessionError("development session causal trace already recorded")
        if trace.get("read_only") is not True:
            raise DevelopmentSessionError("development session causal trace must be read-only")
        self.causal_trace = dict(trace)

    record_causal_trace = set_causal_trace

    def adopt_retained_transport_count(self, count: int, *, source: str = "events.jsonl") -> int:
        """Bind an adapter's retained transport count exactly once.

        Resource actions are counted by ``run_action``; adapters that use an
        existing route controller (World) may adopt its retained dispatch count.
        A second or conflicting count is rejected rather than silently merged.
        """

        if self._transport_count_adopted:
            raise DevelopmentSessionError("development session transport count already adopted")
        value = int(count)
        if value < 0 or value > self.max_inputs:
            raise DevelopmentSessionError("retained transport count exceeds development-session limit")
        if self.input_count not in {0, value}:
            raise DevelopmentSessionError(
                f"retained transport count {value} conflicts with session count {self.input_count}"
            )
        self.input_count = value
        self._transport_count_adopted = True
        self.remember_control("transport_count_source", source)
        return value

    def observe(
        self,
        capture: Callable[[str], CapturedNativeFrame],
        *,
        label: str,
    ) -> CapturedNativeFrame:
        if not self._entered:
            raise DevelopmentSessionError("development session is not active")
        frame = capture(label)
        _validate_development_native_frame(frame)
        return frame

    def run_action(
        self,
        *,
        action_class: str,
        label: str,
        capture: Callable[[str], CapturedNativeFrame],
        dispatch: Callable[[CapturedNativeFrame], None],
        recognize: Callable[[CapturedNativeFrame], str],
        authorize: Callable[[CapturedNativeFrame], None] | None = None,
        target_roi: NativeBox | None = None,
        recover: Callable[[CapturedNativeFrame], bool | int] | None = None,
        recovery_action_identity: str | None = None,
        recovery_action_class: str | None = None,
        recovery_consequence_class: str | None = None,
        consequence_class: str | None = None,
        settled_successor: Callable[[], CapturedNativeFrame] | None = None,
    ) -> DevelopmentActionResult:
        normalized = validate_development_action(action_class)
        if self.input_count >= self.max_inputs:
            raise DevelopmentSessionError("development session input limit reached")
        _validate_development_roi(target_roi)
        before = self.observe(capture, label=f"{label}-immediate-before")
        if authorize is not None:
            authorize(before)
        delegated = current_delegated_runtime_context()
        dispatch_owner = getattr(dispatch, "__self__", None)
        native_guarded = dispatch_owner is not None and hasattr(
            dispatch_owner, "_authorize_dispatch"
        )
        if delegated is not None and not native_guarded:
            receipt = getattr(delegated, "receipt", {})
            requested = str(action_class).strip().lower()
            delegated.reserve_input(
                action_identity=label,
                action_class=requested,
                consequence_class=str(
                    consequence_class or receipt.get("consequence_class") or "navigation_only"
                ),
                source_evidence_hash=before.sha256,
                action_key=label,
            )
        self.input_count += 1
        try:
            dispatch(before)
        except BaseException:
            if delegated is not None:
                delegated.mark_reconciled(label, unresolved=True)
            raise
        if delegated is not None:
            delegated.mark_transported(label)
        immediate_post = self.observe(capture, label=f"{label}-immediate-post")
        after = immediate_post
        state = str(recognize(after) or "unknown")
        settled: CapturedNativeFrame | None = None
        if state.lower() == "unknown" and settled_successor is not None:
            candidate = settled_successor()
            if not isinstance(candidate, CapturedNativeFrame):
                raise DevelopmentSessionError(
                    "settled successor must return a CapturedNativeFrame"
                )
            _validate_development_native_frame(candidate)
            settled = candidate
            after = settled
            state = str(recognize(after) or "unknown")
        recovery_used = False
        recovery_key = recovery_action_identity
        if state.lower() == "unknown" and recover is not None:
            if self.input_count >= self.max_inputs:
                raise DevelopmentSessionError(
                    "development session input limit reached before recovery"
                )
            if delegated is not None:
                if not recovery_action_identity or not recovery_action_class or not recovery_consequence_class:
                    raise DevelopmentSessionError(
                        "delegated recovery requires an explicit action binding"
                    )
                delegated.reserve_input(
                    action_identity=recovery_action_identity,
                    action_class=recovery_action_class,
                    consequence_class=recovery_consequence_class,
                    source_evidence_hash=after.sha256,
                    action_key=recovery_action_identity,
                )
            try:
                recovery_result = recover(after)
            except BaseException:
                if delegated is not None:
                    delegated.mark_reconciled(recovery_key, unresolved=True)
                raise
            recovery_inputs = (
                1
                if recovery_result is True
                else 0
                if recovery_result is False
                else int(recovery_result)
            )
            if recovery_inputs not in {0, 1}:
                raise DevelopmentSessionError("recovery must report zero or one bounded input")
            self.input_count += recovery_inputs
            recovery_used = recovery_inputs == 1
            if delegated is not None:
                if recovery_used:
                    delegated.mark_transported(recovery_key)
                else:
                    delegated.mark_reconciled(recovery_key)
            if recovery_used:
                after = self.observe(capture, label=f"{label}-recovery-post")
                state = str(recognize(after) or "unknown")
        effect_action = any(
            marker in f"{str(action_class).strip().lower()} {str(consequence_class or '').lower()}"
            for marker in ("effect", "resource", "non_idempotent", "owned_item")
        )
        reconciliation_required = state.lower() == "unknown" and effect_action
        status = (
            "effect_reconciliation_required"
            if reconciliation_required
            else "completed"
            if state.lower() != "unknown"
            else "unknown"
        )
        reason = (
            "effect_reconciliation_required"
            if reconciliation_required
            else "recognized_successor"
            if status == "completed"
            else "unknown_successor"
        )
        if delegated is not None:
            delegated.mark_reconciled(
                label,
                unresolved=(status == "unknown" or reconciliation_required),
            )
            if recovery_used:
                delegated.mark_reconciled(
                    recovery_key,
                    unresolved=(status == "unknown" or reconciliation_required),
                )
        row = {
            "ordinal": len(self.actions) + 1,
            "action_class": normalized,
            "requested_action": str(action_class).strip().lower(),
            "label": label,
            "status": status,
            "reason": reason,
            "state": state,
            "before_sha256": before.sha256,
            "immediate_post_sha256": immediate_post.sha256,
            "settled_successor_sha256": settled.sha256 if settled is not None else "",
            "after_sha256": after.sha256,
            "recovery_used": recovery_used,
            "effect_reconciliation_required": reconciliation_required,
        }
        self.actions.append(row)
        with (self.session_directory / "actions.jsonl").open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return DevelopmentActionResult(
            status=status,
            reason=reason,
            state=state,
            before_sha256=before.sha256,
            after_sha256=after.sha256,
            recovery_used=recovery_used,
        )

    def _write_summary(self, exception: BaseException | None) -> None:
        unknown = next(
            (
                row
                for row in reversed(self.actions)
                if row.get("status") in {"unknown", "effect_reconciliation_required"}
            ),
            None,
        )
        terminal_status = self.terminal_status or ("blocked" if unknown else "completed")
        summary: dict[str, Any] = {
            "schema_version": 1,
            "session_kind": "ordinary_development",
            "owner": self.owner,
            "invocation_id": self.invocation_id,
            "status": "failed" if exception else terminal_status,
            "input_count": self.input_count,
            "max_inputs": self.max_inputs,
            "action_count": len(self.actions),
            "ownership_released": True,
            "lifecycle_state_created": False,
            "terminal_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if self._initial_observation is not None:
            summary.update(
                {
                    "initial_observation": self._initial_observation.to_mapping(),
                    "initial_frame_sha256": self._initial_observation.frame_sha256,
                }
            )
        if self.control_memory:
            summary["control_memory"] = dict(self.control_memory)
        if self.causal_trace is not None:
            summary["causal_trace_count"] = 1
        if self.causal_trace is not None:
            summary["causal_trace"] = dict(self.causal_trace)
        if (delegated := current_delegated_runtime_context()) is not None:
            summary.update({"receipt_id": delegated.receipt["receipt_id"], "receipt_digest": delegated.receipt["receipt_digest"], "evidence_result_identity": delegated.result_identity})
        if unknown:
            summary["blocker"] = unknown["reason"]
            summary["next_action"] = (
                "observe-only effect reconciliation; identical retry is denied"
                if unknown.get("effect_reconciliation_required")
                else "repair recognition or recovery and rerun materially changed behavior"
            )
        if self.blocker:
            summary["blocker"] = self.blocker
        if self.next_action:
            summary["next_action"] = self.next_action
        if exception:
            summary["blocker"] = f"{type(exception).__name__}: {exception}"
            summary["next_action"] = "repair the reported development failure"
        (self.session_directory / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._ownership.__exit__(exc_type, exc, tb)
        finally:
            self._write_summary(exc)
            if self._context_token is not None:
                _ACTIVE_DEVELOPMENT_SESSION.reset(self._context_token)
                self._context_token = None
            self._entered = False


def finalize_navigation_evidence(
    session_directory: Path,
    *,
    status: str,
    reason: str,
    records: Sequence[Mapping[str, Any]] = (),
    flow_id: str | None = None,
    scenario_id: str | None = None,
    navigation_input_count: int | None = None,
    authorized_gestures: Sequence[Mapping[str, Any]] = (),
    extra: Mapping[str, Any] | None = None,
    exception: BaseException | None = None,
) -> dict[str, Any]:
    """Write shared terminal evidence on normal and exceptional paths."""

    session = Path(session_directory)
    session.mkdir(parents=True, exist_ok=True)
    original_status = status
    if status not in TERMINAL_RESULT_STATUSES:
        status = "failed" if exception is not None else "blocked"
        suffix = f":{reason}" if reason else ""
        reason = f"invalid_terminal_status:{original_status}{suffix}"
    if exception is not None and status not in {"unresolved", "failed", "blocked", "manual_required"}:
        status = "failed"
        reason = reason or f"exception:{type(exception).__name__}"
    input_count = (
        navigation_input_count
        if navigation_input_count is not None
        else sum(1 for item in records if not str(item.get("action") or "").startswith("no_input_"))
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "navigation_input_count": input_count,
        "session_directory": str(session),
        "records": list(records),
    }
    if flow_id is not None:
        payload["flow_id"] = flow_id
    if scenario_id is not None:
        payload["scenario_id"] = scenario_id
    if extra:
        for key, value in extra.items():
            if key not in payload:
                payload[key] = value
    (session / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    with (session / "ledger.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")
    journal_rows: list[dict[str, Any]] = [
        {
            "status": status,
            "reason": reason,
            "navigation_input_count": input_count,
        }
    ]
    if scenario_id is not None:
        journal_rows[0]["scenario_id"] = scenario_id
    if flow_id is not None:
        journal_rows[0]["flow_id"] = flow_id
    with (session / "journal.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in journal_rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    audit_rows: list[dict[str, Any]] = []
    for item in authorized_gestures:
        row = dict(item)
        audit_rows.append(
            {
                "authority": "NavigationGuardedRuntime",
                "authorized": bool(row.pop("authorized", True)),
                "transport_observed": bool(row.pop("transport_observed", False)),
                **row,
            }
        )
    if exception is not None:
        audit_rows.append(
            {
                "authority": "NavigationGuardedRuntime",
                "authorized": False,
                "transport_observed": False,
                "exception_type": type(exception).__name__,
                "reason": reason,
            }
        )
    with (session / "capability-audit.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in audit_rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    events = session / "events.jsonl"
    if not events.exists():
        events.write_text("", encoding="utf-8")
    return payload


def make_source_safety_facts(
    *,
    recognized: bool,
    source_state: str,
    frame_sha256: str,
    captured_monotonic: float,
    overlay_state: str = "none_observed",
    manual_required: bool = False,
    hard_stop: bool = False,
    unknown_state: bool = False,
    frame_width: int = 0,
    frame_height: int = 0,
    runtime_profile_id: str = "",
    foreground_package: str = "",
    device_state: str = "",
    now_monotonic: float | None = None,
    target_roi: NativeBox | None = None,
) -> SourceStateSafetyFacts:
    """Build adapter recognition facts. Live package/device/profile/dims bind at dispatch."""

    return SourceStateSafetyFacts(
        recognized=recognized,
        source_state=source_state,
        overlay_state=overlay_state,
        manual_required=manual_required,
        hard_stop=hard_stop,
        unknown_state=unknown_state,
        runtime_profile_id=runtime_profile_id,
        foreground_package=foreground_package,
        device_state=device_state,
        frame_width=frame_width,
        frame_height=frame_height,
        frame_sha256=frame_sha256,
        captured_monotonic=captured_monotonic,
        now_monotonic=now_monotonic,
        target_roi=target_roi,
    )
