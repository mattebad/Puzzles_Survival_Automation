#!/usr/bin/env python3
"""Record manual BlueStacks flow observations for later offline translation.

The collector is deliberately a recorder, not a gameplay controller.  It can read a
single explicitly selected local ADB device, capture frames, and dispatch only an
explicitly confirmed individual action.  Mock mode never constructs or invokes an
ADB runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


RAW_WIDTH = 800
RAW_HEIGHT = 1280
RAW_SIZE = (RAW_WIDTH, RAW_HEIGHT)
EXPECTED_PACKAGE = "com.global.ztmslg"
MANIFEST_SCHEMA_VERSION = 1
KNOWN_BLUESTACKS_PRODUCTION_SERIALS = frozenset({"192.168.122.79:5555"})
LOCAL_EMULATOR_SERIAL_RE = re.compile(r"^emulator-\d+$")
FLOW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class CollectorError(RuntimeError):
    """A user-facing collector error that should preserve the session."""


class ADBError(CollectorError):
    """An ADB command failed or was unavailable."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def safe_flow_id(flow_id: str) -> str:
    if not FLOW_ID_RE.fullmatch(flow_id):
        raise CollectorError("flow-id must contain only letters, numbers, dot, dash, or underscore")
    return flow_id


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


def _png_chunks(payload: bytes) -> Iterable[tuple[bytes, bytes]]:
    if not payload.startswith(PNG_SIGNATURE):
        raise CollectorError("image is not a PNG")
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(payload):
            raise CollectorError("truncated PNG chunk")
        chunk = payload[start:end]
        expected_crc = struct.unpack(">I", payload[end : end + 4])[0]
        actual_crc = zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise CollectorError("PNG CRC mismatch")
        yield chunk_type, chunk
        offset = end + 4
        if chunk_type == b"IEND":
            return
    raise CollectorError("PNG has no IEND chunk")


def png_dimensions(payload: bytes) -> tuple[int, int]:
    for chunk_type, chunk in _png_chunks(payload):
        if chunk_type == b"IHDR":
            if len(chunk) != 13:
                raise CollectorError("invalid PNG IHDR")
            width, height = struct.unpack(">II", chunk[:8])
            if width <= 0 or height <= 0:
                raise CollectorError("PNG has invalid dimensions")
            return width, height
    raise CollectorError("PNG IHDR is missing")


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _unfilter_scanlines(raw: bytes, width: int, height: int, bytes_per_pixel: int) -> list[bytes]:
    stride = width * bytes_per_pixel
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise CollectorError("PNG scanline data length mismatch")
    rows: list[bytes] = []
    offset = 0
    previous = bytes(stride)
    for _ in range(height):
        filter_type = raw[offset]
        encoded = raw[offset + 1 : offset + 1 + stride]
        offset += stride + 1
        current = bytearray(stride)
        for index, value in enumerate(encoded):
            left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 0:
                reconstructed = value
            elif filter_type == 1:
                reconstructed = (value + left) & 0xFF
            elif filter_type == 2:
                reconstructed = (value + up) & 0xFF
            elif filter_type == 3:
                reconstructed = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                reconstructed = (value + _paeth(left, up, upper_left)) & 0xFF
            else:
                raise CollectorError(f"unsupported PNG filter type: {filter_type}")
            current[index] = reconstructed
        row = bytes(current)
        rows.append(row)
        previous = row
    return rows


def png_to_rgba(payload: bytes) -> tuple[int, int, bytes]:
    """Decode common 8-bit, non-interlaced PNGs without requiring Pillow/OpenCV."""

    width = height = bit_depth = color_type = interlace = None
    idat: list[bytes] = []
    palette: bytes | None = None
    transparency: bytes | None = None
    for chunk_type, chunk in _png_chunks(payload):
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            idat.append(chunk)
    if width is None or height is None or bit_depth is None or color_type is None or interlace is None:
        raise CollectorError("PNG IHDR is missing")
    if bit_depth != 8 or interlace != 0:
        raise CollectorError("annotation fallback supports only 8-bit non-interlaced PNGs")
    bytes_per_pixel = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if bytes_per_pixel is None:
        raise CollectorError(f"unsupported PNG color type: {color_type}")
    rows = _unfilter_scanlines(zlib.decompress(b"".join(idat)), width, height, bytes_per_pixel)
    output = bytearray(width * height * 4)
    cursor = 0
    for row in rows:
        for index in range(width):
            if color_type == 6:
                red, green, blue, alpha = row[index * 4 : index * 4 + 4]
            elif color_type == 2:
                red, green, blue = row[index * 3 : index * 3 + 3]
                alpha = 255
                if transparency and len(transparency) >= 6:
                    transparent_rgb = struct.unpack(">HHH", transparency[:6])
                    if (red, green, blue) == tuple(value >> 8 for value in transparent_rgb):
                        alpha = 0
            elif color_type == 4:
                red = green = blue = row[index * 2]
                alpha = row[index * 2 + 1]
            elif color_type == 0:
                red = green = blue = row[index]
                alpha = 255
                if transparency and len(transparency) >= 2 and row[index] == struct.unpack(">H", transparency[:2])[0] >> 8:
                    alpha = 0
            else:
                palette_index = row[index]
                palette_offset = palette_index * 3
                if palette is None or palette_offset + 3 > len(palette):
                    raise CollectorError("PNG palette index is out of range")
                red, green, blue = palette[palette_offset : palette_offset + 3]
                alpha = transparency[palette_index] if transparency and palette_index < len(transparency) else 255
            output[cursor : cursor + 4] = bytes((red, green, blue, alpha))
            cursor += 4
    return width, height, bytes(output)


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def rgba_to_png(width: int, height: int, rgba: bytes) -> bytes:
    if len(rgba) != width * height * 4:
        raise CollectorError("RGBA buffer length mismatch")
    scanlines = bytearray()
    row_size = width * 4
    for offset in range(0, len(rgba), row_size):
        scanlines.append(0)
        scanlines.extend(rgba[offset : offset + row_size])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), 9)) + _png_chunk(b"IEND", b"")


