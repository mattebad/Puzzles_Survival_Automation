"""Controlled offline native-frame mutations for separated error measurement.

This module derives temporary test images from the project-owned native replay
fixtures.  It never mutates a source fixture, retained evidence, or runtime
state.  Every derivative records its parent fixture, operator, distinct
mutation identity, and non-evidence output path.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

import cv2
import numpy as np

from tasks.native_frame_replay import (
    EXACT_SOURCE_ORDER,
    EXPECTED_CHANNELS,
    EXPECTED_HEIGHT,
    EXPECTED_PROFILE_ID,
    EXPECTED_WIDTH,
    ReplayFrameContext,
    load_replay_manifest,
    replay_native_frames,
)
from tasks.perception_bundle import NativeFrameIdentity
from tasks.semantic_ocr_crop import compute_transport_digest


SCHEMA_NAME = "native_frame_mutation"
SCHEMA_VERSION = 1
DEFAULT_MANIFEST_RELATIVE = Path("tests/fixtures/native_frame_mutation_manifest.json")
OUTPUT_RELATIVE_ROOT = "temporary/native-frame-mutations"
MAX_TRANSLATION_PX = 8

_SHA256_HEX = frozenset("0123456789abcdef")
_FORBIDDEN_OUTPUT_PARTS = frozenset(
    {"evidence", "." + "local-captures", "." + "local-reference"}
)
_CASE_FIELDS = frozenset(
    {
        "mutation_id",
        "parent_capture_ordinal",
        "parent_relative_path",
        "parent_source_sha256",
        "operator",
        "parameters",
        "expected_outcome",
        "output_name",
    }
)


class NativeFrameMutationError(ValueError):
    """Fail-closed mutation, identity, manifest, or metric denial."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


class MutationOperator(str, Enum):
    BRIGHTNESS = "brightness"
    CONTRAST = "contrast"
    BOUNDED_COMPRESSION = "bounded_compression"
    TRANSLATION = "translation"
    PARTIAL_OCCLUSION = "partial_occlusion"
    DISTRACTOR_TEXT = "distractor_text"
    CROP_TRUNCATION = "crop_truncation"
    STALE_FRAME_SUBSTITUTION = "stale_frame_substitution"


class ExpectedOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MutationDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


def _exact_string(value: object, field: str, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value.strip()):
        raise NativeFrameMutationError("INVALID_SCHEMA", field)
    return value


