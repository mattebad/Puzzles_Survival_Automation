"""Named live-scenario result and budget policy for the MVP Nova canary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


NOVA_CANARY_SCENARIO_ID = "nova_navigation_round_trip_no_praise"
NOVA_SUPERVISED_PULSE_SCENARIO_ID = "nova_praise_one_free_pulse"
NOVA_CANARY_AUTHORIZED_MAXIMUM_ATTEMPTS = frozenset({1, 2})
NOVA_SUPERVISED_PULSE_AUTHORIZED_MAXIMUM_ATTEMPTS = frozenset({1})
NOVA_CANARY_TEMPLATE_CORRECTION_REF = "GF-MVP-009-nova-radial-template-bind"


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


@dataclass(frozen=True)
class SupervisedNovaPulseScenarioAttemptRecord:
    """Named accounting for supervised Home→Nova→one Praise→Home.

    Permits mixed navigation plus exactly one consequential Praise. Does not weaken
    ScenarioAttemptRecord's consequential ban for the no-Praise canary.
    """

    scenario_id: str
    phase: ScenarioPhase
    outcome: ScenarioOutcome
    candidate_commit: str
    navigation_input_count: int
    praise_transport_calls: int
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
        if self.scenario_id != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
            raise ScenarioAttemptError("supervised pulse record requires nova_praise_one_free_pulse")
        if not self.candidate_commit.strip():
            raise ScenarioAttemptError("scenario and candidate commit are required")
        if self.navigation_input_count < 0 or self.praise_transport_calls < 0:
            raise ScenarioAttemptError("input counts cannot be negative")
        if self.praise_transport_calls > 1:
            raise ScenarioAttemptError("supervised pulse permits at most one consequential Praise")
        if self.input_class not in {
            "none",
            "navigation_only",
            "mixed_navigation_and_one_consequential",
        }:
            raise ScenarioAttemptError("invalid supervised pulse input_class")
        if self.terminal_ownership_state not in {"clear", "held", "released", "unknown"}:
            raise ScenarioAttemptError("invalid terminal ownership state")
        if self.phase is ScenarioPhase.PRE_INPUT:
            if (
                self.navigation_input_count != 0
                or self.praise_transport_calls != 0
                or self.input_class != "none"
            ):
                raise ScenarioAttemptError("pre-input record cannot contain transport input")
            if self.consumes_execution_budget:
                raise ScenarioAttemptError("pre-input record cannot consume execution budget")
        if self.phase is ScenarioPhase.EXECUTION:
            if not self.consumes_execution_budget:
                raise ScenarioAttemptError("input-bearing execution must consume scenario budget")
            if self.outcome is ScenarioOutcome.COMPLETED:
                if (
                    self.navigation_input_count < 1
                    or self.praise_transport_calls != 1
                    or self.input_class != "mixed_navigation_and_one_consequential"
                ):
                    raise ScenarioAttemptError(
                        "completed supervised pulse requires navigation plus exactly one Praise"
                    )
            elif self.praise_transport_calls == 1:
                if self.input_class != "mixed_navigation_and_one_consequential":
                    raise ScenarioAttemptError(
                        "one Praise requires mixed_navigation_and_one_consequential"
                    )
                if self.navigation_input_count < 1:
                    raise ScenarioAttemptError("Praise requires preceding navigation inputs")
            elif self.praise_transport_calls == 0:
                if self.navigation_input_count < 1 or self.input_class != "navigation_only":
                    raise ScenarioAttemptError(
                        "execution without Praise begins with navigation-only transport"
                    )
            else:
                raise ScenarioAttemptError("invalid supervised pulse praise count")
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

    @property
    def input_count(self) -> int:
        return self.navigation_input_count + self.praise_transport_calls

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phase"] = self.phase.value
        payload["outcome"] = self.outcome.value
        payload["failure_class"] = (
            self.failure_class.value if self.failure_class is not None else None
        )
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["input_count"] = self.input_count
        return payload


def supervised_pulse_record_from_mapping(
    payload: Mapping[str, Any],
) -> SupervisedNovaPulseScenarioAttemptRecord:
    try:
        if type(payload["navigation_input_count"]) is not int:
            raise ScenarioAttemptError("navigation_input_count must be an integer")
        if type(payload["praise_transport_calls"]) is not int:
            raise ScenarioAttemptError("praise_transport_calls must be an integer")
        if type(payload["consumes_execution_budget"]) is not bool:
            raise ScenarioAttemptError("consumes_execution_budget must be boolean")
        if type(payload.get("unresolved_action", False)) is not bool:
            raise ScenarioAttemptError("unresolved_action must be boolean")
        return SupervisedNovaPulseScenarioAttemptRecord(
            scenario_id=str(payload["scenario_id"]),
            phase=ScenarioPhase(payload["phase"]),
            outcome=ScenarioOutcome(payload["outcome"]),
            candidate_commit=str(payload["candidate_commit"]),
            navigation_input_count=payload["navigation_input_count"],
            praise_transport_calls=payload["praise_transport_calls"],
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
        raise ScenarioAttemptError("invalid supervised pulse attempt mapping") from exc


def validate_supervised_pulse_scenario_state(scenario: Mapping[str, Any]) -> None:
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
        raise ScenarioAttemptError("supervised pulse scenario schema mismatch")
    if scenario["scenario_id"] != NOVA_SUPERVISED_PULSE_SCENARIO_ID:
        raise ScenarioAttemptError("unknown supervised pulse named scenario")
    if scenario["mode"] != "consequential_supervised":
        raise ScenarioAttemptError("supervised pulse must be consequential_supervised")
    maximum = scenario["maximum_execution_attempts"]
    count = scenario["execution_attempt_count"]
    if (
        type(maximum) is not int
        or maximum not in NOVA_SUPERVISED_PULSE_AUTHORIZED_MAXIMUM_ATTEMPTS
    ):
        raise ScenarioAttemptError("supervised pulse maximum attempts must be 1")
    if type(count) is not int or count < 0 or count > maximum:
        raise ScenarioAttemptError("invalid execution attempt count")
    if not isinstance(scenario["attempts"], list) or count != len(scenario["attempts"]):
        raise ScenarioAttemptError("execution attempt count mismatch")
    if not isinstance(scenario["pre_input_results"], list):
        raise ScenarioAttemptError("pre_input_results must be a list")
    if scenario["forbidden_input_classes"] != []:
        raise ScenarioAttemptError("supervised pulse forbids no input class list other than empty")
    expected_status = "exhausted" if count >= maximum else "ready"
    if scenario["status"] != expected_status:
        raise ScenarioAttemptError("named scenario status disagrees with budget")
    for item in scenario["attempts"]:
        record = supervised_pulse_record_from_mapping(item)
        if record.phase is not ScenarioPhase.EXECUTION:
            raise ScenarioAttemptError("attempts must contain execution records")
    for item in scenario["pre_input_results"]:
        record = supervised_pulse_record_from_mapping(item)
        if record.phase is not ScenarioPhase.PRE_INPUT:
            raise ScenarioAttemptError("pre_input_results contains execution record")


def apply_supervised_pulse_scenario_record(
    scenario: Mapping[str, Any],
    record: SupervisedNovaPulseScenarioAttemptRecord,
) -> dict[str, Any]:
    """Return an updated supervised-pulse scenario copy; callers own persistence."""

    validate_supervised_pulse_scenario_state(scenario)
    if record.scenario_id != scenario["scenario_id"]:
        raise ScenarioAttemptError("record belongs to another scenario")
    updated = deepcopy(dict(scenario))
    if record.phase is ScenarioPhase.PRE_INPUT:
        updated["pre_input_results"].append(record.to_mapping())
        validate_supervised_pulse_scenario_state(updated)
        return updated

    if updated["execution_attempt_count"] >= updated["maximum_execution_attempts"]:
        raise ScenarioAttemptError("named scenario execution budget exhausted")
    updated["attempts"].append(record.to_mapping())
    updated["execution_attempt_count"] += 1
    updated["status"] = (
        "exhausted"
        if updated["execution_attempt_count"] >= updated["maximum_execution_attempts"]
        else "ready"
    )
    validate_supervised_pulse_scenario_state(updated)
    return updated


def empty_supervised_pulse_scenario() -> dict[str, Any]:
    return {
        "scenario_id": NOVA_SUPERVISED_PULSE_SCENARIO_ID,
        "mode": "consequential_supervised",
        "maximum_execution_attempts": 1,
        "execution_attempt_count": 0,
        "attempts": [],
        "pre_input_results": [],
        "forbidden_input_classes": [],
        "status": "ready",
    }


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
    if type(maximum) is not int or maximum not in NOVA_CANARY_AUTHORIZED_MAXIMUM_ATTEMPTS:
        raise ScenarioAttemptError("MVP canary maximum attempts must be 1 or authorized 2")
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