def _set_rgba_pixel(rgba: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    if not (0 <= x < width and 0 <= y < height):
        return
    offset = (y * width + x) * 4
    rgba[offset : offset + 4] = bytes(color)


def _draw_line(rgba: bytearray, width: int, height: int, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int, int], thickness: int = 3) -> None:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    radius = max(0, thickness // 2)
    while True:
        for yy in range(y0 - radius, y0 + radius + 1):
            for xx in range(x0 - radius, x0 + radius + 1):
                _set_rgba_pixel(rgba, width, height, xx, yy, color)
        if x0 == x1 and y0 == y1:
            break
        double_error = 2 * error
        if double_error >= dy:
            error += dy
            x0 += sx
        if double_error <= dx:
            error += dx
            y0 += sy


def _draw_circle(rgba: bytearray, width: int, height: int, center: tuple[int, int], radius: int, color: tuple[int, int, int, int]) -> None:
    cx, cy = center
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            distance = (x - cx) ** 2 + (y - cy) ** 2
            if radius * radius - radius * 2 <= distance <= radius * radius + radius * 2:
                _set_rgba_pixel(rgba, width, height, x, y, color)


def annotate_png(source: Path, destination: Path, annotation: dict[str, Any]) -> str:
    """Create a separate marked PNG and return the annotation implementation."""

    payload = source.read_bytes()
    try:
        width, height, rgba = png_to_rgba(payload)
        overlay = bytearray(rgba)
        red = (232, 32, 32, 255)
        yellow = (255, 210, 0, 255)
        if annotation.get("raw_point"):
            point = tuple(int(value) for value in annotation["raw_point"])
            _draw_circle(overlay, width, height, point, 22, red)
            _draw_line(overlay, width, height, (max(0, point[0] - 30), point[1]), (min(width - 1, point[0] + 30), point[1]), yellow, 3)
            _draw_line(overlay, width, height, (point[0], max(0, point[1] - 30)), (point[0], min(height - 1, point[1] + 30)), yellow, 3)
        if annotation.get("raw_start") and annotation.get("raw_end"):
            start = tuple(int(value) for value in annotation["raw_start"])
            end = tuple(int(value) for value in annotation["raw_end"])
            _draw_line(overlay, width, height, start, end, red, 5)
            _draw_circle(overlay, width, height, start, 16, yellow)
            _draw_circle(overlay, width, height, end, 16, yellow)
            direction_x = end[0] - start[0]
            direction_y = end[1] - start[1]
            length = max(1.0, (direction_x * direction_x + direction_y * direction_y) ** 0.5)
            ux, uy = direction_x / length, direction_y / length
            left = (int(end[0] - ux * 28 + uy * 12), int(end[1] - uy * 28 - ux * 12))
            right = (int(end[0] - ux * 28 - uy * 12), int(end[1] - uy * 28 + ux * 12))
            _draw_line(overlay, width, height, end, left, yellow, 4)
            _draw_line(overlay, width, height, end, right, yellow, 4)
        if annotation.get("border"):
            _draw_line(overlay, width, height, (0, 0), (width - 1, 0), red, 4)
            _draw_line(overlay, width, height, (0, height - 1), (width - 1, height - 1), red, 4)
            _draw_line(overlay, width, height, (0, 0), (0, height - 1), red, 4)
            _draw_line(overlay, width, height, (width - 1, 0), (width - 1, height - 1), red, 4)
        atomic_write_bytes(destination, rgba_to_png(width, height, bytes(overlay)))
        return "stdlib-png"
    except Exception:
        # A valid clean frame is still retained even if an uncommon PNG encoding cannot be
        # decoded by the fallback annotator.  Pillow/OpenCV, when available, gets the first
        # opportunity through the optional path below.
        try:
            from PIL import Image, ImageDraw  # type: ignore

            with Image.open(source) as image:
                image = image.convert("RGBA")
                draw = ImageDraw.Draw(image)
                if annotation.get("raw_point"):
                    x, y = (int(value) for value in annotation["raw_point"])
                    draw.ellipse((x - 22, y - 22, x + 22, y + 22), outline=(232, 32, 32, 255), width=4)
                    draw.line((x - 30, y, x + 30, y), fill=(255, 210, 0, 255), width=3)
                    draw.line((x, y - 30, x, y + 30), fill=(255, 210, 0, 255), width=3)
                if annotation.get("raw_start") and annotation.get("raw_end"):
                    draw.line(tuple(annotation["raw_start"]) + tuple(annotation["raw_end"]), fill=(232, 32, 32, 255), width=5)
                if annotation.get("border"):
                    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=(232, 32, 32, 255), width=4)
                temporary = destination.with_name(destination.name + ".tmp")
                image.save(temporary, format="PNG")
                os.replace(temporary, destination)
            return "pillow"
        except Exception as exc:
            # Do not lose the session if the optional image stack is unavailable.  The copy is
            # deliberately separate and the manifest records the fallback limitation.
            shutil.copyfile(source, destination)
            return f"copy-fallback:{type(exc).__name__}"


def point_inside_rendered_image(display_x: float, display_y: float, rendered_bounds: tuple[float, float, float, float]) -> bool:
    left, top, width, height = rendered_bounds
    return width > 0 and height > 0 and left <= display_x < left + width and top <= display_y < top + height


def _translate_axis(value: float, origin: float, display_size: float, raw_size: int) -> int:
    if display_size <= 1:
        return 0
    ratio = (value - origin) * (raw_size - 1) / (display_size - 1)
    return max(0, min(raw_size - 1, int(round(ratio))))


def translate_display_point(
    display_x: float,
    display_y: float,
    rendered_bounds: tuple[float, float, float, float],
    raw_size: tuple[int, int] = RAW_SIZE,
) -> tuple[int, int]:
    if not point_inside_rendered_image(display_x, display_y, rendered_bounds):
        raise ValueError("selection is outside the rendered image")
    left, top, width, height = rendered_bounds
    return (_translate_axis(display_x, left, width, raw_size[0]), _translate_axis(display_y, top, height, raw_size[1]))


