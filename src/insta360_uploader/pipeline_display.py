"""Pure logic for rendering a per-video pipeline mini-status string for the
GUI, e.g. "✓発見 → ✓音声 → ●Drive → ○YouTube". Kept separate from gui.py
so it's testable without Tkinter.

Drive/YouTube completion is read from the record's drive_file_id /
youtube_video_id (set exactly when those uploads succeed) rather than the
live `status` string, since those two fields stay authoritative even after
the record moves on to later stages or finishes. "音声" (audio extraction)
has no such dedicated flag, so it's inferred from status having reached
STATUS_UPLOADING_AUDIO or later.
"""
from __future__ import annotations

from insta360_uploader.processed_store import (
    STATUS_EXTRACTING_AUDIO,
    STATUS_FAILED,
    STATUS_UPLOADING_AUDIO,
    STATUS_UPLOADING_VIDEO,
    ClipRecord,
)

STAGES_WITH_DRIVE = ("発見", "音声", "Drive", "YouTube")
STAGES_WITHOUT_DRIVE = ("発見", "YouTube")

_CURRENT_STAGE_BY_STATUS = {
    STATUS_EXTRACTING_AUDIO: "音声",
    STATUS_UPLOADING_AUDIO: "Drive",
    STATUS_UPLOADING_VIDEO: "YouTube",
}


def build_pipeline_text(record: ClipRecord | None, drive_enabled: bool) -> str:
    stages = STAGES_WITH_DRIVE if drive_enabled else STAGES_WITHOUT_DRIVE

    if record is None:
        return " → ".join(f"○{stage}" for stage in stages)

    done = {"発見": True, "YouTube": record.youtube_video_id is not None}
    if drive_enabled:
        done["音声"] = (
            record.status in (STATUS_UPLOADING_AUDIO, STATUS_UPLOADING_VIDEO)
            or record.drive_file_id is not None
            or record.youtube_video_id is not None
        )
        done["Drive"] = record.drive_file_id is not None

    current_stage = _CURRENT_STAGE_BY_STATUS.get(record.status)
    failed = record.status == STATUS_FAILED

    parts = []
    failure_shown = False
    for stage in stages:
        if done.get(stage):
            parts.append(f"✓{stage}")
        elif stage == current_stage:
            parts.append(f"●{stage}")
        elif failed and not failure_shown:
            parts.append(f"✗{stage}")
            failure_shown = True
        else:
            parts.append(f"○{stage}")
    return " → ".join(parts)
