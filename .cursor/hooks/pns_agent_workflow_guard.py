"""Fail-closed admission for the managed P&S subagentStart hook.

The hook is deliberately narrow: only the checked-in P&S implementer and
reviewer are governed. Other Cursor agents receive an unchanged allow result.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "tasks" / "agentic_workflow_policy.json"
HANDOFF_PATH = ROOT / "CURRENT_HANDOFF.md"
REQUIRED_PROMPT_FIELDS = (
    "Control-Owner",
    "Stage-Revision",
    "Turn-Kind",
    "Product-Precondition",
)
MANAGED_TYPES = {"pns-flow-implementer", "terra-reviewer"}
METADATA_ALIASES = {
    "Control-Owner": ("control_owner", "control_plane_owner", "controlOwner"),
    "Stage-Revision": ("stage_revision", "revision", "stageRevision"),
    "Turn-Kind": ("turn_kind", "turnKind"),
    "Product-Precondition": (
        "product_precondition",
        "productPrecondition",
    ),
}


class WorkflowGuardError(RuntimeError):
    """Raised for malformed managed input or unavailable policy state."""


def _deny(message: str) -> dict[str, str]:
    return {"permission": "deny", "user_message": f"P&S workflow denied: {message}"}


def _allow() -> dict[str, str]:
    return {"permission": "allow"}


def _lookup(payload: Mapping[str, Any], *names: str) -> Any:
    sources: list[Mapping[str, Any]] = [payload]
    for nested_name in ("subagent", "tool_input"):
        nested = payload.get(nested_name)
        if isinstance(nested, Mapping):
            sources.append(nested)
    for source in sources:
        for name in names:
            if name in source:
                return source[name]
    return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowGuardError(f"cannot read {path.name}") from exc
    if not isinstance(value, dict):
        raise WorkflowGuardError(f"{path.name} must contain an object")
    return value


def _load_handoff(repo_root: Path) -> dict[str, Any]:
    try:
        text = (repo_root / "CURRENT_HANDOFF.md").read_text(encoding="utf-8")
        start = text.index("<!-- CURRENT_HANDOFF_STATE_BEGIN -->")
        start = text.index("\n", start) + 1
        end = text.index("<!-- CURRENT_HANDOFF_STATE_END -->", start)
        state = json.loads(text[start:end].strip())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkflowGuardError("cannot read CURRENT_HANDOFF state") from exc
    if not isinstance(state, dict):
        raise WorkflowGuardError("CURRENT_HANDOFF state must contain an object")
    return state


def _repo_head(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise WorkflowGuardError("cannot read Git HEAD") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise WorkflowGuardError("cannot read Git HEAD")
    return result.stdout.strip()


def _latest_handoff_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "CURRENT_HANDOFF.md"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise WorkflowGuardError("cannot read CURRENT_HANDOFF commit") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise WorkflowGuardError("CURRENT_HANDOFF has no committed binding")
    return result.stdout.strip()

def _commit_is_ancestor(repo_root: Path, commit: str, head: str) -> bool:
    if not isinstance(commit, str) or len(commit) != 40:
        return False
    try:
        int(commit, 16)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, head],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return False
    return result.returncode == 0


def _parse_prompt(prompt: Any) -> dict[str, str]:
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkflowGuardError("managed prompt is missing")
    values: dict[str, str] = {}
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name not in REQUIRED_PROMPT_FIELDS:
            continue
        if name in values:
            raise WorkflowGuardError(f"duplicate prompt field {name}")
        value = value.strip()
        if not value:
            raise WorkflowGuardError(f"empty prompt field {name}")
        values[name] = value
    missing = [name for name in REQUIRED_PROMPT_FIELDS if name not in values]
    if missing:
        raise WorkflowGuardError("prompt metadata missing: " + ", ".join(missing))
    return values


def _parse_utc(value: Any, field_name: str, *, required: bool) -> datetime | None:
    if value is None or value == "" or value == "not recorded":
        if required:
            raise WorkflowGuardError(f"{field_name} is not recorded")
        return None
    if not isinstance(value, str):
        raise WorkflowGuardError(f"{field_name} is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowGuardError(f"{field_name} is malformed") from exc
    if parsed.tzinfo is None:
        raise WorkflowGuardError(f"{field_name} must include UTC")
    return parsed.astimezone(timezone.utc)


def _now_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise WorkflowGuardError("test/current time must include UTC")
    return now.astimezone(timezone.utc)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


@contextmanager
def _counter_lock(lock_path: Path):
    """Serialize one parent counter's admission transaction across processes."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = lock_path.open("a+b")
    except OSError as exc:
        raise WorkflowGuardError("cannot open counter lock") from exc

    acquired = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()

        deadline = time.monotonic() + 2.0
        while not acquired:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise WorkflowGuardError(
                        "counter lock acquisition timed out"
                    ) from exc
                time.sleep(0.01)

        try:
            yield
        finally:
            if acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                finally:
                    acquired = False
    finally:
        stream.close()


