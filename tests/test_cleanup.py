import os
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from insta360_uploader import cleanup
from insta360_uploader.config import AppConfig, YoutubeDefaults, YoutubeProfile
from insta360_uploader.processed_store import STATUS_DONE, ProcessedStore


def _config(tmp_path, *, raw_folder=None, mp3_folder=None) -> AppConfig:
    nas = tmp_path / "crotchet rest" / "processed" / "mp4"
    return AppConfig(
        nas_video_folder=nas,
        youtube=YoutubeProfile(client_secret_path=Path(""), token_path=Path("")),
        youtube_defaults=YoutubeDefaults(
            title_prefix="p", privacy_status="unlisted", made_for_kids=False, playlist_id=None
        ),
        drive=None,
        media_sdk=None,
        retention_days=14,
        raw_folder=raw_folder,
        mp3_folder=mp3_folder,
    )


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0")


@pytest.fixture(autouse=True)
def remote_checks(monkeypatch):
    monkeypatch.setattr(cleanup.RemoteArtifacts, "youtube_exists", lambda self, target: True)
    monkeypatch.setattr(cleanup.RemoteArtifacts, "drive_exists", lambda self, target: True)


def _backdate_file(path, days_ago):
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()
    os.utime(path, (stamp, stamp))


def test_find_stale_clips_only_returns_old_done_clips(tmp_path):
    store = ProcessedStore()
    config = _config(tmp_path)

    store.upsert_pending("old_clip", "h1", video_title="old title")
    store.set_status("old_clip", STATUS_DONE)
    _touch(config.nas_video_folder / "old_clip.mp4")
    _backdate_file(config.nas_video_folder / "old_clip.mp4", 20)

    store.upsert_pending("recent_clip", "h2", video_title="recent title")
    store.set_status("recent_clip", STATUS_DONE)
    _touch(config.nas_video_folder / "recent_clip.mp4")

    store.upsert_pending("pending_clip", "h3", video_title="pending title")

    stale = cleanup.find_stale_clips(store, config, retention_days=14)

    assert [c.clip_key for c in stale] == ["old_clip"]
    assert config.nas_video_folder / "old_clip.mp4" in stale[0].files


def test_find_stale_clips_includes_mp3_and_retagged_when_present(tmp_path):
    store = ProcessedStore()
    mp3_folder = tmp_path / "crotchet rest" / "processed" / "mp3"
    config = _config(tmp_path, mp3_folder=mp3_folder)

    store.upsert_pending("clip", "h1", video_title="my title")
    store.set_status("clip", STATUS_DONE)
    _touch(config.nas_video_folder / "clip.mp4")
    _touch(config.nas_video_folder / "_retagged" / "clip_360.mp4")
    from insta360_uploader.artifact_status import make_target
    from insta360_uploader.nas_scanner import VideoFile
    path = config.nas_video_folder / "clip.mp4"
    _backdate_file(path, 30)
    title = make_target(VideoFile("clip", path), config).title
    _touch(mp3_folder / f"{title}.mp3")
    for file in config.nas_video_folder.parent.rglob("*"):
        if file.is_file():
            _backdate_file(file, 30)

    stale = cleanup.find_stale_clips(store, config, retention_days=14)

    assert len(stale) == 1
    assert len(stale[0].files) == 3


def test_find_stale_clips_finds_every_chapter_of_a_grouped_camera_clip(tmp_path):
    store = ProcessedStore()
    raw_folder = tmp_path / "crotchet rest" / "raw"
    config = _config(tmp_path, raw_folder=raw_folder)

    clip_key = "VID_20260906_131910"
    store.upsert_pending(clip_key, "h1", video_title="my title")
    store.set_status(clip_key, STATUS_DONE)
    _touch(config.nas_video_folder / f"{clip_key}.mp4")
    _touch(raw_folder / "VID_20260906_131910_00_005.insv")
    _touch(raw_folder / "VID_20260906_131910_00_006.insv")
    for file in config.nas_video_folder.parent.parent.rglob("*"):
        if file.is_file():
            _backdate_file(file, 30)

    stale = cleanup.find_stale_clips(store, config, retention_days=14)

    assert len(stale) == 1
    assert {p.name for p in stale[0].files} == {
        "VID_20260906_131910_00_005.insv",
        "VID_20260906_131910_00_006.insv",
        f"{clip_key}.mp4",
    }


