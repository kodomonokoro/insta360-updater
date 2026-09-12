from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication

from insta360_uploader import artifact_status as artifacts
from insta360_uploader.config import AppConfig, DriveConfig, YoutubeDefaults, YoutubeProfile
from insta360_uploader.gui_backend import pipeline_model as ui
from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.processed_store import ProcessedStore, STATUS_DONE, STATUS_UPLOADING_VIDEO


@pytest.fixture
def config(tmp_path):
    return AppConfig(
        tmp_path / "processed" / "mp4",
        YoutubeProfile(tmp_path / "secret", tmp_path / "token"),
        YoutubeDefaults("p", "unlisted", False, None),
        DriveConfig(tmp_path / "secret", tmp_path / "token", "parent", "audio"),
        None, 14,
        raw_folder=tmp_path / "raw",
        mp3_folder=tmp_path / "processed" / "mp3",
    )


@pytest.fixture
def video(tmp_path):
    paths = tuple(tmp_path / "camera" / f"VID_20260906_131910_00_{i:03}.insv" for i in (5, 6))
    for path in paths:
        touch(path)
    return VideoFile("VID_20260906_131910", paths[0], paths)


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")


def test_local_completion_without_history_and_after_deletion(config, video):
    target = artifacts.make_target(video, config)
    paths = artifacts.raw_chapter_paths(video, config)
    mp4 = config.nas_video_folder / f"{video.key}.mp4"
    mp3 = config.nas_video_folder.parent / "mp3" / f"{target.title}.mp3"
    touch(paths[0])
    touch(paths[1].with_suffix(".insv.part"))
    assert artifacts.local_states(target, config)["copy"] == "pending"
    for path in [*paths, mp4, mp3]:
        touch(path)
    assert set(artifacts.local_states(target, config).values()) == {"done"}
    mp3.unlink()
    assert artifacts.local_states(target, config)["audio"] == "pending"
    mp4.unlink()
    assert artifacts.local_states(target, config)["stitch"] == "pending"


def test_local_states_reports_unconfigured_without_raising_when_raw_or_mp3_unset(config, video):
    # config.validate_for_run() blocks a real run in this state (raw/mp3
    # required only for the modes that need them) — but the file table
    # itself refreshes independent of any run mode, so this must never
    # crash even when raw/mp3 were never set at all.
    unconfigured = replace(config, raw_folder=None, mp3_folder=None)
    target = artifacts.make_target(video, unconfigured)

    states = artifacts.local_states(target, unconfigured)

    assert states["copy"] == "unconfigured"
    assert states["audio"] == "unconfigured"
    assert states["stitch"] == "pending"  # unaffected — stitch never depended on raw/mp3


def test_target_name_comes_only_from_source(config, video):
    target = artifacts.make_target(video, config)
    assert target.title == "p - 20260906 1319"
    assert not hasattr(target, "youtube_id")
    assert not hasattr(target, "drive_id")


def test_nas_mode_still_reports_existing_raw_and_mp4(config, video):
    path = config.nas_video_folder / f"{video.key}.mp4"
    touch(path)
    touch(artifacts.raw_chapter_paths(video, config)[0])
    target = artifacts.make_target(VideoFile(video.key, path), config)
    assert artifacts.local_states(target, config)["copy"] == "done"
    assert artifacts.local_states(target, config)["stitch"] == "done"


def test_row_does_not_trust_done_or_running_records(config, video):
    store = ProcessedStore()
    store.upsert_pending(video.key, "h", "old title")
    store.set_status(video.key, STATUS_DONE, drive_file_id="old-drive", youtube_video_id="old-youtube")
    row = ui.FileRow(video.key, video.key, "", video)
    row.remote_states = {"drive": "pending", "youtube": "pending"}
    row.refresh_artifacts(config)
    assert set(row.stage_status.values()) == {"pending"}
    store.set_status(video.key, STATUS_UPLOADING_VIDEO)
    row.refresh_artifacts(config)
    assert row.stage_status["youtube"] == "pending"
    # Mode exclusions must not hide actual artifacts.
    touch(config.nas_video_folder / f"{video.key}.mp4")
    row.refresh_artifacts(config)
    assert row.stage_status["stitch"] == "done"
    assert row.stage_status["youtube"] == "pending"


