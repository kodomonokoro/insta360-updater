from types import SimpleNamespace

from insta360_uploader import cli
from insta360_uploader.config import AppConfig, ConfigError, MediaSdkConfig, YoutubeDefaults, YoutubeProfile
from insta360_uploader.nas_scanner import VideoFile


def test_scan_lists_each_discovered_source_video(monkeypatch, capsys, tmp_path):
    config = SimpleNamespace(nas_video_folder=tmp_path)
    video = VideoFile("VID_20260905_153205", tmp_path / "VID_20260905_153205.insv")
    monkeypatch.setattr(cli, "load_app_config", lambda **kwargs: config)
    monkeypatch.setattr(cli, "scan_video_folder", lambda folder: [video])

    assert cli.cmd_scan(SimpleNamespace(config="ignored")) == 0
    output = capsys.readouterr().out
    assert "Found 1 video" in output
    assert video.key in output
    assert str(video.path) in output


def test_intake_without_sdk_fails_before_touching_camera(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_app_config", lambda **kwargs: SimpleNamespace(media_sdk=None))
    monkeypatch.setattr(cli, "find_camera_drive", lambda: (_ for _ in ()).throw(AssertionError("must not scan")))

    assert cli.cmd_intake(SimpleNamespace(config="ignored", stop_after_stitch=False)) == 1
    assert "insta360_sdk is not configured" in capsys.readouterr().err


def test_status_reports_remote_errors_as_unknown_without_aborting(monkeypatch, capsys, tmp_path):
    config = SimpleNamespace(nas_video_folder=tmp_path, drive=None)
    video = VideoFile("VID_20260905_153205", tmp_path / "VID_20260905_153205.mp4")
    monkeypatch.setattr(cli, "load_app_config", lambda **kwargs: config)
    monkeypatch.setattr(cli, "scan_video_folder", lambda folder: [video])

    class Remote:
        def __init__(self, value):
            assert value is config

        def drive_exists(self, target):
            raise AssertionError("unconfigured Drive must not be queried")

        def youtube_exists(self, target):
            raise RuntimeError("offline")

    artifacts = __import__("insta360_uploader.artifact_status", fromlist=["RemoteArtifacts"])
    monkeypatch.setattr(artifacts, "make_target", lambda item, value: object())
    monkeypatch.setattr(artifacts, "local_states", lambda target, value: {"copy": "done"})
    monkeypatch.setattr(artifacts, "RemoteArtifacts", Remote)

    assert cli.cmd_status(SimpleNamespace(config="ignored")) == 0
    captured = capsys.readouterr()
    assert "drive=unconfigured" in captured.out
    assert "youtube=unknown" in captured.out
    assert "offline" in captured.err


def test_intake_fails_cleanly_via_validate_for_run_when_raw_folder_unconfigured(monkeypatch, capsys, tmp_path):
    # cmd_intake's own except clause doesn't list ConfigError — this must
    # still exit cleanly (not crash) by propagating up to main()'s handler.
    sdk_exe = tmp_path / "MediaSDKTest.exe"
    sdk_exe.write_bytes(b"0")
    insv = tmp_path / "VID_001.insv"
    insv.write_bytes(b"0")
    config = AppConfig(
        nas_video_folder=tmp_path / "mp4",
        youtube=YoutubeProfile(client_secret_path=tmp_path / "x", token_path=tmp_path / "no_token.json"),
        youtube_defaults=YoutubeDefaults("p", "unlisted", False, None),
        drive=None,
        media_sdk=MediaSdkConfig(exe_path=sdk_exe, model_root_dir=tmp_path),
        retention_days=14,
        raw_folder=None,  # the thing under test
    )
    video = VideoFile("VID_001", insv, (insv,))
    monkeypatch.setattr(cli, "load_app_config", lambda **kwargs: config)
    monkeypatch.setattr(cli, "find_camera_drive", lambda: tmp_path)
    monkeypatch.setattr(cli, "scan_camera_folder", lambda drive: [video])

    assert cli.main(["intake"]) == 1
    assert "raw" in capsys.readouterr().err


def test_main_converts_config_error_to_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "build_parser", lambda: SimpleNamespace(
        parse_args=lambda argv: SimpleNamespace(func=lambda args: (_ for _ in ()).throw(ConfigError("bad config")))
    ))

    assert cli.main(["scan"]) == 1
    assert "config error: bad config" in capsys.readouterr().err