def _exact_int(value: object, field: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise NativeFrameMutationError("INVALID_SCHEMA", field)
    if minimum is not None and value < minimum:
        raise NativeFrameMutationError("INVALID_SCHEMA", field)
    return value


def _exact_number(
    value: object,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise NativeFrameMutationError("INVALID_SCHEMA", field)
    normalized = float(value)
    if minimum is not None and normalized < minimum:
        raise NativeFrameMutationError("INVALID_SCHEMA", field)
    if maximum is not None and normalized > maximum:
        raise NativeFrameMutationError("INVALID_SCHEMA", field)
    return value


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _SHA256_HEX for char in value):
        raise NativeFrameMutationError("INVALID_DIGEST", field)
    return value


def _normalize_relative_path(value: object, field: str) -> str:
    relative = _exact_string(value, field)
    normalized = relative.replace("\\", "/")
    if (
        normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in f"/{normalized}/"
        or any(part == ".." for part in Path(normalized).parts)
    ):
        raise NativeFrameMutationError("PATH_TRAVERSAL", relative)
    return normalized


def _validate_parameters(
    operator: MutationOperator,
    parameters: object,
) -> Mapping[str, object]:
    if type(parameters) is not dict:
        raise NativeFrameMutationError("INVALID_PARAMETERS")
    copied = dict(parameters)
    expected: dict[MutationOperator, frozenset[str]] = {
        MutationOperator.BRIGHTNESS: frozenset({"delta"}),
        MutationOperator.CONTRAST: frozenset({"alpha"}),
        MutationOperator.BOUNDED_COMPRESSION: frozenset({"quality"}),
        MutationOperator.TRANSLATION: frozenset({"dx", "dy"}),
        MutationOperator.PARTIAL_OCCLUSION: frozenset({"x", "y", "width", "height"}),
        MutationOperator.DISTRACTOR_TEXT: frozenset({"text", "x", "y", "scale", "thickness"}),
        MutationOperator.CROP_TRUNCATION: frozenset({"side", "pixels"}),
        MutationOperator.STALE_FRAME_SUBSTITUTION: frozenset({"replacement_capture_ordinal"}),
    }
    if frozenset(copied) != expected[operator]:
        raise NativeFrameMutationError("INVALID_PARAMETERS", operator.value)

    if operator is MutationOperator.BRIGHTNESS:
        delta = _exact_int(copied["delta"], "delta")
        if delta == 0 or not -32 <= delta <= 32:
            raise NativeFrameMutationError("INVALID_PARAMETERS", "delta")
    elif operator is MutationOperator.CONTRAST:
        alpha = _exact_number(copied["alpha"], "alpha", minimum=0.5, maximum=1.5)
        if float(alpha) == 1.0:
            raise NativeFrameMutationError("INVALID_PARAMETERS", "alpha")
    elif operator is MutationOperator.BOUNDED_COMPRESSION:
        _exact_int(copied["quality"], "quality", minimum=40)
        if copied["quality"] > 90:
            raise NativeFrameMutationError("INVALID_PARAMETERS", "quality")
    elif operator is MutationOperator.TRANSLATION:
        dx = _exact_int(copied["dx"], "dx")
        dy = _exact_int(copied["dy"], "dy")
        if (
            abs(dx) > MAX_TRANSLATION_PX
            or abs(dy) > MAX_TRANSLATION_PX
            or (dx == 0 and dy == 0)
        ):
            raise NativeFrameMutationError("TRANSLATION_EXCEEDS_BOUND")
    elif operator is MutationOperator.PARTIAL_OCCLUSION:
        x = _exact_int(copied["x"], "x", minimum=0)
        y = _exact_int(copied["y"], "y", minimum=0)
        width = _exact_int(copied["width"], "width", minimum=1)
        height = _exact_int(copied["height"], "height", minimum=1)
        if x + width > EXPECTED_WIDTH or y + height > EXPECTED_HEIGHT:
            raise NativeFrameMutationError("INVALID_PARAMETERS", "occlusion_bounds")
    elif operator is MutationOperator.DISTRACTOR_TEXT:
        text = _exact_string(copied["text"], "text")
        x = _exact_int(copied["x"], "x", minimum=0)
        y = _exact_int(copied["y"], "y", minimum=1)
        scale = _exact_number(copied["scale"], "scale", minimum=0.5, maximum=2.0)
        thickness = _exact_int(copied["thickness"], "thickness", minimum=1)
        if len(text) > 32 or x >= EXPECTED_WIDTH or y > EXPECTED_HEIGHT or thickness > 4:
            raise NativeFrameMutationError("INVALID_PARAMETERS", "distractor_text")
        if not math.isfinite(float(scale)):
            raise NativeFrameMutationError("INVALID_PARAMETERS", "scale")
    elif operator is MutationOperator.CROP_TRUNCATION:
        if copied["side"] != "bottom":
            raise NativeFrameMutationError("INVALID_PARAMETERS", "side")
        _exact_int(copied["pixels"], "pixels", minimum=1)
        if copied["pixels"] > 160:
            raise NativeFrameMutationError("INVALID_PARAMETERS", "pixels")
    elif operator is MutationOperator.STALE_FRAME_SUBSTITUTION:
        replacement = _exact_int(
            copied["replacement_capture_ordinal"],
            "replacement_capture_ordinal",
            minimum=1,
        )
        if replacement > len(EXACT_SOURCE_ORDER):
            raise NativeFrameMutationError("INVALID_PARAMETERS", "replacement_capture_ordinal")
    return MappingProxyType(copied)


@dataclass(frozen=True)
class MutationCase:
    """One bounded, deterministic mutation declaration."""

    mutation_id: str
    parent_capture_ordinal: int
    parent_relative_path: str
    parent_source_sha256: str
    operator: MutationOperator
    parameters: Mapping[str, object]
    expected_outcome: ExpectedOutcome
    output_name: str

    def __post_init__(self) -> None:
        mutation_id = _exact_string(self.mutation_id, "mutation_id")
        if "/" in mutation_id or "\\" in mutation_id or mutation_id != mutation_id.strip():
            raise NativeFrameMutationError("INVALID_MUTATION_ID")
        ordinal = _exact_int(self.parent_capture_ordinal, "parent_capture_ordinal", minimum=1)
        if ordinal > len(EXACT_SOURCE_ORDER):
            raise NativeFrameMutationError("INVALID_PARENT_ORDINAL")
        relative = _normalize_relative_path(self.parent_relative_path, "parent_relative_path")
        if relative != EXACT_SOURCE_ORDER[ordinal - 1]:
            raise NativeFrameMutationError("PARENT_SOURCE_ORDER_MISMATCH")
        digest = _require_sha256(self.parent_source_sha256, "parent_source_sha256")
        if not isinstance(self.operator, MutationOperator):
            raise NativeFrameMutationError("INVALID_OPERATOR")
        normalized_parameters = _validate_parameters(self.operator, self.parameters)
        if not isinstance(self.expected_outcome, ExpectedOutcome):
            raise NativeFrameMutationError("INVALID_EXPECTED_OUTCOME")
        output_name = _exact_string(self.output_name, "output_name")
        if (
            Path(output_name).name != output_name
            or not output_name.lower().endswith(".png")
            or output_name in {".", ".."}
        ):
            raise NativeFrameMutationError("INVALID_OUTPUT_NAME")
        object.__setattr__(self, "mutation_id", mutation_id)
        object.__setattr__(self, "parent_capture_ordinal", ordinal)
        object.__setattr__(self, "parent_relative_path", relative)
        object.__setattr__(self, "parent_source_sha256", digest)
        object.__setattr__(self, "parameters", normalized_parameters)


@dataclass(frozen=True)
class MutationManifest:
    """Exact mutation manifest; source fixture hashes are revalidated at load time."""

    schema_name: str
    schema_version: int
    parent_manifest_path: str
    parent_fixture_session_id: str
    output_relative_root: str
    max_translation_px: int
    cases: tuple[MutationCase, ...]

    def __post_init__(self) -> None:
        if self.schema_name != SCHEMA_NAME or type(self.schema_name) is not str:
            raise NativeFrameMutationError("UNSUPPORTED_SCHEMA_NAME")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise NativeFrameMutationError("UNSUPPORTED_SCHEMA_VERSION")
        if self.parent_manifest_path != "tests/fixtures/native_frame_replay_manifest.json":
            raise NativeFrameMutationError("INVALID_PARENT_MANIFEST")
        if type(self.parent_fixture_session_id) is not str or not self.parent_fixture_session_id.strip():
            raise NativeFrameMutationError("INVALID_PARENT_SESSION")
        if "live" in self.parent_fixture_session_id.casefold():
            raise NativeFrameMutationError("LIVE_MASQUERADE")
        if self.output_relative_root != OUTPUT_RELATIVE_ROOT:
            raise NativeFrameMutationError("INVALID_OUTPUT_ROOT")
        if type(self.max_translation_px) is not int or self.max_translation_px != MAX_TRANSLATION_PX:
            raise NativeFrameMutationError("INVALID_TRANSLATION_BOUND")
        if type(self.cases) is not tuple or len(self.cases) != len(tuple(MutationOperator)):
            raise NativeFrameMutationError("INVALID_CASE_COUNT")
        ids: set[str] = set()
        operators: set[MutationOperator] = set()
        for case in self.cases:
            if type(case) is not MutationCase:
                raise NativeFrameMutationError("INVALID_CASE")
            if case.mutation_id in ids:
                raise NativeFrameMutationError("DUPLICATE_MUTATION_ID")
            if case.operator in operators:
                raise NativeFrameMutationError("DUPLICATE_OPERATOR")
            ids.add(case.mutation_id)
            operators.add(case.operator)
        if operators != set(MutationOperator):
            raise NativeFrameMutationError("INCOMPLETE_OPERATOR_SET")


@dataclass(frozen=True)
class MutationArtifact:
    """Persistable derivative metadata. Pixel buffers are deliberately absent."""

    mutation_id: str
    operator: MutationOperator
    expected_outcome: ExpectedOutcome
    parent_fixture_session_id: str
    parent_capture_ordinal: int
    parent_relative_path: str
    parent_source_sha256: str
    parent_identity: NativeFrameIdentity
    mutation_identity: NativeFrameIdentity
    claimed_source_frame: NativeFrameIdentity
    storage_path: str
    output_sha256: str
    width: int
    height: int
    channels: int
    identity_status: str
    identity_reason: str

    def __post_init__(self) -> None:
        if type(self.mutation_id) is not str or not self.mutation_id:
            raise NativeFrameMutationError("INVALID_MUTATION_ID")
        if not isinstance(self.operator, MutationOperator):
            raise NativeFrameMutationError("INVALID_OPERATOR")
        if not isinstance(self.expected_outcome, ExpectedOutcome):
            raise NativeFrameMutationError("INVALID_EXPECTED_OUTCOME")
        if not isinstance(self.parent_identity, NativeFrameIdentity):
            raise NativeFrameMutationError("INVALID_PARENT_IDENTITY")
        if not isinstance(self.mutation_identity, NativeFrameIdentity):
            raise NativeFrameMutationError("INVALID_MUTATION_IDENTITY")
        if not isinstance(self.claimed_source_frame, NativeFrameIdentity):
            raise NativeFrameMutationError("INVALID_CLAIMED_IDENTITY")
        if self.parent_identity.capture_kind != "fixture":
            raise NativeFrameMutationError("LIVE_MASQUERADE")
        if self.mutation_identity.capture_kind != "fixture":
            raise NativeFrameMutationError("LIVE_MASQUERADE")
        if (
            type(self.parent_fixture_session_id) is not str
            or not self.parent_fixture_session_id
            or self.parent_identity.runtime_session_id != self.parent_fixture_session_id
        ):
            raise NativeFrameMutationError("PARENT_SESSION_MISMATCH")
        if (
            type(self.parent_capture_ordinal) is not int
            or self.parent_capture_ordinal != self.parent_identity.capture_ordinal
            or type(self.parent_relative_path) is not str
            or type(self.parent_source_sha256) is not str
        ):
            raise NativeFrameMutationError("INVALID_PARENT_IDENTITY")
        _require_sha256(self.parent_source_sha256, "parent_source_sha256")
        if self.parent_identity.width != EXPECTED_WIDTH or self.parent_identity.height != EXPECTED_HEIGHT:
            raise NativeFrameMutationError("INVALID_PARENT_IDENTITY")
        if self.mutation_identity.same_capture_event(self.parent_identity):
            raise NativeFrameMutationError("MUTATION_IDENTITY_NOT_DISTINCT")
        if type(self.storage_path) is not str or not self.storage_path:
            raise NativeFrameMutationError("INVALID_OUTPUT_PATH")
        _validate_non_evidence_path(Path(self.storage_path))
        _require_sha256(self.output_sha256, "output_sha256")
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or self.width != EXPECTED_WIDTH
            or self.height != EXPECTED_HEIGHT
            or type(self.channels) is not int
            or self.channels != EXPECTED_CHANNELS
        ):
            raise NativeFrameMutationError("INVALID_OUTPUT_GEOMETRY")
        if self.identity_status not in {"valid", "rejected"}:
            raise NativeFrameMutationError("INVALID_IDENTITY_STATUS")
        if type(self.identity_reason) is not str or not self.identity_reason:
            raise NativeFrameMutationError("INVALID_IDENTITY_REASON")


