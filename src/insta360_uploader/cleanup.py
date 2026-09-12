"""Find local cleanup candidates by verifying remote artifacts, never history.

Age means the newest local artifact's modification time. Network failures
abort discovery instead of treating an unverified upload as complete.
Deletion still requires the GUI confirmation.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from insta360_uploader.config import AppConfig
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.artifact_status import make_target, RemoteArtifacts
from insta360_uploader.nas_scanner import scan_video_folder


@dataclass(frozen=True)
class StaleClip:
    clip_key: str
    files: list[Path]


def _clip_files(clip_key: str, video_title: str | None, config: AppConfig) -> list[Path]:
    # A multi-chapter camera recording's clip_key (see camera_scanner.py)
    # doesn't match any single raw filename — every chapter's raw .insv
    # (and, if a stitch was interrupted, its leftover intermediate .mp4)
    # is instead named `<clip_key>_<lens+type>_<seq>`, so glob by prefix
    # rather than assume one exact file. Harmless for a single-chapter
    # clip too, since its raw filename equals clip_key exactly.
    candidates = []
    if config.raw_folder is not None and config.raw_folder.is_dir():
        candidates += config.raw_folder.glob(f"{clip_key}*.insv")
        candidates += config.raw_folder.glob(f"{clip_key}*.mp4")
    candidates += [
        config.nas_video_folder / f"{clip_key}.mp4",
        config.nas_video_folder / "_retagged" / f"{clip_key}_360.mp4",
    ]
    if video_title and config.mp3_folder is not None:
        candidates.append(config.mp3_folder / f"{video_title}.mp3")
    return [p for p in candidates if p.is_file()]


def find_stale_clips(
    store: ProcessedStore, config: AppConfig, retention_days: int
) -> list[StaleClip]:
    """Fully-done clips whose files are older than `retention_days`."""
    return _find_verified_clips(config, retention_days)


def find_orphaned_part_files(*folders: Path) -> list[Path]:
    """Leftover `*.part` files from an interrupted copy/stitch — unusable
    regardless of age, safe to delete without asking."""
    orphaned: list[Path] = []
    for folder in folders:
        if folder.is_dir():
            orphaned.extend(sorted(folder.rglob("*.part")))
    return orphaned


def find_all_clip_files(store: ProcessedStore, config: AppConfig) -> list[StaleClip]:
    """Every done clip's intermediate files, regardless of age — backs the
    Settings screen's manual "delete everything now" button."""
    return _find_verified_clips(config, None)


def _find_verified_clips(config: AppConfig, retention_days: int | None) -> list[StaleClip]:
    if not config.nas_video_folder.is_dir():
        return []
    remote = RemoteArtifacts(config)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).timestamp() if retention_days is not None else None
    result = []
    for video in scan_video_folder(config.nas_video_folder):
        target = make_target(video, config)
        files = _clip_files(video.key, target.title, config)
        if not files or (cutoff is not None and any(p.stat().st_mtime > cutoff for p in files)):
            continue
        if not remote.youtube_exists(target):
            continue
        if config.drive is not None and not remote.drive_exists(target):
            continue
        result.append(StaleClip(video.key, files))
    return result


def count_files(folder: Path) -> int:
    """How many files (not directories) sit anywhere under folder — used
    to show a real number in the confirmation prompt before
    clear_folder_contents() runs."""
    return sum(1 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0


def clear_folder_contents(folder: Path) -> int:
    """Unconditionally deletes everything inside folder (files and
    subfolders alike) — unlike find_stale_clips/find_all_clip_files, this
    never checks whether anything was actually uploaded first. The
    Settings screen only calls this after the user confirms an explicit
    "clear this folder" action, one specific folder (raw/mp4/mp3) at a
    time — folder itself is left in place, just emptied. Returns how many
    files were removed."""
    if not folder.is_dir():
        return 0
    removed = 0
    for child in folder.iterdir():
        if child.is_dir():
            file_count = sum(1 for p in child.rglob("*") if p.is_file())
            shutil.rmtree(child, ignore_errors=True)
            if not child.exists():
                removed += file_count
        else:
            try:
                child.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    return removed


def delete_files(paths: list[Path]) -> list[Path]:
    """Deletes each path that still exists; returns what was actually
    removed (some may have vanished between finding and deleting)."""
    deleted = []
    for path in paths:
        try:
            path.unlink()
            deleted.append(path)
        except FileNotFoundError:
            pass
    return deleted
