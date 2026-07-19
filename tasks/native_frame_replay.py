"""Deterministic offline native-frame replay harness over project-owned fixtures.

Replays exactly the declared project-owned native PNG sources in manifest order so
perception and semantic OCR seams can be exercised without runtime input. Fixture
identities are always capture_kind=\"fixture\" and never confer live freshness or
live-capture authority. Persisted observations and results never retain numpy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterator, Mapping, Optional, Sequence

import cv2
import numpy as np

from tasks.home_atlas_vision import BLUESTACKS_PROFILE_ID, frame_digest
from tasks.perception_bundle import (
    FramePerceptionBundle,
    ImmutableOcrObservation,
    NativeFrameIdentity,
    bundle_from_identity,
)
from tasks.semantic_ocr_crop import (
    CropRoiRequest,
    NormalizationOp,
    ObservationStatus,
    OcrMode,
    compute_transport_digest,
    run_semantic_ocr,
    to_immutable_ocr_observation,
)


SCHEMA_NAME = "native_frame_replay"
SCHEMA_VERSION = 1

EXPECTED_WIDTH = 800
EXPECTED_HEIGHT = 1280
EXPECTED_CHANNELS = 4
EXPECTED_PROFILE_ID = BLUESTACKS_PROFILE_ID
DEFAULT_MANIFEST_RELATIVE = Path("tests/fixtures/native_frame_replay_manifest.json")

EXACT_SOURCE_ORDER: tuple[str, ...] = (
    "tasks/assets/home_atlas/bluestacks/800x1280/tiles/viewport-001.png",
    "tasks/assets/navigation/800x1280/daily_praise_claim.png",
)
ALLOWED_SOURCE_PATHS = frozenset(EXACT_SOURCE_ORDER)

_FORBIDDEN_PATH_PREFIXES = (
    "evidence/",
    "." + "local-captures/",
    "." + "local-reference/",
)

_SHA256_HEX = frozenset("0123456789abcdef")


class NativeFrameReplayError(ValueError):
    """Fail-closed replay, manifest, identity, or callback denial."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise NativeFrameReplayError("INVALID_DIGEST", field)
    if any(character not in _SHA256_HEX for character in value):
        raise NativeFrameReplayError("INVALID_DIGEST", field)
    return value


def _posix_relative(path: str) -> str:
    return path.replace("\\", "/")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_declared_source_path(relative: str) -> str:
    """Validate a declared relative source path and return its posix form."""

    if not isinstance(relative, str) or not relative.strip():
        raise NativeFrameReplayError("INVALID_SOURCE_PATH", str(relative))
    normalized = _posix_relative(relative.strip()).lstrip("/")
    if (
        not normalized
        or normalized.startswith("../")
        or normalized.endswith("/..")
        or "/../" in f"/{normalized}/"
        or "\\" in relative
    ):
        raise NativeFrameReplayError("PATH_TRAVERSAL", relative)
    candidate = Path(normalized)
    if candidate.is_absolute() or normalized.startswith(("~",)) or candidate.parts[:1] == ("..",):
        raise NativeFrameReplayError("PATH_TRAVERSAL", relative)
    if any(part == ".." for part in candidate.parts):
        raise NativeFrameReplayError("PATH_TRAVERSAL", relative)
    lower = normalized.lower()
    for prefix in _FORBIDDEN_PATH_PREFIXES:
        if lower == prefix.rstrip("/") or lower.startswith(prefix):
            raise NativeFrameReplayError("FORBIDDEN_SOURCE_TREE", relative)
    if normalized not in ALLOWED_SOURCE_PATHS:
        raise NativeFrameReplayError("NON_PROJECT_OWNED_SOURCE", relative)
    return normalized


def _resolve_under_repo(relative: str, *, root: Path | None = None) -> Path:
    repo = root or _repo_root()
    normalized = _normalize_declared_source_path(relative)
    resolved = (repo / normalized).resolve()
    try:
        resolved.relative_to(repo.resolve())
    except ValueError as exc:
        raise NativeFrameReplayError("PATH_TRAVERSAL", relative) from exc
    return resolved


