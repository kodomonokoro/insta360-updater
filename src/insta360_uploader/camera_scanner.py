"""Discover raw .insv files on an Insta360 camera connected as a plain USB
mass-storage drive (same idea as an SD card reader — no CameraSDK needed).

Insta360 cameras (confirmed for the X4 Air) mount with a `DCIM/Camera01`
folder holding one `.insv` (master 360 footage) plus a `.lrv` (low-res
preview, phone-app only, not needed for stitching) per clip. Drive letters
aren't stable across USB (re)connections, so the drive itself is found by
scanning for that folder shape rather than being configured.

A recording longer than the camera's per-file limit (observed ~30 minutes)
is split into multiple .insv files ("chapters"), e.g.
VID_20260906_131910_00_005.insv + VID_20260906_131910_00_006.insv. Per
Insta360's official filename docs (onlinemanual.insta360.com, X-series
file formats) the format is VID_<date>_<time>_<lens><master/proxy>_<seq>,
and the trailing <seq> is a camera-wide counter that is never reset per
recording — so it cannot be used to detect where one recording ends and
the next begins. What *is* shared across every chapter of one recording,
confirmed against real chaptered footage, is the <date>_<time> (recording
start) portion. Insta360 Studio's own folder import already presents
chaptered recordings as a single merged clip, which this grouping mirrors.
MediaSDK itself has no API to join chapters into one stitched output in a
single call — confirmed unsupported (open feature request, no built-in
workaround) via Insta360's own MediaSDK-Cpp issue tracker, issue #49 — so
each chapter is stitched individually and the results joined afterward;
see intake.py.
"""
from __future__ import annotations

import re
import string
from pathlib import Path

from insta360_uploader.nas_scanner import VideoFile

INSV_EXTENSION = ".insv"
_CAMERA_SUBPATH = Path("DCIM") / "Camera01"

# VID_<YYYYMMDD>_<HHMMSS>_<lens+master/proxy 2 digits>_<seq 3 digits>
_CHAPTER_NAME_RE = re.compile(r"^VID_(\d{8}_\d{6})_\d{2}_\d{3}$")


def find_camera_drive() -> Path | None:
    """Returns the `DCIM/Camera01` folder of the first drive that has one,
    or None if no Insta360-shaped drive is currently connected."""
    for letter in string.ascii_uppercase:
        candidate = Path(f"{letter}:/") / _CAMERA_SUBPATH
        if candidate.is_dir():
            return candidate
    return None


def scan_camera_folder(folder: str | Path) -> list[VideoFile]:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"camera folder not found: {folder}")

    files = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() == INSV_EXTENSION
    ]

    groups: dict[str, list[Path]] = {}
    order: list[str] = []
    for p in files:
        match = _CHAPTER_NAME_RE.match(p.stem)
        # A name that doesn't match the expected pattern can't be grouped
        # by recording start time, so it's treated as its own single-file
        # group (falls back to the old one-file-one-clip behavior) rather
        # than silently merged with something it may not belong to.
        group_key = match.group(1) if match else p.stem
        if group_key not in groups:
            groups[group_key] = []
            order.append(group_key)
        groups[group_key].append(p)

    videos = []
    for group_key in order:
        # Filenames sort correctly by chapter order: the shared date_time
        # prefix is identical within a group, and the trailing <seq> is
        # zero-padded, so plain path sort == chapter order.
        chapters = sorted(groups[group_key])
        # A single-chapter clip keeps its own filename as the key, exactly
        # as before grouping existed — this is the common case, and it
        # must not change so existing processed-store records (keyed by
        # this exact string) keep matching on rescan. Only an actual
        # multi-chapter group gets the new date_time-based group key,
        # since those were never handled correctly before this existed.
        key = f"VID_{group_key}" if len(chapters) > 1 else chapters[0].stem
        videos.append(VideoFile(key=key, path=chapters[0], chapter_paths=tuple(chapters)))
    return videos
