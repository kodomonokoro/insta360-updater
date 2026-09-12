from dataclasses import replace
from pathlib import Path

import pytest

from insta360_uploader.config import (
    DEFAULT_RETENTION_DAYS,
    AppConfig,
    DriveConfig,
    MediaSdkConfig,
    YoutubeDefaults,
    YoutubeProfile,
    validate_for_run,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0")
    return path


def _bare_config(tmp_path, **overrides) -> AppConfig:
    """Every optional/required-by-mode field starts unset/missing —
    validate_for_run() tests opt individual pieces back in via overrides
    to isolate exactly one missing requirement at a time."""
    defaults = dict(
        nas_video_folder=tmp_path / "crotchet rest" / "processed" / "mp4",
        youtube=YoutubeProfile(client_secret_path=tmp_path / "x", token_path=tmp_path / "no_yt_token.json"),
        youtube_defaults=YoutubeDefaults(
            title_prefix="", privacy_status="unlisted", made_for_kids=False, playlist_id=None
        ),
        drive=None,
        media_sdk=None,
        retention_days=DEFAULT_RETENTION_DAYS,
        raw_folder=None,
        mp3_folder=None,
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


def _drive(tmp_path, *, authenticated: bool) -> DriveConfig:
    token = _touch(tmp_path / "drive_token.json") if authenticated else tmp_path / "no_drive_token.json"
    return DriveConfig(client_secret_path=tmp_path / "x", token_path=token, folder_id=None, subfolder_prefix=None)


def _media_sdk(tmp_path, *, exe_exists: bool) -> MediaSdkConfig:
    exe = _touch(tmp_path / "MediaSDKTest.exe") if exe_exists else tmp_path / "no_such.exe"
    return MediaSdkConfig(exe_path=exe, model_root_dir=tmp_path / "models")


def _fully_configured(tmp_path) -> AppConfig:
    """Passes validate_for_run() for every run mode — every individual
    "missing X" test below takes this and knocks out just one piece."""
    return _bare_config(
        tmp_path,
        youtube=YoutubeProfile(client_secret_path=tmp_path / "x", token_path=_touch(tmp_path / "yt_token.json")),
        drive=_drive(tmp_path, authenticated=True),
        media_sdk=_media_sdk(tmp_path, exe_exists=True),
        raw_folder=tmp_path / "raw",
        mp3_folder=tmp_path / "mp3",
    )


def test_validate_for_run_requires_nas_video_folder(tmp_path):
    config = _bare_config(tmp_path, nas_video_folder=Path(""))
    assert validate_for_run(config, camera=True) is not None


def test_validate_for_run_passes_when_everything_needed_is_configured(tmp_path):
    assert validate_for_run(_fully_configured(tmp_path), camera=False) is None
    assert validate_for_run(_fully_configured(tmp_path), camera=True) is None
    assert validate_for_run(_fully_configured(tmp_path), camera=True, stop_after_stitch=True) is None
    assert validate_for_run(_fully_configured(tmp_path), camera=True, skip_audio_drive=True) is None


@pytest.mark.parametrize("camera", [True, False])
def test_validate_for_run_requires_raw_folder_and_media_sdk_only_when_camera(tmp_path, camera):
    config = replace(_fully_configured(tmp_path), raw_folder=None)
    error = validate_for_run(config, camera=camera)
    assert (error is not None) == camera
    if error:
        assert "raw" in error

    config = replace(_fully_configured(tmp_path), media_sdk=None)
    error = validate_for_run(config, camera=camera)
    assert (error is not None) == camera


def test_validate_for_run_requires_media_sdk_exe_to_actually_exist(tmp_path):
    config = replace(_fully_configured(tmp_path), media_sdk=_media_sdk(tmp_path, exe_exists=False))
    assert validate_for_run(config, camera=True) is not None


@pytest.mark.parametrize(
    "camera,stop_after_stitch,skip_audio_drive",
    [(True, False, False), (False, False, False)],  # 全行程実施, ③④⑤のみ実施
)
def test_validate_for_run_requires_mp3_folder_when_audio_drive_stages_are_wanted(
    tmp_path, camera, stop_after_stitch, skip_audio_drive
):
    config = replace(_fully_configured(tmp_path), mp3_folder=None)
    error = validate_for_run(
        config, camera=camera, stop_after_stitch=stop_after_stitch, skip_audio_drive=skip_audio_drive
    )
    assert error is not None
    assert "MP3" in error


@pytest.mark.parametrize(
    "camera,stop_after_stitch,skip_audio_drive",
    [(True, False, False), (False, False, False)],  # 全行程実施, ③④⑤のみ実施
)
def test_validate_for_run_requires_drive_when_audio_drive_stages_are_wanted(
    tmp_path, camera, stop_after_stitch, skip_audio_drive
):
    config = replace(_fully_configured(tmp_path), drive=None)
    error = validate_for_run(
        config, camera=camera, stop_after_stitch=stop_after_stitch, skip_audio_drive=skip_audio_drive
    )
    assert error is not None
    assert "Google Drive" in error


def test_validate_for_run_requires_drive_authentication_when_audio_drive_stages_are_wanted(tmp_path):
    config = replace(_fully_configured(tmp_path), drive=_drive(tmp_path, authenticated=False))
    error = validate_for_run(config, camera=True)
    assert error is not None
    assert "認証" in error


@pytest.mark.parametrize(
    "camera,stop_after_stitch,skip_audio_drive",
    [(True, True, False), (True, False, True)],  # ①②のみ実施, ①②⑤のみ実施
)
def test_validate_for_run_does_not_require_mp3_or_drive_when_audio_drive_is_skipped(
    tmp_path, camera, stop_after_stitch, skip_audio_drive
):
    config = replace(_fully_configured(tmp_path), mp3_folder=None, drive=None)
    assert validate_for_run(
        config, camera=camera, stop_after_stitch=stop_after_stitch, skip_audio_drive=skip_audio_drive
    ) is None


def test_validate_for_run_requires_youtube_authentication_when_youtube_stage_is_wanted(tmp_path):
    config = replace(_fully_configured(tmp_path), youtube=YoutubeProfile(
        client_secret_path=tmp_path / "x", token_path=tmp_path / "no_yt_token.json"
    ))
    error = validate_for_run(config, camera=True)
    assert error is not None
    assert "YouTube" in error


def test_validate_for_run_does_not_require_youtube_authentication_when_stopping_after_stitch(tmp_path):
    config = replace(_fully_configured(tmp_path), youtube=YoutubeProfile(
        client_secret_path=tmp_path / "x", token_path=tmp_path / "no_yt_token.json"
    ))
    assert validate_for_run(config, camera=True, stop_after_stitch=True) is None