@dataclass(frozen=True)
class ReplaySourceDeclaration:
    """One immutable fixture source declaration from the exact replay manifest.

    ``capture_completed_monotonic`` is fixture-record metadata only. It must be a
    finite, nonnegative number and never grants live freshness authority.
    """

    ordinal: int
    relative_path: str
    source_sha256: str
    width: int
    height: int
    channels: int
    label: str
    capture_completed_monotonic: float

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise NativeFrameReplayError("INVALID_ORDINAL")
        object.__setattr__(
            self,
            "relative_path",
            _normalize_declared_source_path(self.relative_path),
        )
        _require_sha256(self.source_sha256, "source_sha256")
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or self.width != EXPECTED_WIDTH
            or self.height != EXPECTED_HEIGHT
        ):
            raise NativeFrameReplayError("INVALID_DIMENSIONS")
        if type(self.channels) is not int or self.channels != EXPECTED_CHANNELS:
            raise NativeFrameReplayError("INVALID_CHANNELS")
        if not isinstance(self.label, str) or not self.label.strip():
            raise NativeFrameReplayError("INVALID_LABEL")
        monotonic = self.capture_completed_monotonic
        if (
            isinstance(monotonic, bool)
            or type(monotonic) not in (int, float)
        ):
            raise NativeFrameReplayError("INVALID_MONOTONIC")
        try:
            normalized_monotonic = float(monotonic)
        except (OverflowError, ValueError) as exc:
            raise NativeFrameReplayError("INVALID_MONOTONIC") from exc
        if not math.isfinite(normalized_monotonic) or normalized_monotonic < 0:
            raise NativeFrameReplayError("INVALID_MONOTONIC")
        object.__setattr__(
            self,
            "capture_completed_monotonic",
            normalized_monotonic,
        )


@dataclass(frozen=True)
class ReplayManifest:
    """Validated exact-source replay manifest."""

    schema_name: str
    schema_version: int
    runtime_profile_id: str
    capture_kind: str
    fixture_session_id: str
    expected_width: int
    expected_height: int
    expected_channels: int
    sources: tuple[ReplaySourceDeclaration, ...]

    def __post_init__(self) -> None:
        self._validate_structure()

    def _validate_structure(self) -> None:
        if (
            type(self.schema_name) is not str
            or not self.schema_name.strip()
            or self.schema_name != SCHEMA_NAME
        ):
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA_NAME")
        if type(self.schema_version) is not int:
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA", "schema_version")
        if self.schema_version != SCHEMA_VERSION:
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA_VERSION")
        if type(self.runtime_profile_id) is not str or self.runtime_profile_id != EXPECTED_PROFILE_ID:
            raise NativeFrameReplayError("INVALID_PROFILE")
        if type(self.capture_kind) is not str or self.capture_kind != "fixture":
            raise NativeFrameReplayError("LIVE_MASQUERADE", self.capture_kind)
        if (
            type(self.fixture_session_id) is not str
            or not self.fixture_session_id.strip()
        ):
            raise NativeFrameReplayError("MISSING_FIXTURE_SESSION")
        if "live" in self.fixture_session_id.lower():
            raise NativeFrameReplayError("LIVE_MASQUERADE", self.fixture_session_id)
        if (
            type(self.expected_width) is not int
            or type(self.expected_height) is not int
            or type(self.expected_channels) is not int
        ):
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA", "expected_geometry")
        if (
            self.expected_width != EXPECTED_WIDTH
            or self.expected_height != EXPECTED_HEIGHT
            or self.expected_channels != EXPECTED_CHANNELS
        ):
            raise NativeFrameReplayError("INVALID_PROFILE_GEOMETRY")
        if type(self.sources) is not tuple or len(self.sources) != len(EXACT_SOURCE_ORDER):
            raise NativeFrameReplayError("INVALID_SOURCE_COUNT")
        ordinals: set[int] = set()
        paths: set[str] = set()
        for index, source in enumerate(self.sources):
            if type(source) is not ReplaySourceDeclaration:
                raise NativeFrameReplayError("INVALID_SOURCE_DECLARATION")
            if source.relative_path != EXACT_SOURCE_ORDER[index]:
                raise NativeFrameReplayError("MANIFEST_OUT_OF_ORDER", source.relative_path)
            if source.ordinal != index + 1:
                raise NativeFrameReplayError("MANIFEST_OUT_OF_ORDER", f"ordinal:{source.ordinal}")
            if source.ordinal in ordinals:
                raise NativeFrameReplayError("DUPLICATE_ORDINAL", str(source.ordinal))
            if source.relative_path in paths:
                raise NativeFrameReplayError("DUPLICATE_SOURCE", source.relative_path)
            ordinals.add(source.ordinal)
            paths.add(source.relative_path)


