from datetime import datetime
from pathlib import Path

from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.title_builder import assign_titles, extract_capture_datetime


def _touch(path: Path) -> None:
    path.write_bytes(b"0")


def test_extract_capture_datetime_from_filename_pattern(tmp_path):
    path = tmp_path / "VID_20260905_143022_00_010.mp4"
    _touch(path)

    dt = extract_capture_datetime(path)

    assert dt == datetime(2026, 9, 5, 14, 30, 22)


def test_extract_capture_datetime_falls_back_to_mtime(tmp_path):
    path = tmp_path / "renamed_export.mp4"
    _touch(path)

    dt = extract_capture_datetime(path)

    assert dt == datetime.fromtimestamp(path.stat().st_mtime)


def test_assign_titles_numbers_same_day_videos_by_capture_time(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    early = VideoFile(key="a", path=tmp_path / "VID_20260905_090000.mp4")
    late = VideoFile(key="b", path=tmp_path / "VID_20260905_180000.mp4")
    _touch(early.path)
    _touch(late.path)

    # pass them in reverse order to prove sorting by capture time, not input order
    titles = assign_titles("crotchet rest 360", store, [late, early])

    assert titles["a"] == "crotchet rest 360 - 20260905 01"
    assert titles["b"] == "crotchet rest 360 - 20260905 02"


def test_assign_titles_separates_different_dates(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    day1 = VideoFile(key="a", path=tmp_path / "VID_20260905_090000.mp4")
    day2 = VideoFile(key="b", path=tmp_path / "VID_20260906_090000.mp4")
    _touch(day1.path)
    _touch(day2.path)

    titles = assign_titles("crotchet rest 360", store, [day1, day2])

    assert titles["a"] == "crotchet rest 360 - 20260905 01"
    assert titles["b"] == "crotchet rest 360 - 20260906 01"


def test_assign_titles_continues_numbering_across_runs(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.upsert_pending("existing", "hash", video_title="crotchet rest 360 - 20260905 01")

    new_video = VideoFile(key="new", path=tmp_path / "VID_20260905_180000.mp4")
    _touch(new_video.path)

    titles = assign_titles("crotchet rest 360", store, [new_video])

    assert titles["new"] == "crotchet rest 360 - 20260905 02"
