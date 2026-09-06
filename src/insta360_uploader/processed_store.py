"""JSON-backed record of what has been processed, to avoid reprocessing
and to answer `insta360-uploader status`. Never deletes source footage —
this module only tracks state about it.

A plain JSON file (rather than SQLite) since this is a single-user,
single-process tool processing at most a few hundred videos — the whole
file is small enough to read/rewrite each time, and it's easy to open and
read directly if something looks wrong.

No path needs to be configured: by default the file lives in a `data/`
folder next to wherever this package is installed, so nothing here depends
on an absolute path in config.yaml.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

STATUS_PENDING = "pending"
STATUS_UPLOADING_VIDEO = "uploading_video"
STATUS_EXTRACTING_AUDIO = "extracting_audio"
STATUS_UPLOADING_AUDIO = "uploading_audio"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def default_store_path() -> Path:
    """<project root>/data/processed.json — project root is three levels
    up from this file (src/insta360_uploader/processed_store.py -> src ->
    project root)."""
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "processed.json"


@dataclass(frozen=True)
class ClipRecord:
    """`drive_file_id` (and `youtube_video_id`) are a cache/reference, not
    a source of truth: they let the GUI render status and let the
    pipeline skip a costly re-extraction+re-check without hitting the
    Drive/YouTube API on every video, every run. They must never be
    trusted on their own to decide "is this actually still there" —
    see gdrive_uploader.file_exists() and pipeline.process_video(), which
    always re-verify against the live Drive state before skipping or
    creating anything. If you change this file, keep that verification —
    do not turn `drive_file_id is not None` back into "definitely uploaded,
    skip unconditionally" (that was a real bug once; see git history /
    project memory on this).
    """

    clip_key: str
    source_files_hash: str
    status: str
    video_title: str | None = None
    youtube_video_id: str | None = None
    drive_file_id: str | None = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessedStore:
    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path is not None else default_store_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.is_file():
            self._write({})

    def _read(self) -> dict[str, dict]:
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict[str, dict]) -> None:
        # write to a temp file then replace, so a crash mid-write can't
        # corrupt the existing file
        tmp_path = self._path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self._path)

    def get(self, clip_key: str) -> ClipRecord | None:
        data = self._read()
        record = data.get(clip_key)
        return ClipRecord(**record) if record else None

    def is_done(self, clip_key: str, source_files_hash: str) -> bool:
        record = self.get(clip_key)
        return (
            record is not None
            and record.status == STATUS_DONE
            and record.source_files_hash == source_files_hash
        )

    def upsert_pending(
        self, clip_key: str, source_files_hash: str, video_title: str | None = None
    ) -> None:
        """Create or reset a clip's tracking row.

        `video_title` is only stored the first time a clip is seen — a
        retry never overwrites an already-assigned title, so re-running
        after a failure keeps the same YouTube title instead of
        renumbering it.
        """
        data = self._read()
        existing = data.get(clip_key)
        now = _now()
        record = ClipRecord(
            clip_key=clip_key,
            source_files_hash=source_files_hash,
            status=STATUS_PENDING,
            video_title=(existing.get("video_title") if existing else None) or video_title,
            youtube_video_id=existing.get("youtube_video_id") if existing else None,
            drive_file_id=existing.get("drive_file_id") if existing else None,
            error=None,
            created_at=existing.get("created_at") if existing else now,
            updated_at=now,
        )
        data[clip_key] = asdict(record)
        self._write(data)

    def set_status(
        self,
        clip_key: str,
        status: str,
        *,
        youtube_video_id: str | None = None,
        drive_file_id: str | None = None,
    ) -> None:
        data = self._read()
        record = data[clip_key]
        record["status"] = status
        if youtube_video_id is not None:
            record["youtube_video_id"] = youtube_video_id
        if drive_file_id is not None:
            record["drive_file_id"] = drive_file_id
        record["updated_at"] = _now()
        self._write(data)

    def mark_failed(self, clip_key: str, error: str) -> None:
        data = self._read()
        record = data[clip_key]
        record["status"] = STATUS_FAILED
        record["error"] = error
        record["updated_at"] = _now()
        self._write(data)

    def list_all(self) -> list[ClipRecord]:
        data = self._read()
        records = [ClipRecord(**record) for record in data.values()]
        return sorted(records, key=lambda r: r.created_at)
