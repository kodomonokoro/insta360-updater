from pathlib import Path

import pytest

from insta360_uploader import camera_scanner


def _touch(path: Path, size: int = 0) -> None:
    path.write_bytes(b"0" * size)


def test_lists_insv_files(tmp_path):
    _touch(tmp_path / "VID_20260908_120000_00_001.insv", size=10)
    _touch(tmp_path / "VID_20260908_120000_00_001.lrv", size=1)

    videos = camera_scanner.scan_camera_folder(tmp_path)

    assert [v.key for v in videos] == ["VID_20260908_120000_00_001"]
    # Single-chapter clip: chapter_paths still holds the one file, so
    # intake.py's copy_raw/stitch can iterate it unconditionally.
    assert videos[0].chapter_paths == (videos[0].path,)


def test_ignores_non_insv_files(tmp_path):
    _touch(tmp_path / "clip.insv")
    _touch(tmp_path / "clip.mp4")
    _touch(tmp_path / "notes.txt")

    videos = camera_scanner.scan_camera_folder(tmp_path)

    assert len(videos) == 1
    assert videos[0].key == "clip"


def test_groups_chapters_sharing_the_same_recording_start_time(tmp_path):
    # A long recording the camera split into two files: same date_time,
    # different (camera-wide, never reset) trailing sequence number.
    _touch(tmp_path / "VID_20260906_131910_00_005.insv", size=5)
    _touch(tmp_path / "VID_20260906_131910_00_006.insv", size=6)
    # An unrelated single-chapter recording must not get pulled in.
    _touch(tmp_path / "VID_20260906_142310_00_007.insv", size=7)

    videos = camera_scanner.scan_camera_folder(tmp_path)

    assert [v.key for v in videos] == ["VID_20260906_131910", "VID_20260906_142310_00_007"]
    grouped = videos[0]
    assert [p.name for p in grouped.chapter_paths] == [
        "VID_20260906_131910_00_005.insv",
        "VID_20260906_131910_00_006.insv",
    ]
    # `path` is the first chapter — used for capture-date display.
    assert grouped.path == grouped.chapter_paths[0]
    single = videos[1]
    assert single.chapter_paths == (single.path,)


def test_single_chapter_key_unchanged_by_grouping_logic(tmp_path):
    # A lone chapter (no sibling sharing its date_time) must keep the
    # exact old key format — existing processed-store records depend on it.
    _touch(tmp_path / "VID_20260905_153205_00_004.insv")

    videos = camera_scanner.scan_camera_folder(tmp_path)

    assert [v.key for v in videos] == ["VID_20260905_153205_00_004"]


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        camera_scanner.scan_camera_folder(tmp_path / "does-not-exist")


def test_find_camera_drive_returns_first_matching_drive(monkeypatch):
    def fake_is_dir(self):
        return str(self).replace("\\", "/") == "E:/DCIM/Camera01"

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    found = camera_scanner.find_camera_drive()

    assert found is not None
    assert str(found).replace("\\", "/") == "E:/DCIM/Camera01"


def test_find_camera_drive_returns_none_when_not_connected(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    assert camera_scanner.find_camera_drive() is None
