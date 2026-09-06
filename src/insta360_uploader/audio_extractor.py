"""Extract the audio track of a video as an mp3, via ffmpeg.

`output_dir` is normally a NAS path (the mp3 folder next to the video
source) — ffmpeg writes the (small) mp3 there directly over the network,
so no copy of anything lands on local disk.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AudioExtractionError(RuntimeError):
    pass


def extract_mp3(
    video_path: Path,
    output_dir: Path,
    *,
    output_stem: str | None = None,
    bitrate: str = "192k",
    ffmpeg_path: str = "ffmpeg",
) -> Path:
    if shutil.which(ffmpeg_path) is None:
        raise AudioExtractionError(f"ffmpeg not found on PATH (looked for '{ffmpeg_path}')")

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{output_stem or video_path.stem}.mp3"

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
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not output_path.is_file():
        raise AudioExtractionError(
            f"audio extraction failed for {video_path} (exit code {result.returncode}).\n"
            f"stderr: {result.stderr}"
        )
    return output_path
