"""Named live-scenario result and budget policy for the MVP Nova canary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


NOVA_CANARY_SCENARIO_ID = "nova_navigation_round_trip_no_praise"


class ScenarioPhase(str, Enum):
    PRE_INPUT = "pre_input"
    EXECUTION = "execution"


class ScenarioOutcome(str, Enum):
    REPLAY_VALIDATED = "replay_validated"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


class ScenarioFailureClass(str, Enum):
    ENVIRONMENT_PREFLIGHT = "environment_preflight"
    SUPERVISED_IDENTITY = "supervised_identity"
    EXECUTABLE_REGISTRATION = "executable_registration"
    ASSET_CONFIGURATION = "asset_configuration"
    RUNTIME_OWNERSHIP = "runtime_ownership"
    CONTRACT_POLICY = "contract_policy"
    INITIAL_RECOGNITION = "initial_recognition"
    SHARED_NORMALIZATION = "shared_normalization"
    SHARED_NAVIGATION = "shared_navigation"
    TASK_NAVIGATION = "task_navigation"
    SCREEN_RECOGNITION = "screen_recognition"
    PRODUCT_POLICY = "product_policy"
    MANUAL_ONLY = "manual_only"
    MISSING_EVIDENCE = "missing_evidence"
    REPOSITORY_INTERFERENCE = "repository_interference"
    CONSEQUENTIAL_PLAN_PROHIBITED = "consequential_plan_prohibited"
    POSTCONDITION = "postcondition"


class ScenarioAttemptError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioAttemptRecord:
    scenario_id: str
    phase: ScenarioPhase
    outcome: ScenarioOutcome
    candidate_commit: str
    input_count: int
    input_class: str
    consumes_execution_budget: bool
    reason: str
    failure_class: ScenarioFailureClass | None = None
    material_condition_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()
    correction_ref: str | None = None
    terminal_ownership_state: str = "clear"
    unresolved_action: bool = False

    def __post_init__(self) -> None:
        if not self.scenario_id.strip() or not self.candidate_commit.strip():
            raise ScenarioAttemptError("scenario and candidate commit are required")
        if self.input_count < 0:
            raise ScenarioAttemptError("input_count cannot be negative")
        if self.input_class not in {"none", "navigation_only", "consequential"}:
            raise ScenarioAttemptError("invalid input_class")
        if self.terminal_ownership_state not in {"clear", "held", "released", "unknown"}:
            raise ScenarioAttemptError("invalid terminal ownership state")
        if self.input_class == "consequential":
            raise ScenarioAttemptError("MVP Nova canary prohibits consequential input")
        if self.phase is ScenarioPhase.PRE_INPUT:
            if self.input_count != 0 or self.input_class != "none":
                raise ScenarioAttemptError("pre-input record cannot contain transport input")
            if self.consumes_execution_budget:
                raise ScenarioAttemptError("pre-input record cannot consume execution budget")
        if self.phase is ScenarioPhase.EXECUTION:
            if self.input_count < 1 or self.input_class != "navigation_only":
                raise ScenarioAttemptError("execution begins with navigation-only transport")
            if not self.consumes_execution_budget:
                raise ScenarioAttemptError("input-bearing execution must consume scenario budget")
        if self.outcome in {
            ScenarioOutcome.BLOCKED,
            ScenarioOutcome.FAILED,
            ScenarioOutcome.UNRESOLVED,
        }:
            if self.failure_class is None or not self.reason.strip():
                raise ScenarioAttemptError("unsuccessful result requires class and reason")
        elif self.failure_class is not None:
            raise ScenarioAttemptError("successful/replay result cannot have failure_class")
        if self.unresolved_action and self.outcome is not ScenarioOutcome.UNRESOLVED:
            raise ScenarioAttemptError("unresolved action requires unresolved outcome")

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phase"] = self.phase.value
        payload["outcome"] = self.outcome.value
        payload["failure_class"] = (
            self.failure_class.value if self.failure_class is not None else None
        )
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


def validate_named_scenario_state(scenario: Mapping[str, Any]) -> None:
    required = {
        "scenario_id",
        "mode",
        "maximum_execution_attempts",
        "execution_attempt_count",
        "attempts",
        "pre_input_results",
        "forbidden_input_classes",
        "status",
    }
    if set(scenario) != required:
        raise ScenarioAttemptError("named scenario schema mismatch")
    if scenario["scenario_id"] != NOVA_CANARY_SCENARIO_ID:
        raise ScenarioAttemptError("unknown MVP named scenario")
    if scenario["mode"] != "navigation_only":
        raise ScenarioAttemptError("MVP canary must be navigation_only")
    maximum = scenario["maximum_execution_attempts"]
    count = scenario["execution_attempt_count"]
    if type(maximum) is not int or maximum != 1:
        raise ScenarioAttemptError("MVP canary requires one execution attempt")
    if type(count) is not int or count < 0 or count > maximum:
        raise ScenarioAttemptError("invalid execution attempt count")
    if not isinstance(scenario["attempts"], list) or count != len(scenario["attempts"]):
        raise ScenarioAttemptError("execution attempt count mismatch")
    if not isinstance(scenario["pre_input_results"], list):
        raise ScenarioAttemptError("pre_input_results must be a list")
    if scenario["forbidden_input_classes"] != ["consequential"]:
        raise ScenarioAttemptError("MVP canary must prohibit consequential input")
    expected_status = "exhausted" if count >= maximum else "ready"
    if scenario["status"] != expected_status:
        raise ScenarioAttemptError("named scenario status disagrees with budget")
    for item in scenario["attempts"]:
        record = scenario_record_from_mapping(item)
        if record.phase is not ScenarioPhase.EXECUTION:
            raise ScenarioAttemptError("attempts must contain execution records")
    for item in scenario["pre_input_results"]:
        record = scenario_record_from_mapping(item)
        if record.phase is not ScenarioPhase.PRE_INPUT:
            raise ScenarioAttemptError("pre_input_results contains execution record")


def scenario_record_from_mapping(payload: Mapping[str, Any]) -> ScenarioAttemptRecord:
    try:
        if type(payload["input_count"]) is not int:
            raise ScenarioAttemptError("input_count must be an integer")
        if type(payload["consumes_execution_budget"]) is not bool:
            raise ScenarioAttemptError("consumes_execution_budget must be boolean")
        if type(payload.get("unresolved_action", False)) is not bool:
            raise ScenarioAttemptError("unresolved_action must be boolean")
        return ScenarioAttemptRecord(
            scenario_id=str(payload["scenario_id"]),
            phase=ScenarioPhase(payload["phase"]),
            outcome=ScenarioOutcome(payload["outcome"]),
            candidate_commit=str(payload["candidate_commit"]),
            input_count=payload["input_count"],
            input_class=str(payload["input_class"]),
            consumes_execution_budget=payload["consumes_execution_budget"],
            reason=str(payload["reason"]),
            failure_class=(
                ScenarioFailureClass(payload["failure_class"])
                if payload.get("failure_class") is not None
                else None
            ),
            material_condition_digest=payload.get("material_condition_digest"),
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
            correction_ref=payload.get("correction_ref"),
            terminal_ownership_state=str(payload.get("terminal_ownership_state", "clear")),
            unresolved_action=payload.get("unresolved_action", False),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioAttemptError("invalid scenario attempt mapping") from exc


def apply_scenario_record(
    scenario: Mapping[str, Any],
    record: ScenarioAttemptRecord,
) -> dict[str, Any]:
    """Return an updated scenario copy; callers own persistence."""

    validate_named_scenario_state(scenario)
    if record.scenario_id != scenario["scenario_id"]:
        raise ScenarioAttemptError("record belongs to another scenario")
    updated = deepcopy(dict(scenario))
    if record.phase is ScenarioPhase.PRE_INPUT:
        updated["pre_input_results"].append(record.to_mapping())
        validate_named_scenario_state(updated)
        return updated

    if updated["execution_attempt_count"] >= updated["maximum_execution_attempts"]:
        raise ScenarioAttemptError("named scenario execution budget exhausted")
    prior = updated["attempts"]
    if prior:
        previous = scenario_record_from_mapping(prior[-1])
        materially_changed = bool(
            record.candidate_commit != previous.candidate_commit
            or (
                record.material_condition_digest
                and record.material_condition_digest != previous.material_condition_digest
            )
        )
        if not record.correction_ref or not materially_changed:
            raise ScenarioAttemptError(
                "live retry requires correction reference and changed candidate or condition"
            )
    updated["attempts"].append(record.to_mapping())
    updated["execution_attempt_count"] += 1
    updated["status"] = (
        "exhausted"
        if updated["execution_attempt_count"] >= updated["maximum_execution_attempts"]
        else "ready"
    )
    validate_named_scenario_state(updated)
    return updated


def replay_validated_record(
    *,
    candidate_commit: str,
    evidence_refs: tuple[str, ...],
) -> ScenarioAttemptRecord:
    return ScenarioAttemptRecord(
        NOVA_CANARY_SCENARIO_ID,
        ScenarioPhase.PRE_INPUT,
        ScenarioOutcome.REPLAY_VALIDATED,
        candidate_commit,
        0,
        "none",
        False,
        "production_path_replay_validated",
        evidence_refs=evidence_refs,
    )
