"""Offline-only Campaign atlas survey-contract collector dry run.

Despite the platform-qualified filename, this preparation command never opens
ADB, BlueStacks, Bliss, a subprocess, or any input transport.
"""

from __future__ import annotations

import argparse
import json

from tasks.campaign_atlas import default_prep_scan_contract, dry_run_campaign_survey


def build_dry_run_payload() -> dict[str, object]:
    report = dry_run_campaign_survey(default_prep_scan_contract())
    return report.to_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("dry-run",),
        help="validate the zero-input evidence gate without collecting frames",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print(json.dumps(build_dry_run_payload(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
