"""Read-only artifact checks. Names are derived only from the source.

Remote clients belong to one background check, not to the UI thread or an
upload worker. Failed requests must propagate: unknown is not missing.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from googleapiclient.discovery import build

from insta360_uploader import gdrive_uploader, youtube_uploader
from insta360_uploader.config import AppConfig
from insta360_uploader.intake import raw_chapter_paths
from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.title_builder import extract_capture_datetime, title_for_video


@dataclass(frozen=True)
class ArtifactTarget:
    video: VideoFile
    title: str
    drive_subfolder: str | None


def make_target(video: VideoFile, config: AppConfig) -> ArtifactTarget:
    title = title_for_video(config.youtube_defaults.title_prefix, video)
    subfolder = None
    if config.drive and config.drive.subfolder_prefix:
        subfolder = f"{config.drive.subfolder_prefix}_{extract_capture_datetime(video.path):%Y%m%d}"
    return ArtifactTarget(video, title, subfolder)


def local_states(target: ArtifactTarget, config: AppConfig) -> dict[str, str]:
    video = target.video

    if config.raw_folder is None:
        copy_state = "unconfigured"
    else:
        if video.chapter_paths:
            raw_paths = raw_chapter_paths(video, config)
        else:
            # NAS-only input: match the exact clip or its chapter filenames,
            # never an arbitrary filename with a coincidentally shared prefix.
            raw_paths = [config.raw_folder / f"{video.key}.insv"]
            if not raw_paths[0].is_file():
                pattern = re.compile(re.escape(video.key) + r"_\d{2}_\d{3}\.insv$", re.I)
                raw_paths = [p for p in config.raw_folder.glob("*.insv") if pattern.fullmatch(p.name)]
        copy_state = "done" if raw_paths and all(p.is_file() for p in raw_paths) else "pending"

    mp4 = config.nas_video_folder / f"{video.key}.mp4" if video.chapter_paths else video.path

    if config.mp3_folder is None:
        audio_state = "unconfigured"
    else:
        mp3 = config.mp3_folder / f"{target.title}.mp3"
        audio_state = "done" if mp3.is_file() else "pending"

    return {
        "copy": copy_state,
        "stitch": "done" if mp4.is_file() else "pending",
        "audio": audio_state,
    }


class RemoteArtifacts:
    def __init__(self, config: AppConfig):
        self.config = config
        self._drive = None
        self._youtube = None
        self._folders: dict[str, list[str]] = {}
        self._videos: dict[str, dict] | None = None

    def drive_exists(self, target: ArtifactTarget) -> bool:
        config = self.config.drive
        if config is None:
            raise ValueError("Google Driveが未設定です")
        if self._drive is None:
            self._drive = build("drive", "v3", credentials=gdrive_uploader._load_credentials(config))
        drive = self._drive
        parents = [config.folder_id or "root"]
        if target.drive_subfolder:
            if not config.folder_id:
                raise ValueError("日付別フォルダの親フォルダが未設定です")
            if target.drive_subfolder not in self._folders:
                escape = gdrive_uploader._escape_query_value
                query = (f"name = '{escape(target.drive_subfolder)}' and "
                         f"mimeType = '{gdrive_uploader.FOLDER_MIME_TYPE}' and "
                         f"'{escape(config.folder_id)}' in parents and trashed = false")
                folders = []
                token = None
                while True:
                    response = drive.files().list(q=query, fields="files(id),nextPageToken",
                                                  spaces="drive", pageToken=token).execute()
                    folders.extend(f["id"] for f in response.get("files", []))
                    token = response.get("nextPageToken")
                    if not token:
                        break
                self._folders[target.drive_subfolder] = folders
            parents = self._folders[target.drive_subfolder]
        # Match only the source-derived name in the configured destination.
        for parent in parents:
            escape = gdrive_uploader._escape_query_value
            identity = f"name = '{escape(target.title + '.mp3')}'"
            response = drive.files().list(
                q=f"{identity} and '{escape(parent)}' in parents and trashed = false and mimeType != '{gdrive_uploader.FOLDER_MIME_TYPE}'",
                fields="files(id)", spaces="drive",
            ).execute()
            if response.get("files"):
                return True
        return False

    def youtube_exists(self, target: ArtifactTarget) -> bool:
        if self._youtube is None:
            self._youtube = build("youtube", "v3", credentials=youtube_uploader._load_credentials(self.config.youtube))
        youtube = self._youtube
        # Fetch the channel inventory once per refresh (including unlisted
        # and private uploads); do not run a fuzzy search for each row.
        if self._videos is None:
            playlist = youtube_uploader._get_uploads_playlist_id(youtube)
            ids = []
            token = None
            while True:
                response = youtube.playlistItems().list(
                    playlistId=playlist, part="contentDetails", maxResults=50, pageToken=token,
                ).execute()
                ids.extend(item["contentDetails"]["videoId"] for item in response.get("items", []))
                token = response.get("nextPageToken")
                if not token:
                    break
            videos = {}
            for offset in range(0, len(ids), 50):
                response = youtube.videos().list(part="snippet,status", id=",".join(ids[offset:offset + 50])).execute()
                for item in response.get("items", []):
                    if item.get("status", {}).get("uploadStatus") not in ("deleted", "failed", "rejected"):
                        videos[item["id"]] = item
            self._videos = videos
        return any(
            item["snippet"]["title"] == target.title for item in self._videos.values()
        )
