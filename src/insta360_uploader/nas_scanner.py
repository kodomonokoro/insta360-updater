"""Discover already-stitched 360 videos in the NAS folder that Insta360
Studio exports to. No lens-pairing needed here — Studio hands us one
finished file per shot.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = (".mp4", ".mov")


@dataclass(frozen=True)
class VideoFile:
    key: str
    path: Path
    # Non-empty only for camera_scanner.py clips the camera split into
    # multiple .insv files (a long recording hitting its length limit) —
    # `path` is then just the first chapter, kept for display purposes
    # (capture date etc.); intake.py's copy_raw/stitch iterate this
    # instead. Always empty for nas_scanner's own already-stitched .mp4s.
    chapter_paths: tuple[Path, ...] = ()

    @property
    def source_hash(self) -> str:
        """Stable identity for dedupe: filename + size, not full content.
        Covers every chapter when there are several, so adding/losing a
        chapter changes the hash."""
        paths = self.chapter_paths or (self.path,)
        parts = [f"{p.name}:{p.stat().st_size}" for p in paths]
        digest = hashlib.sha256("|".join(parts).encode("utf-8"))
        return digest.hexdigest()


def scan_video_folder(folder: str | Path) -> list[VideoFile]:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"NAS video folder not found: {folder}")

    files = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return [VideoFile(key=p.stem, path=p) for p in files]
