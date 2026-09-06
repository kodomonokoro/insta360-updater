from insta360_uploader.pipeline_display import build_pipeline_text
from insta360_uploader.processed_store import (
    STATUS_DONE,
    STATUS_EXTRACTING_AUDIO,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_UPLOADING_AUDIO,
    STATUS_UPLOADING_VIDEO,
    ClipRecord,
)


def _record(status, *, drive_file_id=None, youtube_video_id=None):
    return ClipRecord(
        clip_key="k",
        source_files_hash="h",
        status=status,
        video_title="t",
        youtube_video_id=youtube_video_id,
        drive_file_id=drive_file_id,
        error=None,
        created_at="",
        updated_at="",
    )


def test_no_record_yet_without_drive():
    assert build_pipeline_text(None, drive_enabled=False) == "○発見 → ○YouTube"


def test_no_record_yet_with_drive():
    assert (
        build_pipeline_text(None, drive_enabled=True)
        == "○発見 → ○音声 → ○Drive → ○YouTube"
    )


def test_pending_with_drive():
    record = _record(STATUS_PENDING)
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ○音声 → ○Drive → ○YouTube"


def test_extracting_audio_shows_current_stage():
    record = _record(STATUS_EXTRACTING_AUDIO)
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ●音声 → ○Drive → ○YouTube"


def test_uploading_audio_shows_audio_done_and_drive_current():
    record = _record(STATUS_UPLOADING_AUDIO)
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ✓音声 → ●Drive → ○YouTube"


def test_uploading_video_with_drive_already_done():
    record = _record(STATUS_UPLOADING_VIDEO, drive_file_id="d1")
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ✓音声 → ✓Drive → ●YouTube"


def test_done_with_drive():
    record = _record(STATUS_DONE, drive_file_id="d1", youtube_video_id="y1")
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ✓音声 → ✓Drive → ✓YouTube"


def test_done_without_drive():
    record = _record(STATUS_DONE, youtube_video_id="y1")
    assert build_pipeline_text(record, drive_enabled=False) == "✓発見 → ✓YouTube"


def test_failed_before_drive_upload():
    record = _record(STATUS_FAILED)
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ✗音声 → ○Drive → ○YouTube"


def test_failed_after_drive_succeeded():
    record = _record(STATUS_FAILED, drive_file_id="d1")
    assert build_pipeline_text(record, drive_enabled=True) == "✓発見 → ✓音声 → ✓Drive → ✗YouTube"


def test_failed_without_drive():
    record = _record(STATUS_FAILED)
    assert build_pipeline_text(record, drive_enabled=False) == "✓発見 → ✗YouTube"