def test_file_row_shows_unconfigured_copy_and_audio_without_raw_or_mp3_folder(config, video):
    unconfigured = replace(config, raw_folder=None, mp3_folder=None)
    row = ui.FileRow(video.key, video.key, "", video)
    row.remote_states = {"drive": "pending", "youtube": "pending"}

    row.refresh_artifacts(unconfigured)

    assert row.stage_status["copy"] == "unconfigured"
    assert row.stage_status["audio"] == "unconfigured"


def test_drive_checks_folder_without_creating_anything(config, video):
    remote = artifacts.RemoteArtifacts(config)
    drive = remote._drive = MagicMock()
    drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "dated"}]}, {"files": [{"id": "real"}]},
        {"files": []},
    ]
    target = artifacts.make_target(video, config)
    assert remote.drive_exists(target)
    assert not remote.drive_exists(target)  # Deletion is observed, no done cache.
    queries = [call.kwargs["q"] for call in drive.files.return_value.list.call_args_list]
    assert "'parent' in parents" in queries[0]
    assert "'dated' in parents" in queries[1]
    assert "trashed = false" in queries[1]
    drive.files.return_value.create.assert_not_called()
    drive.files.return_value.update.assert_not_called()
    drive.files.return_value.delete.assert_not_called()


def test_drive_missing_folder_is_missing_not_created(config, video):
    remote = artifacts.RemoteArtifacts(config)
    remote._drive = MagicMock()
    remote._drive.files.return_value.list.return_value.execute.return_value = {"files": []}
    assert not remote.drive_exists(artifacts.make_target(video, config))
    remote._drive.files.return_value.create.assert_not_called()


def test_youtube_pages_inventory_and_verifies_video_resource(config, video):
    target = artifacts.make_target(video, config)
    remote = artifacts.RemoteArtifacts(config)
    yt = remote._youtube = MagicMock()
    yt.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]
    }
    yt.playlistItems.return_value.list.return_value.execute.side_effect = [
        {"items": [{"contentDetails": {"videoId": "deleted"}}], "nextPageToken": "next"},
        {"items": [{"contentDetails": {"videoId": "live"}}]},
    ]
    yt.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "live", "snippet": {"title": target.title}, "status": {"uploadStatus": "processed"}}]
    }
    assert remote.youtube_exists(target)
    assert not remote.youtube_exists(replace(target, title="other"))
    assert yt.playlistItems.return_value.list.call_count == 2
    assert yt.videos.return_value.list.call_count == 1
    yt.videos.return_value.insert.assert_not_called()


def test_check_error_is_unknown_not_missing(config, video, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    def fail(*args):
        raise RuntimeError("offline")
    monkeypatch.setattr(artifacts.RemoteArtifacts, "drive_exists", fail)
    monkeypatch.setattr(artifacts.RemoteArtifacts, "youtube_exists", lambda *args: True)
    worker = ui.ArtifactCheckWorker(1, [artifacts.make_target(video, config)], config)
    results = []
    worker.result.connect(lambda *args: results.append(args))
    worker.run()
    assert results[0][2:] == ("drive", "unknown", "offline")
    assert results[1][2:] == ("youtube", "done", "")


def test_stale_background_result_is_ignored(config, video, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(ui.PipelineModel, "refresh", lambda self: None)
    model = ui.PipelineModel(config, ProcessedStore())
    row = ui.FileRow(video.key, video.key, "", video)
    model.rows = [row]
    model._check_generation = 2
    model._on_artifact_result(1, video.key, "youtube", "done", "")
    assert row.remote_states["youtube"] == "checking"
    model._on_artifact_result(2, video.key, "youtube", "pending", "")
    assert row.stage_status["youtube"] == "pending"


def test_worker_failure_still_finishes_and_reports_error(config, video):
    app = QCoreApplication.instance() or QCoreApplication([])
    store = ProcessedStore()
    row = ui.FileRow(video.key, video.key, "", video)
    worker = ui.CameraPipelineWorker([row], config, store, False)
    finished = []
    worker.finished_.connect(lambda: finished.append(True))
    worker.run()  # No SDK configured: failure before the first operation.
    assert finished == [True]
    assert store.get(video.key).status == "failed"
