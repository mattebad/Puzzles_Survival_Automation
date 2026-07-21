"""Executable, dry-run-by-default BlueStacks route for Nova Praise.

The adapter consumes current native 800x1280 frames and exposes bound commands to a caller.
It does not register a task or enable the production scheduler.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import time
from typing import Callable

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.nova_praise_runtime import NovaPraiseRuntimeController
from tasks.nova_praise import NOVA_SCREEN, nova_authorizeable
from tasks.nova_praise_vision import (
    NovaFrameRecognition,
    ResearchLabTapProvenance,
    recognize_nova_frame,
)
from scripts.bluestacks_native_runtime import IntegratedRouteResult, LocalBlueStacksRuntime, NativeRuntimePort
from scripts.home_atlas_bluestacks import (
    BlueStacksHostZoomTransport,
    BlueStacksLocalizeFirstHomeDriver,
    HomeDriverDisposition,
)
from tasks.home_atlas import load_home_atlas
from tasks.home_context import HomeContextLevel, HomeReadyObservation, localize_home
from tasks.nova_praise import NOVA_INTERACTION_TARGET
from tasks.nova_praise_pulse import RESEARCH_LAB_BUILDING_ID
from tasks.runtime_identity import VerifiedRuntimeIdentity


@dataclass(frozen=True)
class NovaAdapterConfig:
    dry_run: bool = True
    frame_max_age_seconds: float = 3.0


class BlueStacksNovaPraiseAdapter:
    """Vision-only adapter; transport is an injected callable and disabled by default."""

    def __init__(self, config: NovaAdapterConfig | None = None, *, transport: Callable[[tuple[int, int]], None] | None = None) -> None:
        self.config = config or NovaAdapterConfig()
        self.transport = transport
        self.controller = NovaPraiseRuntimeController()

    def observe(self, frame, *, captured_monotonic: float | None = None, now: float | None = None) -> NovaFrameRecognition:
        stale = bool(
            now is not None
            and captured_monotonic is not None
            and now - captured_monotonic > self.config.frame_max_age_seconds
        )
        return recognize_nova_frame(frame, captured_monotonic=captured_monotonic, stale=stale)

    def command(self, recognition):
        command = self.controller.next_command(recognition)
        if command.action.value == "PRAISE" and not self.config.dry_run:
            raise RuntimeError("Nova Praise dispatch requires the centralized action boundary")
        return command


class NovaPraiseIntegratedRoute:
    """Drive Home → Research Lab → Nova → one Praise → verified cooldown → Home."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        *,
        controller: NovaPraiseRuntimeController | None = None,
        recognizer=recognize_nova_frame,
        action_boundary=None,
        post_input_delay: float = 1.0,
        postcondition_timeout: float = 20.0,
    ) -> None:
        self.runtime = runtime
        self.controller = controller or NovaPraiseRuntimeController(now=time.monotonic())
        self.recognizer = recognizer
        self.action_boundary = action_boundary
        self.post_input_delay = post_input_delay
        self.postcondition_timeout = postcondition_timeout

    def _observe(self, label: str):
        captured = self.runtime.capture(label)
        recognition = self.recognizer(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            stale=False,
        )
        return captured, recognition

    def _return_home(self, captured, recognition, actions: int) -> IntegratedRouteResult:
        for ordinal in range(1, 4):
            if recognition.observation.screen_state == "HOME_BASE":
                return IntegratedRouteResult("completed", "returned_home", actions, str(self.runtime.session))
            self.runtime.back(captured, action_key=f"nova:return-home:{ordinal}")
            time.sleep(self.post_input_delay)
            captured, recognition = self._observe(f"return-home-post-{ordinal}")
        return IntegratedRouteResult("blocked", "home_postcondition_not_recognized", actions, str(self.runtime.session))

    def reconcile_unresolved_praise(self, *, before_frame: Path, action_key: str) -> IntegratedRouteResult:
        """Reconcile one retained Praise from the current cooldown frame; never Praise again."""

        if not self.runtime.execute:
            return IntegratedRouteResult("dry-run", "resume_transport_disabled", 0, str(self.runtime.session))
        captured, recognition = self._observe("resume-current-source")
        if recognition.observation.screen_state != NOVA_SCREEN or not recognition.observation.recognized:
            return IntegratedRouteResult("unresolved", "current_nova_postcondition_not_recognized", 0, str(self.runtime.session))
        before_frame_data = read_frame(before_frame)
        before = self.recognizer(
            before_frame_data,
            captured_monotonic=max(0.0, captured.captured_monotonic - 1.0),
            stale=False,
        ).observation
        if not nova_authorizeable(before):
            return IntegratedRouteResult("blocked", "retained_nova_source_not_authorized", 0, str(self.runtime.session))
        self.controller.progress.awaiting_postcondition = True
        self.controller.now = captured.captured_monotonic
        self.runtime.in_flight_action = action_key
        if not self.controller.accept_postcondition(before, recognition.observation):
            self.runtime.reconcile(action_key, "unresolved", captured, "retained decrement/cooldown not proven")
            return IntegratedRouteResult("unresolved", "retained_nova_postcondition_not_proven", 0, str(self.runtime.session))
        self.runtime.reconcile(action_key, "confirmed", captured, "retained exact decrement and cooldown verified")
        return self._return_home(captured, recognition, 1)

    def run(self, *, max_steps: int = 20) -> IntegratedRouteResult:
        if not self.runtime.execute:
            _, recognition = self._observe("dry-run-source")
            status = "dry-run" if recognition.observation.recognized else "blocked"
            return IntegratedRouteResult(status, f"transport_disabled:{recognition.observation.screen_state}", 0, str(self.runtime.session))
        if self.action_boundary is None:
            return IntegratedRouteResult(
                "blocked",
                "centralized_action_boundary_required",
                0,
                str(self.runtime.session),
            )
        actions = 0
        for step in range(1, max_steps + 1):
            captured, recognition = self._observe(f"step-{step:03d}-source")
            self.controller.now = captured.captured_monotonic
            command = self.controller.next_command(recognition)
            if command.action.value in {"OPEN_LAB", "OPEN_NOVA"}:
                target = recognition.target(command.target_identity or "") or command.target_roi
                self.runtime.tap(
                    captured,
                    target_identity=command.target_identity or "",
                    target_roi=target or (0, 0, 0, 0),
                    action_key=f"nova:{command.action.value.casefold()}:{captured.sha256}",
                )
            elif command.action.value == "PRAISE":
                result = self.action_boundary.execute_praise(captured, recognition)
                if (
                    result.status == "confirmed"
                    and result.after_capture is not None
                    and result.after_recognition is not None
                ):
                    actions += 1
                    return self._return_home(
                        result.after_capture,
                        result.after_recognition,
                        actions,
                    )
                return IntegratedRouteResult(
                    result.status,
                    result.reason,
                    actions,
                    str(self.runtime.session),
                )
            elif command.action.value in {"WAIT_COOLDOWN", "RETURN_HOME"}:
                result = self.action_boundary.record_no_dispatch(
                    recognition.observation,
                    evidence_ref=str(captured.path),
                )
                if result.status not in {"deferred", "complete_for_reset"}:
                    return IntegratedRouteResult(
                        result.status,
                        result.reason,
                        actions,
                        str(self.runtime.session),
                    )
                return self._return_home(captured, recognition, actions)
            else:
                return IntegratedRouteResult("blocked", command.reason or command.action.value, actions, str(self.runtime.session))
            time.sleep(self.post_input_delay)
        return IntegratedRouteResult("blocked", "maximum controller steps exceeded", actions, str(self.runtime.session))