def translate_display_swipe(
    display_start: tuple[float, float],
    display_end: tuple[float, float],
    rendered_bounds: tuple[float, float, float, float],
    raw_size: tuple[int, int] = RAW_SIZE,
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (
        translate_display_point(*display_start, rendered_bounds, raw_size),
        translate_display_point(*display_end, rendered_bounds, raw_size),
    )


def coordinate_self_check() -> dict[str, Any]:
    full_frame = (0.0, 0.0, float(RAW_WIDTH), float(RAW_HEIGHT))
    checks = {
        "top_left": translate_display_point(0, 0, full_frame) == (0, 0),
        "center": translate_display_point(400, 640, full_frame) == (400, 640),
        "bottom_right": translate_display_point(799, 1279, full_frame) == (799, 1279),
        "one_swipe": translate_display_swipe((100, 200), (700, 1100), full_frame) == ((100, 200), (700, 1100)),
    }
    try:
        translate_display_point(800, 640, full_frame)
    except ValueError:
        checks["outside_rendered_frame_rejected"] = True
    else:
        checks["outside_rendered_frame_rejected"] = False
    if not all(checks.values()):
        raise CollectorError("coordinate self-check failed: " + json.dumps(checks, sort_keys=True))
    return checks


def is_permitted_local_bluestacks_serial(serial: str) -> bool:
    if serial in KNOWN_BLUESTACKS_PRODUCTION_SERIALS:
        return False
    if LOCAL_EMULATOR_SERIAL_RE.fullmatch(serial):
        return True
    if serial.startswith("localhost:"):
        return True
    if serial.startswith("127.0.0.1:"):
        return True
    if serial.startswith("[::1]:"):
        return True
    return False


@dataclass(frozen=True)
class ADBDevice:
    serial: str
    state: str
    details: str = ""


class ADBRunner:
    """Minimal read/dispatch wrapper.  It never runs adb connect."""

    def __init__(self, executable: str, serial: str):
        self.executable = executable
        self.serial = serial

    def run(self, *arguments: str, timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
        command = [self.executable, "-s", self.serial, *arguments]
        try:
            return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise ADBError(f"ADB executable was not found: {self.executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ADBError(f"ADB command timed out: {' '.join(command[:5])}") from exc

    def list_devices(self) -> list[ADBDevice]:
        try:
            result = subprocess.run([self.executable, "devices", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        except FileNotFoundError as exc:
            raise ADBError(f"ADB executable was not found: {self.executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ADBError("ADB device listing timed out") from exc
        if result.returncode:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or "ADB device listing failed")
        devices: list[ADBDevice] = []
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            fields = line.split(maxsplit=2)
            if len(fields) >= 2:
                devices.append(ADBDevice(fields[0], fields[1], fields[2] if len(fields) == 3 else ""))
        return devices

    def get_state(self) -> str:
        result = self.run("get-state")
        return result.stdout.decode("utf-8", "replace").strip()

    def capture_png(self) -> bytes:
        result = self.run("exec-out", "screencap", "-p", timeout=45.0)
        if result.returncode:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or "ADB screenshot failed")
        if not result.stdout:
            raise ADBError("ADB screenshot returned no bytes")
        return result.stdout

    def shell_text(self, *arguments: str, timeout: float = 30.0) -> str:
        result = self.run("shell", *arguments, timeout=timeout)
        if result.returncode:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or f"ADB shell command failed: {' '.join(arguments)}")
        return result.stdout.decode("utf-8", "replace")

    def dispatch_tap(self, point: tuple[int, int]) -> None:
        result = self.run("shell", "input", "tap", str(point[0]), str(point[1]), timeout=15.0)
        if result.returncode:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or "ADB tap failed")

    def dispatch_swipe(self, start: tuple[int, int], end: tuple[int, int], duration_ms: int = 400) -> None:
        result = self.run("shell", "input", "swipe", str(start[0]), str(start[1]), str(end[0]), str(end[1]), str(duration_ms), timeout=15.0)
        if result.returncode:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or "ADB swipe failed")

    def dispatch_back(self) -> None:
        result = self.run("shell", "input", "keyevent", "4", timeout=15.0)
        if result.returncode:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or "ADB Back failed")

    def dump_ui(self) -> bytes:
        self.shell_text("uiautomator", "dump", "/sdcard/window.xml", timeout=30.0)
        result = self.run("exec-out", "cat", "/sdcard/window.xml", timeout=30.0)
        if result.returncode or not result.stdout:
            raise ADBError(result.stderr.decode("utf-8", "replace").strip() or "UI hierarchy capture failed")
        return result.stdout


class MockFrameSource:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.payload = path.read_bytes()
        except OSError as exc:
            raise CollectorError(f"cannot read mock image: {path}") from exc
        if png_dimensions(self.payload) != RAW_SIZE:
            raise CollectorError(f"mock image must be exactly {RAW_WIDTH}x{RAW_HEIGHT}")

    def capture(self) -> bytes:
        return bytes(self.payload)


class ADBFrameSource:
    def __init__(self, runner: ADBRunner):
        self.runner = runner

    def capture(self) -> bytes:
        return self.runner.capture_png()


def parse_foreground_package(raw: str) -> str | None:
    foreground_lines = [
        line for line in raw.splitlines()
        if "mCurrentFocus" in line or "mFocusedApp" in line
    ]
    candidates = foreground_lines or raw.splitlines()
    matches = re.findall(r"([A-Za-z][A-Za-z0-9_.]+)/(?:[A-Za-z0-9_.$]+)", "\n".join(candidates))
    return matches[-1] if matches else None


def parse_wm_size(raw: str) -> tuple[int, int] | None:
    match = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", raw)
    return (int(match.group(1)), int(match.group(2))) if match else None


