"""Native recruitment binding; no delivery queue or development receipt authority."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from types import SimpleNamespace
import time

from tasks.noahs_tavern_recruit import RecruitTier
from tasks.noahs_tavern_recruit_maintenance import NoahMaintenanceState

from .handlers import RecruitmentMaintenanceSelectionHandler


class RecruitmentExecutionHandler(RecruitmentMaintenanceSelectionHandler):
    """Use existing eligibility, then execute only after the canonical run fence."""

    max_inputs = 12
    max_actions = 3

    def __init__(self, snapshot, execute):
        super().__init__(snapshot)
        self._execute = execute

    def execute_run(self, run, facts, perception=None):
        return self._execute(run, facts)

def recruitment_reset(now: float) -> str:
    # Approved game reset is midnight UTC.
    return f"game-day-{datetime.fromtimestamp(now, timezone.utc).date().isoformat()}"


class RecruitmentRunner:
    """Call the existing native route; construction never connects to a device."""

    def __init__(self, *, adb: str, serial: str, output_directory: Path,
                 maintenance_path: Path, utc_clock=time.time) -> None:
        self.adb = adb
        self.serial = serial
        self.output_directory = output_directory
        self.maintenance_path = maintenance_path
        self.utc_clock = utc_clock

    def __call__(self, identity, previous_reset_id, checkpoint):
        from scripts.noahs_tavern_recruit_bluestacks import run_noahs_tavern_unified_recruitment

        checkpoint()
        args = SimpleNamespace(
            adb=self.adb, serial=self.serial, output_directory=self.output_directory,
            maintenance_path=self.maintenance_path, previous_reset_id=previous_reset_id,
            utc_clock=self.utc_clock, checkpoint=checkpoint, max_inputs=12,
            settle_seconds=1.0,
        )
        return json.loads(run_noahs_tavern_unified_recruitment(args, identity))


def recruitment_next_due(result, identity, started_at: float) -> float:
    """Accept verified Home completion and UTC tier state, never a selector result."""
    if (result.get("status") != "completed"
            or result.get("terminal_home_verified") is not True
            or result.get("effect_reconciliation_required")
            or result.get("identical_retry_denied")
            or result.get("time_basis") != "utc"):
        raise ValueError(str(result.get("reason") or "recruitment outcome not verified"))
    completed = result.get("completed_at_utc")
    if (type(completed) not in (int, float) or not math.isfinite(completed)
            or completed < started_at):
        raise ValueError("recruitment completion clock is invalid")
    state = NoahMaintenanceState.from_json(json.dumps(result.get("maintenance_state")))
    if (state.account_id, state.server_id, state.reset_id) != (
            identity.account_id, identity.server_id, identity.reset_id):
        raise ValueError("recruitment maintenance identity mismatch")
    next_reset = (math.floor(completed / 86400) + 1) * 86400
    deadlines = [next_reset]
    for tier, item in state.tiers.items():
        if tier is RecruitTier.BASIC and state.basic_daily_count >= 5:
            continue
        if item.next_eligible_at is not None and item.next_eligible_at > completed:
            deadlines.append(item.next_eligible_at)
        else:
            # A bounded pass may leave a tier uninspected; re-observe, not claim success
            # for that tier or occupy Tavern while waiting for another pass.
            deadlines.append(completed + 30)
    return min(deadlines)
