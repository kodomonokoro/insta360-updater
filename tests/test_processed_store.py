from insta360_uploader.processed_store import (
    STATUS_DONE,
    STATUS_PENDING,
    ProcessedStore,
    default_store_path,
)


def test_default_store_path_is_under_project_data_dir():
    path = default_store_path()
    assert path.name == "processed.json"
    assert path.parent.name == "data"


def test_new_clip_is_not_done(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    assert not store.is_done("clip-1", "hash-1")


def test_upsert_then_mark_done_round_trips(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")
    assert store.get("clip-1").status == STATUS_PENDING
    assert store.get("clip-1").video_title == "my title 01"

    store.set_status("clip-1", STATUS_DONE, youtube_video_id="abc123", drive_file_id="drive-1")

    assert store.is_done("clip-1", "hash-1")
    record = store.get("clip-1")
    assert record.youtube_video_id == "abc123"
    assert record.drive_file_id == "drive-1"


def test_is_done_is_false_if_source_hash_changed(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.upsert_pending("clip-1", "hash-1")
    store.set_status("clip-1", STATUS_DONE)

    assert not store.is_done("clip-1", "hash-2")


def test_mark_failed_records_error(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.upsert_pending("clip-1", "hash-1")
    store.mark_failed("clip-1", "upload crashed")

    record = store.get("clip-1")
    assert record.status == "failed"
    assert record.error == "upload crashed"


def test_rerun_after_failure_resets_to_pending(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.upsert_pending("clip-1", "hash-1", video_title="my title 01")
    store.mark_failed("clip-1", "boom")

    store.upsert_pending("clip-1", "hash-1", video_title="a different title 02")

    record = store.get("clip-1")
    assert record.status == STATUS_PENDING
    assert record.error is None
    assert record.video_title == "my title 01"


def test_list_all_returns_every_clip(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.upsert_pending("clip-1", "hash-1")
    store.upsert_pending("clip-2", "hash-2")

    assert {r.clip_key for r in store.list_all()} == {"clip-1", "clip-2"}