@dataclass(frozen=True)
class ReplayFrameObservation:
    """Immutable per-frame replay observation. Never retains pixel buffers."""

    identity: NativeFrameIdentity
    ordinal: int
    relative_path: str
    source_sha256: str
    label: str
    width: int
    height: int
    channels: int
    transport_sha256: str
    semantic_sha256: str
    callback_payload: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        self._validate_structure()

    def _validate_structure(self) -> None:
        if not isinstance(self.identity, NativeFrameIdentity):
            raise NativeFrameReplayError("INVALID_IDENTITY")
        if self.identity.capture_kind != "fixture":
            raise NativeFrameReplayError("LIVE_MASQUERADE")
        if type(self.ordinal) is not int or self.ordinal < 1:
            raise NativeFrameReplayError("INVALID_ORDINAL")
        if self.ordinal != self.identity.capture_ordinal:
            raise NativeFrameReplayError("ORDINAL_MISMATCH")
        if self.ordinal > len(EXACT_SOURCE_ORDER):
            raise NativeFrameReplayError("INVALID_ORDINAL")
        normalized_path = _normalize_declared_source_path(self.relative_path)
        if normalized_path != EXACT_SOURCE_ORDER[self.ordinal - 1]:
            raise NativeFrameReplayError("MANIFEST_OUT_OF_ORDER", normalized_path)
        object.__setattr__(self, "relative_path", normalized_path)
        if not isinstance(self.label, str) or not self.label.strip():
            raise NativeFrameReplayError("INVALID_LABEL")
        if self.label != self.identity.label:
            raise NativeFrameReplayError("LABEL_MISMATCH")
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or self.width != EXPECTED_WIDTH
            or self.height != EXPECTED_HEIGHT
        ):
            raise NativeFrameReplayError("INVALID_DIMENSIONS")
        if type(self.channels) is not int or self.channels != EXPECTED_CHANNELS:
            raise NativeFrameReplayError("INVALID_CHANNELS")
        if self.identity.width != self.width or self.identity.height != self.height:
            raise NativeFrameReplayError("IDENTITY_GEOMETRY_MISMATCH")
        if self.identity.runtime_profile_id != EXPECTED_PROFILE_ID:
            raise NativeFrameReplayError("INVALID_PROFILE")
        _require_sha256(self.source_sha256, "source_sha256")
        _require_sha256(self.transport_sha256, "transport_sha256")
        _require_sha256(self.semantic_sha256, "semantic_sha256")
        if self.transport_sha256 != self.identity.transport_sha256:
            raise NativeFrameReplayError("TRANSPORT_DIGEST_MISMATCH")
        if self.semantic_sha256 != self.identity.semantic_sha256:
            raise NativeFrameReplayError("SEMANTIC_DIGEST_MISMATCH")
        if not isinstance(self.callback_payload, Mapping):
            raise NativeFrameReplayError("INVALID_CALLBACK_PAYLOAD")
        copied = dict(self.callback_payload)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in copied.items()):
            raise NativeFrameReplayError("INVALID_CALLBACK_PAYLOAD")
        if any(_is_numpy_like(value) for value in copied.values()):
            raise NativeFrameReplayError("NUMPY_RETAINED")
        object.__setattr__(self, "callback_payload", MappingProxyType(copied))


