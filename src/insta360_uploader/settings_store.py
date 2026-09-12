"""GUI-managed application settings, persisted as plain JSON.
Execution state is separate and is never persisted.

Two files, deliberately not one:

- data/settings.json — tracked in git, shipped with the repo, always
  blank. It exists only so the app has *something* to read on a fresh
  checkout; it must never accumulate anyone's real paths, Drive folder
  ID, or playlist ID.
- data/settings.local.json — gitignored (matches data/*'s existing
  wildcard in .gitignore; not given a negation like settings.json is),
  this is where a real user's actual settings live. load_app_config()
  prefers this file whenever it exists, and save_app_config() writes
  here by default — so once a machine has any real settings at all,
  they never touch the tracked template again.

The JSON parsing here is deliberately permissive: a settings file must
always load, even completely blank on a fresh install, so missing fields
just become empty/None defaults instead of errors (contrast the old
YAML loader this replaced, which used to raise on anything missing — a
hand-authored config.yaml with a missing field was a real mistake worth
surfacing; machine-written JSON has no such hand-authoring failure mode).
"""
from __future__ import annotations

import json
from pathlib import Path

from insta360_uploader.config import (
    DEFAULT_RETENTION_DAYS,
    AppConfig,
    DriveConfig,
    MediaSdkConfig,
    YoutubeDefaults,
    YoutubeProfile,
)


def default_settings_path() -> Path:
    """<project root>/data/settings.json — the tracked, always-blank
    template shipped with the repo. See local_settings_path() for where
    a real user's actual settings live."""
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "settings.json"


def local_settings_path() -> Path:
    """<project root>/data/settings.local.json — gitignored; this is
    where a real user's actual settings (paths, Drive folder ID,
    playlist ID) live, never in the tracked settings.json."""
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "settings.local.json"


def _blank_app_config() -> AppConfig:
    return AppConfig(
        nas_video_folder=Path(""),
        youtube=YoutubeProfile(client_secret_path=Path(""), token_path=Path("")),
        youtube_defaults=YoutubeDefaults(
            title_prefix="", privacy_status="unlisted", made_for_kids=False, playlist_id=None
        ),
        drive=None,
        media_sdk=None,
        retention_days=DEFAULT_RETENTION_DAYS,
    )


def _app_config_to_dict(config: AppConfig) -> dict:
    raw: dict = {
        "source": {
            "nas_video_folder": str(config.nas_video_folder),
            "raw_folder": str(config.raw_folder) if config.raw_folder else None,
            "mp3_folder": str(config.mp3_folder) if config.mp3_folder else None,
        },
        "youtube": {
            "client_secret_path": str(config.youtube.client_secret_path),
            "token_path": str(config.youtube.token_path),
        },
        "youtube_defaults": {
            "title_prefix": config.youtube_defaults.title_prefix,
            "privacy_status": config.youtube_defaults.privacy_status,
            "made_for_kids": config.youtube_defaults.made_for_kids,
            "playlist_id": config.youtube_defaults.playlist_id,
        },
    }
    if config.drive is not None:
        raw["google_drive"] = {
            "client_secret_path": str(config.drive.client_secret_path),
            "token_path": str(config.drive.token_path),
            "folder_id": config.drive.folder_id,
            "subfolder_prefix": config.drive.subfolder_prefix,
        }
    if config.media_sdk is not None:
        raw["insta360_sdk"] = {
            "exe_path": str(config.media_sdk.exe_path),
            "model_root_dir": str(config.media_sdk.model_root_dir),
        }
    raw["retention_days"] = config.retention_days
    return raw


def _app_config_from_dict(raw: dict) -> AppConfig:
    source = raw.get("source") or {}
    youtube_raw = raw.get("youtube") or {}
    defaults_raw = raw.get("youtube_defaults") or {}
    drive_raw = raw.get("google_drive")
    media_sdk_raw = raw.get("insta360_sdk")

    drive = None
    if drive_raw:
        drive = DriveConfig(
            client_secret_path=Path(drive_raw.get("client_secret_path") or ""),
            token_path=Path(drive_raw.get("token_path") or ""),
            folder_id=drive_raw.get("folder_id") or None,
            subfolder_prefix=drive_raw.get("subfolder_prefix") or None,
        )

    media_sdk = None
    if media_sdk_raw:
        media_sdk = MediaSdkConfig(
            exe_path=Path(media_sdk_raw.get("exe_path") or ""),
            model_root_dir=Path(media_sdk_raw.get("model_root_dir") or ""),
        )

    return AppConfig(
        nas_video_folder=Path(source.get("nas_video_folder") or ""),
        raw_folder=Path(source["raw_folder"]) if source.get("raw_folder") else None,
        mp3_folder=Path(source["mp3_folder"]) if source.get("mp3_folder") else None,
        youtube=YoutubeProfile(
            client_secret_path=Path(youtube_raw.get("client_secret_path") or ""),
            token_path=Path(youtube_raw.get("token_path") or ""),
        ),
        youtube_defaults=YoutubeDefaults(
            title_prefix=defaults_raw.get("title_prefix") or "",
            privacy_status=defaults_raw.get("privacy_status") or "unlisted",
            made_for_kids=bool(defaults_raw.get("made_for_kids", False)),
            playlist_id=defaults_raw.get("playlist_id") or None,
        ),
        drive=drive,
        media_sdk=media_sdk,
        retention_days=int(raw.get("retention_days") or DEFAULT_RETENTION_DAYS),
    )


def save_app_config(config: AppConfig, settings_path: str | Path | None = None) -> None:
    # Defaults to the *local* (gitignored) file, not the tracked template —
    # every real save (Settings screen, first-run seeding below) belongs
    # there, never in settings.json.
    path = Path(settings_path) if settings_path is not None else local_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # write to a temp file then replace, so a crash mid-write can't corrupt
    # the existing file (same pattern as processed_store.py).
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(_app_config_to_dict(config), f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def _read(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return _app_config_from_dict(raw)


def load_app_config(settings_path: str | Path | None = None) -> AppConfig:
    if settings_path is not None:
        # Explicit path (tests, or any future caller that wants one exact
        # file): behaves exactly like a single-file store — no
        # local/tracked distinction, matching the pre-local_settings_path
        # behavior other callers still rely on.
        path = Path(settings_path)
        if path.is_file():
            return _read(path)
        config = _blank_app_config()
        save_app_config(config, path)
        return config

    # Real app usage: a real user's settings, once they exist at all,
    # live in the gitignored local file — never overwritten by loading it.
    local_path = local_settings_path()
    if local_path.is_file():
        return _read(local_path)

    # Nothing local yet: seed from the tracked template if present (kept
    # deliberately blank in git, but this also covers a future templated
    # value), else start blank — either way, write the result into the
    # *local* file so the tracked template is never touched again.
    default_path = default_settings_path()
    config = _read(default_path) if default_path.is_file() else _blank_app_config()
    save_app_config(config, local_path)
    return config