def test_find_stale_clips_does_not_crash_when_raw_and_mp3_are_unconfigured(tmp_path):
    # config.raw_folder/mp3_folder default to None (see _config()) — must
    # never crash trying to glob/join a None folder; a clip with just its
    # mp4 present is still found stale.
    store = ProcessedStore()
    config = _config(tmp_path)
    assert config.raw_folder is None
    assert config.mp3_folder is None

    store.upsert_pending("clip", "h1", video_title="my title")
    store.set_status("clip", STATUS_DONE)
    _touch(config.nas_video_folder / "clip.mp4")
    _backdate_file(config.nas_video_folder / "clip.mp4", 30)

    stale = cleanup.find_stale_clips(store, config, retention_days=14)

    assert len(stale) == 1
    assert [p.name for p in stale[0].files] == ["clip.mp4"]


def test_find_orphaned_part_files(tmp_path):
    folder_a = tmp_path / "raw"
    folder_b = tmp_path / "mp4"
    _touch(folder_a / "x.insv.part")
    _touch(folder_b / "y.mp4.part")
    _touch(folder_b / "z.mp4")

    found = cleanup.find_orphaned_part_files(folder_a, folder_b)

    assert {p.name for p in found} == {"x.insv.part", "y.mp4.part"}


def test_find_all_clip_files_ignores_age(tmp_path):
    store = ProcessedStore()
    config = _config(tmp_path)
    store.upsert_pending("clip", "h", video_title="t")
    store.set_status("clip", STATUS_DONE)
    _touch(config.nas_video_folder / "clip.mp4")

    result = cleanup.find_all_clip_files(store, config)

    assert [c.clip_key for c in result] == ["clip"]


def test_delete_files_removes_existing_and_skips_missing(tmp_path):
    existing = tmp_path / "a.txt"
    _touch(existing)
    missing = tmp_path / "b.txt"

    deleted = cleanup.delete_files([existing, missing])

    assert deleted == [existing]
    assert not existing.exists()


def test_remote_missing_prevents_cleanup_even_with_done_record(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _touch(config.nas_video_folder / "clip.mp4")
    store = ProcessedStore()
    store.upsert_pending("clip", "h")
    store.set_status("clip", STATUS_DONE)
    monkeypatch.setattr(cleanup.RemoteArtifacts, "youtube_exists", lambda self, target: False)
    assert cleanup.find_all_clip_files(store, config) == []


def test_remote_error_aborts_cleanup(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _touch(config.nas_video_folder / "clip.mp4")
    def fail(*args):
        raise RuntimeError("offline")
    monkeypatch.setattr(cleanup.RemoteArtifacts, "youtube_exists", fail)
    with pytest.raises(RuntimeError, match="offline"):
        cleanup.find_all_clip_files(ProcessedStore(), config)


def test_count_files_counts_nested_files(tmp_path):
    folder = tmp_path / "raw"
    _touch(folder / "a.insv")
    _touch(folder / "sub" / "b.insv")
    assert cleanup.count_files(folder) == 2


def test_count_files_missing_folder_is_zero(tmp_path):
    assert cleanup.count_files(tmp_path / "does-not-exist") == 0


def test_clear_folder_contents_removes_files_and_subfolders(tmp_path):
    folder = tmp_path / "raw"
    _touch(folder / "a.insv")
    _touch(folder / "sub" / "b.insv")

    removed = cleanup.clear_folder_contents(folder)

    assert removed == 2
    assert folder.is_dir()  # the folder itself stays, just emptied
    assert list(folder.iterdir()) == []


def test_clear_folder_contents_missing_folder_removes_nothing(tmp_path):
    assert cleanup.clear_folder_contents(tmp_path / "does-not-exist") == 0