@dataclass(frozen=True)
class MutationEvaluation:
    mutation_id: str
    expected_outcome: ExpectedOutcome
    observed_outcome: MutationDecision
    reason_code: str

    def __post_init__(self) -> None:
        _exact_string(self.mutation_id, "mutation_id")
        if not isinstance(self.expected_outcome, ExpectedOutcome):
            raise NativeFrameMutationError("INVALID_EXPECTED_OUTCOME")
        if not isinstance(self.observed_outcome, MutationDecision):
            raise NativeFrameMutationError("INVALID_MUTATION_DECISION")
        _exact_string(self.reason_code, "reason_code")

    @property
    def false_accept(self) -> bool:
        return (
            self.expected_outcome is ExpectedOutcome.REJECTED
            and self.observed_outcome is MutationDecision.ACCEPTED
        )

    @property
    def false_reject(self) -> bool:
        return (
            self.expected_outcome is ExpectedOutcome.ACCEPTED
            and self.observed_outcome is MutationDecision.REJECTED
        )


@dataclass(frozen=True)
class MutationMetrics:
    total_cases: int
    expected_accept_count: int
    expected_reject_count: int
    observed_accept_count: int
    observed_reject_count: int
    false_accept_count: int
    false_reject_count: int
    ambiguous_count: int
    unresolved_count: int

    def __post_init__(self) -> None:
        values = (
            self.total_cases,
            self.expected_accept_count,
            self.expected_reject_count,
            self.observed_accept_count,
            self.observed_reject_count,
            self.false_accept_count,
            self.false_reject_count,
            self.ambiguous_count,
            self.unresolved_count,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise NativeFrameMutationError("INVALID_METRICS")
        if self.expected_accept_count + self.expected_reject_count != self.total_cases:
            raise NativeFrameMutationError("INVALID_METRICS")

    @property
    def false_accept_rate(self) -> float:
        return self.false_accept_count / self.expected_reject_count if self.expected_reject_count else 0.0

    @property
    def false_reject_rate(self) -> float:
        return self.false_reject_count / self.expected_accept_count if self.expected_accept_count else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "ambiguous_count": self.ambiguous_count,
            "expected_accept_count": self.expected_accept_count,
            "expected_reject_count": self.expected_reject_count,
            "false_accept_count": self.false_accept_count,
            "false_accept_rate": self.false_accept_rate,
            "false_reject_count": self.false_reject_count,
            "false_reject_rate": self.false_reject_rate,
            "observed_accept_count": self.observed_accept_count,
            "observed_reject_count": self.observed_reject_count,
            "total_cases": self.total_cases,
            "unresolved_count": self.unresolved_count,
        }


