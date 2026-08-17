"""Retired compatibility shim for the former receipt-free Daily Claim canary.

The receipt-bound implementation lives in
``scripts.daily_row_claim_bluestacks`` and is reachable through the canonical
``scripts/pnsctl.py development-session daily-row-claim`` command.  This module
intentionally has no runtime, ADB, session, or input-dispatch dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


CANONICAL_COMMAND = (
    "python scripts/pnsctl.py development-session daily-row-claim "
    "--mode canary --max-inputs 1 --delegated-receipt <RECEIPT_DB> "
    "--agent-identity <AGENT_ID> --task-id daily-row-claim "
    "--flow-id DAILY-ROW-CLAIM-BLUESTACKS-INTEGRATION "
    "--scenario selected-daily-aggregate-claim "
    "--variant aggregate-claim-canary"
)


def run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Return a fail-closed compatibility result without touching runtime."""

    return {
        "status": "evidence_required",
        "input_count": 0,
        "resource_affecting_inputs": 0,
        "combat_confirmations": 0,
        "reason": "standalone Daily Claim canary retired; use the canonical pnsctl route",
        "canonical_command": CANONICAL_COMMAND,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retired; use the receipt-bound pnsctl Daily Claim route."
    )
    parser.parse_known_args(argv)
    payload = run()
    print(json.dumps(payload, sort_keys=True))
    print(f"Use: {CANONICAL_COMMAND}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
