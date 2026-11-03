"""Loader for the committed ``tests/fixtures/phase_e_*_observations.json`` fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, TypeVar

_T = TypeVar("_T")


def load_observation(fixture: Path, name: str, cls: Callable[..., _T], tuple_fields: Iterable[str]) -> _T:
    """Build ``cls`` from ``observations[name]``, turning the JSON lists in ``tuple_fields`` into tuples."""
    payload = json.loads(fixture.read_text(encoding="utf-8"))["observations"][name]
    for field in tuple_fields:
        payload[field] = tuple(payload[field])
    return cls(**payload)
