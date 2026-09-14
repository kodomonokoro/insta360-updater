"""Lightweight video metadata for display in the GUI (duration, file size).

`probe_duration_seconds` is also reused by audio_extractor.py to turn
ffmpeg's `-progress` output into a 0-1 fraction (elapsed / total duration).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from insta360_uploader.process_utils import NO_WINDOW_KWARGS


def probe_duration_seconds(path: Path, ffprobe_path: str = "ffprobe") -> float | None:
    """Best-effort: None if ffprobe is missing or fails, never raises."""
    if shutil.which(ffprobe_path) is None:
        return None

    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        **NO_WINDOW_KWARGS,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def probe_resolution_fps(path: Path, ffprobe_path: str = "ffprobe") -> tuple[int, int, float | None] | None:
    """Best-effort: None if ffprobe is missing or fails, never raises.

    fps is the stream's own declared (`r_frame_rate`) rate, not a computed
    average — for genuinely fixed-rate footage the two agree, but this
    avoids depending on ffprobe having read enough packets to compute an
    average. Callers should only display it once rounded to a whole
    number *and* close enough to trust (see format_resolution) — a
    variable/unusual rate isn't a single meaningful number to show.
    """
    if shutil.which(ffprobe_path) is None:
        return None

    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "default=noprint_wrappers=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        **NO_WINDOW_KWARGS,
    )
    if result.returncode != 0:
        return None

    values: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value

    try:
        width = int(values["width"])
        height = int(values["height"])
        num, _, den = values["r_frame_rate"].partition("/")
        fps = float(num) / float(den) if den and float(den) != 0 else None
    except (KeyError, ValueError):
        return None
    return width, height, fps


# Equirectangular output width -> the "K" label it's marketed as, matching
# stitcher.py's own confirmed profiles (8K=7680, 6K=6016) plus the
# conventional 4K UHD width (3840, matching a Studio "4K" export or a
# still-unverified stitcher profile — see project_insv_resolution_
# verification memory). A small tolerance absorbs minor encoder rounding;
# anything else falls back to raw pixel dimensions rather than guessing.
_RESOLUTION_LABELS = ((7680, "8K"), (6016, "6K"), (3840, "4K"))
_RESOLUTION_LABEL_TOLERANCE = 100


def resolution_label(width: int) -> str | None:
    for known_width, label in _RESOLUTION_LABELS:
        if abs(width - known_width) <= _RESOLUTION_LABEL_TOLERANCE:
            return label
    return None


def format_resolution(width: int, height: int, fps: float | None, *, label: str | None = None) -> str:
    """Omits fps entirely unless it's close to a whole number — a source
    reporting a genuinely variable/unusual rate has no single fps worth
    showing, and showing a misleadingly-precise decimal (e.g. "29.97")
    reads as more meaningful than it is.

    `label` overrides the width-based lookup — needed for a raw .insv's
    per-lens track width, which doesn't correspond to any equirect "K"
    bucket directly (e.g. a 3840px lens track stitches to 8K, not 4K);
    callers probing a raw file should pass stitcher.detect_profile_label's
    result here instead of letting this derive one from `width`.
    """
    label = label or resolution_label(width) or f"{width}x{height}"
    if fps is not None and abs(fps - round(fps)) < 0.05:
        return f"{label} {round(fps)}fps"
    return label


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"  # pragma: no cover - unreachable for realistic file sizes
