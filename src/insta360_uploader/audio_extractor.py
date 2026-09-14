"""Extract the audio track of a video as an mp3, via ffmpeg.

`output_dir` is normally a NAS path (the mp3 folder next to the video
source) — ffmpeg writes the (small) mp3 there directly over the network,
so no copy of anything lands on local disk.

Wraps ffmpeg the same streaming way stitcher.py wraps MediaSDKTest.exe:
`-progress pipe:1` makes ffmpeg emit clean `key=value` lines instead of its
default human-readable `\r`-updated stats line, so `out_time=HH:MM:SS.ffffff`
can be parsed reliably and turned into a 0-1 fraction against the input's
own duration (probed separately via ffprobe — ffmpeg's `-progress` output
has no notion of "percent done" on its own, only elapsed output time).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from insta360_uploader.process_utils import NO_WINDOW_KWARGS
from insta360_uploader.video_info import probe_duration_seconds

_OUT_TIME_RE = re.compile(r"^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)$")


class AudioExtractionError(RuntimeError):
    pass


def extract_mp3(
    video_path: Path,
    output_dir: Path,
    *,
    output_stem: str | None = None,
    bitrate: str = "192k",
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    progress_callback: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    if shutil.which(ffmpeg_path) is None:
        raise AudioExtractionError(f"ffmpeg not found on PATH (looked for '{ffmpeg_path}')")

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{output_stem or video_path.stem}.mp3"
    part_path = output_path.with_name(output_path.name + ".part")

    # Best-effort (None if ffprobe is missing/fails) — progress just never
    # fires in that case, same as everywhere else duration is optional.
    duration = probe_duration_seconds(video_path, ffprobe_path)

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "mp3",
        str(part_path),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        **NO_WINDOW_KWARGS,
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip("\n")
        output_lines.append(line)
        if log:
            log(line)
        match = _OUT_TIME_RE.match(line)
        if match and duration and progress_callback:
            hours, minutes, seconds = match.groups()
            elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            progress_callback(min(elapsed / duration, 1.0))
    return_code = process.wait()

    if return_code != 0 or not part_path.is_file():
        part_path.unlink(missing_ok=True)
        raise AudioExtractionError(
            f"audio extraction failed for {video_path} (exit code {return_code}).\n"
            + "\n".join(output_lines[-20:])
        )
    part_path.replace(output_path)
    return output_path
