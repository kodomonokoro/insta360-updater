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

    @property
    def source_hash(self) -> str:
        """Stable identity for dedupe: filename + size, not full content."""
        stat = self.path.stat()
        digest = hashlib.sha256(f"{self.path.name}:{stat.st_size}".encode("utf-8"))
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
