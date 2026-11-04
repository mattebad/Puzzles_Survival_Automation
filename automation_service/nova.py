"""Executor-bound Nova pulses using the existing native action boundary."""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
import time

from tasks.nova_praise import NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS, NOVA_POLICY_COOLDOWN_SECONDS
from tasks.nova_praise_pulse import NOVA_TASK_ID
from tasks.runtime_identity import (
    RuntimeIdentityAssurance, VerifiedRuntimeIdentity, derive_fixed_runtime_binding,
)

from .handlers import NovaPraiseSelectionHandler
from .registry import NOVA_MAX_INPUTS
from tasks.profile import ACTIVE_RUNTIME_PROFILE_ID


class NovaExecutionHandler(NovaPraiseSelectionHandler):
    selection_only = False
    max_inputs = NOVA_MAX_INPUTS
    max_actions = 1

    def __init__(self, snapshot, execute):
        super().__init__(snapshot)
        self._execute = execute

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)


class NovaRunner:
    """Construction is device-free; execution reuses the canonical SafetyStore."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path,
                 utc_clock=time.time, monotonic_clock=time.monotonic) -> None:
        self.adb = adb
        self.serial = serial
        self.output_directory = output_directory
        self.utc_clock = utc_clock
        self.monotonic_clock = monotonic_clock
        self.binding = derive_fixed_runtime_binding(
            serial, ACTIVE_RUNTIME_PROFILE_ID, "com.global.ztmslg",
            "primary-login-slot-v1",
        )

    def __call__(self, identity, previous_reset_id, checkpoint):
        from scripts.nova_praise_bluestacks import (
            NovaNativePartialResultError, run_nova_praise_one_free_pulse,
        )

        if identity.task_id != NOVA_TASK_ID:
            raise ValueError("Nova runner requires the nova_praise task identity")
        checkpoint()
        verified = VerifiedRuntimeIdentity(
            runtime_scope=self.binding.runtime_scope,
            account_id=identity.account_id, server_id=identity.server_id,
            reset_id=identity.reset_id,
            assurance=RuntimeIdentityAssurance.SUPERVISED_NAVIGATION_BINDING,
            evidence_refs=(f"runtime-binding:{self.binding.binding_digest}",
                           "identity-source:operator-fixed-login-slot",
                           "identity-source:static-utc-midnight-reset"),
        )
        args = SimpleNamespace(
            adb=self.adb, serial=self.serial, output_directory=self.output_directory,
            owner="automation-service:nova", max_inputs=NOVA_MAX_INPUTS, settle_seconds=1.0,
            checkpoint=checkpoint, utc_clock=self.utc_clock,
            monotonic_clock=self.monotonic_clock,
        )
        result = json.loads(run_nova_praise_one_free_pulse(args, verified))
        if not isinstance(result, dict):
            raise ValueError("Nova native result must be an object")
        result["total_input_count"] = result.get("total_input_count", result.get("transport_calls"))
        result.update(account_id=identity.account_id, server_id=identity.server_id,
                      reset_id=identity.reset_id)
        completed = result.get("completed_at_utc")
        deadline = result.get("next_eligible_at")
        if (result.get("time_basis") != "utc"
                or type(completed) not in (int, float) or not math.isfinite(completed)
                or completed < 0 or "next_eligible_at" not in result
                or ("next_eligible_at_utc" in result
                    and result["next_eligible_at_utc"] != deadline)
                or (deadline is not None and (
                    type(deadline) not in (int, float) or not math.isfinite(deadline)
                    or deadline < 0))):
            reason = "Nova native UTC clock contract is missing or invalid"
            raise NovaNativePartialResultError(
                reason, partial_result=dict(result, status="unresolved", reason=reason,
                                            effect_reconciliation_required=True,
                                            identical_retry_denied=True),
            )
        return result


def nova_next_due(result, identity, started_at: float) -> float:
    """Accept only a verified single Praise or observed no-work with Home return."""
    if (result.get("status") not in {"completed", "deferred", "complete_for_reset"}
            or result.get("terminal_home_verified") is not True
            or result.get("effect_reconciliation_required")
            or result.get("identical_retry_denied")
            or result.get("time_basis") != "utc"):
        raise ValueError(str(result.get("reason") or "Nova outcome not verified"))
    if (result.get("account_id"), result.get("server_id"), result.get("reset_id")) != (
            identity.account_id, identity.server_id, identity.reset_id):
        raise ValueError("Nova result identity mismatch")
    completed = result.get("completed_at_utc")
    if (type(completed) not in (int, float) or not math.isfinite(completed)
            or completed < started_at):
        raise ValueError("Nova completion clock is invalid")
    before, after = result.get("attempts_before"), result.get("attempts_after")
    calls = result.get("praise_transport_calls")
    if type(before) is not int or type(after) is not int or min(before, after) < 0:
        raise ValueError("Nova observed attempt counts are missing")
    if type(calls) is not int or calls not in (0, 1):
        raise ValueError("Nova Praise budget is invalid")
    if calls:
        if (result.get("status") != "completed" or before < 1 or after != before - 1
                or str(result.get("journal_status")).casefold() != "confirmed"):
            raise ValueError("Nova single Praise effect is not verified")
    elif before != after:
        raise ValueError("Nova no-work changed observed attempts")
    if after == 0:
        return (math.floor(completed / 86400) + 1) * 86400
    cooldown = result.get("cooldown_seconds")
    if (type(cooldown) not in (int, float) or not math.isfinite(cooldown)
            or not 0 < cooldown <= NOVA_POLICY_COOLDOWN_SECONDS
            or (calls and cooldown < NOVA_COOLDOWN_MINIMUM_ACCEPTABLE_SECONDS)):
        raise ValueError("Nova cooldown is not verified")
    due = result.get("next_eligible_at")
    if (type(due) not in (int, float) or not math.isfinite(due)
            or due <= started_at or due > completed + NOVA_POLICY_COOLDOWN_SECONDS):
        raise ValueError("Nova UTC cooldown deadline is invalid")
    # A slow Home return may pass the deadline. Re-observe on the next pulse.
    return max(completed, due)
