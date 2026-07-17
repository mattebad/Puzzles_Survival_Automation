#!/usr/bin/env python3
"""Inspect one retained native Ruins frame without connecting to or controlling BlueStacks.

This is intentionally an offline adapter.  Live BlueStacks inspection and input for this task
were performed through the Computer Use skill; this utility only makes a saved native frame
available to the project-owned recognizer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.ruins_challenge_vision import recognize_ruins_frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame", type=Path)
    parser.add_argument("--reset-identity", required=True)
    args = parser.parse_args(argv)
    frame = cv2.imread(str(args.frame), cv2.IMREAD_COLOR)
    recognition = recognize_ruins_frame(frame, reset_identity=args.reset_identity)
    observation = recognition.observation
    print(json.dumps({
        "screen_identity": observation.screen_identity,
        "recognized": observation.recognized,
        "points_balance": observation.points_balance,
        "rows": [
            {
                "identity": row.identity,
                "day": row.day_label,
                "availability": row.availability.value,
                "progress": [row.progress_current, row.progress_maximum],
                "control": row.challenge_control.value,
                "chest": row.chest_state.value,
            }
            for row in observation.rows
        ],
        "targets": list(recognition.targets),
        "diagnostics": recognition.diagnostics,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
