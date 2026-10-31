"""Shared Personal Might Praise identity and daily duplicate key; no runtime authority."""

from __future__ import annotations

import hashlib
import json


FLOW_ID = "PERSONAL-MIGHT-PRAISE-BLUESTACKS-INTEGRATION"
SEMANTIC_ACTION = "PRAISE_PERSONAL_MIGHT_FREE"
SOURCE_STATE = "PERSONAL_MIGHT_RANK"
TARGET_IDENTITY = "personal-might-praise"
CONTROL_CLASS = "PRAISE"
CONSEQUENCE = "praise_zero_cost"
POSTCONDITION = "PERSONAL_MIGHT_PRAISE_RESULT"


def personal_might_daily_key(
    *, runtime_scope: str, account_id: str, server_id: str, reset_id: str,
) -> str:
    """Fence one Praise per fixed runtime/account/server/reset identity and task."""

    identity = {
        "runtime_scope": runtime_scope,
        "account_id": account_id,
        "server_id": server_id,
        "reset_id": reset_id,
        "task_id": FLOW_ID,
    }
    for name, value in identity.items():
        if (
            type(value) is not str
            or not value
            or value != value.strip()
            or any(character.isspace() for character in value)
        ):
            raise ValueError(f"{name} must be a non-empty normalized identity")
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"personal-might-praise:daily:{hashlib.sha256(encoded).hexdigest()}"
