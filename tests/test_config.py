import pytest

from insta360_uploader.config import ConfigError, load_config

VALID = """
source:
  nas_video_folder: "//NAS/insta360-exports"
youtube:
  client_secret_path: "C:/secrets/main_client_secret.json"
  token_path: "C:/secrets/main_token.json"
youtube_defaults:
  title_prefix: "crotchet rest 360"
  privacy_status: unlisted
"""

VALID_WITH_DRIVE = (
    VALID
    + """
google_drive:
  client_secret_path: "C:/secrets/gdrive_client_secret.json"
  token_path: "C:/secrets/gdrive_token.json"
  folder_id: "abc123"
"""
)


def _write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_config_without_drive(tmp_path):
    config = load_config(_write(tmp_path, VALID))
    assert config.youtube.client_secret_path.name == "main_client_secret.json"
    assert config.drive is None
    assert config.youtube_defaults.title_prefix == "crotchet rest 360"
    assert config.youtube_defaults.privacy_status == "unlisted"
    assert config.youtube_defaults.made_for_kids is False


def test_loads_valid_config_with_drive(tmp_path):
    config = load_config(_write(tmp_path, VALID_WITH_DRIVE))
    assert config.drive is not None
    assert config.drive.folder_id == "abc123"
    assert config.drive.subfolder_prefix is None


def test_drive_subfolder_prefix_is_parsed(tmp_path):
    with_prefix = VALID_WITH_DRIVE + '  subfolder_prefix: "practice"\n'
    config = load_config(_write(tmp_path, with_prefix))
    assert config.drive.subfolder_prefix == "practice"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_missing_nas_video_folder_raises(tmp_path):
    bad = VALID.replace('nas_video_folder: "//NAS/insta360-exports"', "")
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_missing_youtube_section_raises(tmp_path):
    bad = VALID.replace(
        'youtube:\n  client_secret_path: "C:/secrets/main_client_secret.json"\n'
        '  token_path: "C:/secrets/main_token.json"\n',
        "",
    )
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_missing_youtube_defaults_raises(tmp_path):
    bad = VALID.replace(
        'youtube_defaults:\n  title_prefix: "crotchet rest 360"\n  privacy_status: unlisted\n',
        "",
    )
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_invalid_privacy_status_raises(tmp_path):
    bad = VALID.replace("privacy_status: unlisted", "privacy_status: bogus")
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_made_for_kids_can_be_set_true(tmp_path):
    with_kids = VALID.replace(
        "privacy_status: unlisted", "privacy_status: unlisted\n  made_for_kids: true"
    )
    config = load_config(_write(tmp_path, with_kids))
    assert config.youtube_defaults.made_for_kids is True


def test_drive_missing_required_field_raises(tmp_path):
    bad = VALID_WITH_DRIVE.replace(
        '  token_path: "C:/secrets/gdrive_token.json"\n',
        "",
    )
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))