@dataclass(frozen=True)
class ReplayResult:
    """Immutable ordered replay result. Never retains pixel buffers."""

    schema_name: str
    schema_version: int
    fixture_session_id: str
    capture_kind: str
    observations: tuple[ReplayFrameObservation, ...]

    def __post_init__(self) -> None:
        self._validate_structure()

    def _validate_structure(self) -> None:
        if (
            type(self.schema_name) is not str
            or not self.schema_name.strip()
            or self.schema_name != SCHEMA_NAME
        ):
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA")
        if type(self.capture_kind) is not str or self.capture_kind != "fixture":
            raise NativeFrameReplayError("LIVE_MASQUERADE")
        if (
            type(self.fixture_session_id) is not str
            or not self.fixture_session_id.strip()
        ):
            raise NativeFrameReplayError("MISSING_FIXTURE_SESSION")
        if "live" in self.fixture_session_id.lower():
            raise NativeFrameReplayError("LIVE_MASQUERADE", self.fixture_session_id)
        if type(self.observations) is not tuple:
            raise NativeFrameReplayError("INVALID_OBSERVATIONS")
        if len(self.observations) != len(EXACT_SOURCE_ORDER):
            raise NativeFrameReplayError("INVALID_SOURCE_COUNT")
        seen_ordinals: set[int] = set()
        seen_identities: list[NativeFrameIdentity] = []
        for index, observation in enumerate(self.observations):
            if type(observation) is not ReplayFrameObservation:
                raise NativeFrameReplayError("INVALID_OBSERVATION")
            if not isinstance(observation.identity, NativeFrameIdentity):
                raise NativeFrameReplayError("INVALID_IDENTITY")
            if observation.identity.capture_kind != "fixture":
                raise NativeFrameReplayError("LIVE_MASQUERADE")
            if any(
                observation.identity.same_capture_event(identity)
                for identity in seen_identities
            ):
                raise NativeFrameReplayError("DUPLICATE_CAPTURE_EVENT")
            if type(observation.ordinal) is int and observation.ordinal in seen_ordinals:
                raise NativeFrameReplayError("DUPLICATE_ORDINAL", str(observation.ordinal))
            observation._validate_structure()
            seen_ordinals.add(observation.ordinal)
            seen_identities.append(observation.identity)
            if observation.ordinal != index + 1:
                raise NativeFrameReplayError("MANIFEST_OUT_OF_ORDER")
            if observation.relative_path != EXACT_SOURCE_ORDER[index]:
                raise NativeFrameReplayError("MANIFEST_OUT_OF_ORDER")
            if observation.identity.runtime_session_id != self.fixture_session_id:
                raise NativeFrameReplayError("SESSION_MISMATCH")
            if any(_is_numpy_like(value) for value in observation.__dict__.values()):
                raise NativeFrameReplayError("NUMPY_RETAINED")


@dataclass(frozen=True)
class ReplayFrameContext:
    """Ephemeral callback context. Pixel accessors return fresh copies only."""

    identity: NativeFrameIdentity
    ordinal: int
    relative_path: str
    source_sha256: str
    label: str
    _pixels_bgr: np.ndarray

    def pixels_bgr(self) -> np.ndarray:
        """Return a fresh BGR copy for immediate processing. Do not retain on records."""

        return np.ascontiguousarray(self._pixels_bgr.copy())


ReplayCallback = Callable[[ReplayFrameContext], Optional[Mapping[str, str]]]


def _is_numpy_like(value: object) -> bool:
    if isinstance(value, np.ndarray):
        return True
    module = getattr(type(value), "__module__", "")
    return module.startswith("numpy")


