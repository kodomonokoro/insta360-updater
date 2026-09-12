from datetime import datetime
from pathlib import Path

from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.title_builder import assign_titles, extract_capture_datetime, title_for_video


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


def test_assign_titles_uses_capture_start_time(tmp_path):
    early = VideoFile(key="a", path=tmp_path / "VID_20260905_090000.mp4")
    late = VideoFile(key="b", path=tmp_path / "VID_20260905_180000.mp4")
    _touch(early.path)
    _touch(late.path)

    titles = assign_titles("crotchet rest 360", [late, early])

    assert titles["a"] == "crotchet rest 360 - 20260905 0900"
    assert titles["b"] == "crotchet rest 360 - 20260905 1800"


def test_assign_titles_is_independent_of_input_order():
    # No processed-store lookups involved anymore — each title is derived
    # purely from that video's own capture time, so order shouldn't matter.
    videos = [
        VideoFile(key="b", path=Path("VID_20260906_090000.mp4")),
        VideoFile(key="a", path=Path("VID_20260905_090000.mp4")),
    ]

    titles = assign_titles("crotchet rest 360", videos)

    assert titles["a"] == "crotchet rest 360 - 20260905 0900"
    assert titles["b"] == "crotchet rest 360 - 20260906 0900"


def test_title_for_video_depends_only_on_its_source_name(tmp_path):
    video = VideoFile("VID_20260905_153205", tmp_path / "VID_20260905_153205_00_001.insv")
    assert title_for_video("crotchet rest 360", video) == "crotchet rest 360 - 20260905 1532"