@dataclass(frozen=True)
class MutationCorpusResult:
    manifest: MutationManifest
    artifacts: tuple[MutationArtifact, ...]
    evaluations: tuple[MutationEvaluation, ...]
    metrics: MutationMetrics

    def __post_init__(self) -> None:
        if type(self.artifacts) is not tuple or type(self.evaluations) is not tuple:
            raise NativeFrameMutationError("INVALID_CORPUS_RESULT")
        if len(self.artifacts) != len(self.manifest.cases):
            raise NativeFrameMutationError("INVALID_CORPUS_RESULT")
        if len(self.evaluations) != len(self.manifest.cases):
            raise NativeFrameMutationError("INVALID_CORPUS_RESULT")
        for artifact, evaluation, case in zip(
            self.artifacts,
            self.evaluations,
            self.manifest.cases,
        ):
            if artifact.mutation_id != case.mutation_id or evaluation.mutation_id != case.mutation_id:
                raise NativeFrameMutationError("INVALID_CORPUS_RESULT")
        expected_metrics = measure_mutation_metrics(self.evaluations)
        if expected_metrics != self.metrics:
            raise NativeFrameMutationError("INVALID_METRICS")


MutationClassifier = Callable[
    [MutationCase, np.ndarray, NativeFrameIdentity, NativeFrameIdentity],
    object,
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _validate_non_evidence_path(path: Path) -> None:
    normalized = path.resolve()
    lowered = normalized.as_posix().casefold()
    if any(f"/{part}/" in f"{lowered}/" for part in _FORBIDDEN_OUTPUT_PARTS):
        raise NativeFrameMutationError("FORBIDDEN_OUTPUT_PATH", str(path))


def _validate_output_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    _validate_non_evidence_path(resolved)
    try:
        resolved.relative_to(_repo_root().resolve())
    except ValueError:
        pass
    else:
        raise NativeFrameMutationError("OUTPUT_MUST_BE_TEMPORARY")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def default_manifest_path(*, root: Path | None = None) -> Path:
    return (root or _repo_root()) / DEFAULT_MANIFEST_RELATIVE


def _strict_payload_keys(payload: Mapping[str, object], expected: frozenset[str]) -> None:
    if frozenset(payload) != expected:
        raise NativeFrameMutationError("INVALID_SCHEMA_KEYS")


def load_mutation_manifest(
    path: Path | str | None = None,
    *,
    root: Path | None = None,
) -> MutationManifest:
    """Load the exact mutation manifest and revalidate every parent source hash."""

    repo = root or _repo_root()
    manifest_path = Path(path) if path is not None else default_manifest_path(root=repo)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NativeFrameMutationError("MISSING_MANIFEST", str(manifest_path)) from exc
    except json.JSONDecodeError as exc:
        raise NativeFrameMutationError("MALFORMED_JSON", str(exc)) from exc
    if type(payload) is not dict:
        raise NativeFrameMutationError("MALFORMED_JSON")
    _strict_payload_keys(
        payload,
        frozenset(
            {
                "schema_name",
                "schema_version",
                "parent_manifest_path",
                "parent_fixture_session_id",
                "output_relative_root",
                "max_translation_px",
                "cases",
            }
        ),
    )
    if type(payload["cases"]) is not list:
        raise NativeFrameMutationError("INVALID_CASE_COUNT")
    cases: list[MutationCase] = []
    for item in payload["cases"]:
        if type(item) is not dict:
            raise NativeFrameMutationError("INVALID_CASE")
        _strict_payload_keys(item, _CASE_FIELDS)
        try:
            cases.append(
                MutationCase(
                    mutation_id=item["mutation_id"],
                    parent_capture_ordinal=item["parent_capture_ordinal"],
                    parent_relative_path=item["parent_relative_path"],
                    parent_source_sha256=item["parent_source_sha256"],
                    operator=MutationOperator(item["operator"]),
                    parameters=item["parameters"],
                    expected_outcome=ExpectedOutcome(item["expected_outcome"]),
                    output_name=item["output_name"],
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            if isinstance(exc, NativeFrameMutationError):
                raise
            raise NativeFrameMutationError("INVALID_CASE") from exc
    try:
        manifest = MutationManifest(
            schema_name=payload["schema_name"],
            schema_version=payload["schema_version"],
            parent_manifest_path=payload["parent_manifest_path"],
            parent_fixture_session_id=payload["parent_fixture_session_id"],
            output_relative_root=payload["output_relative_root"],
            max_translation_px=payload["max_translation_px"],
            cases=tuple(cases),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, NativeFrameMutationError):
            raise
        raise NativeFrameMutationError("INVALID_SCHEMA") from exc

    replay_manifest = load_replay_manifest(root=repo)
    if manifest.parent_fixture_session_id != replay_manifest.fixture_session_id:
        raise NativeFrameMutationError("PARENT_SESSION_MISMATCH")
    for case in manifest.cases:
        declaration = replay_manifest.sources[case.parent_capture_ordinal - 1]
        if (
            case.parent_relative_path != declaration.relative_path
            or case.parent_source_sha256 != declaration.source_sha256
        ):
            raise NativeFrameMutationError("PARENT_SOURCE_HASH_MISMATCH", case.mutation_id)
    return manifest


def _derive_mutation_identity(
    parent: NativeFrameIdentity,
    case: MutationCase,
    pixels_bgr: np.ndarray,
) -> NativeFrameIdentity:
    transport = compute_transport_digest(pixels_bgr)
    semantic = sha256(
        f"{parent.semantic_sha256}|{case.mutation_id}|{transport}".encode("ascii")
    ).hexdigest()
    return NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=f"{parent.runtime_session_id}:mutation:{case.mutation_id}",
        capture_ordinal=parent.capture_ordinal,
        capture_completed_monotonic=parent.capture_completed_monotonic,
        transport_sha256=transport,
        semantic_sha256=semantic,
        runtime_profile_id=EXPECTED_PROFILE_ID,
        width=EXPECTED_WIDTH,
        height=EXPECTED_HEIGHT,
        label=f"{parent.label}:{case.mutation_id}",
        evidence_path="",
    )


def _apply_pixels(
    case: MutationCase,
    parent_pixels_bgr: np.ndarray,
    replacement_pixels_bgr: np.ndarray | None = None,
) -> np.ndarray:
    """Apply one bounded operator to an ephemeral BGR frame copy."""

    if (
        not isinstance(parent_pixels_bgr, np.ndarray)
        or parent_pixels_bgr.shape != (EXPECTED_HEIGHT, EXPECTED_WIDTH, 3)
        or parent_pixels_bgr.dtype != np.uint8
    ):
        raise NativeFrameMutationError("INVALID_PARENT_FRAME")
    parameters = case.parameters
    operator = case.operator
    if operator is MutationOperator.BRIGHTNESS:
        return cv2.convertScaleAbs(parent_pixels_bgr, alpha=1.0, beta=int(parameters["delta"]))
    if operator is MutationOperator.CONTRAST:
        return cv2.convertScaleAbs(parent_pixels_bgr, alpha=float(parameters["alpha"]), beta=0)
    if operator is MutationOperator.BOUNDED_COMPRESSION:
        ok, encoded = cv2.imencode(
            ".jpg",
            parent_pixels_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, int(parameters["quality"])],
        )
        if not ok:
            raise NativeFrameMutationError("COMPRESSION_FAILED")
        decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if decoded is None or decoded.shape != parent_pixels_bgr.shape:
            raise NativeFrameMutationError("COMPRESSION_FAILED")
        return np.ascontiguousarray(decoded)
    if operator is MutationOperator.TRANSLATION:
        matrix = np.float32(
            [[1.0, 0.0, int(parameters["dx"])], [0.0, 1.0, int(parameters["dy"])]]
        )
        return cv2.warpAffine(
            parent_pixels_bgr,
            matrix,
            (EXPECTED_WIDTH, EXPECTED_HEIGHT),
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
    if operator is MutationOperator.PARTIAL_OCCLUSION:
        result = np.ascontiguousarray(parent_pixels_bgr.copy())
        x, y = int(parameters["x"]), int(parameters["y"])
        width, height = int(parameters["width"]), int(parameters["height"])
        result[y : y + height, x : x + width] = 0
        return result
    if operator is MutationOperator.DISTRACTOR_TEXT:
        result = np.ascontiguousarray(parent_pixels_bgr.copy())
        cv2.putText(
            result,
            str(parameters["text"]),
            (int(parameters["x"]), int(parameters["y"])),
            cv2.FONT_HERSHEY_SIMPLEX,
            float(parameters["scale"]),
            (0, 0, 255),
            int(parameters["thickness"]),
            lineType=cv2.LINE_AA,
        )
        return result
    if operator is MutationOperator.CROP_TRUNCATION:
        result = np.ascontiguousarray(parent_pixels_bgr.copy())
        result[
            EXPECTED_HEIGHT - int(parameters["pixels"]) : EXPECTED_HEIGHT,
            :,
        ] = 0
        return result
    if operator is MutationOperator.STALE_FRAME_SUBSTITUTION:
        if replacement_pixels_bgr is None:
            raise NativeFrameMutationError("MISSING_REPLACEMENT_FRAME")
        if replacement_pixels_bgr.shape != parent_pixels_bgr.shape:
            raise NativeFrameMutationError("REPLACEMENT_GEOMETRY_MISMATCH")
        return np.ascontiguousarray(replacement_pixels_bgr.copy())
    raise NativeFrameMutationError("UNKNOWN_OPERATOR")


def validate_claimed_identity(frame_bgr: np.ndarray, claimed_identity: NativeFrameIdentity) -> None:
    """Require the supplied pixels to belong to the claimed capture identity."""

    if not isinstance(claimed_identity, NativeFrameIdentity):
        raise NativeFrameMutationError("INVALID_CLAIMED_IDENTITY")
    if claimed_identity.capture_kind != "fixture":
        raise NativeFrameMutationError("LIVE_MASQUERADE")
    if (
        not isinstance(frame_bgr, np.ndarray)
        or frame_bgr.shape != (claimed_identity.height, claimed_identity.width, 3)
        or frame_bgr.dtype != np.uint8
    ):
        raise NativeFrameMutationError("FRAME_GEOMETRY_MISMATCH")
    if compute_transport_digest(frame_bgr) != claimed_identity.transport_sha256:
        raise NativeFrameMutationError("CAPTURE_IDENTITY_MISMATCH")


def _write_mutation_png(path: Path, pixels_bgr: np.ndarray) -> tuple[str, int, int, int]:
    bgra = cv2.cvtColor(pixels_bgr, cv2.COLOR_BGR2BGRA)
    ok, encoded = cv2.imencode(".png", bgra)
    if not ok:
        raise NativeFrameMutationError("OUTPUT_ENCODE_FAILED")
    payload = encoded.tobytes()
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise NativeFrameMutationError("OUTPUT_ALREADY_EXISTS", str(path)) from exc
    except OSError as exc:
        raise NativeFrameMutationError("OUTPUT_WRITE_FAILED", str(path)) from exc
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if (
        decoded is None
        or decoded.ndim != 3
        or decoded.shape != (EXPECTED_HEIGHT, EXPECTED_WIDTH, EXPECTED_CHANNELS)
    ):
        raise NativeFrameMutationError("OUTPUT_GEOMETRY_MISMATCH")
    return sha256(payload).hexdigest(), EXPECTED_WIDTH, EXPECTED_HEIGHT, EXPECTED_CHANNELS


def _decision(value: MutationDecision | str) -> MutationDecision:
    if isinstance(value, MutationDecision):
        return value
    if type(value) is str:
        try:
            return MutationDecision(value)
        except ValueError as exc:
            raise NativeFrameMutationError("INVALID_MUTATION_DECISION") from exc
    raise NativeFrameMutationError("INVALID_MUTATION_DECISION")


def measure_mutation_metrics(
    evaluations: Sequence[MutationEvaluation],
) -> MutationMetrics:
    if not isinstance(evaluations, Sequence):
        raise NativeFrameMutationError("INVALID_EVALUATIONS")
    expected_accept = sum(item.expected_outcome is ExpectedOutcome.ACCEPTED for item in evaluations)
    expected_reject = sum(item.expected_outcome is ExpectedOutcome.REJECTED for item in evaluations)
    observed_accept = sum(item.observed_outcome is MutationDecision.ACCEPTED for item in evaluations)
    observed_reject = sum(item.observed_outcome is MutationDecision.REJECTED for item in evaluations)
    return MutationMetrics(
        total_cases=len(evaluations),
        expected_accept_count=expected_accept,
        expected_reject_count=expected_reject,
        observed_accept_count=observed_accept,
        observed_reject_count=observed_reject,
        false_accept_count=sum(item.false_accept for item in evaluations),
        false_reject_count=sum(item.false_reject for item in evaluations),
        ambiguous_count=sum(item.observed_outcome is MutationDecision.AMBIGUOUS for item in evaluations),
        unresolved_count=sum(item.observed_outcome is MutationDecision.UNRESOLVED for item in evaluations),
    )


def generate_mutation_corpus(
    manifest: MutationManifest | Path | str | None = None,
    *,
    root: Path | None = None,
    output_dir: Path | str,
    classifier: MutationClassifier | None = None,
) -> MutationCorpusResult:
    """Generate temporary derivatives and measure separate accept/reject errors.

    The classifier receives an ephemeral BGR array and must not retain it.  A
    stale substitution is rejected before classification when its pixels do
    not match the claimed parent identity.
    """

    repo = root or _repo_root()
    validated = (
        manifest
        if isinstance(manifest, MutationManifest)
        else load_mutation_manifest(manifest, root=repo)
    )
    validated.__post_init__()
    output_root = _validate_output_directory(Path(output_dir))
    contexts: dict[int, tuple[NativeFrameIdentity, np.ndarray]] = {}

    def collect(context: ReplayFrameContext) -> Mapping[str, str]:
        contexts[context.ordinal] = (context.identity, context.pixels_bgr())
        return {}

    replay_native_frames(root=repo, callback=collect)
    artifacts: list[MutationArtifact] = []
    evaluations: list[MutationEvaluation] = []
    try:
        for case in validated.cases:
            parent_identity, parent_pixels = contexts[case.parent_capture_ordinal]
            replacement_pixels: np.ndarray | None = None
            if case.operator is MutationOperator.STALE_FRAME_SUBSTITUTION:
                replacement_ordinal = int(case.parameters["replacement_capture_ordinal"])
                replacement_pixels = contexts[replacement_ordinal][1]
            pixels = _apply_pixels(case, parent_pixels, replacement_pixels)
            mutation_identity = _derive_mutation_identity(parent_identity, case, pixels)
            claimed_identity = (
                parent_identity
                if case.operator is MutationOperator.STALE_FRAME_SUBSTITUTION
                else mutation_identity
            )
            identity_status = "valid"
            identity_reason = "IDENTITY_VALID"
            try:
                validate_claimed_identity(pixels, claimed_identity)
            except NativeFrameMutationError as exc:
                if case.operator is not MutationOperator.STALE_FRAME_SUBSTITUTION:
                    raise
                identity_status = "rejected"
                identity_reason = exc.reason_code
            output_path = output_root / case.output_name
            output_sha256, width, height, channels = _write_mutation_png(output_path, pixels)
            artifact = MutationArtifact(
                mutation_id=case.mutation_id,
                operator=case.operator,
                expected_outcome=case.expected_outcome,
                parent_fixture_session_id=validated.parent_fixture_session_id,
                parent_capture_ordinal=case.parent_capture_ordinal,
                parent_relative_path=case.parent_relative_path,
                parent_source_sha256=case.parent_source_sha256,
                parent_identity=parent_identity,
                mutation_identity=mutation_identity,
                claimed_source_frame=claimed_identity,
                storage_path=str(output_path),
                output_sha256=output_sha256,
                width=width,
                height=height,
                channels=channels,
                identity_status=identity_status,
                identity_reason=identity_reason,
            )
            if identity_status == "rejected":
                observed = MutationDecision.REJECTED
                reason = identity_reason
            elif classifier is None:
                observed = MutationDecision.UNRESOLVED
                reason = "NO_CLASSIFIER"
            else:
                try:
                    observed = _decision(
                        classifier(case, pixels.copy(), claimed_identity, mutation_identity)
                    )
                    reason = observed.value
                except NativeFrameMutationError:
                    raise
                except Exception as exc:  # noqa: BLE001 - classifier faults are unresolved, never accepted
                    observed = MutationDecision.UNRESOLVED
                    reason = f"CLASSIFIER_EXCEPTION:{type(exc).__name__}"
            artifacts.append(artifact)
            evaluations.append(
                MutationEvaluation(
                    mutation_id=case.mutation_id,
                    expected_outcome=case.expected_outcome,
                    observed_outcome=observed,
                    reason_code=reason,
                )
            )
            del pixels
    finally:
        for _identity, pixels in contexts.values():
            del pixels
        contexts.clear()
    return MutationCorpusResult(
        manifest=validated,
        artifacts=tuple(artifacts),
        evaluations=tuple(evaluations),
        metrics=measure_mutation_metrics(evaluations),
    )


def _json_ready(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_ready(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, np.ndarray):
        raise NativeFrameMutationError("NUMPY_RETAINED")
    return value


def serialize_mutation_result(result: MutationCorpusResult) -> str:
    """Serialize metadata and separated metrics, never generated pixels."""

    if type(result) is not MutationCorpusResult:
        raise NativeFrameMutationError("INVALID_CORPUS_RESULT")
    result.__post_init__()
    return json.dumps(_json_ready(result), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "DEFAULT_MANIFEST_RELATIVE",
    "ExpectedOutcome",
    "MAX_TRANSLATION_PX",
    "MutationArtifact",
    "MutationCase",
    "MutationClassifier",
    "MutationCorpusResult",
    "MutationDecision",
    "MutationEvaluation",
    "MutationManifest",
    "MutationMetrics",
    "MutationOperator",
    "NativeFrameMutationError",
    "OUTPUT_RELATIVE_ROOT",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "default_manifest_path",
    "generate_mutation_corpus",
    "load_mutation_manifest",
    "measure_mutation_metrics",
    "serialize_mutation_result",
    "validate_claimed_identity",
]
