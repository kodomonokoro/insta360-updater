"""Application config types and start-of-run validation.

data/settings.json (settings_store.py) is the only configuration file —
there is no YAML loader here any more."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

VALID_PRIVACY_STATUSES = ("public", "unlisted", "private")
DEFAULT_RETENTION_DAYS = 14


class ConfigError(ValueError):
    """Raised when a run is started with settings that don't support it —
    see validate_for_run()."""


@dataclass(frozen=True)
class YoutubeProfile:
    client_secret_path: Path
    token_path: Path


@dataclass(frozen=True)
class YoutubeDefaults:
    title_prefix: str
    privacy_status: str
    made_for_kids: bool
    playlist_id: str | None


@dataclass(frozen=True)
class DriveConfig:
    client_secret_path: Path
    token_path: Path
    folder_id: str | None
    subfolder_prefix: str | None


@dataclass(frozen=True)
class MediaSdkConfig:
    """Points at a locally-unzipped Insta360 MediaSDK release (not vendored
    in this repo — see settings_store.py). `exe_path` is MediaSDKTest.exe;
    `model_root_dir` is the SDK's `models/` folder it needs alongside it."""

    exe_path: Path
    model_root_dir: Path


@dataclass(frozen=True)
class AppConfig:
    nas_video_folder: Path
    youtube: YoutubeProfile
    youtube_defaults: YoutubeDefaults
    drive: DriveConfig | None
    media_sdk: MediaSdkConfig | None
    retention_days: int
    # None means "not configured" — no fallback is derived from
    # nas_video_folder. A run mode that needs one of these but doesn't have
    # it is rejected by validate_for_run() before anything starts, rather
    # than silently guessing a path. Independently settable because raw
    # camera footage is large and may need its own (e.g. faster or bigger)
    # volume, unlike mp3s/the _retagged safety-net copy, which stay
    # implicitly under nas_video_folder — see project chat.
    raw_folder: Path | None = None
    mp3_folder: Path | None = None


def validate_for_run(
    config: AppConfig, *, camera: bool, stop_after_stitch: bool = False, skip_audio_drive: bool = False
) -> str | None:
    """Checked once, at 開始-press time (GUI) or at the top of
    run_camera_pipeline()/process_videos() (CLI and any other caller) —
    not earlier, so editing settings mid-session doesn't need its own
    separate re-validation trigger. Returns a user-facing error message if
    this specific run mode is missing something it needs, else None.

    Mirrors lifecycle.enabled_stages()'s own conditions exactly, stage by
    stage, so a setting is only required when the mode being run would
    actually reach the stage that needs it:

    - 映像(nas_video_folder): always required.
    - raw_folder / Insta360 SDK (MediaSDKTest.exe): only when `camera` (①
      copy, ② stitch are part of this run).
    - mp3_folder / Google Drive (config + auth token): only when this mode
      wants audio extraction + Drive upload (`needs_audio_drive` below —
      same condition as enabled_stages()'s own audio/drive gate).
    - YouTube auth token: whenever this mode reaches ⑤ YouTube upload,
      i.e. every mode except "①②のみ実施" (camera + stop_after_stitch).
    """
    if not str(config.nas_video_folder):
        return "映像抽出先(MP4)フォルダが設定されていません。設定画面で指定してください。"

    if camera:
        if config.raw_folder is None:
            return "Insta360ファイルコピー先(raw)フォルダが設定されていません。設定画面で指定してください。"
        if config.media_sdk is None or not config.media_sdk.exe_path.is_file():
            return (
                "Insta360 SDK(MediaSDKTest.exe)が設定されていないか、"
                "ファイルが見つかりません。設定画面で指定してください。"
            )

    needs_audio_drive = not skip_audio_drive and not (camera and stop_after_stitch)
    if needs_audio_drive:
        if config.mp3_folder is None:
            return "音声抽出先(MP3)フォルダが設定されていません。設定画面で指定してください。"
        if config.drive is None:
            return (
                "この実行モードには音声抽出・Google Driveアップロードが含まれますが、"
                "Google Driveが設定されていません。設定画面で設定するか、"
                "実行モードを「①②⑤のみ実施」に変更してください。"
            )
        if not config.drive.token_path.is_file():
            return "Google Driveの認証が完了していません。設定画面で認証してください。"

    needs_youtube = not (camera and stop_after_stitch)
    if needs_youtube and not config.youtube.token_path.is_file():
        return "YouTubeの認証が完了していません。設定画面で認証してください。"

    return None
