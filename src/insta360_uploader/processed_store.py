"""In-memory execution state only. No history is read or persisted.

The legacy class name remains for pipeline callers. Artifact existence,
not these records, determines the displayed completion state.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

STATUS_COPYING_RAW = "copying_raw"
STATUS_STITCHING = "stitching"
STATUS_PENDING = "pending"
STATUS_UPLOADING_VIDEO = "uploading_video"
STATUS_EXTRACTING_AUDIO = "extracting_audio"
STATUS_UPLOADING_AUDIO = "uploading_audio"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ClipRecord:
    clip_key: str
    source_files_hash: str
    status: str
    video_title: str | None = None
    youtube_video_id: str | None = None
    drive_file_id: str | None = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    # The status right before mark_failed() overwrote it to STATUS_FAILED —
    # otherwise a failure late in the pipeline (e.g. the YouTube upload)
    # would erase all evidence that copy/stitch had already succeeded. None
    # for records from before this field existed, or that never failed.
    last_status: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessedStore:
    def __init__(self):
        self._data = {}

    def clear(self) -> None:
        self._data = {}

    def _read(self) -> dict[str, dict]:
        return deepcopy(self._data)

    def _write(self, data: dict[str, dict]) -> None:
        self._data = data

    def get(self, clip_key: str) -> ClipRecord | None:
        data = self._read()
        record = data.get(clip_key)
        return ClipRecord(**record) if record else None

    def upsert_pending(
        self, clip_key: str, source_files_hash: str, video_title: str | None = None
    ) -> None:
        """Create or reset a clip's tracking row for a fresh run.

        `video_title` is passed in already resolved by the caller (which
        reads the prior record itself before this reset, if one exists) —
        a retry keeps the same YouTube title instead of renumbering it.

        `youtube_video_id`/`drive_file_id` are deliberately NOT preserved
        here — every real run start wipes them, so the GUI never blends
        "what actually happened this run" with a stale result left over
        from a completely different earlier run/pipeline for the same
        clip (that confusion was a real reported bug). This is safe:
        `gdrive_uploader.upload_file()`/`youtube_uploader.upload_video()`
        both independently re-check the live Drive/YouTube state by name
        before creating anything (see their own docstrings/comments), and
        `copy_raw()`/`stitch()`/`extract_audio()` each check the actual
        destination file's existence — so a wiped cache costs a few extra
        by-name lookups on retry, never a duplicate upload or re-copy.
        """
        data = self._read()
        existing = data.get(clip_key)
        now = _now()
        record = ClipRecord(
            clip_key=clip_key,
            source_files_hash=source_files_hash,
            status=STATUS_PENDING,
            video_title=video_title,
            youtube_video_id=None,
            drive_file_id=None,
            error=None,
            created_at=existing.get("created_at") if existing else now,
            updated_at=now,
            last_status=None,
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
        clear_youtube_video_id: bool = False,
        clear_drive_file_id: bool = False,
    ) -> None:
        """`youtube_video_id`/`drive_file_id` are only ever set here, never
        cleared by simply omitting them (omitting keeps whatever was there
        before). Use `clear_youtube_video_id`/`clear_drive_file_id` when a
        previously-recorded id is being deliberately redone (e.g. it no
        longer exists on YouTube/Drive) — otherwise the stale id lingers
        and makes the GUI show that stage as already done while the new
        upload is still in progress.
        """
        data = self._read()
        record = data[clip_key]
        record["status"] = status
        if clear_youtube_video_id:
            record["youtube_video_id"] = None
        elif youtube_video_id is not None:
            record["youtube_video_id"] = youtube_video_id
        if clear_drive_file_id:
            record["drive_file_id"] = None
        elif drive_file_id is not None:
            record["drive_file_id"] = drive_file_id
        record["updated_at"] = _now()
        self._write(data)

    def mark_failed(self, clip_key: str, error: str) -> None:
        data = self._read()
        record = data[clip_key]
        if record["status"] != STATUS_FAILED:
            record["last_status"] = record["status"]
        record["status"] = STATUS_FAILED
        record["error"] = error
        record["updated_at"] = _now()
        self._write(data)

    def list_all(self) -> list[ClipRecord]:
        data = self._read()
        records = [ClipRecord(**record) for record in data.values()]
        return sorted(records, key=lambda r: r.created_at)
