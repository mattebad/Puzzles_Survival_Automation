"""Temporary read-only diagnostics for the two ticket #24 native OCR failures."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from unittest.mock import patch

from ticket24_offline_proof import FORBIDDEN, ROOT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    import cv2
    import pytesseract
    from scripts.bluestacks_native_runtime import captured_native_frame_from_png
    from scripts.home_atlas_bluestacks import identity_from_captured
    from tasks import campaign_auto_battle_vision as campaign
    from tasks import personal_might_vision as might
    from tasks.campaign_auto_battle import CampaignStage

    attempts = []
    popen = subprocess.Popen

    def offline_popen(command, *positional, **kwargs):
        executable = kwargs.get("executable") or (command[0] if isinstance(command, (list, tuple)) else str(command).split()[0])
        if Path(str(executable).strip('"')).stem.casefold() in FORBIDDEN:
            attempts.append(str(executable))
            raise AssertionError("device executable forbidden in read-only native OCR probe")
        return popen(command, *positional, **kwargs)

    receipt = {"commit": os.environ.get("GITHUB_SHA"), "python": platform.python_version(),
               "platform": platform.platform(), "campaign": [], "personal_might": {},
               "forbidden_process_attempts": attempts}
    with patch.object(subprocess, "Popen", offline_popen):
        receipt["tesseract"] = str(pytesseract.get_tesseract_version())
        original_boxes = campaign._ocr_boxes
        box_calls = []

        def traced_boxes(frame, box):
            result = original_boxes(frame, box)
            box_calls.append({"roi": box, "tokens": result})
            return result

        with patch.object(campaign, "_ocr_boxes", traced_boxes):
            for name in ("current-winner-44.png", "current-winner-45.png", "current-winner-46.png", "retained-winner.png", "retained-defeat.png"):
                path = ROOT / "tests/fixtures/campaign_victory" / name
                payload = path.read_bytes()
                box_calls.clear()
                result = campaign.recognize_campaign_frame(cv2.imread(str(path)), CampaignStage(1, 15, 9))
                receipt["campaign"].append({"fixture": name, "png_sha256": hashlib.sha256(payload).hexdigest(),
                                            "observation": asdict(result.observation), "targets": result.targets,
                                            "diagnostics": result.diagnostics, "ocr_boxes": list(box_calls)})

        path = ROOT / "tests/fixtures/personal_might/native-personal-might-rank-20261029.png"
        payload = path.read_bytes()
        captured = captured_native_frame_from_png(payload, path=path, captured_monotonic=time.monotonic())
        identity = identity_from_captured(captured, session_id="offline-native-probe", ordinal=1, label="committed-fixture")
        tokens, labels, thumbs, targets = [], [], [], []
        original_tokens, original_label = might._tokens, might._label_box
        original_thumb, original_target = might._thumb, might._target

        def traced_tokens(frame, roi, **kwargs):
            result = original_tokens(frame, roi, **kwargs)
            tokens.append({"roi": roi, "psm": kwargs.get("psm", 7), "scale": kwargs.get("scale", 2), "tokens": result})
            return result

        def traced_label(frame, roi, expected, **kwargs):
            result = original_label(frame, roi, expected, **kwargs)
            labels.append({"roi": roi, "expected": expected, "box": result})
            return result

        def traced_thumb(frame, rank_y, *, disabled):
            result = original_thumb(frame, rank_y, disabled=disabled)
            thumbs.append({"rank_y": rank_y, "disabled": disabled, "box": result})
            return result

        def traced_target(source, target_identity, box, *evidence):
            result = original_target(source, target_identity, box, *evidence)
            targets.append({"identity": target_identity, "candidate_box": box,
                            "bound_box": None if result is None else result.target_roi})
            return result

        with patch.object(might, "_tokens", traced_tokens), patch.object(might, "_label_box", traced_label), patch.object(might, "_thumb", traced_thumb), patch.object(might, "_target", traced_target):
            result = might.bind_personal_might_praise(captured.frame, source_frame=identity, source_png=payload)
        receipt["personal_might"] = {"fixture": path.name, "png_sha256": hashlib.sha256(payload).hexdigest(),
                                     "bound_box": None if result is None else result.target_roi,
                                     "tokens": tokens, "labels": labels, "thumbs": thumbs, "targets": targets}
    text = json.dumps(receipt, indent=2, default=lambda value: value.value if isinstance(value, Enum) else str(value))
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with args.destination.open("x", encoding="utf-8") as output:
        output.write(text + "\n")
    print(text)
    return 0 if not attempts else 1


if __name__ == "__main__":
    raise SystemExit(main())
