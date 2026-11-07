"""Canonical reset-scoped Ruins execution through the injected native route."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time as datetime_time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from safe_action_core import (
    ActionClass,
    ActionStatus,
    CentralPolicy,
    Observation,
    PolicyRequest,
    SafeActionExecutor,
    TransportResult,
)
from tasks.ruins_challenge import (
    KNOWN_CHALLENGE_IDENTITIES,
    RUINS_CHALLENGE_DISPATCH_ACTION,
    RUINS_CHALLENGE_RESULT_POSTCONDITION,
    RUINS_CHEST_CLAIM_ACTION,
    RUINS_CHEST_CLAIM_POSTCONDITION,
)
from tasks.runtime_identity import (
    BLUESTACKS_ADB,
    BLUESTACKS_SERIAL,
    VerifiedRuntimeIdentity,
    derive_resource_runtime_identity,
    derive_static_utc_reset,
    resource_fixed_runtime_binding,
)
from tasks.scheduler_task_result import SchedulerIdentity

from .contracts import NormalizedOutcome, NormalizedResult
from .native_execution import NativeRouteBoundary, NativeRouteOutcome, NativeRouteRequest
from .recruitment import recruitment_reset
from .registry import (
    RUINS_FLOW_ID,
    RUINS_MAX_INPUTS,
    RUINS_PRODUCT_ID,
    RUINS_PRODUCT_REVISION,
    RUINS_PROFILE_ID,
    RegisteredDispatchSnapshot,
    canonical_entry,
)


PRODUCT_ID = RUINS_PRODUCT_ID
PRODUCT_REVISION = RUINS_PRODUCT_REVISION
PROFILE_ID = RUINS_PROFILE_ID
MAX_INPUTS = RUINS_MAX_INPUTS
MAX_ACTIONS = 13
MAX_CHEST_CATEGORIES = len(KNOWN_CHALLENGE_IDENTITIES)
REOBSERVE_SECONDS = 3600.0


class RuinsNativePartialResultError(RuntimeError):
    """A canonical native invocation stopped with retained partial accounting."""

    def __init__(self, reason: str, *, partial_result: Mapping[str, Any]):
        super().__init__(reason)
        self.partial_result = dict(partial_result)


class RuinsExecutionHandler:
    """Typed, product-bound dispatch handler; service ownership stays external."""

    selection_only = False
    max_inputs = MAX_INPUTS
    max_actions = MAX_ACTIONS

    def __init__(self, snapshot: RegisteredDispatchSnapshot, execute):
        if not isinstance(snapshot, RegisteredDispatchSnapshot):
            raise TypeError("Ruins execution requires a typed registration")
        if (
            snapshot.flow_id,
            snapshot.product_id,
            snapshot.product_revision,
            snapshot.profile,
        ) != (RUINS_FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID):
            raise ValueError("Ruins registration identity mismatch")
        if not callable(execute):
            raise TypeError("Ruins executor must be callable")
        self.snapshot = snapshot
        self._execute = execute

    def describe(self):
        return canonical_entry(RUINS_FLOW_ID).descriptor

    def eligibility(self, facts, perception=None):
        return bool(
            not facts.gate_failures(self.describe())
            and facts.accepted_product == PRODUCT_ID
            and facts.product_revision == PRODUCT_REVISION
            and facts.registration_status == "REGISTERED"
            and facts.scheduler_eligible is True
            and (perception is None or perception.profile_id == PROFILE_ID)
        )

    revalidate = eligibility

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)

    def plan(self, facts, perception=None):
        return self.recover("RUINS_CANONICAL_RUN_REQUIRED")

    def reconcile(self, plan, perception=None):
        return plan if isinstance(plan, NormalizedResult) else self.recover("RUINS_UNKNOWN_RESULT")

    def recover(self, reason):
        return NormalizedResult(NormalizedOutcome.BLOCKED, reason, verified=False)

    def summarize(self):
        return {"flow_id": RUINS_FLOW_ID, "selection_only": False, "transport_count": 0}


class RuinsCanonicalActionBoundary:
    """Use the borrowed SQLite SafetyStore and canonical SafeActionExecutor."""

    def __init__(
        self,
        context,
        identity: SchedulerIdentity,
        runtime_identity: VerifiedRuntimeIdentity,
        validate_identity: Callable[[], None],
        *,
        monotonic_clock: Callable[[], float],
        utc_clock: Callable[[], float],
        settle_seconds: float,
    ) -> None:
        self.context = context
        self.identity = identity
        self.runtime_identity = runtime_identity
        self.validate_identity = validate_identity
        self.store = context.action_store
        self.session = context.session
        self.runtime = context.runtime
        self.monotonic_clock = monotonic_clock
        self.utc_clock = utc_clock
        self.settle_seconds = settle_seconds
        self.policy = CentralPolicy({PRODUCT_ID})
        self.transport_calls_by_category = {"challenge": 0, "chest": 0}

    @staticmethod
    def _status_spec(spec: Mapping[str, Any]) -> tuple[str, str, str] | None:
        action_key = spec.get("action_key")
        semantic_action = spec.get("semantic_action")
        game_day_id = spec.get("game_day_id")
        if not all(isinstance(value, str) and value.strip() for value in (action_key, semantic_action, game_day_id)):
            return None
        return action_key, semantic_action, game_day_id

    def status(self, spec: Mapping[str, Any]) -> Mapping[str, Any]:
        fields = self._status_spec(spec)
        if fields is None:
            return {"status": "blocked", "reason": "ruins_action_identity_incomplete"}
        action_key, semantic_action, game_day_id = fields
        existing = self.store.get_action_by_key(action_key)
        if existing is None:
            if self.store.action_key_exists(action_key):
                return {"status": "blocked", "reason": "ruins_action_key_store_mismatch"}
            if self.store.has_action_block():
                return {"status": "unknown", "reason": "canonical_unresolved_action"}
            return {"status": "new"}
        expected = {
            "action_key": action_key,
            "task_id": PRODUCT_ID,
            "semantic_action": semantic_action,
            "game_day_id": game_day_id,
            "source_state": spec.get("source_state"),
            "target_identity": spec.get("target_identity"),
            "expected_postcondition": spec.get("expected_postcondition"),
            "consequence": spec.get("consequence"),
            "cost_type": "none",
            "cost_amount": 0.0,
            "quantity": 1,
            "consequential": 1,
        }
        for field, expected_value in expected.items():
            actual = existing.get(field)
            if field == "cost_amount" and type(actual) in (int, float):
                if float(actual) != 0.0:
                    return {"status": "blocked", "reason": "ruins_existing_action_cost_conflict"}
            elif actual != expected_value:
                return {"status": "blocked", "reason": f"ruins_existing_action_{field}_conflict"}
        final_status = existing.get("final_status")
        if final_status == ActionStatus.CONFIRMED.value:
            proof = existing.get("reconciliation_result_json")
            try:
                result = json.loads(proof) if isinstance(proof, str) and proof else {}
            except (TypeError, json.JSONDecodeError):
                return {"status": "blocked", "reason": "ruins_confirmation_record_malformed"}
            return {"status": "confirmed", "result": result}
        if final_status in {"prepared", "input_sent", "unresolved"}:
            return {"status": "unknown", "reason": f"ruins_existing_action_{final_status}"}
        return {"status": "blocked", "reason": f"ruins_existing_action_{final_status or 'unknown'}"}

    def execute(
        self,
        *,
        spec: Mapping[str, Any],
        proposal_capture,
        proposal_observation: Observation,
        capture: Callable[[str], Any],
        observe: Callable[[Any], Observation | None],
        dispatch: Callable[[Any, Observation], None],
        successor: Callable[[Any], str],
        settle_seconds: float,
    ) -> Mapping[str, Any]:
        category = spec.get("category")
        if category not in self.transport_calls_by_category:
            return {"status": "blocked", "reason": "ruins_action_category_invalid", "transport_calls": 0}
        category_calls_before = self.transport_calls_by_category[category]
        action_key = spec["action_key"]
        prior = self.status(spec)
        if prior.get("status") != "new":
            return {**prior, "transport_calls": 0}
        self.validate_identity()
        immediate_capture = capture(f"ruins-{spec['category']}-policy-immediate-before")
        immediate = observe(immediate_capture)
        if (
            not isinstance(immediate, Observation)
            or immediate.frame_sha256 != immediate_capture.sha256
            or immediate.capture_completed_monotonic <= proposal_observation.capture_completed_monotonic
        ):
            return {
                "status": "blocked",
                "reason": "ruins_policy_immediate_observation_not_fresh_or_exact",
                "transport_calls": 0,
            }
        if proposal_observation.frame_sha256 != proposal_capture.sha256:
            return {"status": "blocked", "reason": "ruins_proposal_capture_mismatch", "transport_calls": 0}
        action_id = "ruins-" + hashlib.sha256(
            f"{action_key}:{self.context.invocation_id}".encode("utf-8")
        ).hexdigest()
        semantic_preconditions = spec.get("semantic_preconditions")
        if type(semantic_preconditions) is not tuple or any(type(item) is not str for item in semantic_preconditions):
            return {"status": "blocked", "reason": "ruins_policy_preconditions_malformed", "transport_calls": 0}

        def request(observation: Observation) -> PolicyRequest:
            return PolicyRequest(
                action_id=action_id,
                action_key=action_key,
                task_id=PRODUCT_ID,
                task_mode="supervised_validation",
                semantic_action=spec["semantic_action"],
                expected_runtime_profile_id=PROFILE_ID,
                observation=observation,
                monotonic_now=self.monotonic_clock(),
                observation_max_age_seconds=30.0,
                dispatch_max_age_seconds=30.0,
                lease_owner=self.session.owner,
                lease_valid=self.store.lease_valid_for(self.session.owner, self.utc_clock()),
                unresolved_action=self.store.has_action_block(),
                duplicate_action_key=self.store.action_key_exists(action_key),
                game_day_id=spec["game_day_id"],
                action_class=ActionClass.ZERO_COST_CONSEQUENTIAL,
                action_kind=spec["action_kind"],
                subject=spec["subject"],
                maximum_cost=0,
                free_only=True,
                semantic_preconditions=semantic_preconditions,
                semantic_postconditions=(spec["expected_postcondition"],),
                runtime_session_id=str(self.runtime.session),
            )

        issue_request = request(immediate)
        issued = self.policy.issue_capability(issue_request)
        self.store.audit(PRODUCT_ID, "capability_issued", self.utc_clock(), issued.audit, action_id)
        if not issued.authorized or issued.capability is None:
            return {"status": "blocked", "reason": issued.reason_code, "transport_calls": 0}
        post_captures: list[Any] = []
        post_states: dict[str, bool] = {}
        immediate_capture_returned = False

        def single_immediate(label: str):
            nonlocal immediate_capture_returned
            if not immediate_capture_returned:
                immediate_capture_returned = True
                return immediate_capture
            return capture(label)

        def recognize_after(after) -> str:
            state = successor(after)
            post_captures.append(after)
            post_states[str(after.path)] = state == spec["expected_postcondition"]
            return state

        def settled_successor():
            after = None
            for ordinal in (1, 2):
                if settle_seconds > 0:
                    time.sleep(settle_seconds)
                after = capture(f"ruins-{spec['category']}-settled-{ordinal}")
                if recognize_after(after) == spec["expected_postcondition"]:
                    break
            return after

        def transport(_intent):
            self.validate_identity()
            def dispatch_transport(before):
                self.transport_calls_by_category[category] += 1
                dispatch(before, immediate)

            self.session.run_action(
                action_class="free_action",
                label=action_key,
                capture=single_immediate,
                dispatch=dispatch_transport,
                recognize=recognize_after,
                settled_successor=settled_successor,
                consequence_class=spec["consequence"],
            )
            return TransportResult(True, "RUINS_CANONICAL_DISPATCH")

        def post_observe():
            for captured in post_captures:
                positive = post_states[str(captured.path)]
                yield replace(
                    immediate,
                    frame_sha256=captured.sha256,
                    capture_completed_monotonic=captured.captured_monotonic,
                    source_state=spec["expected_postcondition"] if positive else "UNKNOWN",
                    overlay_state="none_observed" if positive else "unknown",
                    target_identity=None,
                    target_roi=None,
                    recognized=positive,
                    control_class=None,
                    consequence=None,
                    cost_type=None,
                    cost_amount=None,
                    quantity=None,
                    expected_postcondition=None,
                    evidence_refs=(str(captured.path),),
                    critical_roi_hashes=(),
                    ocr_result_frame_sha256=captured.sha256,
                    ocr_result_capture_completed_monotonic=captured.captured_monotonic,
                    target_isolated=False,
                )

        def successor_verified(_intent, observed):
            return bool(
                post_captures
                and observed.frame_sha256 == post_captures[-1].sha256
                and observed.capture_completed_monotonic == post_captures[-1].captured_monotonic
                and post_states[str(post_captures[-1].path)]
            )

        # Keep the original proposal as SafeActionExecutor's base so its
        # immediate recapture is fresh while matching the capability bound above.
        try:
            execution = SafeActionExecutor(
                self.store,
                self.policy,
                self.session.owner,
                self.monotonic_clock,
                transport,
                lambda: immediate,
                post_observe,
                successor_verified,
                wall_clock=self.utc_clock,
                max_pre_dispatch_attempts=1,
            ).execute(request(proposal_observation), issued.capability)
        except Exception as exc:
            calls = self.transport_calls_by_category["challenge"] + self.transport_calls_by_category["chest"]
            exc.partial_result = {
                "status": "unresolved" if calls else "blocked",
                "reason": f"canonical_action_executor_failed:{type(exc).__name__}",
                "ruins_dispatch_count": calls,
                "challenge_transport_calls": self.transport_calls_by_category["challenge"],
                "chest_claim_transport_calls": self.transport_calls_by_category["chest"],
                "unresolved_action": calls > 0,
            }
            raise
        journal = self.store.get_action_by_key(action_key)
        if execution.status is ActionStatus.CONFIRMED:
            status = "confirmed"
        elif execution.status is ActionStatus.UNRESOLVED:
            status = "unresolved"
        else:
            status = "blocked"
        return {
            "status": status,
            "reason": execution.reason,
            "transport_calls": self.transport_calls_by_category[category] - category_calls_before,
            "journal_status": journal.get("final_status") if journal else None,
        }


class RuinsRunner:
    """Device-free service runner using only its injected fixed native boundary."""

    def __init__(
        self,
        native: NativeRouteBoundary | None,
        *,
        output_directory: Path,
        utc_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        settle_seconds: float = 1.0,
    ) -> None:
        self.native = native
        self.output_directory = Path(output_directory)
        self.utc_clock = utc_clock
        self.monotonic_clock = monotonic_clock
        self.settle_seconds = _epoch(settle_seconds, "settle delay")
        if native is not None and (
            native.flow_id,
            native.product_id,
            native.product_revision,
            native.runtime_profile_id,
            native.max_inputs,
            native.max_actions,
        ) != (RUINS_FLOW_ID, PRODUCT_ID, PRODUCT_REVISION, PROFILE_ID, MAX_INPUTS, MAX_ACTIONS):
            raise ValueError("Ruins native binding does not match the fixed route contract")

    def __call__(
        self,
        identity: SchedulerIdentity,
        previous_reset_id: str | None,
        checkpoint: Callable[[], None],
        *,
        runtime_input_lock,
        occurrence_key: str,
    ) -> dict[str, Any]:
        if self.native is None:
            raise RuinsNativePartialResultError(
                "Ruins native route binding is unavailable",
                partial_result={"status": "blocked", "reason": "native_route_unbound", "input_count": 0},
            )
        started = _epoch(self.utc_clock(), "start")
        _scheduler_identity(identity, started)
        binding = resource_fixed_runtime_binding()
        if str(BLUESTACKS_ADB) == "" or not BLUESTACKS_SERIAL:
            raise ValueError("Ruins fixed BlueStacks backend is unavailable")
        evaluated = datetime.fromtimestamp(started, timezone.utc)
        current_day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[evaluated.weekday()]
        backend = derive_resource_runtime_identity(binding, evaluated)
        backend_window = derive_static_utc_reset(evaluated)
        if (
            identity.account_id != backend.account_id
            or identity.server_id != backend.server_id
            or backend.reset_id != backend_window.reset_identity_id
            or backend.reset_start_utc != backend_window.reset_start_text
            or backend.reset_deadline_utc != backend_window.reset_deadline_text
        ):
            raise ValueError("Ruins scheduler and fixed-backend identities do not share one account/server/reset window")

        def validate_identity() -> None:
            now = _epoch(self.utc_clock(), "identity clock")
            current_utc = datetime.fromtimestamp(now, timezone.utc)
            current_backend = derive_resource_runtime_identity(binding, current_utc)
            current_window = derive_static_utc_reset(current_utc)
            if (
                identity.account_id != current_backend.account_id
                or identity.server_id != current_backend.server_id
                or current_backend.runtime_scope != backend.runtime_scope
                or current_backend.account_id != backend.account_id
                or current_backend.server_id != backend.server_id
                or current_backend.runtime_binding_digest != backend.runtime_binding_digest
                or current_backend.reset_id != backend.reset_id
                or current_backend.reset_start_utc != backend.reset_start_utc
                or current_backend.reset_deadline_utc != backend.reset_deadline_utc
                or current_window.reset_identity_id != backend.reset_id
                or current_window.reset_start_text != backend.reset_start_utc
                or current_window.reset_deadline_text != backend.reset_deadline_utc
                or current_backend.expires_utc != backend.expires_utc
                or now > _parse_utc_epoch(backend.expires_utc)
            ):
                raise ValueError("Ruins verified backend reset window changed during the invocation")

        validate_identity()

        def action_executor_factory(context):
            return RuinsCanonicalActionBoundary(
                context,
                identity,
                backend,
                validate_identity,
                monotonic_clock=self.monotonic_clock,
                utc_clock=self.utc_clock,
                settle_seconds=self.settle_seconds,
            )

        request = NativeRouteRequest(
            flow_id=RUINS_FLOW_ID,
            product_id=PRODUCT_ID,
            product_revision=PRODUCT_REVISION,
            runtime_profile_id=PROFILE_ID,
            identity=identity,
            previous_reset_id=previous_reset_id,
            occurrence_key=occurrence_key,
            checkpoint=checkpoint,
            validate_identity=validate_identity,
            runtime_input_lock=runtime_input_lock,
            adb=str(BLUESTACKS_ADB),
            serial=BLUESTACKS_SERIAL,
            output_directory=self.output_directory,
            max_inputs=MAX_INPUTS,
            max_actions=MAX_ACTIONS,
            settle_seconds=self.settle_seconds,
            arguments={
                "account_id": identity.account_id,
                "server_id": identity.server_id,
                "current_day": current_day,
                "runtime_identity": backend,
                "runtime_scope": backend.runtime_scope,
                "action_executor_factory": action_executor_factory,
            },
            utc_clock=self.utc_clock,
        )
        outcome = self.native.run(request)
        if not isinstance(outcome, NativeRouteOutcome) or outcome.flow_id != RUINS_FLOW_ID:
            raise RuinsNativePartialResultError(
                "Ruins native boundary returned the wrong typed route identity",
                partial_result={"status": "blocked", "reason": "native_route_identity_mismatch", "input_count": 0},
            )
        if not isinstance(outcome.native_result, Mapping) or (
            outcome.partial_result is not None and not isinstance(outcome.partial_result, Mapping)
        ):
            raise RuinsNativePartialResultError(
                "Ruins native outcome result fields are not mappings",
                partial_result={"status": "unresolved", "reason": "native_result_malformed", "input_count": 0},
            )
        native_result = dict(outcome.native_result)
        partial = dict(outcome.partial_result or native_result)
        if not outcome.execution_verified:
            partial.update(
                status="unresolved" if outcome.input_count else "blocked",
                reason=outcome.failure or "native_route_accounting_unverified",
                flow_id=RUINS_FLOW_ID,
                product_id=PRODUCT_ID,
                product_revision=PRODUCT_REVISION,
                task_id=PRODUCT_ID,
                input_count=outcome.input_count,
                session_input_count=outcome.session_input_count,
                runtime_input_count=outcome.runtime_input_count,
                accounting_verified=outcome.accounting_verified,
                terminal_home_verified=False,
                effect_reconciliation_required=bool(outcome.input_count),
            )
            partial.setdefault("challenge_transport_calls", 0)
            partial.setdefault("chest_claim_transport_calls", 0)
            partial.setdefault(
                "ruins_dispatch_count",
                partial["challenge_transport_calls"] + partial["chest_claim_transport_calls"],
            )
            partial.setdefault("unresolved_action", bool(outcome.input_count))
            raise RuinsNativePartialResultError(str(partial["reason"]), partial_result=partial)
        validate_identity()
        result = self._normalize_native_result(
            native_result,
            outcome=outcome,
            identity=identity,
            backend=backend,
            started=started,
        )
        result["next_due_at_utc"] = ruins_next_due(result, identity, started)
        return result

    @staticmethod
    def _normalize_native_result(
        native: Mapping[str, Any],
        *,
        outcome: NativeRouteOutcome,
        identity: SchedulerIdentity,
        backend: VerifiedRuntimeIdentity,
        started: float,
    ) -> dict[str, Any]:
        if not isinstance(native, Mapping):
            raise RuinsNativePartialResultError(
                "Ruins native result is not an object",
                partial_result={"status": "unresolved", "input_count": outcome.input_count},
            )
        challenge_calls = native.get("challenge_transport_calls")
        chest_calls = native.get("chest_claim_transport_calls")
        total = native.get("ruins_dispatch_count")
        if (
            type(challenge_calls) is not int or challenge_calls not in (0, 1)
            or type(chest_calls) is not int or not 0 <= chest_calls <= MAX_CHEST_CATEGORIES
            or type(total) is not int or total != challenge_calls + chest_calls
            or total > MAX_ACTIONS
        ):
            raise RuinsNativePartialResultError(
                "Ruins consequential dispatch accounting is inconsistent",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        coverage = native.get("chest_coverage")
        allowed_coverage = {
            "newly claimed",
            "already claimed",
            "locked",
            "unavailable/no reward",
            "unresolved",
        }
        if (
            not isinstance(coverage, Mapping)
            or set(coverage) != set(KNOWN_CHALLENGE_IDENTITIES)
            or any(status not in allowed_coverage for status in coverage.values())
        ):
            raise RuinsNativePartialResultError(
                "Ruins chest coverage does not exactly cover the canonical categories",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        if any(
            type(getattr(outcome, name)) is not int
            or not 0 <= getattr(outcome, name) <= MAX_INPUTS
            for name in ("input_count", "session_input_count", "runtime_input_count")
        ) or (
            outcome.input_count != outcome.session_input_count
            or outcome.input_count != outcome.runtime_input_count
            or outcome.accounting_verified is not True
        ):
            raise RuinsNativePartialResultError(
                "Ruins input accounting is outside the route bounds or inconsistent",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        if native.get("accounting_verified") is not True or native.get("terminal_home_verified") is not True:
            raise RuinsNativePartialResultError(
                str(native.get("reason") or "Ruins terminal Home/accounting proof is missing"),
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        if native.get("scheduler_reset_id") != identity.reset_id or native.get("backend_reset_id") != backend.reset_id:
            raise RuinsNativePartialResultError(
                "Ruins scheduler and verified backend reset identities differ from their sources",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        completed = _epoch(native.get("completed_at_utc"), "completion")
        if completed < started:
            raise RuinsNativePartialResultError(
                "Ruins completion predates its canonical service claim",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        if native.get("status") not in {"completed", "unresolved", "blocked"}:
            raise RuinsNativePartialResultError(
                "Ruins native terminal state is invalid",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        if native.get("actions_completed") != total:
            raise RuinsNativePartialResultError(
                "Ruins route action count differs from consequential dispatch count",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        challenge_participation = native.get("challenge_participation_confirmed")
        challenge_status = native.get("challenge_status")
        if (
            type(challenge_participation) is not bool
            or challenge_status not in {"confirmed", "unavailable", "unknown", "unresolved"}
            or native.get("daily_action_ready") is not challenge_participation
            or (
                challenge_calls == 1
                and challenge_participation
                and native.get("challenge_result") not in {"success", "failure"}
            )
            or (
                native.get("status") == "completed"
                and challenge_status not in {"confirmed", "unavailable"}
            )
        ):
            raise RuinsNativePartialResultError(
                "Ruins challenge participation proof is inconsistent",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        claims = native.get("newly_claimed_chests")
        resource_delta = native.get("resource_delta")
        if (
            not isinstance(claims, list)
            or type(resource_delta) is not int
            or resource_delta < 0
            or any(
                not isinstance(claim, Mapping)
                or claim.get("identity") not in KNOWN_CHALLENGE_IDENTITIES
                or type(claim.get("ruins_medals")) is not int
                or claim["ruins_medals"] <= 0
                or coverage.get(claim.get("identity")) != "newly claimed"
                for claim in claims
            )
            or len({claim["identity"] for claim in claims}) != len(claims)
            or sum(claim["ruins_medals"] for claim in claims) != resource_delta
            or (native.get("status") == "completed" and chest_calls != len(claims))
            or (
                native.get("status") == "completed"
                and any(value == "unresolved" for value in coverage.values())
            )
        ):
            raise RuinsNativePartialResultError(
                "Ruins confirmed chest rewards do not match their consequential dispatches",
                partial_result={**dict(native), "status": "unresolved", "input_count": outcome.input_count},
            )
        result = dict(native)
        result.update(
            status=native["status"],
            flow_id=RUINS_FLOW_ID,
            product_id=PRODUCT_ID,
            product_revision=PRODUCT_REVISION,
            task_id=PRODUCT_ID,
            account_id=identity.account_id,
            server_id=identity.server_id,
            reset_id=identity.reset_id,
            backend_runtime_scope=backend.runtime_scope,
            backend_reset_id=backend.reset_id,
            backend_reset_start_utc=backend.reset_start_utc,
            backend_reset_deadline_utc=backend.reset_deadline_utc,
            backend_runtime_binding_digest=backend.runtime_binding_digest,
            time_basis="utc",
            started_at_utc=started,
            completed_at_utc=completed,
            total_input_count=outcome.input_count,
            input_count=outcome.input_count,
            action_count=total,
            ruins_dispatch_count=total,
            challenge_transport_calls=challenge_calls,
            chest_claim_transport_calls=chest_calls,
            no_work=total == 0,
            accounting_verified=True,
            effect_reconciliation_required=bool(native.get("unresolved_action")),
            identical_retry_denied=bool(native.get("unresolved_action")),
            execution_verified=True,
            invocation_id=outcome.invocation_id,
            session_directory=outcome.session_directory,
        )
        return result


# Name parallels the existing route runners while keeping construction device-free.
Runner = RuinsRunner


def ruins_next_due(result: Mapping[str, Any], identity: SchedulerIdentity, started_at: float) -> float:
    """Normalize reset-complete and partial routes to bounded UTC re-observation."""

    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Ruins due time requires the exact product scheduler identity")
    if (
        result.get("flow_id"),
        result.get("product_id"),
        result.get("product_revision"),
        result.get("task_id"),
        result.get("account_id"),
        result.get("server_id"),
        result.get("reset_id"),
    ) != (
        RUINS_FLOW_ID,
        PRODUCT_ID,
        PRODUCT_REVISION,
        PRODUCT_ID,
        identity.account_id,
        identity.server_id,
        identity.reset_id,
    ):
        raise ValueError("Ruins outcome identity is not exact")
    if result.get("terminal_home_verified") is not True or result.get("accounting_verified") is not True:
        raise ValueError("Ruins next due requires exact current Home and input accounting")
    started = _epoch(started_at, "start")
    completed = _epoch(result.get("completed_at_utc"), "completion")
    if completed < started:
        raise ValueError("Ruins completion predates the service claim")
    reset_date = _scheduler_reset_date(identity.reset_id)
    if reset_date != datetime.fromtimestamp(completed, timezone.utc).date():
        raise ValueError("Ruins scheduler reset does not match the completion UTC day")
    next_reset = datetime.combine(reset_date + timedelta(days=1), datetime_time.min, timezone.utc).timestamp()
    coverage = result.get("chest_coverage")
    coverage_complete = isinstance(coverage, Mapping) and set(coverage) == set(KNOWN_CHALLENGE_IDENTITIES) and all(
        status in {"newly claimed", "already claimed", "locked", "unavailable/no reward"}
        for status in coverage.values()
    )
    challenge_status = result.get("challenge_status")
    challenge_calls = result.get("challenge_transport_calls")
    challenge_reconciled = (
        result.get("challenge_participation_confirmed") is True
        and challenge_status == "confirmed"
    ) or (
        result.get("challenge_participation_confirmed") is False
        and challenge_status == "unavailable"
        and challenge_calls == 0
    )
    fully_reconciled = (
        result.get("status") == "completed"
        and challenge_reconciled
        and coverage_complete
        and not result.get("effect_reconciliation_required")
        and not result.get("identical_retry_denied")
    )
    return next_reset if fully_reconciled else min(next_reset, completed + REOBSERVE_SECONDS)


def _scheduler_identity(identity: SchedulerIdentity, now: float) -> None:
    if not isinstance(identity, SchedulerIdentity) or identity.task_id != PRODUCT_ID:
        raise ValueError("Ruins requires its exact scheduler product identity")
    if identity.reset_id != recruitment_reset(now):
        raise ValueError("Ruins scheduler game-day identity is not current UTC reset")


def _scheduler_reset_date(reset_id: object):
    if not isinstance(reset_id, str) or not reset_id.startswith("game-day-"):
        raise ValueError("Ruins reset id is not a canonical scheduler game-day")
    try:
        return datetime.fromisoformat(reset_id.removeprefix("game-day-")).date()
    except ValueError as exc:
        raise ValueError("Ruins scheduler reset id is malformed") from exc


def _parse_utc_epoch(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("Ruins verified backend expiry is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Ruins verified backend expiry is not timezone-aware")
    return parsed.astimezone(timezone.utc).timestamp()


def _epoch(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"Ruins {label} must be a finite UTC epoch")
    return float(value)


__all__ = [
    "MAX_ACTIONS",
    "MAX_INPUTS",
    "PROFILE_ID",
    "PRODUCT_ID",
    "PRODUCT_REVISION",
    "REOBSERVE_SECONDS",
    "RUINS_FLOW_ID",
    "RuinsCanonicalActionBoundary",
    "RuinsExecutionHandler",
    "RuinsNativePartialResultError",
    "RuinsRunner",
    "Runner",
    "ruins_next_due",
]
