"""Stitch a raw Insta360 .insv into a 360 .mp4, via MediaSDKTest.exe (part
of Insta360's official MediaSDK — the same engine Insta360 Studio's own
"360 Panorama" export uses internally).

MediaSDKTest is a plain CLI tool (not a library binding), so this wraps it
the same way audio_extractor.py wraps ffmpeg: subprocess, not ctypes/pybind.
Progress is reported on stdout as `process = 8%` lines (confirmed against
real MediaSDKTest.exe output — an earlier assumed `progress: 0.42; finished:
false` format never actually matched anything).

Output-quality settings (-output_size/-bitrate/-enable_h265_encoder/
-stitch_type aistitch/-enable_flowstate/-enable_denoise/
-enable_stitchfusion/-camera_accessory_type) come from a real comparison
against Insta360 Studio's own output — see
`analysis/insta360-studio-match/results/comparison.md` for the full
methodology, source files, and caveats. In short:

- **8K** (per-lens raw track 3840x3840 -> 7680x3840 output, 154 Mbps):
  verified against Studio's actual 705-frame output on the same source
  file. SSIM 0.981903 / PSNR 41.82 dB against Studio — a close match, NOT
  a confirmed pixel-identical reproduction. Do not describe this as
  "identical to Studio" anywhere (GUI, logs, docs).
  ~2% of samples still differ.
- **6K** (per-lens raw track 3008x3008 -> 6016x3008 output, 50 Mbps): the
  bitrate matches Studio's own HEVC HRD header value (not just an average-
  bitrate guess), but only the trailing ~148s of one chapter was compared
  — a ~1px spatial offset and second-by-second bitrate-variation mismatch
  remain unresolved, and the long first chapter was never independently
  verified at this setting. Treat 50 Mbps as this clip's best candidate,
  not a confirmed default for all 6K footage.

Both profiles were derived by testing against ONE clip each — not a
systematic sweep across all X4 Air recording modes. Any per-lens track
width other than the two confirmed below is deliberately treated as
unrecognized (StitchError) rather than guessed at via the width-doubling
formula alone (see [[project_insv_resolution_verification]] memory for why
that formula, while plausible, isn't itself sufficient to derive a
bitrate).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from insta360_uploader.config import MediaSdkConfig

_PROGRESS_RE = re.compile(r"process\s*=\s*(\d+(?:\.\d+)?)%")


class StitchError(RuntimeError):
    pass


@dataclass(frozen=True)
class _StitchProfile:
    label: str
    output_size: str
    bitrate: int


# Per-lens raw track width (both video streams in the .insv are this exact
# WxW square) -> confirmed output profile. See module docstring for the
# comparison methodology behind each entry. Deliberately NOT a formula
# (e.g. "double the track width") — only resolutions actually verified
# against real Studio output are listed; anything else raises StitchError.
_PROFILES_BY_TRACK_WIDTH: dict[int, _StitchProfile] = {
    3840: _StitchProfile(label="8K", output_size="7680x3840", bitrate=154_000_000),
    3008: _StitchProfile(label="6K", output_size="6016x3008", bitrate=50_000_000),
}

# Flags shared by every resolution profile. Framerate is deliberately never
# specified here — MediaSDKTest has no CLI flag for it (confirmed via
# `-help` and example/main.cc's argument parser) and preserves the source's
# own framerate by default; do not add one to force 30fps.
_COMMON_STITCH_ARGS = [
    "-stitch_type",
    "aistitch",
    "-enable_flowstate",
    "-enable_denoise",
    "-enable_stitchfusion",
    "-camera_accessory_type",
    "0",
]


def _probe_lens_track_widths(insv_path: Path, ffprobe_path: str) -> list[int]:
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(insv_path),
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        raise StitchError(f"failed to probe {insv_path} for lens resolution: {result.stderr}")
    try:
        streams = json.loads(result.stdout)["streams"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise StitchError(f"unexpected ffprobe output for {insv_path}: {exc}") from exc

    # Every lens stream must be present and square — checking every stream
    # (not just the first) is the point: a lopsided or partial read here
    # must not silently fall through to picking a profile off one number.
    if len(streams) != 2:
        raise StitchError(
            f"{insv_path}: expected 2 lens video streams, found {len(streams)} "
            f"({streams}) — unrecognized .insv structure, refusing to guess an output profile"
        )
    widths = []
    for stream in streams:
        width, height = stream.get("width"), stream.get("height")
        if width is None or height is None or width != height:
            raise StitchError(
                f"{insv_path}: lens stream is not a square frame ({stream}) — "
                "unrecognized .insv structure, refusing to guess an output profile"
            )
        widths.append(width)
    return widths


def _detect_stitch_profile(insv_path: Path, ffprobe_path: str) -> _StitchProfile:
    widths = _probe_lens_track_widths(insv_path, ffprobe_path)
    if widths[0] != widths[1]:
        raise StitchError(
            f"{insv_path}: the 2 lens streams have different resolutions ({widths}) — "
            "unrecognized .insv structure, refusing to guess an output profile"
        )
    track_width = widths[0]
    profile = _PROFILES_BY_TRACK_WIDTH.get(track_width)
    if profile is None:
        raise StitchError(
            f"{insv_path}: unrecognized per-lens track width {track_width}px — "
            f"no verified stitch profile for this resolution (known: "
            f"{sorted(_PROFILES_BY_TRACK_WIDTH)}px). See "
            "analysis/insta360-studio-match/ to add a new verified profile "
            "rather than guessing one from the width-doubling formula alone."
        )
    return profile


def detect_profile_label(insv_path: Path, ffprobe_path: str = "ffprobe") -> str | None:
    """Best-effort, non-raising: the label (e.g. "8K") this raw .insv would
    stitch to, based on its per-lens track width — the same lookup
    stitch_to_mp4() uses internally, exposed so the GUI can show a
    predicted resolution before stitching has actually happened. None on
    any failure (ffprobe missing, unrecognized structure, unverified
    width) rather than guessing — see _detect_stitch_profile's own
    docstring for why an unknown width is never guessed at.
    """
    try:
        return _detect_stitch_profile(insv_path, ffprobe_path).label
    except StitchError:
        return None


def _verify_stitched_output(part_path: Path, profile: _StitchProfile, ffprobe_path: str) -> None:
    """Exit code 0 + a file existing isn't proof MediaSDKTest actually
    wrote a usable video at the resolution we asked for — confirm both the
    resolution and that the file has real duration before treating a run
    as successful."""
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(part_path),
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        raise StitchError(f"could not verify stitched output {part_path}: ffprobe failed: {result.stderr}")
    try:
        info = json.loads(result.stdout)
        stream = info["streams"][0]
        duration = float(info["format"]["duration"])
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as exc:
        raise StitchError(f"could not verify stitched output {part_path}: unexpected ffprobe result ({exc})") from exc

    expected_width, expected_height = (int(x) for x in profile.output_size.split("x"))
    if stream.get("width") != expected_width or stream.get("height") != expected_height:
        raise StitchError(
            f"stitched output {part_path} is {stream.get('width')}x{stream.get('height')}, "
            f"expected {profile.output_size} ({profile.label} profile)"
        )
    if duration <= 0:
        raise StitchError(f"stitched output {part_path} has zero/invalid duration")


def stitch_to_mp4(
    insv_path: Path,
    output_path: Path,
    *,
    media_sdk: MediaSdkConfig,
    progress_callback: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
    ffprobe_path: str = "ffprobe",
) -> Path:
    if not media_sdk.exe_path.is_file():
        raise StitchError(f"MediaSDKTest.exe not found: {media_sdk.exe_path}")
    if shutil.which(ffprobe_path) is None:
        raise StitchError(f"ffprobe not found on PATH (looked for '{ffprobe_path}')")

    insv_path, output_path = Path(insv_path), Path(output_path)

    profile = _detect_stitch_profile(insv_path, ffprobe_path)
    if log:
        log(
            f"detected {profile.label} source ({insv_path.name}) -> "
            f"output_size={profile.output_size}, bitrate={profile.bitrate}bps, H.265"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Write under a working name so a crash/kill mid-stitch never leaves a
    # file sitting at the final name that looks done but isn't.
    part_path = output_path.with_name(output_path.name + ".part")

    command = [
        str(media_sdk.exe_path),
        "-inputs",
        str(insv_path),
        "-output",
        str(part_path),
        "-model_root_dir",
        str(media_sdk.model_root_dir),
        "-output_size",
        profile.output_size,
        "-enable_h265_encoder",
        "-bitrate",
        str(profile.bitrate),
        *_COMMON_STITCH_ARGS,
    ]
    if log:
        log("running: " + " ".join(command))

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",  # never let an undecodable byte from MediaSDKTest's own output kill the stitch
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip("\n")
        output_lines.append(line)
        if log:
            log(line)
        match = _PROGRESS_RE.search(line)
        if match and progress_callback:
            progress_callback(float(match.group(1)) / 100)
    return_code = process.wait()

    if return_code != 0 or not part_path.is_file():
        part_path.unlink(missing_ok=True)
        raise StitchError(
            f"stitching failed for {insv_path} (exit code {return_code}).\n"
            + "\n".join(output_lines[-20:])
        )

    try:
        _verify_stitched_output(part_path, profile, ffprobe_path)
    except StitchError:
        part_path.unlink(missing_ok=True)
        raise

    part_path.replace(output_path)
    return output_path
