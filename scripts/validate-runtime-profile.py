#!/usr/bin/env python3
"""Validate the selected runtime profile and fail closed on asset mismatch."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]+$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_profile_bytes(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("profile_content_sha256", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_manifest(manifest: dict[str, Any], schema_path: Path) -> str:
    schema = load_json(schema_path)
    require(schema.get("$schema", "").startswith("https://json-schema.org/"), "schema identifier missing")
    required = {
        "$schema", "schema_version", "profile_id", "profile_version", "profile_content_sha256",
        "created_at", "runtime", "vm", "graphics", "display", "game", "transport", "startup",
        "account_guard", "compatibility", "rollback", "evidence",
    }
    schema_required = set(schema.get("required", []))
    require(required.issubset(schema_required), "schema does not require every manifest section")
    require(required.issubset(manifest), "manifest required field missing")
    require(manifest["schema_version"] == 1, "unsupported manifest schema_version")
    require(isinstance(manifest["profile_id"], str) and PROFILE_ID_RE.fullmatch(manifest["profile_id"]), "invalid profile_id")
    require(isinstance(manifest["profile_version"], str) and SEMVER_RE.fullmatch(manifest["profile_version"]), "invalid profile_version")
    digest = manifest["profile_content_sha256"]
    require(isinstance(digest, str) and SHA256_RE.fullmatch(digest), "invalid profile_content_sha256")
    calculated = hashlib.sha256(canonical_profile_bytes(manifest)).hexdigest()
    require(digest == calculated, f"profile hash mismatch: expected {calculated}, found {digest}")

    for field in required - {"$schema", "schema_version", "profile_id", "profile_version", "profile_content_sha256", "created_at", "evidence"}:
        require(isinstance(manifest[field], dict) and manifest[field], f"manifest section is empty: {field}")
    require(isinstance(manifest["evidence"], list) and manifest["evidence"], "evidence references missing")
    require(manifest["compatibility"].get("asset_schema_version") == 1, "unsupported asset schema version")
    require(manifest["compatibility"].get("mismatch_action") == "GLOBAL_INPUT_LOCK", "mismatch action is not fail-closed")
    require(manifest["compatibility"].get("missing_metadata_action") == "GLOBAL_INPUT_LOCK", "missing metadata action is not fail-closed")
    require(manifest["game"].get("gameplay_input_enabled") is False, "manifest enables gameplay input")
    require(manifest["account_guard"].get("automatic_gameplay_authorized") is False, "manifest authorizes automatic gameplay")
    require(manifest["startup"].get("normalization", {}).get("max_inputs") == 1, "startup normalization input bound missing")
    require(manifest["startup"].get("normalization", {}).get("positive_source_and_target_required") is True, "startup positive recognition guard missing")
    return calculated


def validate_asset(asset: dict[str, Any], manifest: dict[str, Any]) -> None:
    required = {"asset_id", "asset_schema_version", "profile_id", "profile_content_sha256", "asset_kind"}
    missing = required - asset.keys()
    require(not missing, f"asset metadata missing fields: {', '.join(sorted(missing))}")
    require(asset["asset_schema_version"] == manifest["compatibility"]["asset_schema_version"], "asset schema version mismatch; GLOBAL_INPUT_LOCK")
    require(asset["profile_id"] == manifest["profile_id"], "asset profile_id mismatch; GLOBAL_INPUT_LOCK")
    require(asset["profile_content_sha256"] == manifest["profile_content_sha256"], "asset profile hash mismatch; GLOBAL_INPUT_LOCK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("runtime-profile/manifest.json"))
    parser.add_argument("--schema", type=Path, default=Path("runtime-profile/schema.json"))
    parser.add_argument("--asset", type=Path)
    args = parser.parse_args()
    try:
        manifest = load_json(args.manifest)
        digest = validate_manifest(manifest, args.schema)
        print(f"manifest=valid profile_id={manifest['profile_id']} profile_content_sha256={digest}")
        if args.asset:
            asset = load_json(args.asset)
            validate_asset(asset, manifest)
            print(f"asset=compatible asset_id={asset['asset_id']} input_lock=false")
        else:
            print("asset=not_supplied input_lock=false")
        return 0
    except ValueError as exc:
        print(f"GLOBAL_INPUT_LOCK: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
