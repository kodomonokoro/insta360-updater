from pathlib import Path

import pytest

from insta360_uploader.nas_scanner import scan_video_folder


def _touch(path: Path, size: int = 0) -> None:
    path.write_bytes(b"0" * size)


def test_lists_video_files(tmp_path):
    _touch(tmp_path / "clip_a.mp4", size=10)
    _touch(tmp_path / "clip_b.mov", size=20)

    videos = scan_video_folder(tmp_path)

    assert {v.key for v in videos} == {"clip_a", "clip_b"}


def test_ignores_non_video_files(tmp_path):
    _touch(tmp_path / "clip_a.mp4")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "clip_a.insv")

    videos = scan_video_folder(tmp_path)

    assert len(videos) == 1
    assert videos[0].key == "clip_a"


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_video_folder(tmp_path / "does-not-exist")


def test_source_hash_changes_with_file_size(tmp_path):
    path = tmp_path / "clip_a.mp4"

    _touch(path, size=5)
    hash_small = scan_video_folder(tmp_path)[0].source_hash

    _touch(path, size=50)
    hash_large = scan_video_folder(tmp_path)[0].source_hash

    assert hash_small != hash_large
