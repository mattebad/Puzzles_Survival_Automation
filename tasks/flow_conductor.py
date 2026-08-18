"""Executable flow-delivery conductor state and decision logic.

Owns per-flow machine-readable state under ``.local-orchestrator/conductor/``.
Does not dispatch gameplay input itself: live work goes through ``pnsctl``
development-session observe / run-flow. Safety kernel stays in pnsctl.

This module is the **routine delivery driver**. Chat-Heavy Sol/Luna/Terra frozen
manifests are not required for ordinary live reproof of already-contracted
flows; reserve that ceremony for architecture, safety-boundary, or
cross-contract redesign (see ``AGENTS.md`` route matrix).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


CONDUCTOR_STATE_ROOT = Path(".local-orchestrator") / "conductor"
SCHEMA_VERSION = 1


class ConductorDecision(str, Enum):
    CONTINUE = "CONTINUE"
    STEP_BACK = "STEP_BACK"
    ESCALATE = "ESCALATE"
    DONE = "DONE"
    EXTERNAL_BLOCK = "EXTERNAL_BLOCK"
    FRAMING_INCOMPLETE = "FRAMING_INCOMPLETE"


@dataclass(frozen=True)
class FramingChecklist:
    intent_match: bool = False
    no_documented_unsafe_input: bool = False
    no_manual_only_precondition: bool = False
    consequential_actions_enumerated: bool = False
    durable_knowledge_consulted: bool = False

    def complete(self) -> bool:
        return all(
            (
                self.intent_match,
                self.no_documented_unsafe_input,
                self.no_manual_only_precondition,
                self.consequential_actions_enumerated,
                self.durable_knowledge_consulted,
            )
        )


@dataclass
class ConductorState:
    flow_id: str
    schema_version: int = SCHEMA_VERSION
    status: str = "idle"
    furthest_milestone: str = ""
    iterations_since_progress: int = 0
    defect_signatures: list[str] = field(default_factory=list)
    step_backs_spent: int = 0
    framing: dict[str, bool] = field(default_factory=dict)
    last_decision: str = ""
    last_blocker: str = ""
    last_summary: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConductorState":
        return cls(
            flow_id=str(payload["flow_id"]),
            schema_version=int(payload.get("schema_version", SCHEMA_VERSION)),
            status=str(payload.get("status", "idle")),
            furthest_milestone=str(payload.get("furthest_milestone", "")),
            iterations_since_progress=int(payload.get("iterations_since_progress", 0)),
            defect_signatures=list(payload.get("defect_signatures") or []),
            step_backs_spent=int(payload.get("step_backs_spent", 0)),
            framing=dict(payload.get("framing") or {}),
            last_decision=str(payload.get("last_decision", "")),
            last_blocker=str(payload.get("last_blocker", "")),
            last_summary=dict(payload.get("last_summary") or {}),
            evidence_refs=list(payload.get("evidence_refs") or []),
        )


def state_path(flow_id: str, *, root: Path | None = None) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in flow_id)
    base = root if root is not None else CONDUCTOR_STATE_ROOT
    return base / f"{safe}.json"


def load_state(flow_id: str, *, root: Path | None = None) -> ConductorState:
    path = state_path(flow_id, root=root)
    if not path.is_file():
        return ConductorState(flow_id=flow_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ConductorState.from_dict(payload)


def save_state(state: ConductorState, *, root: Path | None = None) -> Path:
    path = state_path(state.flow_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def apply_framing(state: ConductorState, checklist: FramingChecklist) -> ConductorState:
    state.framing = asdict(checklist)
    if checklist.complete():
        state.status = "framed"
        state.last_decision = ConductorDecision.CONTINUE.value
        state.last_blocker = ""
    else:
        state.status = "framing_incomplete"
        state.last_decision = ConductorDecision.FRAMING_INCOMPLETE.value
        state.last_blocker = "framing_checklist_incomplete"
    return state


_EXTERNAL_BLOCKERS = frozenset(
    {
        "manual_only",
        "manual_only_state",
        "captcha",
        "login",
        "account_selection",
        "cash_mall",
        "real_money",
        "product_state",
        "unsupported_product_state",
    }
)
_DONE_STATUSES = frozenset(
    {
        "completed",
        "complete_for_reset",
        "success",
        "done",
    }
)


def classify_summary(
    summary: Mapping[str, Any],
    *,
    state: ConductorState,
) -> tuple[ConductorDecision, str]:
    """Classify a development-session summary into a conductor decision."""

    status = str(summary.get("status") or summary.get("terminal") or "").casefold()
    blocker = str(
        summary.get("blocker")
        or summary.get("reason")
        or summary.get("next_action")
        or ""
    )
    blocker_key = blocker.casefold()

    if status in _DONE_STATUSES or summary.get("terminal_home_verified") is True:
        if summary.get("praise_taps") or summary.get("dispatch") or status in _DONE_STATUSES:
            return ConductorDecision.DONE, blocker or "terminal_postcondition_proven"

    for token in _EXTERNAL_BLOCKERS:
        if token in blocker_key or token == status:
            return ConductorDecision.EXTERNAL_BLOCK, blocker or token

    signature = blocker_key.strip() or status or "unknown_blocker"
    repeats = state.defect_signatures.count(signature)
    if repeats >= 1 or state.iterations_since_progress >= 2:
        if state.step_backs_spent >= 1:
            return ConductorDecision.ESCALATE, signature
        return ConductorDecision.STEP_BACK, signature

    if status in {"blocked", "unresolved", "failed", "blocked_fail_closed"}:
        return ConductorDecision.CONTINUE, signature

    if not status and not blocker:
        return ConductorDecision.CONTINUE, "empty_summary"

    return ConductorDecision.CONTINUE, signature


def record_iteration(
    state: ConductorState,
    *,
    summary: Mapping[str, Any],
    milestone: str | None = None,
    evidence_ref: str | None = None,
) -> ConductorState:
    decision, blocker = classify_summary(summary, state=state)
    state.last_summary = dict(summary)
    state.last_decision = decision.value
    state.last_blocker = blocker
    if evidence_ref:
        state.evidence_refs.append(evidence_ref)

    if decision is ConductorDecision.DONE:
        state.status = "done"
        if milestone:
            state.furthest_milestone = milestone
        state.iterations_since_progress = 0
        return state

    if decision is ConductorDecision.EXTERNAL_BLOCK:
        state.status = "external_block"
        return state

    signature = blocker
    progressed = bool(milestone) and milestone != state.furthest_milestone
    if progressed and milestone:
        state.furthest_milestone = milestone
        state.iterations_since_progress = 0
    else:
        state.iterations_since_progress += 1
    state.defect_signatures.append(signature)

    if decision is ConductorDecision.STEP_BACK:
        state.status = "step_back"
        state.step_backs_spent += 1
    elif decision is ConductorDecision.ESCALATE:
        state.status = "escalated"
    else:
        state.status = "local_defect"
    return state


def framing_plan(flow_id: str) -> dict[str, Any]:
    """Dry-run framing packet the conductor prints before any live input."""

    return {
        "flow_id": flow_id,
        "entrypoint": "pnsctl conduct",
        "live_requires": ["--live", "--yes"],
        "observe_command": [
            "python",
            "scripts/pnsctl.py",
            "development-session",
            "observe",
            "--flow-id",
            flow_id,
        ],
        "run_command": [
            "python",
            "scripts/pnsctl.py",
            "development-session",
            "run-flow",
            flow_id,
            "--live",
            "--yes",
        ],
        "state_path": str(state_path(flow_id)),
        "decisions": [item.value for item in ConductorDecision],
        "note": (
            "Conductor classifies summary.json and writes per-flow state; "
            "it never bypasses pnsctl singleton ownership or input safety."
        ),
    }
