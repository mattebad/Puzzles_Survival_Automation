"""Shared native BlueStacks runtime boundary for local workflow integration.

The workflow controllers own semantic decisions.  This module owns only exact local-device
selection, fresh native capture, evidence retention, duplicate-input guards, and transport.
It never connects ADB, never registers a production task, and never enables a scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Protocol

import cv2
import numpy as np

from scripts.bluestacks_flow_collector import (
    ADBError,
    ADBRunner,
    EXPECTED_PACKAGE,
    is_permitted_local_bluestacks_serial,
    parse_foreground_package,
)
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


def current_delegated_runtime_context():
    """Resolve the optional delegated context lazily to avoid an import cycle."""

    from scripts.navigation_development_boundary import (
        current_delegated_runtime_context as current,
    )

    return current()


NativeBox = tuple[int, int, int, int]
NATIVE_WIDTH = 800
NATIVE_HEIGHT = 1280
NATIVE_RUNTIME_PROFILE_ID = ACTIVE_RUNTIME_PROFILE_ID
_CAMPAIGN_BATTLE_CHILDREN = {
    "campaign-lineup-challenge": True,
    "campaign-auto": False,
    "campaign-victory-continue": False,
}

_PORTABLE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_WINDOWS_RESERVED_FILENAME_COMPONENTS = frozenset(
    {
        "AUX",
        "CON",
        "NUL",
        "PRN",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


def portable_filename_component(value: object, *, field: str) -> str:
    """Return a safe new filename component without changing its identity.

    New runtime paths are deliberately stricter than historical evidence paths:
    path separators, drive/ADS syntax, traversal components, and empty values
    are normalized or rejected before any device or file operation.  Other
    punctuation is collapsed to ``-`` so ordinary labels remain readable and
    portable.
    """

    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{field} filename component is required")
    original = value.strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", original).strip(".-")
    if not safe or safe in {".", ".."}:
        raise RuntimeError(f"{field} filename component is ambiguous")
    if not _PORTABLE_FILENAME_RE.fullmatch(safe):
        raise RuntimeError(f"{field} filename component is not portable")
    if safe.upper().split(".", 1)[0] in _WINDOWS_RESERVED_FILENAME_COMPONENTS:
        raise RuntimeError(f"{field} filename component is a reserved Windows name")
    return safe


def reject_real_money_confirmation(target_identity: str, action_key: str = "") -> None:
    """Reject explicit real-money Cash Mall confirmation identities."""

    identity = f"{target_identity} {action_key}".strip().lower().replace("_", "-")
    exact_markers = (
        "cash-mall-real-money-confirm",
        "real-money-cash-mall-confirm",
        "cash-mall-payment-confirm",
    )
    cash_mall = "cash-mall" in identity or ("cash" in identity and "mall" in identity)
    payment = any(
        token in identity
        for token in ("real-money", "payment", "checkout", "credit-card", "bank-card", "usd", "dollar")
    )
    confirmation = any(
        token in identity for token in ("confirm", "purchase", "buy", "pay", "submit", "order")
    )
    if any(token in identity for token in exact_markers) or (
        cash_mall and payment and confirmation
    ):
        raise RuntimeError("real-money Cash Mall confirmation is unsupported")


@dataclass(frozen=True)
class CapturedNativeFrame:
    frame: np.ndarray
    png: bytes
    sha256: str
    captured_monotonic: float
    path: Path


@dataclass
class _CampaignStageLineage:
    transported: bool = False
    confirmed_post_sha256: str | None = None
    invalidated: bool = False
    child_targets: set[str] = field(default_factory=set)
    transported_child_targets: set[str] = field(default_factory=set)


def captured_native_frame_from_png(
    payload: bytes,
    *,
    captured_monotonic: float,
    path: Path,
) -> CapturedNativeFrame:
    """Apply the production native PNG validation used by live capture and replay."""

    frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (NATIVE_HEIGHT, NATIVE_WIDTH):
        raise RuntimeError("BlueStacks capture is not a native 800x1280 frame")
    return CapturedNativeFrame(
        frame,
        payload,
        hashlib.sha256(payload).hexdigest(),
        captured_monotonic,
        path,
    )


@dataclass(frozen=True)
class IntegratedRouteResult:
    status: str
    reason: str
    actions_completed: int
    session: str


class NativeRuntimePort(Protocol):
    execute: bool
    in_flight_action: str | None
    session: Path

    def capture(self, label: str) -> CapturedNativeFrame: ...

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        action_class: str = "navigation",
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None: ...

    def dispatch_prepared_resource_item_use(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        transport_intent_token: object,
    ): ...

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str = "tier-carousel-swipe",
    ) -> None: ...

    def long_press(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        duration_ms: int,
        action_key: str,
        consequential: bool = True,
    ) -> None: ...

    def type_text(
        self,
        source: CapturedNativeFrame,
        *,
        text: str,
        action_key: str,
    ) -> None: ...

    def clear_numeric_text(
        self,
        source: CapturedNativeFrame,
        *,
        max_digits: int,
        action_key: str,
    ) -> None: ...

    def press_key(
        self,
        source: CapturedNativeFrame,
        *,
        key: str,
        action_key: str,
    ) -> None: ...

    def zoom_out(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
    ) -> None: ...

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        target_identity: str = "android-back",
        continuation_of: str | None = None,
    ) -> None: ...

    def reconcile(self, action_key: str, status: str, post: CapturedNativeFrame, reason: str) -> None: ...

    def record_recovery(
        self,
        *,
        action_key: str,
        previous_session: str,
        previous_source_sha256: str,
        previous_post_sha256: str,
        current: CapturedNativeFrame,
        expected_completion_timestamp: str,
        reason: str,
    ) -> None: ...


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def box_center(box: NativeBox) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= NATIVE_WIDTH and 0 <= y0 < y1 <= NATIVE_HEIGHT):
        raise RuntimeError("target is outside native 800x1280 bounds")
    return ((x0 + x1) // 2, (y0 + y1) // 2)


class LocalBlueStacksRuntime:
    """Evidence-retaining runtime for bounded ordinary development interactions."""

    def __init__(
        self,
        runner: ADBRunner,
        session: Path,
        *,
        execute: bool,
        frame_max_age_seconds: float = 30.0,
    ) -> None:
        self.runner = runner
        self.session = session
        self.execute = execute
        self.frame_max_age_seconds = frame_max_age_seconds
        self.frames = session / "frames"
        self.frames.mkdir(parents=True, exist_ok=False)
        self.events = session / "events.jsonl"
        self.ordinal = 0
        self.action_keys: set[str] = set()
        self.frame_actions: set[tuple[str, str, NativeBox | None]] = set()
        self._campaign_stage_parents: dict[str, _CampaignStageLineage] = {}
        self._campaign_child_parents: dict[str, tuple[_CampaignStageLineage, str]] = {}
        self.in_flight_action: str | None = None
        try:
            self.max_inputs = int(os.environ.get("PNS_DEVELOPMENT_MAX_INPUTS", "40"))
        except ValueError as exc:
            raise RuntimeError("PNS_DEVELOPMENT_MAX_INPUTS must be an integer") from exc
        if not 1 <= self.max_inputs <= 100:
            raise RuntimeError("PNS_DEVELOPMENT_MAX_INPUTS must be between 1 and 100")
        self.input_count = 0
        self.checkpoint = None
        self.observation_guard = None

    @classmethod
    def connect(
        cls,
        *,
        adb: str,
        serial: str,
        output_directory: Path,
        workflow: str,
        execute: bool,
    ) -> "LocalBlueStacksRuntime":
        safe_workflow = portable_filename_component(workflow, field="workflow")
        if not is_permitted_local_bluestacks_serial(serial):
            raise RuntimeError("serial is not a permitted local BlueStacks endpoint")
        runner = ADBRunner(adb, serial)
        devices = {device.serial: device.state for device in runner.list_devices()}
        if devices.get(serial) != "device" or runner.get_state() != "device":
            raise RuntimeError("exact local BlueStacks serial is not in device state")
        foreground = parse_foreground_package(runner.shell_text("dumpsys", "window", "windows"))
        if foreground != EXPECTED_PACKAGE:
            raise RuntimeError(f"unexpected foreground package: {foreground!r}")
        session = output_directory / f"{safe_workflow}-{utc_stamp()}"
        return cls(runner, session, execute=execute)

    def _event(self, kind: str, payload: dict[str, object]) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": kind, **payload}
        with self.events.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def measure_device_state(self) -> str:
        """Live ADB device state for navigation-development boundary checks."""

        return self.runner.get_state()

    def measure_foreground_package(self) -> str:
        """Live foreground package from dumpsys for navigation-development boundary checks."""

        return parse_foreground_package(self.runner.shell_text("dumpsys", "window", "windows"))

    def capture(self, label: str) -> CapturedNativeFrame:
        for attempt in (1, 2):
            if self.checkpoint is not None:
                self.checkpoint()
            safe_label = portable_filename_component(label, field="capture label")
            try:
                payload = self.runner.capture_png()
                break
            except ADBError as exc:
                if not isinstance(exc.__cause__, subprocess.TimeoutExpired):
                    raise
                self._event("capture_failure", {
                    "label": label,
                    "attempt": attempt,
                    "error_class": type(exc).__name__,
                    "cause_class": type(exc.__cause__).__name__,
                    "retrying": attempt == 1,
                })
                if attempt == 2:
                    raise
        captured = time.monotonic()
        self.ordinal += 1
        path = self.frames / f"{self.ordinal:04d}-{safe_label}.png"
        result = captured_native_frame_from_png(
            payload,
            captured_monotonic=captured,
            path=path,
        )
        path.write_bytes(payload)
        self._event(
            "capture",
            {
                "label": label,
                "filename_component": safe_label,
                "path": str(path),
                "sha256": result.sha256,
                "captured_monotonic": result.captured_monotonic,
            },
        )
        if self.observation_guard is not None:
            self.observation_guard(result)
        return result

    def _authorize_dispatch(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        target_identity: str,
        target_roi: NativeBox | None,
        consequential: bool,
        continuation_of: str | None,
        action_class: str = "navigation",
    ) -> None:
        if self.checkpoint is not None:
            self.checkpoint()
        reject_real_money_confirmation(target_identity, action_key)
        if not isinstance(action_class, str) or not action_class.strip():
            raise RuntimeError("action class is required")
        from scripts.bluestacks_popup_recognition import (
            NETWORK_DISCONNECT_TARGET, recognize_shared_interruption,
        )
        detail = recognize_shared_interruption(source.frame)
        if action_class == "network_reconnect":
            if (not detail.get("recognized") or detail.get("popup_identity") == "UPDATE_RESTART_REQUIRED" or consequential
                    or target_identity != NETWORK_DISCONNECT_TARGET
                    or target_roi != detail.get("target")
                    or not action_key.startswith("network-recovery:")):
                raise RuntimeError("network reconnect source and target are not exact")
        elif detail.get("recognized") or detail.get("blocking_unknown_modal"):
            from scripts.startup_recovery import NetworkDisconnectError
            raise NetworkDisconnectError(source, detail)
        age = time.monotonic() - source.captured_monotonic
        if age < 0 or age > self.frame_max_age_seconds:
            raise RuntimeError("dispatch source frame is stale")
        if self.input_count >= self.max_inputs:
            raise RuntimeError("development session input limit reached")
        if not action_key or action_key in self.action_keys:
            raise RuntimeError("duplicate or missing action key")
        campaign_parent = self._campaign_child_parent(source, target_identity, action_class, consequential, continuation_of)
        stage_parent = action_class == "campaign_ap_challenge"
        if stage_parent:
            from tasks.campaign_ap_challenge import CAMPAIGN_AP_COSTS

            if (consequential is not True or continuation_of is not None
                    or target_identity not in {f"campaign-challenge-{stage}" for stage in CAMPAIGN_AP_COSTS}):
                raise RuntimeError("Campaign Stage parent identity is not exact")
        fingerprint = (source.sha256, target_identity, target_roi)
        if fingerprint in self.frame_actions and campaign_parent is None:
            raise RuntimeError("identical source/target input is forbidden")
        # Recognition/OCR may outlive the caller's original authority window.
        if self.checkpoint is not None:
            self.checkpoint()
        delegated = current_delegated_runtime_context()
        if delegated is not None:
            delegated.reserve_input(
                action_identity=target_identity,
                action_class=(
                    "combat_confirmation"
                    if consequential
                    else action_class
                ),
                consequence_class=(
                    "combat_confirmation"
                    if consequential
                    else str(getattr(delegated, "receipt", {}).get("consequence_class") or "navigation_only")
                ),
                source_evidence_hash=source.sha256,
                action_key=action_key,
            )
        self.action_keys.add(action_key)
        self.frame_actions.add(fingerprint)
        self.input_count += 1
        if campaign_parent is not None:
            campaign_parent.child_targets.add(target_identity)
            self._campaign_child_parents[action_key] = (campaign_parent, target_identity)
        if stage_parent:
            self._campaign_stage_parents[action_key] = _CampaignStageLineage()

    def _campaign_child_parent(self, source, target_identity, action_class, consequential, continuation_of):
        if target_identity not in _CAMPAIGN_BATTLE_CHILDREN:
            return None
        if continuation_of is None and target_identity != "campaign-lineup-challenge":
            # Explicit Victory-only recovery retains the ordinary duplicate guard.
            return None
        if (type(continuation_of) is not str or not continuation_of
                or action_class != "navigation"
                or consequential is not _CAMPAIGN_BATTLE_CHILDREN[target_identity]):
            raise RuntimeError("Campaign child requires exact confirmed Stage lineage")
        parent = self._campaign_stage_parents.get(continuation_of)
        if (parent is None or not parent.transported or parent.invalidated
                or parent.confirmed_post_sha256 is None):
            raise RuntimeError("Campaign Stage parent is not confirmed in this runtime")
        if target_identity in parent.child_targets:
            raise RuntimeError("Campaign child target is already consumed for this Stage parent")
        if target_identity == "campaign-lineup-challenge":
            if source.sha256 != parent.confirmed_post_sha256:
                raise RuntimeError("Campaign Lineup source does not match the confirmed Stage successor")
        elif "campaign-lineup-challenge" not in parent.transported_child_targets:
            raise RuntimeError("Campaign battle continuation requires its transported Lineup")
        return parent

    def _invalidate_campaign_lineage(self, action_key: str) -> None:
        parent = self._campaign_stage_parents.get(action_key)
        child = self._campaign_child_parents.get(action_key)
        if parent is not None:
            parent.invalidated = True
        if child is not None:
            child[0].invalidated = True

    @staticmethod
    def _delegated_transport_result(action_key: str, error: BaseException | None = None) -> None:
        delegated = current_delegated_runtime_context()
        if delegated is None:
            return
        if error is None:
            delegated.mark_transported(action_key)
        else:
            delegated.mark_reconciled(action_key, unresolved=True)

    def _dispatch_transport(self, action_key: str, transport) -> None:
        try:
            if self.checkpoint is not None:
                self.checkpoint()
        except BaseException:
            self._invalidate_campaign_lineage(action_key)
            raise
        try:
            transport()
        except BaseException as exc:
            self._invalidate_campaign_lineage(action_key)
            self._delegated_transport_result(action_key, exc)
            raise
        try:
            self._delegated_transport_result(action_key)
        except BaseException:
            self._invalidate_campaign_lineage(action_key)
            raise
        parent = self._campaign_stage_parents.get(action_key)
        if parent is not None:
            parent.transported = True
        child = self._campaign_child_parents.get(action_key)
        if child is not None:
            child[0].transported_child_targets.add(child[1])

    def tap(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        action_class: str = "navigation",
        consequential: bool = False,
        continuation_of: str | None = None,
    ) -> None:
        if action_class == "resource_item_use" or target_identity == "daily-resource-item:use-1k-food":
            raise RuntimeError(
                "Resource Use requires a prepared durable Resource effect fence"
            )
        point = box_center(target_roi)
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=target_roi,
            consequential=consequential,
            action_class=action_class,
            continuation_of=continuation_of,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "target_roi": target_roi,
                "point": point,
                "source_sha256": source.sha256,
                "action_class": action_class,
                "consequential": consequential,
                "continuation_of": continuation_of,
                "execute": self.execute,
            },
        )
        if not self.execute:
            self._invalidate_campaign_lineage(action_key)
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(action_key, lambda: self.runner.dispatch_tap(point))

    def dispatch_prepared_resource_item_use(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        action_key: str,
        transport_intent_token: object,
    ):
        """Dispatch the sole Resource Use seam after durable intent consumption."""

        from safe_action_core.models import TransportResult
        from safe_action_core.resource_effect_authority import ResourceTransportIntentToken

        if type(transport_intent_token) is not ResourceTransportIntentToken:
            raise RuntimeError("opaque Resource transport-intent token is required")
        if not transport_intent_token.consumed:
            raise RuntimeError("Resource transport intent must be consumed before adapter dispatch")
        if (
            target_identity != "daily-resource-item:use-1k-food"
            or not action_key
            or transport_intent_token.reservation_id == ""
        ):
            raise RuntimeError("Resource Use target or prepared intent is not exact")
        point = box_center(target_roi)
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=target_roi,
            consequential=False,
            continuation_of=None,
            action_class="owned_item_non_idempotent",
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "target_roi": target_roi,
                "point": point,
                "source_sha256": source.sha256,
                "action_class": "owned_item_non_idempotent",
                "consequential": False,
                "resource_transport_intent": True,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; Resource input was not dispatched")
        self._dispatch_transport(action_key, lambda: self.runner.dispatch_tap(point))
        return TransportResult(True, "DISPATCHED")

    def swipe(
        self,
        source: CapturedNativeFrame,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        action_key: str,
        target_identity: str = "tier-carousel-swipe",
        duration_ms: int = 500,
    ) -> None:
        """Forward the recorded gesture duration explicitly, independent of runner defaults."""
        if type(duration_ms) is not int or not 1 <= duration_ms <= 10000:
            raise ValueError("swipe duration_ms must be an integer between 1 and 10000")
        if not all(0 <= point[0] < 800 and 0 <= point[1] < 1280 for point in (start, end)):
            raise RuntimeError("swipe must remain inside native 800x1280 bounds")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=(
                min(start[0], end[0]),
                min(start[1], end[1]),
                min(800, max(start[0], end[0]) + 1),
                min(1280, max(start[1], end[1]) + 1),
            ),
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "gesture": "swipe",
                "start": start,
                "end": end,
                "duration_ms": duration_ms,
                "action_class": "navigation",
                "consequence_class": "navigation_only",
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(
            action_key, lambda: self.runner.dispatch_swipe(start, end, duration_ms)
        )

    def long_press(
        self,
        source: CapturedNativeFrame,
        *,
        target_identity: str,
        target_roi: NativeBox,
        duration_ms: int,
        action_key: str,
        consequential: bool = True,
    ) -> None:
        if not 500 <= duration_ms <= 12_000:
            raise RuntimeError("long press duration must be between 500 and 12000 ms")
        point = box_center(target_roi)
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=target_roi,
            consequential=consequential,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "target_roi": target_roi,
                "point": point,
                "duration_ms": duration_ms,
                "gesture": "zero-distance-long-press",
                "source_sha256": source.sha256,
                "consequential": consequential,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(
            action_key, lambda: self.runner.dispatch_swipe(point, point, duration_ms=duration_ms)
        )

    def type_text(
        self,
        source: CapturedNativeFrame,
        *,
        text: str,
        action_key: str,
    ) -> None:
        if not text or not text.isdigit():
            raise RuntimeError("native route text input is restricted to decimal quantities")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="quantity-editor",
            target_roi=(560, 1030, 760, 1160),
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "quantity-editor",
                "text": text,
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(action_key, lambda: self.runner.dispatch_text(text))

    def clear_numeric_text(
        self,
        source: CapturedNativeFrame,
        *,
        max_digits: int,
        action_key: str,
    ) -> None:
        if not 1 <= max_digits <= 4:
            raise RuntimeError("numeric editor clear is restricted to one through four digits")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="quantity-editor-clear",
            target_roi=(560, 1030, 760, 1160),
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "quantity-editor-clear",
                "max_digits": max_digits,
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(
            action_key, lambda: self.runner.dispatch_clear_numeric_text(max_digits)
        )

    def press_key(
        self,
        source: CapturedNativeFrame,
        *,
        key: str,
        action_key: str,
    ) -> None:
        normalized = key.strip().upper()
        if normalized not in {"ENTER", "BACK"}:
            raise RuntimeError("native route key input is restricted to ENTER or BACK; numeric clearing has a dedicated route")
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=f"key:{normalized}",
            target_roi=None,
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": f"key:{normalized}",
                "consequential": False,
                "execute": self.execute,
                "source_sha256": source.sha256,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(
            action_key,
            lambda: self.runner.dispatch_keyevent("ENTER" if normalized == "ENTER" else "4"),
        )

    def zoom_out(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
    ) -> None:
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="home-zoom-out",
            target_roi=None,
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "home-zoom-out",
                "transport": "android-scrcpy-motion-event-pinch",
                "source_sha256": source.sha256,
                "consequential": False,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(action_key, self.runner.dispatch_zoom_out)

    def dispatch_external_zoom(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        transport,
    ) -> None:
        """Account for an adapter-owned native zoom transport inside this session."""

        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity="home-zoom-out",
            target_roi=None,
            consequential=False,
            continuation_of=None,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": "home-zoom-out",
                "transport": "adapter-owned-native-zoom",
                "source_sha256": source.sha256,
                "consequential": False,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(action_key, transport)

    def back(
        self,
        source: CapturedNativeFrame,
        *,
        action_key: str,
        target_identity: str = "android-back",
        continuation_of: str | None = None,
    ) -> None:
        self._authorize_dispatch(
            source,
            action_key=action_key,
            target_identity=target_identity,
            target_roi=None,
            consequential=False,
            continuation_of=continuation_of,
        )
        self._event(
            "dispatch",
            {
                "action_key": action_key,
                "target_identity": target_identity,
                "source_sha256": source.sha256,
                "consequential": False,
                "execute": self.execute,
            },
        )
        if not self.execute:
            raise RuntimeError("runtime is dry-run; input was not dispatched")
        self._dispatch_transport(action_key, self.runner.dispatch_back)

    def reconcile(self, action_key: str, status: str, post: CapturedNativeFrame, reason: str) -> None:
        if status not in {"confirmed", "failed_confirmed", "unresolved"}:
            raise ValueError("invalid reconciliation status")
        if status != "confirmed":
            self._invalidate_campaign_lineage(action_key)
        parent = self._campaign_stage_parents.get(action_key)
        if parent is not None:
            if status != "confirmed":
                parent.invalidated = True
            elif (not parent.transported or parent.invalidated
                    or not isinstance(post, CapturedNativeFrame)
                    or not re.fullmatch(r"[0-9a-f]{64}", post.sha256)
                    or (parent.confirmed_post_sha256 is not None
                        and parent.confirmed_post_sha256 != post.sha256)):
                parent.invalidated = True
                raise RuntimeError("Campaign Stage reconciliation cannot establish confirmed lineage")
        self._event(
            "reconcile",
            {
                "action_key": action_key,
                "status": status,
                "post_sha256": post.sha256,
                "post_path": str(post.path),
                "reason": reason,
            },
        )
        delegated = current_delegated_runtime_context()
        if delegated is not None:
            delegated.mark_reconciled(action_key, unresolved=status == "unresolved")
        if parent is not None and status == "confirmed":
            parent.confirmed_post_sha256 = post.sha256
        self.in_flight_action = None

    def record_recovery(
        self,
        *,
        action_key: str,
        previous_session: str,
        previous_source_sha256: str,
        previous_post_sha256: str,
        current: CapturedNativeFrame,
        expected_completion_timestamp: str,
        reason: str,
    ) -> None:
        """Record a fresh live reconciliation without recreating a dispatch."""

        if not action_key or not previous_session or not previous_source_sha256 or not previous_post_sha256:
            raise ValueError("recovery requires the prior action and evidence identities")
        self._event(
            "recovery_reconcile",
            {
                "action_key": action_key,
                "previous_session": previous_session,
                "previous_source_sha256": previous_source_sha256,
                "previous_post_sha256": previous_post_sha256,
                "current_sha256": current.sha256,
                "current_path": str(current.path),
                "expected_completion_timestamp": expected_completion_timestamp,
                "reason": reason,
                "execute": self.execute,
            },
        )
