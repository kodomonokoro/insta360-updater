from insta360_uploader.processed_store import (
    STATUS_DONE,
    STATUS_PENDING,
    ProcessedStore,
)


def test_state_is_not_persisted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1")
    store.set_status("clip-1", STATUS_DONE)
    assert ProcessedStore().get("clip-1") is None
    assert list(tmp_path.iterdir()) == []
    store.clear()
    assert store.list_all() == []


def test_upsert_then_mark_done_round_trips(tmp_path):
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")
    assert store.get("clip-1").status == STATUS_PENDING
    assert store.get("clip-1").video_title == "my title 01"

    store.set_status("clip-1", STATUS_DONE, youtube_video_id="abc123", drive_file_id="drive-1")

    assert store.get("clip-1").status == STATUS_DONE
    record = store.get("clip-1")
    assert record.youtube_video_id == "abc123"
    assert record.drive_file_id == "drive-1"


def test_mark_failed_records_error(tmp_path):
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1")
    store.mark_failed("clip-1", "upload crashed")

    record = store.get("clip-1")
    assert record.status == "failed"
    assert record.error == "upload crashed"


def test_rerun_after_failure_resets_to_pending(tmp_path):
    # Title preservation-on-retry is the caller's job now (pipeline.py /
    # camera_pipeline.py resolve the existing title themselves before
    # calling upsert_pending) — upsert_pending just stores whatever title
    # it's given, so this passes the same title the caller would resolve.
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")
    store.mark_failed("clip-1", "boom")

    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")

    record = store.get("clip-1")
    assert record.status == STATUS_PENDING
    assert record.error is None
    assert record.video_title == "my title 01"


def test_upsert_pending_wipes_stale_drive_and_youtube_ids(tmp_path):
    """A fresh run start must not blend a *different* earlier run's
    success into this run's result — e.g. a clip that got as far as Drive
    before, then genuinely fails at copy this time, must not still show
    Drive as done for this run. Safe because upload_file()/upload_video()
    both re-check the live Drive/YouTube state by name before creating
    anything, rather than trusting a cached id."""
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")
    store.set_status("clip-1", STATUS_DONE, youtube_video_id="abc123", drive_file_id="drive-1")

    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")

    record = store.get("clip-1")
    assert record.status == STATUS_PENDING
    assert record.youtube_video_id is None
    assert record.drive_file_id is None


def test_set_status_can_clear_stale_ids(tmp_path):
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1")
    store.set_status("clip-1", STATUS_DONE, youtube_video_id="abc123", drive_file_id="drive-1")

    store.set_status("clip-1", STATUS_PENDING, clear_youtube_video_id=True, clear_drive_file_id=True)

    record = store.get("clip-1")
    assert record.youtube_video_id is None
    assert record.drive_file_id is None


def test_set_status_without_clear_flags_preserves_existing_ids(tmp_path):
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1")
    store.set_status("clip-1", STATUS_DONE, youtube_video_id="abc123", drive_file_id="drive-1")

    store.set_status("clip-1", STATUS_PENDING)

    record = store.get("clip-1")
    assert record.youtube_video_id == "abc123"
    assert record.drive_file_id == "drive-1"


def test_list_all_returns_every_clip(tmp_path):
    store = ProcessedStore()
    store.upsert_pending("clip-1", "hash-1")
    store.upsert_pending("clip-2", "hash-2")

    assert {r.clip_key for r in store.list_all()} == {"clip-1", "clip-2"}
