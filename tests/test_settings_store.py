import json
from dataclasses import replace
from pathlib import Path

from insta360_uploader.config import DEFAULT_RETENTION_DAYS, DriveConfig, MediaSdkConfig
from insta360_uploader.settings_store import (
    default_settings_path,
    load_app_config,
    local_settings_path,
    save_app_config,
)


def test_default_settings_path_is_under_project_data_dir():
    path = default_settings_path()
    assert path.name == "settings.json"
    assert path.parent.name == "data"


def test_old_alias_setting_is_ignored_and_removed_on_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"title_aliases": {"clip": "old title"}}), encoding="utf-8")
    config = load_app_config(path)
    assert not hasattr(config, "title_aliases")
    save_app_config(config, path)
    assert "title_aliases" not in json.loads(path.read_text(encoding="utf-8"))


def test_missing_settings_file_returns_blank_and_creates_one(tmp_path):
    settings_path = tmp_path / "settings.json"

    config = load_app_config(settings_path=settings_path)

    assert config.nas_video_folder == Path("")
    assert config.youtube_defaults.title_prefix == ""
    assert config.youtube_defaults.privacy_status == "unlisted"
    assert config.drive is None
    assert config.media_sdk is None
    assert config.raw_folder is None
    assert config.mp3_folder is None
    assert config.retention_days == DEFAULT_RETENTION_DAYS
    assert settings_path.is_file()  # blank config written so it exists from now on


def test_existing_settings_file_is_never_overwritten_by_loading(tmp_path):
    settings_path = tmp_path / "settings.json"
    original = load_app_config(settings_path=settings_path)
    customized = replace(original, youtube_defaults=replace(
        original.youtube_defaults, title_prefix="my custom title"
    ))
    save_app_config(customized, settings_path)

    # Loading again must not regenerate/reset the file — it already exists.
    reloaded = load_app_config(settings_path=settings_path)
    assert reloaded.youtube_defaults.title_prefix == "my custom title"


def test_the_shipped_data_settings_json_is_tracked_and_blank():
    """data/settings.json is the tracked-in-git template — it must always
    parse, and must never carry a real user's paths/IDs (those belong in
    the gitignored data/settings.local.json instead — see
    settings_store.py's module docstring and
    test_local_settings_takes_priority_over_the_tracked_template)."""
    path = default_settings_path()
    assert path.is_file()

    config = load_app_config(path)

    assert config.nas_video_folder == Path("")
    assert config.raw_folder is None
    assert config.mp3_folder is None
    assert config.drive is None
    assert config.media_sdk is None
    assert config.youtube_defaults.playlist_id is None

    # No path-shaped field may contain OAuth token/client-secret *content*
    # either (only paths to those files, which live under secrets/) — this
    # would be true of a blank file by construction, but locks it in.
    serialized = json.dumps(json.loads(path.read_text(encoding="utf-8")))
    for secret_marker in ("access_token", "refresh_token", "client_secret\":", "private_key"):
        assert secret_marker not in serialized


def test_local_settings_takes_priority_over_the_tracked_template(monkeypatch, tmp_path):
    import insta360_uploader.settings_store as store

    tracked = tmp_path / "settings.json"
    local = tmp_path / "settings.local.json"
    tracked.write_text(json.dumps({"source": {"nas_video_folder": ""}}), encoding="utf-8")
    local.write_text(json.dumps({"source": {"nas_video_folder": r"\\NAS\real-path"}}), encoding="utf-8")
    monkeypatch.setattr(store, "default_settings_path", lambda: tracked)
    monkeypatch.setattr(store, "local_settings_path", lambda: local)

    config = load_app_config()  # no explicit path: exercises the real local-vs-tracked lookup

    assert config.nas_video_folder == Path(r"\\NAS\real-path")


def test_load_app_config_seeds_local_file_from_tracked_template_when_local_is_missing(monkeypatch, tmp_path):
    import insta360_uploader.settings_store as store

    tracked = tmp_path / "settings.json"
    local = tmp_path / "settings.local.json"
    tracked.write_text(
        json.dumps({"youtube_defaults": {"title_prefix": "from template", "privacy_status": "unlisted"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "default_settings_path", lambda: tracked)
    monkeypatch.setattr(store, "local_settings_path", lambda: local)
    assert not local.exists()

    config = load_app_config()

    assert config.youtube_defaults.title_prefix == "from template"
    assert local.is_file()  # seeded so it's never re-read from the template again
    assert "from template" in local.read_text(encoding="utf-8")


def test_load_app_config_starts_blank_when_neither_file_exists(monkeypatch, tmp_path):
    import insta360_uploader.settings_store as store

    tracked = tmp_path / "settings.json"
    local = tmp_path / "settings.local.json"
    monkeypatch.setattr(store, "default_settings_path", lambda: tracked)
    monkeypatch.setattr(store, "local_settings_path", lambda: local)

    config = load_app_config()

    assert config.nas_video_folder == Path("")
    assert local.is_file()  # a blank config was seeded into the local file
    assert not tracked.exists()  # the (nonexistent) tracked template is never created by this


def test_save_then_load_round_trips_with_drive(tmp_path):
    settings_path = tmp_path / "settings.json"
    config = load_app_config(settings_path=settings_path)
    with_drive = replace(
        config,
        drive=DriveConfig(
            client_secret_path=config.youtube.client_secret_path,
            token_path=config.youtube.token_path,
            folder_id="folder-123",
            subfolder_prefix="practice",
        ),
    )
    save_app_config(with_drive, settings_path)

    reloaded = load_app_config(settings_path=settings_path)
    assert reloaded.drive is not None
    assert reloaded.drive.folder_id == "folder-123"
    assert reloaded.drive.subfolder_prefix == "practice"


def test_save_then_load_round_trips_raw_and_mp3_folder(tmp_path):
    settings_path = tmp_path / "settings.json"
    config = load_app_config(settings_path=settings_path)
    with_folders = replace(
        config, raw_folder=Path("D:/insta360-raw"), mp3_folder=Path("//NAS/insta360-audio")
    )
    save_app_config(with_folders, settings_path)

    reloaded = load_app_config(settings_path=settings_path)
    assert reloaded.raw_folder == Path("D:/insta360-raw")
    assert reloaded.mp3_folder == Path("//NAS/insta360-audio")


def test_save_without_raw_or_mp3_folder_round_trips_to_none(tmp_path):
    settings_path = tmp_path / "settings.json"
    config = load_app_config(settings_path=settings_path)
    save_app_config(config, settings_path)

    reloaded = load_app_config(settings_path=settings_path)
    assert reloaded.raw_folder is None
    assert reloaded.mp3_folder is None


def test_save_without_drive_round_trips_to_none(tmp_path):
    settings_path = tmp_path / "settings.json"
    config = load_app_config(settings_path=settings_path)
    save_app_config(config, settings_path)

    reloaded = load_app_config(settings_path=settings_path)
    assert reloaded.drive is None


def test_save_then_load_round_trips_media_sdk_and_retention_days(tmp_path):
    settings_path = tmp_path / "settings.json"
    config = load_app_config(settings_path=settings_path)
    updated = replace(
        config,
        media_sdk=MediaSdkConfig(
            exe_path=Path("C:/sdk/MediaSDKTest.exe"), model_root_dir=Path("C:/sdk/models")
        ),
        retention_days=7,
    )
    save_app_config(updated, settings_path)

    reloaded = load_app_config(settings_path=settings_path)
    assert reloaded.media_sdk is not None
    assert reloaded.media_sdk.exe_path.name == "MediaSDKTest.exe"
    assert reloaded.retention_days == 7