def _reject_numpy_graph(value: object, *, depth: int = 0) -> None:
    if depth > 8:
        raise NativeFrameReplayError("CALLBACK_PAYLOAD_TOO_DEEP")
    if _is_numpy_like(value):
        raise NativeFrameReplayError("NUMPY_RETAINED")
    if isinstance(value, Mapping):
        for nested in value.values():
            _reject_numpy_graph(nested, depth=depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            _reject_numpy_graph(nested, depth=depth + 1)
        return
    if is_dataclass(value) and not isinstance(value, type):
        _reject_numpy_graph(
            {field.name: getattr(value, field.name) for field in fields(value)},
            depth=depth + 1,
        )


def _json_ready(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_ready(getattr(value, field.name)) for field in fields(value)}
    if _is_numpy_like(value):
        raise NativeFrameReplayError("NUMPY_RETAINED")
    return value


def default_manifest_path(*, root: Path | None = None) -> Path:
    repo = root or _repo_root()
    return repo / DEFAULT_MANIFEST_RELATIVE


def load_replay_manifest(
    path: Path | str | None = None,
    *,
    root: Path | None = None,
) -> ReplayManifest:
    """Parse and validate the exact native-frame replay manifest. Fail closed."""

    repo = root or _repo_root()
    manifest_path = Path(path) if path is not None else default_manifest_path(root=repo)
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NativeFrameReplayError("MISSING_MANIFEST", str(manifest_path)) from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise NativeFrameReplayError("MALFORMED_JSON", str(exc)) from exc
    if not isinstance(payload, dict):
        raise NativeFrameReplayError("MALFORMED_JSON", "root must be object")
    sources_raw = payload.get("sources")
    if not isinstance(sources_raw, list):
        raise NativeFrameReplayError("INVALID_SOURCE_COUNT")
    sources: list[ReplaySourceDeclaration] = []
    for item in sources_raw:
        if not isinstance(item, dict):
            raise NativeFrameReplayError("INVALID_SOURCE_DECLARATION")
        try:
            sources.append(
                ReplaySourceDeclaration(
                    ordinal=item["ordinal"],
                    relative_path=item["relative_path"],
                    source_sha256=item["source_sha256"],
                    width=item["width"],
                    height=item["height"],
                    channels=item["channels"],
                    label=item["label"],
                    capture_completed_monotonic=item["capture_completed_monotonic"],
                )
            )
        except KeyError as exc:
            raise NativeFrameReplayError("INVALID_SOURCE_DECLARATION", str(exc)) from exc
        except TypeError as exc:
            raise NativeFrameReplayError("INVALID_SOURCE_DECLARATION", str(exc)) from exc
    def _require_int(field: str) -> int:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise NativeFrameReplayError("UNSUPPORTED_SCHEMA", field)
        return value

    try:
        return ReplayManifest(
            schema_name=payload.get("schema_name", ""),  # type: ignore[arg-type]
            schema_version=_require_int("schema_version"),
            runtime_profile_id=payload.get("runtime_profile_id", ""),  # type: ignore[arg-type]
            capture_kind=payload.get("capture_kind", ""),  # type: ignore[arg-type]
            fixture_session_id=payload.get("fixture_session_id", ""),  # type: ignore[arg-type]
            expected_width=_require_int("expected_width"),
            expected_height=_require_int("expected_height"),
            expected_channels=_require_int("expected_channels"),
            sources=tuple(sources),
        )
    except NativeFrameReplayError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise NativeFrameReplayError("UNSUPPORTED_SCHEMA", str(exc)) from exc


def deterministic_fixture_session_id(sources: Sequence[ReplaySourceDeclaration]) -> str:
    """Stable fixture session identity bound to ordered source digests and paths."""

    material = "|".join(f"{source.ordinal}:{source.relative_path}:{source.source_sha256}" for source in sources)
    digest = sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"fixture-replay-{digest}"


def assert_fixture_capture_kind(identity: NativeFrameIdentity) -> None:
    """Reject any non-fixture capture kind. Fixtures can never coerce to live."""

    if not isinstance(identity, NativeFrameIdentity):
        raise NativeFrameReplayError("INVALID_IDENTITY")
    if identity.capture_kind != "fixture":
        raise NativeFrameReplayError("LIVE_MASQUERADE", identity.capture_kind)


def reject_live_capture_request(*, requested_capture_kind: str) -> None:
    """APIs that request live capture must fail closed against this harness."""

    if requested_capture_kind != "fixture":
        raise NativeFrameReplayError("LIVE_CAPTURE_REQUESTED", requested_capture_kind)


def reject_fixture_as_live_freshness(identity: NativeFrameIdentity) -> None:
    """Fixture monotonic timestamps never authorize live transport freshness."""

    assert_fixture_capture_kind(identity)
    raise NativeFrameReplayError("FIXTURE_NOT_LIVE_FRESHNESS")


def coerce_identity_capture_kind(
    identity: NativeFrameIdentity,
    *,
    capture_kind: str,
) -> NativeFrameIdentity:
    """Refuse live labeling/coercion of fixture identities."""

    assert_fixture_capture_kind(identity)
    if capture_kind != "fixture":
        raise NativeFrameReplayError("LIVE_MASQUERADE", capture_kind)
    return identity


def build_fixture_identity(
    declaration: ReplaySourceDeclaration,
    *,
    fixture_session_id: str,
    transport_sha256: str,
    semantic_sha256: str,
) -> NativeFrameIdentity:
    """Build an explicit fixture NativeFrameIdentity for one declared source."""

    if "live" in fixture_session_id.lower():
        raise NativeFrameReplayError("LIVE_MASQUERADE", fixture_session_id)
    identity = NativeFrameIdentity(
        capture_kind="fixture",
        runtime_session_id=fixture_session_id,
        capture_ordinal=declaration.ordinal,
        capture_completed_monotonic=declaration.capture_completed_monotonic,
        transport_sha256=_require_sha256(transport_sha256, "transport_sha256"),
        semantic_sha256=_require_sha256(semantic_sha256, "semantic_sha256"),
        runtime_profile_id=EXPECTED_PROFILE_ID,
        width=declaration.width,
        height=declaration.height,
        label=declaration.label,
        evidence_path="",
    )
    assert_fixture_capture_kind(identity)
    return identity


def _load_validated_source(
    declaration: ReplaySourceDeclaration,
    *,
    root: Path | None = None,
) -> tuple[bytes, np.ndarray, np.ndarray]:
    path = _resolve_under_repo(declaration.relative_path, root=root)
    if not path.is_file():
        raise NativeFrameReplayError("MISSING_SOURCE", declaration.relative_path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise NativeFrameReplayError("MISSING_SOURCE", declaration.relative_path) from exc
    digest = sha256(payload).hexdigest()
    if digest != declaration.source_sha256:
        raise NativeFrameReplayError("SOURCE_HASH_MISMATCH", declaration.relative_path)
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise NativeFrameReplayError("UNSUPPORTED_FORMAT", declaration.relative_path)
    if decoded.ndim != 3 or decoded.shape[2] != EXPECTED_CHANNELS:
        raise NativeFrameReplayError("INVALID_CHANNELS", declaration.relative_path)
    height, width = int(decoded.shape[0]), int(decoded.shape[1])
    if width != declaration.width or height != declaration.height:
        raise NativeFrameReplayError("INVALID_DIMENSIONS", declaration.relative_path)
    if width != EXPECTED_WIDTH or height != EXPECTED_HEIGHT:
        raise NativeFrameReplayError("INVALID_DIMENSIONS", declaration.relative_path)
    bgr = cv2.cvtColor(decoded, cv2.COLOR_BGRA2BGR)
    if bgr.shape != (EXPECTED_HEIGHT, EXPECTED_WIDTH, 3):
        raise NativeFrameReplayError("INVALID_DIMENSIONS", declaration.relative_path)
    return payload, decoded, bgr


def _digests_for_decoded_bgr(bgr: np.ndarray, source_sha256: str) -> tuple[str, str]:
    """Dual digests: transport from decoded BGR pixels; semantic bound to source file hash."""

    transport = compute_transport_digest(bgr)
    # Keep digests dual and OCR-compatible: transport matches decode pixels;
    # semantic remains distinct and bound to the validated on-disk source digest.
    semantic = sha256(f"{source_sha256}:{transport}:semantic".encode("ascii")).hexdigest()
    if transport == semantic:
        raise NativeFrameReplayError("DIGEST_COLLISION")
    # Sanity: semantic path also differs from frame_digest when equal to transport.
    _ = frame_digest(bgr)
    return transport, semantic


def serialize_replay_result(result: ReplayResult) -> str:
    """Deterministic JSON serialization of an immutable replay result."""

    if not isinstance(result, ReplayResult):
        raise NativeFrameReplayError("INVALID_RESULT")
    result._validate_structure()
    payload = _json_ready(result)
    if not isinstance(payload, dict):
        raise NativeFrameReplayError("INVALID_RESULT")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def replay_native_frames(
    manifest: ReplayManifest | Path | str | None = None,
    *,
    root: Path | None = None,
    callback: ReplayCallback | None = None,
) -> ReplayResult:
    """Replay exactly the declared sources in manifest order.

    Ephemeral decode arrays exist only during per-frame processing and are never
    retained on returned observations or results.
    """

    repo = root or _repo_root()
    if isinstance(manifest, ReplayManifest):
        validated = manifest
        validated._validate_structure()
    else:
        validated = load_replay_manifest(manifest, root=repo)
    expected_session = deterministic_fixture_session_id(validated.sources)
    if validated.fixture_session_id != expected_session:
        raise NativeFrameReplayError("FIXTURE_SESSION_MISMATCH", validated.fixture_session_id)

    observations: list[ReplayFrameObservation] = []
    for declaration in validated.sources:
        _payload, _rgba, bgr = _load_validated_source(declaration, root=repo)
        transport, semantic = _digests_for_decoded_bgr(bgr, declaration.source_sha256)
        identity = build_fixture_identity(
            declaration,
            fixture_session_id=validated.fixture_session_id,
            transport_sha256=transport,
            semantic_sha256=semantic,
        )
        context = ReplayFrameContext(
            identity=identity,
            ordinal=declaration.ordinal,
            relative_path=declaration.relative_path,
            source_sha256=declaration.source_sha256,
            label=declaration.label,
            _pixels_bgr=bgr,
        )
        payload_map: Mapping[str, str] = MappingProxyType({})
        if callback is not None:
            try:
                callback_result = callback(context)
            except NativeFrameReplayError:
                raise
            except Exception as exc:  # noqa: BLE001 - fail closed on any callback fault
                raise NativeFrameReplayError("CALLBACK_EXCEPTION", type(exc).__name__) from exc
            if callback_result is not None:
                _reject_numpy_graph(callback_result)
                if not isinstance(callback_result, Mapping):
                    raise NativeFrameReplayError("INVALID_CALLBACK_PAYLOAD")
                copied = dict(callback_result)
                if any(
                    not isinstance(key, str) or not isinstance(value, str)
                    for key, value in copied.items()
                ):
                    raise NativeFrameReplayError("INVALID_CALLBACK_PAYLOAD")
                payload_map = MappingProxyType(copied)
        observations.append(
            ReplayFrameObservation(
                identity=identity,
                ordinal=declaration.ordinal,
                relative_path=declaration.relative_path,
                source_sha256=declaration.source_sha256,
                label=declaration.label,
                width=declaration.width,
                height=declaration.height,
                channels=declaration.channels,
                transport_sha256=transport,
                semantic_sha256=semantic,
                callback_payload=payload_map,
            )
        )
        del bgr, _rgba, _payload, context

    return ReplayResult(
        schema_name=SCHEMA_NAME,
        schema_version=SCHEMA_VERSION,
        fixture_session_id=validated.fixture_session_id,
        capture_kind="fixture",
        observations=tuple(observations),
    )


def iter_replay_observations(
    manifest: ReplayManifest | Path | str | None = None,
    *,
    root: Path | None = None,
    callback: ReplayCallback | None = None,
) -> Iterator[ReplayFrameObservation]:
    """Yield immutable observations in deterministic manifest order."""

    result = replay_native_frames(manifest, root=root, callback=callback)
    yield from result.observations


def built_in_perception_ocr_callback(
    *,
    roi: tuple[int, int, int, int] = (40, 40, 120, 80),
    ocr_engine: Callable[[np.ndarray, int], str] | None = None,
) -> ReplayCallback:
    """Narrow built-in adapter exercising FramePerceptionBundle and run_semantic_ocr.

    Returns string-only payload fields suitable for immutable replay records. Does not
    authorize transport and never labels fixtures as live.
    """

    def _callback(context: ReplayFrameContext) -> Mapping[str, str]:
        assert_fixture_capture_kind(context.identity)
        reject_live_capture_request(requested_capture_kind=context.identity.capture_kind)
        pixels = context.pixels_bgr()
        try:
            observation = run_semantic_ocr(
                pixels,
                CropRoiRequest(context.identity, roi),
                ocr_mode=OcrMode.UNIFORM_BLOCK,
                normalization=(NormalizationOp.TO_GRAYSCALE,),
                ocr_engine=ocr_engine or (lambda _image, _psm: "fixture-ocr"),
            )
            bundle: FramePerceptionBundle = bundle_from_identity(context.identity)
            if observation.status is ObservationStatus.OK:
                immutable: ImmutableOcrObservation = to_immutable_ocr_observation(observation)
                if not immutable.source_frame.same_capture_event(context.identity):
                    raise NativeFrameReplayError("CAPTURE_EVENT_MISMATCH")
                bundle = bundle.with_ocr(immutable)
            if not bundle.frame.same_capture_event(context.identity):
                raise NativeFrameReplayError("CAPTURE_EVENT_MISMATCH")
            assert_fixture_capture_kind(bundle.frame)
            return MappingProxyType(
                {
                    "ocr_status": observation.status.value,
                    "ocr_reason": observation.reason_code,
                    "ocr_text": observation.text,
                    "bundle_capture_kind": bundle.frame.capture_kind,
                    "bundle_ordinal": str(bundle.frame.capture_ordinal),
                    "same_capture": "true",
                }
            )
        finally:
            del pixels

    return _callback


def source_paths_are_writable() -> bool:
    """Replay sources are read-only references; this harness never exposes writers."""

    return False


def mutation_operators_available() -> bool:
    """Mutation/augmentation APIs are intentionally absent from this harness."""

    return False


def generate_images_supported() -> bool:
    """Generated/mutated corpus expansion is forbidden."""

    return False


__all__ = [
    "ALLOWED_SOURCE_PATHS",
    "EXACT_SOURCE_ORDER",
    "EXPECTED_CHANNELS",
    "EXPECTED_HEIGHT",
    "EXPECTED_PROFILE_ID",
    "EXPECTED_WIDTH",
    "NativeFrameReplayError",
    "ReplayCallback",
    "ReplayFrameContext",
    "ReplayFrameObservation",
    "ReplayManifest",
    "ReplayResult",
    "ReplaySourceDeclaration",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "assert_fixture_capture_kind",
    "build_fixture_identity",
    "built_in_perception_ocr_callback",
    "coerce_identity_capture_kind",
    "default_manifest_path",
    "deterministic_fixture_session_id",
    "generate_images_supported",
    "iter_replay_observations",
    "load_replay_manifest",
    "mutation_operators_available",
    "reject_fixture_as_live_freshness",
    "reject_live_capture_request",
    "replay_native_frames",
    "serialize_replay_result",
    "source_paths_are_writable",
]
