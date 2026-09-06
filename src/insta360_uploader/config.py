"""Loading and validating config.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_PRIVACY_STATUSES = ("public", "unlisted", "private")


class ConfigError(ValueError):
    """Raised when config.yaml is missing or malformed."""


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
class AppConfig:
    nas_video_folder: Path
    youtube: YoutubeProfile
    youtube_defaults: YoutubeDefaults
    drive: DriveConfig | None


def _require(mapping: dict, key: str, context: str) -> object:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"missing required '{key}' in {context}")
    return mapping[key]


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ConfigError("config.yaml must contain a mapping at the top level")

    source = _require(raw, "source", "config")
    nas_video_folder = Path(_require(source, "nas_video_folder", "source"))

    youtube_raw = _require(raw, "youtube", "config")
    youtube = YoutubeProfile(
        client_secret_path=Path(_require(youtube_raw, "client_secret_path", "youtube")),
        token_path=Path(_require(youtube_raw, "token_path", "youtube")),
    )

    defaults_raw = _require(raw, "youtube_defaults", "config")
    privacy_status = _require(defaults_raw, "privacy_status", "youtube_defaults")
    if privacy_status not in VALID_PRIVACY_STATUSES:
        raise ConfigError(
            f"youtube_defaults.privacy_status must be one of {VALID_PRIVACY_STATUSES}, "
            f"got {privacy_status!r}"
        )
    youtube_defaults = YoutubeDefaults(
        title_prefix=str(_require(defaults_raw, "title_prefix", "youtube_defaults")),
        privacy_status=privacy_status,
        made_for_kids=bool(defaults_raw.get("made_for_kids", False)),
        playlist_id=defaults_raw.get("playlist_id") or None,
    )

    drive_raw = raw.get("google_drive")
    drive = None
    if drive_raw:
        drive = DriveConfig(
            client_secret_path=Path(
                _require(drive_raw, "client_secret_path", "google_drive")
            ),
            token_path=Path(_require(drive_raw, "token_path", "google_drive")),
            folder_id=drive_raw.get("folder_id") or None,
            subfolder_prefix=drive_raw.get("subfolder_prefix") or None,
        )

    return AppConfig(
        nas_video_folder=nas_video_folder,
        youtube=youtube,
        youtube_defaults=youtube_defaults,
        drive=drive,
    )