def _counter_path(
    repo_root: Path,
    parent_conversation_id: str,
    counter_dir: Path | None,
) -> Path:
    directory = counter_dir
    if directory is None:
        directory = repo_root / ".local-orchestrator" / "agentic-workflow-control"
    else:
        directory = Path(directory)
        if not directory.is_absolute():
            directory = repo_root / directory
    digest = hashlib.sha256(parent_conversation_id.encode("utf-8")).hexdigest()
    return directory / f"{digest}.json"


def _reserve_turn(
    *,
    repo_root: Path,
    parent_conversation_id: str,
    stage_revision: str,
    turn_kind: str,
    policy: Mapping[str, Any],
    counter_dir: Path | None,
) -> None:
    path = _counter_path(repo_root, parent_conversation_id, counter_dir)
    with _counter_lock(path.with_name(f".{path.name}.lock")):
        if path.exists():
            counters = _load_json(path)
        else:
            counters = {
                "schema_version": 1,
                "parent_conversation_id": parent_conversation_id,
                "managed_turns": 0,
                "stage_revisions": [],
                "stages": {},
            }
        if counters.get("schema_version") != 1:
            raise WorkflowGuardError("counter state schema is unsupported")
        if counters.get("parent_conversation_id") != parent_conversation_id:
            raise WorkflowGuardError("counter state belongs to another conversation")
        stage_revisions = counters.get("stage_revisions")
        stages = counters.get("stages")
        if not isinstance(stage_revisions, list) or not isinstance(stages, dict):
            raise WorkflowGuardError("counter state is malformed")
        managed_turns = counters.get("managed_turns")
        if not isinstance(managed_turns, int) or managed_turns < 0:
            raise WorkflowGuardError("counter turn total is malformed")

        limits = policy["limits"]
        conversation_limits = limits["per_parent_conversation"]
        stage_limits = limits["per_stage"]
        max_turns = int(conversation_limits["managed_turns"])
        max_revisions = int(conversation_limits["stage_revisions"])
        turn_limit = int(stage_limits[turn_kind])
        if managed_turns >= max_turns:
            raise WorkflowGuardError("parent-conversation managed-turn limit reached")
        if stage_revision not in stage_revisions and len(stage_revisions) >= max_revisions:
            raise WorkflowGuardError("parent-conversation stage-revision limit reached")

        stage_state = stages.get(stage_revision)
        if stage_state is None:
            stage_state = {"turns": {}}
            stages[stage_revision] = stage_state
            stage_revisions.append(stage_revision)
        if not isinstance(stage_state, dict) or not isinstance(stage_state.get("turns"), dict):
            raise WorkflowGuardError("counter stage state is malformed")
        turn_count = stage_state["turns"].get(turn_kind, 0)
        if not isinstance(turn_count, int) or turn_count < 0:
            raise WorkflowGuardError("counter turn state is malformed")
        if turn_count >= turn_limit:
            raise WorkflowGuardError(f"{turn_kind} turn already consumed for stage")

        stage_state["turns"][turn_kind] = turn_count + 1
        counters["managed_turns"] = managed_turns + 1
        _atomic_write_json(path, counters)


