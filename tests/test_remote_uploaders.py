from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from insta360_uploader import gdrive_uploader as drive
from insta360_uploader import youtube_uploader as youtube
from insta360_uploader.config import DriveConfig, YoutubeProfile


@pytest.fixture
def drive_config(tmp_path):
    return DriveConfig(tmp_path / "drive-secret.json", tmp_path / "drive-token.json", "parent", None)


@pytest.fixture
def youtube_profile(tmp_path):
    return YoutubeProfile(tmp_path / "youtube-secret.json", tmp_path / "youtube-token.json")


def _patch_drive_client(monkeypatch, client):
    monkeypatch.setattr(drive, "_load_credentials", lambda config: object())
    monkeypatch.setattr(drive, "build", lambda *args, **kwargs: client)


def _patch_youtube_client(monkeypatch, client):
    monkeypatch.setattr(youtube, "_load_credentials", lambda profile: object())
    monkeypatch.setattr(youtube, "build", lambda *args, **kwargs: client)


def test_drive_existing_name_is_reused_without_creating_or_overwriting(
    drive_config, tmp_path, monkeypatch
):
    client = MagicMock()
    client.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "old-id"}]}
    _patch_drive_client(monkeypatch, client)
    skipped, logs = [], []

    result = drive.upload_file(
        drive_config, tmp_path / "input.mp3", name="source-title.mp3", on_skip=lambda: skipped.append(True), log=logs.append
    )

    assert result == "old-id"
    assert skipped == [True]
    assert "skipped upload" in logs[0]
    client.files.return_value.create.assert_not_called()
    client.files.return_value.update.assert_not_called()
    client.files.return_value.delete.assert_not_called()


def test_drive_new_upload_reports_chunk_progress_and_returns_id(drive_config, tmp_path, monkeypatch):
    client = MagicMock()
    files = client.files.return_value
    files.list.return_value.execute.return_value = {"files": []}
    request = MagicMock()
    request.next_chunk.side_effect = [
        (SimpleNamespace(progress=lambda: 0.25), None),
        (SimpleNamespace(progress=lambda: 1.0), {"id": "new-id"}),
    ]
    files.create.return_value = request
    _patch_drive_client(monkeypatch, client)
    media = MagicMock()
    monkeypatch.setattr(drive, "MediaFileUpload", media)
    progress = []

    assert drive.upload_file(drive_config, tmp_path / "input.mp3", progress_callback=progress.append) == "new-id"
    assert progress == [0.25, 1.0]
    assert request.next_chunk.call_args_list[0].kwargs == {"num_retries": 5}
    files.create.assert_called_once_with(
        body={"name": "input.mp3", "parents": ["parent"]}, media_body=media.return_value, fields="id"
    )


def test_youtube_exact_title_is_reused_after_paging_uploads(youtube_profile, tmp_path, monkeypatch):
    client = MagicMock()
    client.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads-id"}}}]
    }
    client.playlistItems.return_value.list.return_value.execute.side_effect = [
        {"items": [], "nextPageToken": "second"},
        {"items": [{"snippet": {"title": "source-title", "resourceId": {"videoId": "old-video"}}}]},
    ]
    _patch_youtube_client(monkeypatch, client)
    skipped = []

    assert youtube.upload_video(
        youtube_profile, tmp_path / "input.mp4", title="source-title", on_skip=lambda: skipped.append(True)
    ) == "old-video"
    assert skipped == [True]
    assert client.playlistItems.return_value.list.call_count == 2
    client.videos.return_value.insert.assert_not_called()


def test_youtube_new_upload_reports_progress_and_keeps_requested_metadata(
    youtube_profile, tmp_path, monkeypatch
):
    client = MagicMock()
    client.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads-id"}}}]
    }
    client.playlistItems.return_value.list.return_value.execute.return_value = {"items": []}
    request = MagicMock()
    request.next_chunk.side_effect = [(SimpleNamespace(progress=lambda: 0.5), None), (None, {"id": "new-video"})]
    client.videos.return_value.insert.return_value = request
    _patch_youtube_client(monkeypatch, client)
    media = MagicMock()
    monkeypatch.setattr(youtube, "MediaFileUpload", media)
    progress = []

    result = youtube.upload_video(
        youtube_profile, tmp_path / "input.mp4", title="source-title", description="desc",
        privacy_status="unlisted", made_for_kids=True, progress_callback=progress.append,
    )

    assert result == "new-video"
    assert progress == [0.5]
    assert request.next_chunk.call_args_list[0].kwargs == {"num_retries": 5}
    assert client.videos.return_value.insert.call_args.kwargs["body"] == {
        "snippet": {"title": "source-title", "description": "desc"},
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": True},
    }


def test_playlist_addition_is_idempotent_and_only_inserts_missing_video(youtube_profile, monkeypatch):
    client = MagicMock()
    _patch_youtube_client(monkeypatch, client)
    client.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "existing-item", "snippet": {"resourceId": {"videoId": "video-1"}}}]
    }

    youtube.add_video_to_playlist(youtube_profile, "video-1", "playlist")
    client.playlistItems.return_value.insert.assert_not_called()

    client.playlistItems.return_value.list.return_value.execute.return_value = {"items": []}
    youtube.add_video_to_playlist(youtube_profile, "video-2", "playlist")
    assert client.playlistItems.return_value.insert.call_args.kwargs["body"] == {
        "snippet": {"playlistId": "playlist", "resourceId": {"kind": "youtube#video", "videoId": "video-2"}}
    }
