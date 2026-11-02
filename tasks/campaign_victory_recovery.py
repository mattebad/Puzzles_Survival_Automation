"""Read-only proof of one pending Campaign battle; never input authority."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

import cv2
import numpy as np

from automation_service.registry import CAMPAIGN_FLOW_ID, RegisteredDispatchSnapshot
from tasks.campaign_auto_battle import CAMPAIGN_STAGE_COSTS, CampaignScreen, CampaignStage
from tasks.campaign_auto_battle_vision import recognize_campaign_frame


SESSIONS_ROOT = Path(__file__).resolve().parents[1] / ".local-captures" / "development-sessions"
PROFILE = "pns-bluestacks-5-p64-800x1280-v1"
_STAMP = re.compile(r"^" + re.escape(CAMPAIGN_FLOW_ID) + r"-(\d{8}T\d{12}Z)$")


def _path(path: Path, root: Path) -> Path:
    if ".." in path.parts:
        raise ValueError("recovery evidence path contains traversal")
    absolute = path.absolute()
    for part in (absolute, *absolute.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("recovery evidence path contains a link")
    resolved = absolute.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("recovery evidence path escaped development sessions")
    return resolved


def _read(path: Path, root: Path) -> bytes:
    candidate = _path(path, root)
    if not candidate.is_file():
        raise ValueError("recovery evidence file is missing")
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise ValueError("recovery evidence file is unreadable") from exc


def _json(path: Path, root: Path) -> tuple[dict, str]:
    raw = _read(path, root)
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("recovery evidence JSON is malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("recovery evidence JSON must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _frame(path: Path, root: Path) -> tuple[np.ndarray, dict]:
    raw = _read(path, root)
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("recovery frame is not PNG")
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (1280, 800, 3):
        raise ValueError("recovery frame is not native 800x1280")
    return image, {
        "path": str(_path(path, root)),
        "png_sha256": hashlib.sha256(raw).hexdigest(),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
    }


def load_victory_recovery_proof(
    session: Path,
    *,
    now: datetime | None = None,
    sessions_root: Path | None = None,
    recognizer: Callable | None = None,
) -> dict:
    """Validate one same-game-day pending supported AP battle without altering evidence.

    ``sessions_root`` and ``recognizer`` permit isolated offline fixtures. Runtime
    callers use the fixed repository root and production recognizer. A fresh
    Winner screen and separate current authorization remain mandatory elsewhere.
    """

    root = SESSIONS_ROOT if sessions_root is None else Path(sessions_root)
    session = _path(Path(session), root)
    match = _STAMP.fullmatch(session.name)
    if match is None:
        raise ValueError("recovery session invocation is invalid")
    started = datetime.strptime(match[1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("recovery time must be timezone aware")
    current = current.astimezone(timezone.utc)
    if started > current or started.date() != current.date():
        raise ValueError("recovery session is future or outside current game day")

    outer, result_hash = _json(session / "result.json", root)
    result = outer.get("result")
    if not isinstance(result, dict):
        raise ValueError("recovery session lacks typed route result")
    delivery, delivery_hash = _json(session / "runtime" / "flow-delivery-result.json", root)
    for record in (outer, result, delivery):
        if record.get("flow_id") != CAMPAIGN_FLOW_ID:
            raise ValueError("recovery flow identity mismatch")
    if delivery.get("serial") != "emulator-5554" or (
        delivery.get("native_width"), delivery.get("native_height")
    ) != (800, 1280):
        raise ValueError("recovery runtime profile or device mismatch")
    snapshot = RegisteredDispatchSnapshot.from_mapping(result.get("registration_snapshot"))
    if snapshot.flow_id != CAMPAIGN_FLOW_ID or snapshot.profile != PROFILE:
        raise ValueError("recovery registration is not Campaign AP")
    if delivery.get("registration_snapshot") != snapshot.to_mapping():
        raise ValueError("recovery registration aliases disagree")
    destination = result.get("destination")
    if not isinstance(destination, str) or destination not in CAMPAIGN_STAGE_COSTS:
        raise ValueError("recovery destination is not supported")
    ap_cost = CAMPAIGN_STAGE_COSTS[destination]
    for record in (result, delivery):
        if record.get("destination") != destination or type(record.get("ap_cost")) is not int or record["ap_cost"] != ap_cost:
            raise ValueError("recovery destination or cost mismatch")
        if record.get("status") != "effect_reconciliation_required" or record.get("effect_reconciliation_required") is not True:
            raise ValueError("recovery source is not a pending battle")

    if outer.get("status") != "effect_reconciliation_required":
        raise ValueError("recovery outer session is not pending reconciliation")
    _, initial_ref = _frame(session / "source.png", root)
    for record in (outer, result, delivery):
        observation = record.get("initial_observation")
        if not isinstance(observation, dict) or any((
            observation.get("device_state") != "device",
            observation.get("foreground_package") != "com.global.ztmslg",
            observation.get("native_width") != 800,
            observation.get("native_height") != 1280,
            observation.get("invocation_id") != session.name,
            observation.get("frame_path") != "source.png",
            observation.get("frame_sha256") != initial_ref["png_sha256"],
            record.get("initial_frame_sha256") != initial_ref["png_sha256"],
        )):
            raise ValueError("recovery initial frame or invocation binding mismatch")

    runtime = _path(session / "runtime", root)
    try:
        leaves = [path for path in runtime.iterdir() if re.fullmatch(re.escape(destination) + r"-\d{8}T\d{12}Z", path.name)]
    except OSError as exc:
        raise ValueError("recovery runtime directory is missing or unreadable") from exc
    if len(leaves) != 1:
        raise ValueError("recovery route leaf is missing or ambiguous")
    leaf = _path(leaves[0], root)
    leaf_started = datetime.strptime(leaf.name.removeprefix(destination + "-"), "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
    if not started <= leaf_started <= current:
        raise ValueError("recovery route leaf timestamp is outside invocation")
    events_path = leaf / "events.jsonl"
    raw_events = _read(events_path, root)
    if len(raw_events) > 2_000_000:
        raise ValueError("recovery event stream exceeds bounded route proof")
    try:
        rows = [json.loads(line) for line in raw_events.splitlines() if line.strip()]
    except (UnicodeError, ValueError) as exc:
        raise ValueError("recovery events are malformed") from exc
    row_types = {"observation", "command", "home_atlas_entry_result", "home_atlas_entry_verified"}
    if not rows or len(rows) > 512 or any(not isinstance(row, dict) or row.get("type") not in row_types for row in rows):
        raise ValueError("recovery events are empty or invalid")
    commands = [(index, row) for index, row in enumerate(rows) if row.get("type") == "command"]
    allowed = {"OPEN_CAMPAIGN", "SELECT_TIER", "NAVIGATE_CHAPTER", "NAVIGATE_STAGE", "SELECT_STAGE", "CHALLENGE_STAGE", "CONFIRM_LINEUP", "ENABLE_AUTO", "WAIT_FOR_BATTLE_RESULT"}
    if any(row.get("action") not in allowed for _, row in commands):
        raise ValueError("recovery source contains Continue, retry, or unsupported action")
    if any(re.search(r"continue|retry|refill|blitz|buy", str(row.get("target_identity") or ""), re.I) for _, row in commands):
        raise ValueError("recovery source contains forbidden target")
    confirms = [(index, row) for index, row in commands if row.get("action") == "CONFIRM_LINEUP"]
    challenges = [(index, row) for index, row in commands if row.get("action") == "CHALLENGE_STAGE"]
    if len(confirms) != 1 or len(challenges) != 1 or challenges[0][0] >= confirms[0][0]:
        raise ValueError("recovery source does not prove exactly one battle")
    confirm_index, confirm = confirms[0]
    challenge_index, challenge = challenges[0]
    if confirm.get("kind") != "tap" or confirm.get("target_identity") != "campaign-lineup-challenge" or challenge.get("target_identity") != f"campaign-challenge-{destination}":
        raise ValueError("recovery battle target mismatch")
    if any(row.get("action") not in {"ENABLE_AUTO", "WAIT_FOR_BATTLE_RESULT"} for index, row in commands if index > confirm_index):
        raise ValueError("recovery source has further gameplay after pending battle")
    progress = confirm.get("progress")
    fields = {"initial_ap", "current_ap", "ap_spent", "ap_regenerated", "completed_runs", "loss_seen"}
    if not isinstance(progress, dict) or set(progress) != fields or challenge.get("progress") != progress:
        raise ValueError("recovery baseline or pending battle accounting mismatch")
    for command in (challenge, confirm):
        current_progress = command["progress"]
        if any(type(current_progress[key]) is not int for key in fields if key != "loss_seen") or current_progress["loss_seen"] is not False:
            raise ValueError("recovery progress is not typed AP accounting")
    baseline_ap = progress["initial_ap"]
    pre_battle_ap = progress["current_ap"]
    if (
        baseline_ap < ap_cost or progress["ap_regenerated"] < 0
        or progress["ap_spent"] != 0 or progress["completed_runs"] != 0
        or pre_battle_ap != baseline_ap + progress["ap_regenerated"]
    ):
        raise ValueError("recovery AP baseline or regeneration conservation mismatch")

    def preceding(index: int, screen: CampaignScreen) -> dict:
        candidates = [row for row in rows[:index] if row.get("type") == "observation"]
        if not candidates or candidates[-1].get("screen") != screen.value:
            raise ValueError("recovery command lacks exact source observation")
        if type(candidates[-1].get("step")) is not int or candidates[-1]["step"] != rows[index].get("step"):
            raise ValueError("recovery command step differs from source observation")
        return candidates[-1]

    stage_row = preceding(challenge_index, CampaignScreen.STAGE_DIALOG)
    lineup_row = preceding(confirm_index, CampaignScreen.HERO_LINEUP)
    battle_rows = [row for row in rows[confirm_index + 1:] if row.get("type") == "observation" and row.get("screen") == CampaignScreen.BATTLE.value and row.get("recognized") is True]
    if not battle_rows:
        raise ValueError("recovery confirmation has no positive battle successor")
    stage = CampaignStage.parse(destination)
    recognize = recognize_campaign_frame if recognizer is None else recognizer
    refs = {"initial": initial_ref}
    recognitions = {}
    for label, row, expected_screen in (("stage", stage_row, CampaignScreen.STAGE_DIALOG), ("lineup", lineup_row, CampaignScreen.HERO_LINEUP), ("battle", battle_rows[0], CampaignScreen.BATTLE)):
        reference = row.get("frame")
        if not isinstance(reference, str) or row.get("recognized") is not True:
            raise ValueError("recovery source frame reference is invalid")
        image, ref = _frame(_path(Path(reference) if Path(reference).is_absolute() else leaf / reference, leaf), root)
        if row.get("frame_sha256") != ref["pixel_sha256"]:
            raise ValueError("recovery source frame pixel hash mismatch")
        replay = recognize(image, stage)
        if replay.observation.recognized is not True or replay.observation.screen != expected_screen:
            raise ValueError("recovery source frame failed current semantic replay")
        refs[label], recognitions[label] = ref, replay
    observed = recognitions["stage"].observation
    if observed.stage_dialog != stage or observed.ap_current != pre_battle_ap or observed.ap_cost != ap_cost or observed.refill_visible or not observed.challenge_ready:
        raise ValueError("recovery stage, cost, or baseline replay mismatch")
    for label, command in (("stage", challenge), ("lineup", confirm)):
        target = recognitions[label].target(command["target_identity"])
        if target is None or list(target) != command.get("target_roi"):
            raise ValueError("recovery command target does not match current-frame replay")
    if not recognitions["lineup"].observation.lineup_challenge_ready:
        raise ValueError("recovery lineup challenge is not ready")
    return {
        "source_session": str(session), "source_result_sha256": result_hash,
        "source_delivery_result_sha256": delivery_hash,
        "source_events_path": str(events_path), "source_events_sha256": hashlib.sha256(raw_events).hexdigest(),
        "baseline_ap": baseline_ap, "pre_battle_ap": pre_battle_ap,
        "ap_regenerated_before_battle": progress["ap_regenerated"],
        "destination": destination, "ap_cost": ap_cost,
        "registration_snapshot": snapshot.to_mapping(),
        "game_day_id": f"game-day-{started.date().isoformat()}",
        "new_battle_count": 0, "frame_refs": refs,
    }
