from dataclasses import replace

from PySide6.QtCore import QCoreApplication

from insta360_uploader.config import AppConfig, YoutubeDefaults, YoutubeProfile
from insta360_uploader.gui_backend.pipeline_model import PipelineModel
from insta360_uploader.gui_backend.settings_model import SettingsModel
from insta360_uploader.processed_store import ProcessedStore


def _config(nas_video_folder) -> AppConfig:
    return AppConfig(
        nas_video_folder=nas_video_folder,
        youtube=YoutubeProfile(client_secret_path=nas_video_folder, token_path=nas_video_folder / "no_token.json"),
        youtube_defaults=YoutubeDefaults(title_prefix="p", privacy_status="unlisted", made_for_kids=False, playlist_id=None),
        drive=None,
        media_sdk=None,
        retention_days=14,
    )


def test_save_emits_config_saved_with_the_new_settings(tmp_path, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    config = _config(tmp_path / "mp4")
    monkeypatch.setattr("insta360_uploader.gui_backend.settings_model.save_app_config", lambda *a, **k: None)
    model = SettingsModel(config, ProcessedStore())
    new_folder = tmp_path / "new_mp4"
    model.nasFolder = str(new_folder)

    received = []
    model.configSaved.connect(received.append)
    model.save()

    assert len(received) == 1
    assert received[0].nas_video_folder == new_folder


def test_save_with_drive_disabled_keeps_previously_entered_fields(tmp_path, monkeypatch):
    # Regression: toggling "GoogleドライブにMP3ファイルを格納する" off and
    # saving must not discard a previously-entered secret/token/folder —
    # only the *active* flag should change, not the underlying fields.
    app = QCoreApplication.instance() or QCoreApplication([])
    config = _config(tmp_path / "mp4")
    monkeypatch.setattr("insta360_uploader.gui_backend.settings_model.save_app_config", lambda *a, **k: None)
    model = SettingsModel(config, ProcessedStore())
    model.driveEnabled = True
    model.driveSecretPath = str(tmp_path / "secret.json")
    model.driveTokenPath = str(tmp_path / "token.json")
    model.driveFolderId = "folder-123"
    received = []
    model.configSaved.connect(received.append)
    model.save()
    assert received[-1].drive.enabled is True
    assert received[-1].drive.folder_id == "folder-123"

    model.driveEnabled = False
    model.save()

    saved = received[-1]
    assert saved.drive is not None
    assert saved.drive.enabled is False
    assert saved.drive.folder_id == "folder-123"  # not wiped by disabling
    assert saved.drive_active is False


def test_pipeline_model_apply_new_config_updates_config_and_refreshes_without_restart(tmp_path, monkeypatch):
    # This is exactly what gui_qml.py wires configSaved to — the fix that
    # removed the "restart required to see new settings" limitation.
    app = QCoreApplication.instance() or QCoreApplication([])
    config = _config(tmp_path / "old_mp4")
    monkeypatch.setattr(PipelineModel, "refresh", lambda self: None)  # keep __init__ from touching real disk
    model = PipelineModel(config, ProcessedStore())
    assert model.config is config

    new_config = replace(config, nas_video_folder=tmp_path / "new_mp4")
    refreshed = []
    monkeypatch.setattr(PipelineModel, "refresh", lambda self: refreshed.append(model.config))

    model.apply_new_config(new_config)

    assert model.config is new_config
    assert refreshed == [new_config]  # refresh() ran against the already-swapped config


def test_pipeline_model_apply_new_config_does_not_crash_mid_run(tmp_path, monkeypatch):
    # refresh() itself already no-ops while a run is in progress — applying
    # a config saved mid-run must not fight with that, just take effect
    # (via self.config) the next time refresh() actually runs.
    app = QCoreApplication.instance() or QCoreApplication([])
    config = _config(tmp_path / "old_mp4")
    monkeypatch.setattr(PipelineModel, "refresh", lambda self: None)
    model = PipelineModel(config, ProcessedStore())
    model._running = True

    new_config = replace(config, nas_video_folder=tmp_path / "new_mp4")
    model.apply_new_config(new_config)

    assert model.config is new_config
