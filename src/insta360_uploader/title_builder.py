"""Builds YouTube titles as "{prefix} - {YYYYMMDD} {HHMM}", using the
video's actual capture start time rather than a per-day sequence number.

A sequence number (01, 02, ...) was tried first, numbered in capture-time
order — but that order only holds if same-day videos are all processed
together in one run. Insta360 Studio's export is slow enough that videos
get uploaded one at a time as each finishes, in whatever order that happens
to be, so a per-day counter can end up out of chronological order across
separate runs. The capture time itself doesn't have that problem: it's
already unique to the minute for a single camera and never depends on
processing order.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from insta360_uploader.nas_scanner import VideoFile

_TIMESTAMP_RE = re.compile(r"(\d{8})_(\d{6})")


def extract_capture_datetime(path: Path) -> datetime:
    match = _TIMESTAMP_RE.search(path.stem)
    if match:
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    return datetime.fromtimestamp(path.stat().st_mtime)


def title_for_video(prefix: str, video: VideoFile) -> str:
    """Derive the stable destination title from this source video alone."""
    return f"{prefix} - {extract_capture_datetime(video.path).strftime('%Y%m%d %H%M')}"


def assign_titles(prefix: str, new_videos: list[VideoFile]) -> dict[str, str]:
    return {video.key: title_for_video(prefix, video) for video in new_videos}
