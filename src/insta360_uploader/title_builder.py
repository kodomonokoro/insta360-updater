"""Builds YouTube titles as "{prefix} - {YYYYMMDD} {NN}", numbering same-day
videos in capture-time order and never reusing a number already recorded
in the processed store (so numbering stays consistent across separate runs).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.processed_store import ProcessedStore

_TIMESTAMP_RE = re.compile(r"(\d{8})_(\d{6})")


def extract_capture_datetime(path: Path) -> datetime:
    match = _TIMESTAMP_RE.search(path.stem)
    if match:
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    return datetime.fromtimestamp(path.stat().st_mtime)


def _title_pattern(prefix: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(prefix)} - (\d{{8}}) (\d{{2}})$")


def assign_titles(
    prefix: str, store: ProcessedStore, new_videos: list[VideoFile]
) -> dict[str, str]:
    pattern = _title_pattern(prefix)
    used_by_date: dict[str, set[int]] = {}
    for record in store.list_all():
        if not record.video_title:
            continue
        match = pattern.match(record.video_title)
        if match:
            used_by_date.setdefault(match.group(1), set()).add(int(match.group(2)))

    videos_with_dt = sorted(
        ((video, extract_capture_datetime(video.path)) for video in new_videos),
        key=lambda item: item[1],
    )

    titles: dict[str, str] = {}
    for video, dt in videos_with_dt:
        date_str = dt.strftime("%Y%m%d")
        used = used_by_date.setdefault(date_str, set())
        seq = 1
        while seq in used:
            seq += 1
        used.add(seq)
        titles[video.key] = f"{prefix} - {date_str} {seq:02d}"

    return titles