@dataclass(frozen=True)
class NovaNavigationCanaryResult:
    status: str
    reason: str
    navigation_input_count: int
    praise_taps: int
    terminal_home_verified: bool
    records: tuple[dict[str, object], ...]
    session: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "navigation_input_count": self.navigation_input_count,
            "praise_taps": self.praise_taps,
            "terminal_home_verified": self.terminal_home_verified,
            "records": list(self.records),
            "session": self.session,
        }


class NovaNavigationCanaryRoute:
    """Bounded no-Praise Home → Research Lab → radial → Nova → Home route."""

    def __init__(
        self,
        runtime: NativeRuntimePort,
        identity: VerifiedRuntimeIdentity,
        *,
        atlas_path: Path,
        home_driver: BlueStacksLocalizeFirstHomeDriver | None = None,
        recognizer=recognize_nova_frame,
        zoom_transport=None,
        settle_seconds: float = 1.0,
        maximum_steps: int = 12,
        maximum_return_inputs: int = 3,
    ) -> None:
        self.runtime = runtime
        self.identity = identity
        self.atlas_path = atlas_path
        self.atlas = load_home_atlas(atlas_path)
        ready = HomeReadyObservation(True, True, identity, False, False)
        self.home_driver = home_driver or BlueStacksLocalizeFirstHomeDriver(
            self.atlas,
            atlas_path,
            ready,
            RESEARCH_LAB_BUILDING_ID,
        )
        self.recognizer = recognizer
        self.zoom_transport = zoom_transport
        self.settle_seconds = settle_seconds
        self.maximum_steps = maximum_steps
        self.maximum_return_inputs = maximum_return_inputs
        self.records: list[dict[str, object]] = []
        self.input_count = 0

    def _capture(self, label: str):
        return self.runtime.capture(label)

    def _record_input(self, action: str, source, successor, **details) -> None:
        self.records.append(
            {
                "action": action,
                "source_sha256": source.sha256,
                "successor_sha256": successor.sha256,
                **details,
            }
        )
        self.input_count += 1

    def _recognize(self, captured, *, provenance=None, home_visible=False):
        return self.recognizer(
            captured.frame,
            captured_monotonic=captured.captured_monotonic,
            stale=False,
            research_lab_tap_provenance=provenance,
            home_context_visible=home_visible,
        )

    def _settle(self, immediate_label: str, settled_label: str):
        immediate_post = self._capture(immediate_label)
        if self.settle_seconds > 0:
            time.sleep(self.settle_seconds)
        settled = self._capture(settled_label)
        return immediate_post, settled

    def _home_localized(self, captured) -> bool:
        localization = self.home_driver.localizer.localize(captured.frame)
        decision = localize_home(self.home_driver.ready, localization)
        return decision.level in {
            HomeContextLevel.HOME_LOCALIZED,
            HomeContextLevel.HOME_CANONICAL,
        }

    def _return_home(self, captured, recognition) -> NovaNavigationCanaryResult:
        current_capture = captured
        current_recognition = recognition
        for ordinal in range(1, self.maximum_return_inputs + 1):
            if self._home_localized(current_capture):
                return NovaNavigationCanaryResult(
                    "completed",
                    "verified_safe_return_home",
                    self.input_count,
                    0,
                    True,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            if (
                not current_recognition.observation.recognized
                or current_recognition.observation.screen_state
                not in {"NOVA", "RESEARCH_LAB_MENU"}
            ):
                return NovaNavigationCanaryResult(
                    "blocked",
                    "return_source_not_recognized",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            immediate_before = self._capture(
                f"canary-return-{ordinal:02d}-immediate-before"
            )
            rebound = self._recognize(immediate_before)
            if (
                not rebound.observation.recognized
                or rebound.observation.screen_state
                != current_recognition.observation.screen_state
            ):
                return NovaNavigationCanaryResult(
                    "blocked",
                    "return_source_revalidation_failed",
                    self.input_count,
                    0,
                    False,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            self.runtime.back(
                immediate_before,
                action_key=f"nova-canary:return:{ordinal}:{immediate_before.sha256}",
            )
            _immediate_post, settled = self._settle(
                f"canary-return-{ordinal:02d}-immediate-post",
                f"canary-return-{ordinal:02d}-settled",
            )
            self._record_input("safe_return_back", immediate_before, settled)
            if self._home_localized(settled):
                return NovaNavigationCanaryResult(
                    "completed",
                    "verified_safe_return_home",
                    self.input_count,
                    0,
                    True,
                    tuple(self.records),
                    str(self.runtime.session),
                )
            current_capture = settled
            current_recognition = self._recognize(settled)
        return NovaNavigationCanaryResult(
            "blocked",
            "maximum_safe_return_inputs",
            self.input_count,
            0,
            False,
            tuple(self.records),
            str(self.runtime.session),
        )

    def run(self) -> NovaNavigationCanaryResult:
        self._capture("canary-source")
        provenance: ResearchLabTapProvenance | None = None
        for ordinal in range(1, self.maximum_steps + 1):
            immediate_before = self._capture(
                f"canary-home-{ordinal:02d}-immediate-before"
            )
            step = self.home_driver.observe(immediate_before.frame)
            if step.disposition is HomeDriverDisposition.RECOVER_ZOOM:
                if self.zoom_transport is None:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "bounded_zoom_transport_unavailable",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self.zoom_transport.zoom_out_once()
                self.home_driver.record_zoom_input_dispatched(
                    step.source_frame_sha256
                )
                _immediate_post, settled = self._settle(
                    f"canary-zoom-{ordinal:02d}-immediate-post",
                    f"canary-zoom-{ordinal:02d}-settled",
                )
                self._record_input("bounded_zoom_out", immediate_before, settled)
                continue
            if step.disposition is HomeDriverDisposition.PAN:
                plan = step.plan
                if plan is None or plan.drag_start is None or plan.drag_end is None:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "home_pan_geometry_missing",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self.runtime.swipe(
                    immediate_before,
                    start=plan.drag_start,
                    end=plan.drag_end,
                    action_key=f"nova-canary:pan:{ordinal}:{immediate_before.sha256}",
                    target_identity="home-camera-click-drag",
                )
                _immediate_post, settled = self._settle(
                    f"canary-pan-{ordinal:02d}-immediate-post",
                    f"canary-pan-{ordinal:02d}-settled",
                )
                after_localization = self.home_driver.localizer.localize(settled.frame)
                progress = self.home_driver.record_pan_progress(
                    step.localization,
                    after_localization,
                )
                self._record_input(
                    "bounded_home_pan",
                    immediate_before,
                    settled,
                    progress_reason=progress.reason,
                    progress_accepted=progress.accepted,
                )
                if not progress.accepted:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        f"home_pan_no_progress:{progress.reason}",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                continue
            if step.disposition is HomeDriverDisposition.BIND:
                self.records.append(
                    {
                        "action": "no_input_rebind_research_lab",
                        "source_sha256": immediate_before.sha256,
                    }
                )
                continue
            if step.disposition is HomeDriverDisposition.COMPLETE and step.binding is not None:
                action_key = (
                    f"nova-canary:open-research-lab:{immediate_before.sha256}"
                )
                self.runtime.tap(
                    immediate_before,
                    target_identity=RESEARCH_LAB_BUILDING_ID,
                    target_roi=step.binding.target_roi,
                    action_key=action_key,
                    consequential=False,
                )
                provenance = ResearchLabTapProvenance(
                    action_key,
                    RESEARCH_LAB_BUILDING_ID,
                    immediate_before.sha256,
                    step.binding.target_roi,
                    immediate_before.captured_monotonic,
                )
                _immediate_post, radial_capture = self._settle(
                    "canary-open-lab-immediate-post",
                    "canary-open-lab-settled",
                )
                self._record_input(
                    "tap_research_lab_navigation",
                    immediate_before,
                    radial_capture,
                )
                radial = self._recognize(
                    radial_capture,
                    provenance=provenance,
                    home_visible=True,
                )
                target = radial.target(NOVA_INTERACTION_TARGET)
                if (
                    not radial.observation.recognized
                    or radial.observation.screen_state != "RESEARCH_LAB_MENU"
                    or target is None
                ):
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "research_lab_radial_not_bound",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                nova_before = self._capture("canary-open-nova-immediate-before")
                radial_rebound = self._recognize(
                    nova_before,
                    provenance=provenance,
                    home_visible=True,
                )
                target = radial_rebound.target(NOVA_INTERACTION_TARGET)
                if target is None:
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "fresh_nova_target_not_bound",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                self.runtime.tap(
                    nova_before,
                    target_identity=NOVA_INTERACTION_TARGET,
                    target_roi=target,
                    action_key=f"nova-canary:open-nova:{nova_before.sha256}",
                    consequential=False,
                )
                _immediate_post, nova_capture = self._settle(
                    "canary-open-nova-immediate-post",
                    "canary-open-nova-settled",
                )
                self._record_input("tap_nova_navigation", nova_before, nova_capture)
                nova = self._recognize(nova_capture)
                if (
                    not nova.observation.recognized
                    or nova.observation.screen_state != NOVA_SCREEN
                ):
                    return NovaNavigationCanaryResult(
                        "blocked",
                        "nova_lab_successor_not_recognized",
                        self.input_count,
                        0,
                        False,
                        tuple(self.records),
                        str(self.runtime.session),
                    )
                return self._return_home(nova_capture, nova)
            return NovaNavigationCanaryResult(
                "blocked",
                step.reason,
                self.input_count,
                0,
                False,
                tuple(self.records),
                str(self.runtime.session),
            )
        return NovaNavigationCanaryResult(
            "blocked",
            "maximum_navigation_steps",
            self.input_count,
            0,
            False,
            tuple(self.records),
            str(self.runtime.session),
        )


def run_nova_navigation_canary(args, identity: VerifiedRuntimeIdentity) -> str:
    """Checked-in pnsctl live runner; invoked only by GF-MVP-009 authorization."""

    atlas_path = (
        ROOT
        / "tasks"
        / "assets"
        / "home_atlas"
        / "bluestacks"
        / "800x1280"
        / "atlas.json"
    )
    runtime = LocalBlueStacksRuntime.connect(
        adb=str(args.adb),
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="nova-navigation-canary",
        execute=True,
    )
    route = NovaNavigationCanaryRoute(
        runtime,
        identity,
        atlas_path=atlas_path,
        zoom_transport=BlueStacksHostZoomTransport(),
        settle_seconds=args.settle_seconds,
    )
    result = route.run()
    payload = {
        "schema_version": 1,
        "flow_id": "NOVA-PRAISE-HOME-ATLAS-MIGRATION",
        "scenario_id": "nova_navigation_round_trip_no_praise",
        **result.to_mapping(),
        "production_registration": "NOT_REGISTERED",
        "scheduler_enabled": False,
    }
    (runtime.session / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name, records in (
        ("ledger.jsonl", result.records),
        (
            "capability-audit.jsonl",
            tuple(
                {
                    "action": item["action"],
                    "authority": "LocalBlueStacksRuntime._authorize_dispatch",
                    "authorized": True,
                    "transport_observed": True,
                    "source_sha256": item["source_sha256"],
                    "successor_sha256": item["successor_sha256"],
                }
                for item in result.records
                if item["action"] != "no_input_rebind_research_lab"
            ),
        ),
        (
            "journal.jsonl",
            (
                {
                    "scenario_id": "nova_navigation_round_trip_no_praise",
                    "status": result.status,
                    "navigation_input_count": result.navigation_input_count,
                    "praise_taps": 0,
                },
            ),
        ),
    ):
        with (runtime.session / name).open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return json.dumps(
        {
            "status": result.status,
            "reason": result.reason,
            "scenario_id": "nova_navigation_round_trip_no_praise",
            "session_directory": str(runtime.session),
            "navigation_input_count": result.navigation_input_count,
            "praise_taps": 0,
            "transport_calls": result.navigation_input_count,
            "production_registration": "NOT_REGISTERED",
            "scheduler_enabled": False,
        },
        sort_keys=True,
    )


def read_frame(path: Path):
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot read BlueStacks frame: {path}")
    return frame


def load_unresolved_praise(session: Path) -> tuple[Path, str]:
    events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    unresolved = next((event for event in reversed(events) if event.get("type") == "reconcile" and event.get("status") == "unresolved"), None)
    if unresolved is None:
        raise RuntimeError("session has no unresolved Nova Praise")
    action_key = str(unresolved["action_key"])
    dispatch = next((event for event in events if event.get("type") == "dispatch" and event.get("action_key") == action_key and event.get("consequential") is True), None)
    if dispatch is None:
        raise RuntimeError("unresolved Nova action has no retained dispatch")
    capture = next((event for event in events if event.get("type") == "capture" and event.get("sha256") == dispatch.get("source_sha256")), None)
    if capture is None:
        raise RuntimeError("unresolved Nova source frame is missing")
    source = Path(str(capture["path"]))
    if not source.is_absolute():
        source = ROOT / source
    return source, action_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes", action="store_true", help="confirm the exact local BlueStacks target non-interactively")
    parser.add_argument("--resume-unresolved-session", type=Path)
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures/nova-praise-integrated"))
    args = parser.parse_args(argv)
    if args.execute and not args.yes:
        parser.error("--execute requires --yes")
    runtime = LocalBlueStacksRuntime.connect(
        adb=args.adb,
        serial=args.serial,
        output_directory=args.output_directory,
        workflow="nova-praise",
        execute=args.execute,
    )
    route = NovaPraiseIntegratedRoute(runtime)
    if args.resume_unresolved_session is not None:
        before_frame, action_key = load_unresolved_praise(args.resume_unresolved_session)
        result = route.reconcile_unresolved_praise(before_frame=before_frame, action_key=action_key)
    else:
        result = route.run()
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0 if result.status in {"completed", "dry-run"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