class CollectorSession:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.flow_id = safe_flow_id(args.flow_id)
        session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        root = Path(args.output_directory).expanduser().absolute()
        self.session_dir = root / "bluestacks" / self.flow_id / session_id
        self.frames_dir = self.session_dir / "frames"
        self.ui_dir = self.session_dir / "ui"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.ui_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.session_dir / "manifest.json"
        self.device_path = self.session_dir / "device.json"
        self.log_path = self.session_dir / "session.log"
        self.zip_path = self.session_dir / "flow.zip"
        self.current_frame_path: Path | None = None
        self.current_screen_label = ""
        self.pending_target_label = ""
        self.pending_successor_label = ""
        self.pending_notes: list[str] = []
        self.step_count = 0
        self.runner: ADBRunner | None = None
        self.source: MockFrameSource | ADBFrameSource | None = None
        self.manifest: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "collector": "bluestacks_flow_collector",
            "flow_id": self.flow_id,
            "daily_objective": args.daily_objective,
            "session_id": session_id,
            "started_at_utc": utc_now(),
            "completed_at_utc": None,
            "mode": "mock" if args.mock_image else ("live-record-only" if args.record_only else "live-dispatch"),
            "session_status": "active",
            "device_diagnostics": {},
            "dispatch_safety_gate": {},
            "observations": [],
            "steps": [],
            "current_context": {
                "screen_label": "",
                "target_label": "",
                "expected_successor": "",
            },
            "notes": [],
            "objective_progress": {"before": None, "after": None},
            "final_row_control_state": None,
            "claim_state": "unset",
            "structured_errors": [],
            "artifact_inventory": [],
            "exported_zip_path": "flow.zip",
        }
        self._append_log("session_started")
        self._initialize_device()
        self._persist_manifest()

    def _append_log(self, event: str, detail: Any | None = None) -> None:
        record = {"timestamp_utc": utc_now(), "event": event}
        if detail is not None:
            record["detail"] = detail
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _rel(self, path: Path | None) -> str | None:
        if path is None:
            return None
        return path.relative_to(self.session_dir).as_posix()

    def _inventory(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(item for item in self.session_dir.rglob("*") if item.is_file()):
            relative = path.relative_to(self.session_dir).as_posix()
            if relative in {"manifest.json", self.zip_path.name} or path.name.endswith(".tmp"):
                continue
            records.append({"path": relative, "sha256": sha256_file(path), "size": path.stat().st_size})
        return records

    def _persist_manifest(self) -> None:
        self.manifest["artifact_inventory"] = self._inventory()
        atomic_write_json(self.manifest_path, self.manifest)

    def _record_error(self, code: str, message: str, *, phase: str, exception: str | None = None) -> None:
        error: dict[str, Any] = {"timestamp_utc": utc_now(), "code": code, "message": message, "phase": phase}
        if exception:
            error["exception"] = exception
        self.manifest["structured_errors"].append(error)
        self._append_log("error", error)
        self._persist_manifest()

    def _initialize_device(self) -> None:
        if self.args.mock_image:
            try:
                self.source = MockFrameSource(Path(self.args.mock_image))
            except Exception as exc:
                self.manifest["session_status"] = "failed"
                self._record_error("MOCK_IMAGE_INVALID", str(exc), phase="initialization", exception=type(exc).__name__)
                atomic_write_json(self.device_path, {"mode": "mock", "serial": None, "adb_invoked": False})
                return
            self.manifest["device_diagnostics"] = {
                "mode": "mock",
                "serial": None,
                "adb_invoked": False,
                "image_size": {"width": RAW_WIDTH, "height": RAW_HEIGHT},
                "foreground_package": None,
            }
            self.manifest["dispatch_safety_gate"] = {
                "dispatch_enabled": False,
                "reason": "mock_mode_is_record_only",
                "checks": {"mock_mode": True, "record_only": True, "adb_invoked": False},
            }
            atomic_write_json(self.device_path, self.manifest["device_diagnostics"])
            self._capture_initial()
            return

        try:
            serial, devices = self._select_and_confirm_serial()
            self.runner = ADBRunner(self.args.adb, serial)
            self.source = ADBFrameSource(self.runner)
            permitted = is_permitted_local_bluestacks_serial(serial)
            known_production = serial in KNOWN_BLUESTACKS_PRODUCTION_SERIALS
            diagnostics: dict[str, Any] = {
                "mode": "live",
                "adb_executable": str(self.args.adb),
                "serial": serial,
                "confirmed_serial": serial,
                "adb_invoked": True,
                "device_list": [{"serial": item.serial, "state": item.state, "details": item.details} for item in devices],
                "selected_device_state": next((item.state for item in devices if item.serial == serial), "missing"),
                "permitted_local_bluestacks_endpoint": permitted,
                "known_production_serial": known_production,
            }
            if not permitted or known_production:
                diagnostics["rejection"] = "serial_is_not_a_permitted_local_bluestacks_endpoint"
                self.manifest["device_diagnostics"] = diagnostics
                self.manifest["dispatch_safety_gate"] = {
                    "dispatch_enabled": False,
                    "reason": diagnostics["rejection"],
                    "checks": {
                        "serial_selected_explicitly": True,
                        "serial_confirmation_matches": True,
                        "permitted_local_bluestacks_endpoint": permitted,
                        "known_production_serial": known_production,
                        "record_only": bool(self.args.record_only),
                    },
                }
                self.manifest["session_status"] = "failed"
                atomic_write_json(self.device_path, diagnostics)
                self._record_error("SERIAL_REJECTED", diagnostics["rejection"], phase="device-selection")
                return
            self.manifest["device_diagnostics"] = diagnostics
            self._capture_initial()
            self._finish_live_diagnostics()
        except Exception as exc:
            self.manifest["session_status"] = "failed"
            self._record_error("DEVICE_INITIALIZATION_FAILED", str(exc), phase="initialization", exception=type(exc).__name__)
            atomic_write_json(self.device_path, self.manifest["device_diagnostics"] or {"mode": "live", "adb_invoked": True})

    def _select_and_confirm_serial(self) -> tuple[str, list[ADBDevice]]:
        probe = ADBRunner(self.args.adb, self.args.serial or "__selection__")
        devices = probe.list_devices()
        serial = self.args.serial
        if serial is None:
            print("ADB devices (select an exact serial; no device is selected automatically):")
            for device in devices:
                print(f"  {device.serial}\t{device.state}\t{device.details}")
            try:
                serial = input("Enter the exact BlueStacks serial: ").strip()
            except EOFError as exc:
                raise CollectorError("an explicit serial or interactive device selection is required") from exc
        if not serial:
            raise CollectorError("an explicit serial or interactive device selection is required")
        selected = next((device for device in devices if device.serial == serial), None)
        if selected is None:
            raise CollectorError("selected serial is not present in the current ADB device list")
        try:
            answer = input(f"Confirm exact BlueStacks serial {serial!r} for this session? [y/N]: ").strip().lower()
        except EOFError as exc:
            raise CollectorError("serial confirmation was not received") from exc
        if answer not in {"y", "yes"}:
            raise CollectorError("serial confirmation canceled")
        if selected.serial != serial:
            raise CollectorError("confirmed serial mismatch")
        if selected.state != "device":
            raise CollectorError(f"selected serial is not reachable and ready (state={selected.state})")
        return serial, devices

    def _capture_initial(self) -> None:
        if self.source is None:
            return
        try:
            payload = self.source.capture()
            dimensions = png_dimensions(payload)
            clean = self.frames_dir / "000-initial.png"
            atomic_write_bytes(clean, payload)
            self.current_frame_path = clean
            self.manifest["observations"].append({
                "captured_at_utc": utc_now(),
                "screen_label": "",
                "frame_path": self._rel(clean),
                "width": dimensions[0],
                "height": dimensions[1],
                "sha256": sha256_bytes(payload),
            })
            self.manifest["device_diagnostics"]["screenshot_capture_succeeded"] = True
            self.manifest["device_diagnostics"]["screenshot_size"] = {"width": dimensions[0], "height": dimensions[1]}
            self.manifest["device_diagnostics"]["portrait_frame"] = dimensions[0] < dimensions[1]
            self.manifest["device_diagnostics"]["exact_800x1280"] = dimensions == RAW_SIZE
            self._append_log("initial_frame_captured", {"path": self._rel(clean), "sha256": sha256_bytes(payload)})
            if dimensions != RAW_SIZE:
                self.manifest["dispatch_safety_gate"] = {
                    "dispatch_enabled": False,
                    "reason": "wrong_frame_size_or_orientation",
                    "checks": {"portrait": dimensions[0] < dimensions[1], "exact_800x1280": dimensions == RAW_SIZE},
                }
                self.manifest["session_status"] = "failed"
                self._record_error("FRAME_PROFILE_REJECTED", f"expected {RAW_WIDTH}x{RAW_HEIGHT}, got {dimensions[0]}x{dimensions[1]}", phase="initial-capture")
        except Exception as exc:
            self.manifest["device_diagnostics"]["screenshot_capture_succeeded"] = False
            self.manifest["session_status"] = "failed"
            self._record_error("INITIAL_SCREENSHOT_FAILED", str(exc), phase="initial-capture", exception=type(exc).__name__)
            atomic_write_json(self.device_path, self.manifest["device_diagnostics"])

    def _finish_live_diagnostics(self) -> None:
        if self.runner is None:
            return
        diagnostics = self.manifest["device_diagnostics"]
        checks: dict[str, Any] = {
            "serial_selected_explicitly": bool(diagnostics.get("confirmed_serial")),
            "serial_confirmation_matches": diagnostics.get("confirmed_serial") == diagnostics.get("serial"),
            "device_reachable": diagnostics.get("selected_device_state") == "device",
            "permitted_local_bluestacks_endpoint": diagnostics.get("permitted_local_bluestacks_endpoint", False),
            "known_production_serial": diagnostics.get("known_production_serial", False),
            "screenshot_capture_succeeded": diagnostics.get("screenshot_capture_succeeded", False),
            "portrait": diagnostics.get("portrait_frame", False),
            "exact_800x1280": diagnostics.get("exact_800x1280", False),
            "foreground_package_expected": False,
            "record_only": bool(self.args.record_only),
        }
        try:
            state = self.runner.get_state()
            diagnostics["adb_state"] = state
            checks["device_reachable"] = checks["device_reachable"] and state == "device"
        except Exception as exc:
            self._record_error("ADB_STATE_CHECK_FAILED", str(exc), phase="diagnostics", exception=type(exc).__name__)
        try:
            wm_size_raw = self.runner.shell_text("wm", "size")
            diagnostics["wm_size_raw"] = wm_size_raw.strip()
            diagnostics["wm_size"] = ({"width": parse_wm_size(wm_size_raw)[0], "height": parse_wm_size(wm_size_raw)[1]} if parse_wm_size(wm_size_raw) else None)
        except Exception as exc:
            self._record_error("WM_SIZE_CHECK_FAILED", str(exc), phase="diagnostics", exception=type(exc).__name__)
        try:
            foreground_raw = self.runner.shell_text("dumpsys", "window", "windows")
            foreground_package = parse_foreground_package(foreground_raw)
            diagnostics["foreground_raw"] = foreground_raw[-4000:]
            diagnostics["foreground_package"] = foreground_package
            checks["foreground_package_expected"] = foreground_package == EXPECTED_PACKAGE
        except Exception as exc:
            self._record_error("FOREGROUND_CHECK_FAILED", str(exc), phase="diagnostics", exception=type(exc).__name__)
        dispatch_enabled = bool(
            all(passed for name, passed in checks.items() if name != "record_only")
            and not checks["record_only"]
            and not checks["known_production_serial"]
        )
        self.manifest["dispatch_safety_gate"] = {
            "dispatch_enabled": dispatch_enabled,
            "checks": checks,
            "rejection_reasons": [name for name, passed in checks.items() if not passed and name != "record_only"],
        }
        atomic_write_json(self.device_path, diagnostics)
        self._append_log("live_diagnostics_complete", self.manifest["dispatch_safety_gate"])
        self._persist_manifest()

    @property
    def dispatch_enabled(self) -> bool:
        return bool(self.manifest.get("dispatch_safety_gate", {}).get("dispatch_enabled"))

    @property
    def record_only(self) -> bool:
        return self.manifest["mode"] != "live-dispatch" or not self.dispatch_enabled

    def is_usable(self) -> bool:
        return self.current_frame_path is not None and self.manifest["session_status"] not in {"failed"}

    def capture_current_frame(self) -> Path:
        if self.source is None:
            raise CollectorError("no screenshot source is available")
        payload = self.source.capture()
        dimensions = png_dimensions(payload)
        path = self.frames_dir / f"observation-{len(self.manifest['observations']) + 1:03d}.png"
        atomic_write_bytes(path, payload)
        self.current_frame_path = path
        self.manifest["observations"].append({
            "captured_at_utc": utc_now(),
            "action_type": "observation-only",
            "dispatch_status": "observation-only",
            "screen_label": self.current_screen_label,
            "frame_path": self._rel(path),
            "width": dimensions[0],
            "height": dimensions[1],
            "sha256": sha256_bytes(payload),
        })
        self._append_log("observation_captured", {"path": self._rel(path), "sha256": sha256_bytes(payload)})
        self._persist_manifest()
        return path

    def _before_frame(self, step_id: str) -> Path:
        if self.source is None:
            raise CollectorError("no screenshot source is available")
        payload = self.source.capture()
        if png_dimensions(payload) != RAW_SIZE:
            raise CollectorError("immediate-before frame is not exactly 800x1280")
        path = self.frames_dir / f"{step_id}-before.png"
        atomic_write_bytes(path, payload)
        self.current_frame_path = path
        return path

    def _after_frame(self, step_id: str) -> Path:
        if self.source is None:
            raise CollectorError("no screenshot source is available")
        payload = self.source.capture()
        if png_dimensions(payload) != RAW_SIZE:
            raise CollectorError("immediate-after frame is not exactly 800x1280")
        path = self.frames_dir / f"{step_id}-after.png"
        atomic_write_bytes(path, payload)
        self.current_frame_path = path
        return path

    def _context_step_fields(self) -> dict[str, Any]:
        return {
            "source_label": self.current_screen_label or "unset",
            "target_label": self.pending_target_label or "unset",
            "expected_successor": self.pending_successor_label or "unset",
            "notes": list(self.pending_notes),
            "objective_progress_before": self.manifest["objective_progress"]["before"],
            "objective_progress_after": self.manifest["objective_progress"]["after"],
            "final_row_control_state": self.manifest["final_row_control_state"],
            "claim_state": self.manifest["claim_state"],
        }

    def _append_partial_step(self, step: dict[str, Any]) -> None:
        self.manifest["steps"].append(step)
        self.step_count += 1
        self.pending_notes.clear()
        self.pending_target_label = ""
        self.pending_successor_label = ""
        self._persist_manifest()

    def record_action(
        self,
        action_type: str,
        coordinates: dict[str, Any] | None,
        annotation: dict[str, Any],
        confirmation: Callable[[str], bool],
        *,
        wait_seconds: float | None = None,
    ) -> dict[str, Any]:
        if action_type not in {"tap", "swipe", "android_back", "wait"}:
            raise CollectorError(f"unsupported action type: {action_type}")
        step_id = f"step-{self.step_count + 1:03d}"
        step: dict[str, Any] = {
            "step_id": step_id,
            "ordinal": self.step_count + 1,
            "action_type": action_type,
            **self._context_step_fields(),
            "display_coordinates": coordinates.get("display") if coordinates else None,
            "raw_coordinates": coordinates.get("raw") if coordinates else None,
            "before_frame_path": None,
            "after_frame_path": None,
            "annotated_frame_path": None,
            "annotation_implementation": None,
            "ui_dump_path": None,
            "dispatch_status": "not_started",
            "dispatch_transport": None,
            "semantic_result": {"status": "unset", "notes": []},
            "started_at_utc": utc_now(),
            "completed_at_utc": None,
        }
        try:
            before = self._before_frame(step_id)
            step["before_frame_path"] = self._rel(before)
            annotated = self.frames_dir / f"{step_id}-annotated.png"
            step["annotation_implementation"] = annotate_png(before, annotated, annotation)
            step["annotated_frame_path"] = self._rel(annotated)
        except Exception as exc:
            step["dispatch_status"] = "failed_before_dispatch"
            step["semantic_result"] = {"status": "error", "notes": [str(exc)]}
            self.manifest["structured_errors"].append({"timestamp_utc": utc_now(), "code": "BEFORE_CAPTURE_FAILED", "message": str(exc), "phase": step_id, "exception": type(exc).__name__})
            self._append_log("step_failed_before_dispatch", {"step_id": step_id, "error": str(exc)})
            self._append_partial_step(step)
            return step

        if action_type == "wait":
            requested_wait = self.args.post_action_delay if wait_seconds is None else max(0.0, wait_seconds)
            prompt = f"Record a Wait step of {requested_wait:.2f} seconds?\n\nBefore: {step['before_frame_path']}"
        elif self.record_only:
            prompt = f"Record-only step {action_type}.\n\nPerform this action manually, then choose Yes when the successor is ready.\n\nRaw coordinates: {step['raw_coordinates']}"
        else:
            prompt = f"Dispatch exactly one {action_type} to the selected BlueStacks device?\n\nSerial: {self.manifest['device_diagnostics'].get('serial')}\nRaw coordinates: {step['raw_coordinates']}\n\nThe clean before frame and annotation are ready."
        if not confirmation(prompt):
            step["dispatch_status"] = "canceled"
            step["semantic_result"] = {"status": "canceled", "notes": ["user canceled confirmation"]}
            step["completed_at_utc"] = utc_now()
            self._append_log("step_canceled", {"step_id": step_id})
            self._append_partial_step(step)
            return step

        dispatched = False
        if action_type == "wait":
            step["dispatch_status"] = "wait"
            time.sleep(max(0.0, self.args.post_action_delay if wait_seconds is None else wait_seconds))
        elif self.record_only:
            step["dispatch_status"] = "record_only"
        else:
            if self.runner is None:
                step["dispatch_status"] = "failed_before_dispatch"
                step["semantic_result"] = {"status": "error", "notes": ["dispatch gate enabled without an ADB runner"]}
                self._append_partial_step(step)
                return step
            try:
                if action_type == "tap":
                    raw_point = step["raw_coordinates"]["point"]
                    self.runner.dispatch_tap((int(raw_point["x"]), int(raw_point["y"])))
                elif action_type == "swipe":
                    raw = step["raw_coordinates"]
                    raw_start = raw["start"]
                    raw_end = raw["end"]
                    self.runner.dispatch_swipe(
                        (int(raw_start["x"]), int(raw_start["y"])),
                        (int(raw_end["x"]), int(raw_end["y"])),
                    )
                elif action_type == "android_back":
                    self.runner.dispatch_back()
                dispatched = True
                step["dispatch_status"] = "dispatched"
                step["dispatch_transport"] = "adb_command_succeeded"
            except Exception as exc:
                step["dispatch_status"] = "failed_after_dispatch"
                step["dispatch_transport"] = "adb_command_failed_or_ambiguous"
                step["semantic_result"] = {"status": "unresolved", "notes": [str(exc), "no automatic retry"]}
                self.manifest["structured_errors"].append({"timestamp_utc": utc_now(), "code": "DISPATCH_FAILED", "message": str(exc), "phase": step_id, "exception": type(exc).__name__})
                self._append_log("step_failed_after_dispatch", {"step_id": step_id, "error": str(exc)})
                self._append_partial_step(step)
                return step
            time.sleep(max(0.0, self.args.post_action_delay))

        try:
            after = self._after_frame(step_id)
            step["after_frame_path"] = self._rel(after)
            if dispatched and self.runner is not None:
                try:
                    ui_payload = self.runner.dump_ui()
                    ui_path = self.ui_dir / f"{step_id}-after.xml"
                    atomic_write_bytes(ui_path, ui_payload)
                    step["ui_dump_path"] = self._rel(ui_path)
                except Exception as exc:
                    self.manifest["structured_errors"].append({"timestamp_utc": utc_now(), "code": "OPTIONAL_UI_DUMP_FAILED", "message": str(exc), "phase": step_id, "exception": type(exc).__name__})
                    self._append_log("optional_ui_dump_failed", {"step_id": step_id, "error": str(exc)})
            step["semantic_result"] = {"status": "user_to_label", "notes": ["transport does not establish semantic success"]}
        except Exception as exc:
            step["dispatch_status"] = "failed_after_dispatch" if dispatched else "failed_before_dispatch"
            step["semantic_result"] = {"status": "unresolved", "notes": [str(exc), "after frame unavailable; no automatic retry"]}
            self.manifest["structured_errors"].append({"timestamp_utc": utc_now(), "code": "AFTER_CAPTURE_FAILED", "message": str(exc), "phase": step_id, "exception": type(exc).__name__})
            self._append_log("step_failed_after_capture", {"step_id": step_id, "error": str(exc)})
        step["completed_at_utc"] = utc_now()
        self._append_log("step_recorded", {"step_id": step_id, "dispatch_status": step["dispatch_status"]})
        self._append_partial_step(step)
        return step

    def set_screen_label(self, label: str) -> None:
        self.current_screen_label = label.strip()
        self.manifest["current_context"]["screen_label"] = self.current_screen_label
        if self.manifest["observations"]:
            self.manifest["observations"][-1]["screen_label"] = self.current_screen_label
        self._append_log("screen_label_set", self.current_screen_label)
        self._persist_manifest()

    def set_target_label(self, label: str) -> None:
        self.pending_target_label = label.strip()
        self.manifest["current_context"]["target_label"] = self.pending_target_label
        self._append_log("target_label_set", self.pending_target_label)
        self._persist_manifest()

    def set_successor_label(self, label: str) -> None:
        self.pending_successor_label = label.strip()
        self.manifest["current_context"]["expected_successor"] = self.pending_successor_label
        self._append_log("successor_label_set", self.pending_successor_label)
        self._persist_manifest()

    def add_note(self, note: str) -> None:
        note = note.strip()
        if not note:
            return
        self.pending_notes.append(note)
        self.manifest["notes"].append({"timestamp_utc": utc_now(), "text": note})
        self._append_log("note_added", note)
        self._persist_manifest()

    def set_objective_progress(self, position: str, value: str) -> None:
        if position not in {"before", "after"}:
            raise CollectorError("objective progress position must be before or after")
        self.manifest["objective_progress"][position] = value.strip()
        self._append_log("objective_progress_set", {position: value.strip()})
        self._persist_manifest()

    def set_final_row_control(self, value: str) -> None:
        self.manifest["final_row_control_state"] = value.strip()
        self._append_log("final_row_control_set", value.strip())
        self._persist_manifest()

    def set_claim_state(self, value: str) -> None:
        if value not in {"unset", "yes", "no"}:
            raise CollectorError("Claim state must be unset, yes, or no")
        self.manifest["claim_state"] = value
        self._append_log("claim_state_set", value)
        self._persist_manifest()

    def mark_complete(self) -> None:
        if self.manifest["session_status"] == "failed":
            raise CollectorError("a failed session cannot be marked complete")
        self.manifest["session_status"] = "completed"
        self.manifest["completed_at_utc"] = utc_now()
        self._append_log("session_completed")
        self._persist_manifest()

    def abort(self) -> None:
        self.manifest["session_status"] = "aborted"
        self.manifest["completed_at_utc"] = utc_now()
        self._append_log("session_aborted")
        self._persist_manifest()

    def interrupt(self) -> None:
        if self.manifest["session_status"] == "active":
            self.manifest["session_status"] = "interrupted"
            self.manifest["completed_at_utc"] = utc_now()
            self._append_log("session_interrupted")
            self._persist_manifest()

    def export_zip(self) -> dict[str, Any]:
        self._append_log("zip_export_started", {"path": self.zip_path.name})
        self._persist_manifest()
        entries = ["manifest.json"] + [item["path"] for item in self.manifest["artifact_inventory"]]
        entries = sorted(set(entries))
        temporary = self.zip_path.with_name(self.zip_path.name + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for relative in entries:
                    info = zipfile.ZipInfo(relative)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    archive.writestr(info, (self.session_dir / relative).read_bytes())
            os.replace(temporary, self.zip_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        checked = 0
        with zipfile.ZipFile(self.zip_path, "r") as archive:
            names = set(archive.namelist())
            if names != set(entries):
                raise CollectorError("ZIP member set is not deterministic or complete")
            archived_manifest = json.loads(archive.read("manifest.json"))
            for item in archived_manifest["artifact_inventory"]:
                relative = item["path"]
                if relative not in names:
                    raise CollectorError(f"archived artifact is missing: {relative}")
                digest = sha256_bytes(archive.read(relative))
                if digest != item["sha256"] or not SHA256_RE.fullmatch(digest):
                    raise CollectorError(f"archived artifact hash mismatch: {relative}")
                checked += 1
        return {"zip_path": self._rel(self.zip_path), "members": len(entries), "artifacts_checked": checked, "verified": True}


def _prompt_gui_value(tk: Any, title: str, prompt: str, initial: str = "") -> str | None:
    from tkinter import simpledialog

    return simpledialog.askstring(title, prompt, initialvalue=initial)


class CollectorGUI:
    def __init__(self, session: CollectorSession):
        try:
            import tkinter as tk
            from tkinter import messagebox
        except Exception as exc:
            raise CollectorError(f"tkinter is unavailable: {exc}") from exc
        self.tk = tk
        self.messagebox = messagebox
        self.session = session
        self.root = tk.Tk()
        self.root.title(f"BlueStacks Flow Collector — {session.flow_id}")
        self.root.geometry("980x900")
        self.root.minsize(700, 600)
        self.selection_mode: str | None = None
        self.swipe_start: tuple[int, int] | None = None
        self.rendered_bounds: tuple[float, float, float, float] = (0, 0, RAW_WIDTH, RAW_HEIGHT)
        self.image_ref: Any = None
        self.canvas_image_id: int | None = None
        self.status_var = tk.StringVar()
        self.info_var = tk.StringVar()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_display()

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = self.tk.Frame(self.root, padx=8, pady=6)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.tk.Label(header, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="ew")
        self.tk.Label(header, textvariable=self.info_var, anchor="w", justify="left").grid(row=1, column=0, sticky="ew")
        self.canvas = self.tk.Canvas(self.root, background="#202020", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._refresh_display())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        controls = self.tk.Frame(self.root, padx=8, pady=8)
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        groups = [
            ("Capture", [("Refresh", self._refresh_display), ("Capture current frame", self._capture_current), ("Tap", lambda: self._select("tap")), ("Swipe", lambda: self._select("swipe")), ("Android Back", self._back), ("Wait", self._wait)]),
            ("Labels", [("Label current screen", self._label_screen), ("Set target label", self._label_target), ("Set expected successor", self._label_successor), ("Add note", self._add_note)]),
            ("Semantic result", [("Objective progress before", lambda: self._set_progress("before")), ("Objective progress after", lambda: self._set_progress("after")), ("Set final row control", self._set_final_control), ("Claim unset", lambda: self._set_claim("unset")), ("Claim yes", lambda: self._set_claim("yes")), ("Claim no", lambda: self._set_claim("no"))]),
            ("Session", [("Mark flow complete", self._complete), ("Abort preserving data", self._abort), ("Export ZIP", self._export)]),
        ]
        for row, (title, buttons) in enumerate(groups):
            frame = self.tk.LabelFrame(controls, text=title, padx=4, pady=4)
            frame.grid(row=row, column=0, sticky="ew", pady=2)
            for column, (label, command) in enumerate(buttons):
                self.tk.Button(frame, text=label, command=command).grid(row=0, column=column, padx=2, pady=2, sticky="ew")
                frame.columnconfigure(column, weight=1)

    def _status(self) -> None:
        gate = self.session.manifest.get("dispatch_safety_gate", {})
        if self.session.manifest["mode"] == "mock":
            mode = "MOCK MODE — no ADB code is invoked; record-only"
        elif self.session.manifest["mode"] == "live-record-only":
            mode = "RECORD-ONLY — no ADB input commands"
        elif gate.get("dispatch_enabled"):
            mode = "DISPATCH-ENABLED — exact serial and safety gates passed; each action needs confirmation"
        else:
            mode = "READ-ONLY — dispatch safety gate failed"
        self.status_var.set(f"{mode} | status={self.session.manifest['session_status']} | session={self.session.session_dir}")
        self.info_var.set(
            f"Screen: {self.session.current_screen_label or 'unset'} | Target: {self.session.pending_target_label or 'unset'} | "
            f"Successor: {self.session.pending_successor_label or 'unset'} | Claim: {self.session.manifest['claim_state']}"
        )

    def _load_tk_image(self, path: Path, width: int, height: int) -> tuple[Any, int, int]:
        try:
            from PIL import Image, ImageTk  # type: ignore

            with Image.open(path) as image:
                image = image.convert("RGBA")
                image.thumbnail((max(1, width), max(1, height)), Image.Resampling.LANCZOS)
                rendered = ImageTk.PhotoImage(image)
                return rendered, rendered.width(), rendered.height()
        except Exception:
            original = self.tk.PhotoImage(file=str(path))
            scale = max(1, int(max(original.width() / max(1, width), original.height() / max(1, height)) + 0.999))
            rendered = original.subsample(scale, scale) if scale > 1 else original
            return rendered, rendered.width(), rendered.height()

    def _refresh_display(self) -> None:
        self._status()
        if self.session.current_frame_path is None or not self.session.current_frame_path.exists():
            return
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        image, rendered_width, rendered_height = self._load_tk_image(self.session.current_frame_path, width - 8, height - 8)
        self.image_ref = image
        left = (width - rendered_width) / 2
        top = (height - rendered_height) / 2
        self.rendered_bounds = (left, top, float(rendered_width), float(rendered_height))
        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(left, top, image=image, anchor="nw")

    def _on_press(self, event: Any) -> None:
        if self.selection_mode == "swipe":
            self.swipe_start = (event.x, event.y)

    def _on_release(self, event: Any) -> None:
        mode = self.selection_mode
        if mode == "tap":
            self.selection_mode = None
            self._record_selected("tap", (event.x, event.y))
        elif mode == "swipe" and self.swipe_start is not None:
            start = self.swipe_start
            self.swipe_start = None
            self.selection_mode = None
            self._record_selected("swipe", start, (event.x, event.y))

    def _select(self, mode: str) -> None:
        self.selection_mode = mode
        self.swipe_start = None
        self.messagebox.showinfo("Select action", f"Click the {mode} target on the displayed frame." if mode == "tap" else "Press and release on the displayed frame to define the swipe.")

    def _record_selected(self, action_type: str, start: tuple[float, float], end: tuple[float, float] | None = None) -> None:
        try:
            if action_type == "tap":
                raw = translate_display_point(*start, self.rendered_bounds)
                coordinates = {
                    "display": {"point": {"x": start[0], "y": start[1]}, "rendered_bounds": self.rendered_bounds},
                    "raw": {"point": {"x": raw[0], "y": raw[1]}},
                }
                annotation = {"raw_point": raw}
            else:
                if end is None:
                    raise ValueError("swipe end point is missing")
                raw_start, raw_end = translate_display_swipe(start, end, self.rendered_bounds)
                coordinates = {
                    "display": {"start": {"x": start[0], "y": start[1]}, "end": {"x": end[0], "y": end[1]}, "rendered_bounds": self.rendered_bounds},
                    "raw": {"start": {"x": raw_start[0], "y": raw_start[1]}, "end": {"x": raw_end[0], "y": raw_end[1]}},
                }
                annotation = {"raw_start": raw_start, "raw_end": raw_end}
            step = self.session.record_action(action_type, coordinates, annotation, self._confirm)
            self._refresh_display()
            self.messagebox.showinfo("Step recorded", f"{step['step_id']}: {step['dispatch_status']}")
        except Exception as exc:
            self.session._record_error("GUI_ACTION_FAILED", str(exc), phase="gui", exception=type(exc).__name__)
            self.messagebox.showerror("Collector error", str(exc))

    def _confirm(self, prompt: str) -> bool:
        return bool(self.messagebox.askyesno("Confirm recorder action", prompt))

    def _capture_current(self) -> None:
        try:
            self.session.capture_current_frame()
            self._refresh_display()
        except Exception as exc:
            self.session._record_error("OBSERVATION_CAPTURE_FAILED", str(exc), phase="gui", exception=type(exc).__name__)
            self.messagebox.showerror("Capture failed", str(exc))

    def _back(self) -> None:
        try:
            step = self.session.record_action("android_back", None, {"border": True}, self._confirm)
            self._refresh_display()
            self.messagebox.showinfo("Step recorded", f"{step['step_id']}: {step['dispatch_status']}")
        except Exception as exc:
            self.session._record_error("GUI_ACTION_FAILED", str(exc), phase="gui", exception=type(exc).__name__)
            self.messagebox.showerror("Back capture failed", str(exc))

    def _wait(self) -> None:
        from tkinter import simpledialog

        value = simpledialog.askfloat("Wait", "Seconds to wait", initialvalue=self.session.args.post_action_delay, minvalue=0.0)
        if value is None:
            return
        try:
            step = self.session.record_action("wait", None, {"border": True}, self._confirm, wait_seconds=value)
            self._refresh_display()
            self.messagebox.showinfo("Step recorded", f"{step['step_id']}: {step['dispatch_status']}")
        except Exception as exc:
            self.session._record_error("GUI_ACTION_FAILED", str(exc), phase="gui", exception=type(exc).__name__)
            self.messagebox.showerror("Wait capture failed", str(exc))

    def _label_screen(self) -> None:
        value = _prompt_gui_value(self.tk, "Screen label", "Label the current screen", self.session.current_screen_label)
        if value is not None:
            self.session.set_screen_label(value)
            self._status()

    def _label_target(self) -> None:
        value = _prompt_gui_value(self.tk, "Target label", "Label the selected target/control", self.session.pending_target_label)
        if value is not None:
            self.session.set_target_label(value)
            self._status()

    def _label_successor(self) -> None:
        value = _prompt_gui_value(self.tk, "Expected successor", "Label the expected next screen/result", self.session.pending_successor_label)
        if value is not None:
            self.session.set_successor_label(value)
            self._status()

    def _add_note(self) -> None:
        value = _prompt_gui_value(self.tk, "Note", "Add a note to the next step/session")
        if value is not None:
            self.session.add_note(value)
            self._status()

    def _set_progress(self, position: str) -> None:
        value = _prompt_gui_value(self.tk, "Objective progress", f"Set progress {position} (for example 0/20)", self.session.manifest["objective_progress"][position] or "")
        if value is not None:
            self.session.set_objective_progress(position, value)
            self._status()

    def _set_final_control(self) -> None:
        value = _prompt_gui_value(self.tk, "Final row control", "Describe the final Daily row control (for example Claim-ready; Claim untapped)", self.session.manifest["final_row_control_state"] or "")
        if value is not None:
            self.session.set_final_row_control(value)
            self._status()

    def _set_claim(self, state: str) -> None:
        self.session.set_claim_state(state)
        self._status()

    def _complete(self) -> None:
        try:
            self.session.mark_complete()
            self._status()
        except Exception as exc:
            self.messagebox.showerror("Cannot complete", str(exc))

    def _abort(self) -> None:
        self.session.abort()
        self._status()

    def _export(self) -> None:
        try:
            result = self.session.export_zip()
            self.messagebox.showinfo("ZIP verified", json.dumps(result, indent=2, sort_keys=True))
        except Exception as exc:
            self.session._record_error("ZIP_EXPORT_FAILED", str(exc), phase="zip", exception=type(exc).__name__)
            self.messagebox.showerror("ZIP export failed", str(exc))

    def _on_close(self) -> None:
        self.session.interrupt()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb", help="ADB executable path (live mode only)")
    parser.add_argument("--serial", help="explicit BlueStacks ADB serial; never selects the first device")
    parser.add_argument("--mock-image", type=Path, help="local synthetic/non-game PNG; invokes no ADB code")
    parser.add_argument("--flow-id", required=False, default="bluestacks-flow", help="stable flow identifier")
    parser.add_argument("--daily-objective", default="", help="Daily objective being demonstrated")
    parser.add_argument("--post-action-delay", type=float, default=2.0, help="seconds to wait before the after frame")
    parser.add_argument("--record-only", action="store_true", help="capture manual actions without ADB input")
    parser.add_argument("--output-directory", type=Path, default=Path(".local-captures"), help="capture root; sessions are stored below bluestacks/<flow-id>/<UTC-session-id>")
    parser.add_argument("--no-gui", action="store_true", help="create, capture, export, and exit for headless mock verification")
    parser.add_argument("--self-check", action="store_true", help="run pure coordinate translation checks and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_check:
        print(json.dumps(coordinate_self_check(), sort_keys=True))
        return 0
    if args.mock_image and args.serial:
        parser.error("--mock-image and --serial are mutually exclusive")
    if args.post_action_delay < 0:
        parser.error("--post-action-delay must be non-negative")
    try:
        session = CollectorSession(args)
    except Exception as exc:
        print(f"collector initialization failed: {exc}", file=sys.stderr)
        return 2
    if session.manifest["session_status"] == "failed":
        print(json.dumps({"session_directory": str(session.session_dir), "status": "failed", "manifest": str(session.manifest_path)}, sort_keys=True))
        return 1
    if args.no_gui:
        try:
            session.mark_complete()
            result = session.export_zip()
            print(json.dumps({"session_directory": str(session.session_dir), "manifest": str(session.manifest_path), "zip": result}, sort_keys=True))
            return 0
        except Exception as exc:
            session._record_error("HEADLESS_VERIFICATION_FAILED", str(exc), phase="headless", exception=type(exc).__name__)
            print(json.dumps({"session_directory": str(session.session_dir), "status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
            return 1
    try:
        CollectorGUI(session).run()
        return 0
    except CollectorError as exc:
        session._record_error("GUI_UNAVAILABLE", str(exc), phase="gui", exception=type(exc).__name__)
        print(f"GUI unavailable; preserved session at {session.session_dir}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        session._record_error("GUI_FAILED", str(exc), phase="gui", exception=type(exc).__name__)
        print(f"GUI failed; preserved session at {session.session_dir}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