def admit(
    event: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    counter_dir: Path | None = None,
) -> dict[str, str]:
    """Return the supported subagentStart permission response."""

    if not isinstance(event, Mapping):
        return _deny("event must be a JSON object")
    agent_type = _lookup(event, "subagent_type", "agent_type", "subagentType")
    if agent_type not in MANAGED_TYPES:
        return _allow()

    root = Path(repo_root) if repo_root is not None else ROOT
    try:
        policy = _load_json(root / "tasks" / "agentic_workflow_policy.json")
        if policy.get("kind") != "agentic_workflow_control":
            raise WorkflowGuardError("workflow policy kind is unsupported")
        managed_policy = policy["managed_agent_types"].get(agent_type)
        if not isinstance(managed_policy, dict):
            raise WorkflowGuardError("managed agent policy is missing")

        event_name = _lookup(event, "hook_event_name", "event_name", "eventName")
        if event_name is not None and event_name != "subagentStart":
            raise WorkflowGuardError("event is not subagentStart")
        parent_id = _lookup(
            event,
            "parent_conversation_id",
            "parentConversationId",
            "parentConversationID",
            "parent_id",
            "parentId",
            "conversation_id",
            "conversationId",
        )
        model = _lookup(event, "subagent_model", "model", "model_id", "modelId")
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise WorkflowGuardError("parent conversation ID is missing")
        if not isinstance(model, str) or model not in managed_policy["accepted_model_slugs"]:
            raise WorkflowGuardError("model does not match the managed assignment")

        prompt = _lookup(
            event,
            "prompt",
            "subagent_prompt",
            "user_prompt",
            "task",
        )
        prompt_fields = _parse_prompt(prompt)
        handoff = _load_handoff(root)
        required_handoff = (
            "head_binding",
            "control_owner",
            "control_parent_conversation_id",
            "stage_revision",
            "stage_type",
            "product_precondition",
            "failure_class",
            "stage_start_utc",
            "continuation_checkpoint_utc",
            "budgets",
        )
        missing_handoff = [name for name in required_handoff if name not in handoff]
        if missing_handoff:
            raise WorkflowGuardError(
                "handoff metadata missing: " + ", ".join(missing_handoff)
            )
        if handoff["control_owner"] != "sol_parent":
            raise WorkflowGuardError("control owner must be sol_parent")
        control_parent_id = handoff["control_parent_conversation_id"]
        if (
            not isinstance(control_parent_id, str)
            or not control_parent_id
            or control_parent_id.strip() != control_parent_id
        ):
            raise WorkflowGuardError(
                "control parent conversation ID is malformed"
            )
        if parent_id != control_parent_id:
            raise WorkflowGuardError(
                "parent conversation ID disagrees with CURRENT_HANDOFF"
            )
        repo_head = _repo_head(root)
        if not _commit_is_ancestor(root, handoff["head_binding"], repo_head):
            raise WorkflowGuardError(
                "CURRENT_HANDOFF head binding must be a full ancestor commit"
            )
        if _latest_handoff_commit(root) != repo_head:
            raise WorkflowGuardError(
                "CURRENT_HANDOFF was not updated in the current Git head"
            )
        if not isinstance(handoff["stage_revision"], str) or not handoff["stage_revision"]:
            raise WorkflowGuardError("handoff stage revision is missing")
        if not isinstance(handoff["stage_type"], str) or not handoff["stage_type"]:
            raise WorkflowGuardError("handoff stage type is missing")
        if handoff["product_precondition"] not in policy["product_preconditions"]:
            raise WorkflowGuardError("handoff product precondition is unsupported")
        if handoff["failure_class"] not in policy["failure_classes"]:
            raise WorkflowGuardError("handoff failure class is unsupported")
        if not isinstance(handoff["budgets"], dict):
            raise WorkflowGuardError("handoff budgets are malformed")

        expected_fields = {
            "Control-Owner": handoff["control_owner"],
            "Stage-Revision": handoff["stage_revision"],
            "Turn-Kind": None,
            "Product-Precondition": handoff["product_precondition"],
        }
        for name in REQUIRED_PROMPT_FIELDS:
            event_value = _lookup(event, *METADATA_ALIASES[name])
            if event_value is not None and event_value != prompt_fields[name]:
                raise WorkflowGuardError(f"{name} disagrees with prompt metadata")
        if prompt_fields["Control-Owner"] != expected_fields["Control-Owner"]:
            raise WorkflowGuardError("Control-Owner disagrees with CURRENT_HANDOFF")
        if prompt_fields["Stage-Revision"] != expected_fields["Stage-Revision"]:
            raise WorkflowGuardError("Stage-Revision disagrees with CURRENT_HANDOFF")
        if prompt_fields["Product-Precondition"] != expected_fields["Product-Precondition"]:
            raise WorkflowGuardError(
                "Product-Precondition disagrees with CURRENT_HANDOFF"
            )
        if prompt_fields["Turn-Kind"] not in managed_policy["turn_kinds"]:
            raise WorkflowGuardError("Turn-Kind is not allowed for this agent")

        if handoff["product_precondition"] not in {"proven", "not_applicable"}:
            raise WorkflowGuardError(
                "product precondition blocks implementation/review"
            )
        if handoff["failure_class"] == "product_state":
            raise WorkflowGuardError("product-state failure terminates the stage")

        stage_start = _parse_utc(
            handoff["stage_start_utc"], "stage_start_utc", required=True
        )
        checkpoint = _parse_utc(
            handoff["continuation_checkpoint_utc"],
            "continuation_checkpoint_utc",
            required=False,
        )
        user_continuation = _parse_utc(
            handoff.get("user_continuation_utc"),
            "user_continuation_utc",
            required=False,
        )
        current = _now_utc(now)
        if stage_start > current:
            raise WorkflowGuardError("stage start is in the future")
        elapsed_seconds = (current - stage_start).total_seconds()
        timing = policy["timing_minutes"]
        if elapsed_seconds >= int(timing["visible_checkpoint"]) * 60:
            if checkpoint is None or checkpoint <= stage_start or checkpoint > current:
                raise WorkflowGuardError("visible 60-minute checkpoint is required")
        if elapsed_seconds >= int(timing["hard_stop"]) * 60:
            if (
                user_continuation is None
                or user_continuation <= stage_start
                or user_continuation > current
            ):
                raise WorkflowGuardError(
                    "90-minute continuation requires explicit user continuation"
                )

        _reserve_turn(
            repo_root=root,
            parent_conversation_id=parent_id,
            stage_revision=handoff["stage_revision"],
            turn_kind=prompt_fields["Turn-Kind"],
            policy=policy,
            counter_dir=counter_dir,
        )
        return _allow()
    except (KeyError, TypeError, ValueError, WorkflowGuardError) as exc:
        return _deny(str(exc))
    except Exception:
        return _deny("internal workflow policy failure")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = admit(payload)
    except Exception:
        result = _deny("malformed hook input")
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
