"""QML-facing settings screen backend — a straight port of gui.py's
SettingsView (Flet) onto Property/Slot, same behavior:
- Saving builds a brand-new AppConfig from the form fields, calls
  settings_store.save_app_config(), and emits configSaved(new_config) so
  gui_qml.py's wiring can push it into PipelineModel live — no restart
  needed any more (each backend otherwise only ever sees the AppConfig
  it was constructed with).
- OAuth flows run on a background QThread (network + opens a browser for
  consent) so the GUI thread never blocks, same reason gui.py's
  _on_auth_youtube_click/_on_auth_gdrive_click use page.run_thread.
- media_sdk is only constructed if the user filled in at least one of its
  two fields, matching gui.py's _on_save_clicked exactly (an all-blank SDK
  section means "not configured", not "configured with empty paths").
"""
from __future__ import annotations

from pathlib import Path
from threading import Thread

from PySide6.QtCore import QObject, Property, Signal, Slot, QThread

from insta360_uploader import cleanup
from insta360_uploader.config import (
    DEFAULT_RETENTION_DAYS,
    VALID_PRIVACY_STATUSES,
    AppConfig,
    DriveConfig,
    MediaSdkConfig,
    YoutubeDefaults,
    YoutubeProfile,
)
from insta360_uploader.gdrive_uploader import DriveError
from insta360_uploader.gdrive_uploader import run_oauth_flow as run_gdrive_oauth_flow
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.settings_store import save_app_config
from insta360_uploader.youtube_uploader import UploadError
from insta360_uploader.youtube_uploader import run_oauth_flow as run_youtube_oauth_flow


class _OAuthWorker(QThread):
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, flow_fn, arg):
        super().__init__()
        self._flow_fn = flow_fn
        self._arg = arg

    def run(self):
        try:
            self._flow_fn(self._arg)
        except (UploadError, DriveError) as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit()


class _CleanupCheckWorker(QObject):
    result = Signal(object, object, str, bool)

    def __init__(self, config, store, expired_only):
        super().__init__()
        self.config, self.store, self.expired_only = config, store, expired_only

    def run(self):
        try:
            if self.expired_only:
                clips = cleanup.find_stale_clips(self.store, self.config, self.config.retention_days)
            else:
                clips = cleanup.find_all_clip_files(self.store, self.config)
            folders = [self.config.nas_video_folder]
            if self.config.raw_folder is not None:
                folders.append(self.config.raw_folder)
            if self.config.mp3_folder is not None:
                folders.append(self.config.mp3_folder)
            parts = cleanup.find_orphaned_part_files(*folders)
            error = ""
        except Exception as exc:
            clips, parts, error = [], [], str(exc)
        try:
            self.result.emit(clips, parts, error, self.expired_only)
        except RuntimeError:
            pass


class SettingsModel(QObject):
    fieldsChanged = Signal()
    driveEnabledChanged = Signal()
    authStatusChanged = Signal()
    authBusyChanged = Signal()
    saved = Signal(str)  # message for a confirmation dialog
    cleanupCandidates = Signal(str)  # pre-built confirmation message
    cleanupDone = Signal(int)  # total_files deleted
    cleanupNone = Signal()
    clearFolderCandidate = Signal(str)  # pre-built confirmation message
    clearFolderFilesChanged = Signal()  # backs clearFolderFiles below
    clearFolderDone = Signal(int)  # files removed — separate from `saved`
    # so the file table can be refreshed after, like cleanupDone does
    configSaved = Signal(object)  # the new AppConfig — see save(); lets
    # PipelineModel pick it up live instead of needing a restart, since
    # each backend otherwise only ever sees the AppConfig it was
    # constructed with (gui_qml.py wires this to PipelineModel.apply_new_config).

    def __init__(self, config: AppConfig, store: ProcessedStore):
        super().__init__()
        self.store = store
        self._oauth_worker: QThread | None = None
        self._cleanup_worker = None
        self._pending_clear_folder: Path | None = None
        self._clear_folder_files: list[str] = []
        self._load_from(config)

    def _load_from(self, config: AppConfig) -> None:
        self.config = config
        self.nas_folder = str(config.nas_video_folder)
        # No auto-derived fallback exists any more — blank genuinely means
        # "not configured", checked at 開始-press time by
        # config.validate_for_run() for whichever run mode actually needs
        # it (raw for ①②, mp3 for ③④). Not required just to open Settings.
        self.raw_folder = str(config.raw_folder) if config.raw_folder else ""
        self.mp3_folder = str(config.mp3_folder) if config.mp3_folder else ""
        self.yt_secret_path = str(config.youtube.client_secret_path)
        self.yt_token_path = str(config.youtube.token_path)
        self.title_prefix = config.youtube_defaults.title_prefix
        self.privacy_status = config.youtube_defaults.privacy_status
        self.made_for_kids = config.youtube_defaults.made_for_kids
        self.playlist_id = config.youtube_defaults.playlist_id or ""
        drive = config.drive
        # Field values populate whenever a DriveConfig exists at all — even
        # disabled, its fields are exactly what the user last entered, and
        # should reappear as-is if they flip the toggle back on.
        self.drive_enabled = drive is not None and drive.enabled
        self.drive_secret_path = str(drive.client_secret_path) if drive else ""
        self.drive_token_path = str(drive.token_path) if drive else ""
        self.drive_folder_id = (drive.folder_id or "") if drive else ""
        self.drive_subfolder_prefix = (drive.subfolder_prefix or "") if drive else ""
        media_sdk = config.media_sdk
        self.sdk_exe_path = str(media_sdk.exe_path) if media_sdk else ""
        self.sdk_model_dir = str(media_sdk.model_root_dir) if media_sdk else ""
        self.retention_days = config.retention_days

    # ---- simple string/bool/int fields (two-way, no per-field notify —
    # QML TextField.text: backend.xxx bindings here are one-shot initial
    # values read once at screen-open time, matching how gui.py's
    # SettingsView only ever reads its fields back out at save time; not
    # updated live from elsewhere while the screen is open) ----
    def get_nas_folder(self):
        return self.nas_folder

    def set_nas_folder(self, v):
        self.nas_folder = v

    nasFolder = Property(str, get_nas_folder, set_nas_folder)

    def get_raw_folder(self):
        return self.raw_folder

    def set_raw_folder(self, v):
        self.raw_folder = v

    rawFolder = Property(str, get_raw_folder, set_raw_folder)

    def get_mp3_folder(self):
        return self.mp3_folder

    def set_mp3_folder(self, v):
        self.mp3_folder = v

    mp3Folder = Property(str, get_mp3_folder, set_mp3_folder)

    def get_yt_secret_path(self):
        return self.yt_secret_path

    def set_yt_secret_path(self, v):
        self.yt_secret_path = v

    ytSecretPath = Property(str, get_yt_secret_path, set_yt_secret_path)

    def get_yt_token_path(self):
        return self.yt_token_path

    def set_yt_token_path(self, v):
        self.yt_token_path = v

    ytTokenPath = Property(str, get_yt_token_path, set_yt_token_path)

    def get_title_prefix(self):
        return self.title_prefix

    def set_title_prefix(self, v):
        self.title_prefix = v

    titlePrefix = Property(str, get_title_prefix, set_title_prefix)

    def get_privacy_status(self):
        return self.privacy_status

    def set_privacy_status(self, v):
        self.privacy_status = v

    privacyStatus = Property(str, get_privacy_status, set_privacy_status)

    def get_privacy_options(self):
        return list(VALID_PRIVACY_STATUSES)

    privacyOptions = Property("QVariantList", get_privacy_options, constant=True)

    def get_made_for_kids(self):
        return self.made_for_kids

    def set_made_for_kids(self, v):
        self.made_for_kids = v

    madeForKids = Property(bool, get_made_for_kids, set_made_for_kids)

    def get_playlist_id(self):
        return self.playlist_id

    def set_playlist_id(self, v):
        self.playlist_id = v

    playlistId = Property(str, get_playlist_id, set_playlist_id)

    def get_drive_enabled(self):
        return self.drive_enabled

    def set_drive_enabled(self, v):
        if v != self.drive_enabled:
            self.drive_enabled = v
            self.driveEnabledChanged.emit()

    driveEnabled = Property(bool, get_drive_enabled, set_drive_enabled, notify=driveEnabledChanged)

    def get_drive_secret_path(self):
        return self.drive_secret_path

    def set_drive_secret_path(self, v):
        self.drive_secret_path = v

    driveSecretPath = Property(str, get_drive_secret_path, set_drive_secret_path)

    def get_drive_token_path(self):
        return self.drive_token_path

    def set_drive_token_path(self, v):
        self.drive_token_path = v

    driveTokenPath = Property(str, get_drive_token_path, set_drive_token_path)

    def get_drive_folder_id(self):
        return self.drive_folder_id

    def set_drive_folder_id(self, v):
        self.drive_folder_id = v

    driveFolderId = Property(str, get_drive_folder_id, set_drive_folder_id)

    def get_drive_subfolder_prefix(self):
        return self.drive_subfolder_prefix

    def set_drive_subfolder_prefix(self, v):
        self.drive_subfolder_prefix = v

    driveSubfolderPrefix = Property(str, get_drive_subfolder_prefix, set_drive_subfolder_prefix)

    def get_sdk_exe_path(self):
        return self.sdk_exe_path

    def set_sdk_exe_path(self, v):
        self.sdk_exe_path = v

    sdkExePath = Property(str, get_sdk_exe_path, set_sdk_exe_path)

    def get_sdk_model_dir(self):
        return self.sdk_model_dir

    def set_sdk_model_dir(self, v):
        self.sdk_model_dir = v

    sdkModelDir = Property(str, get_sdk_model_dir, set_sdk_model_dir)

    def get_retention_days(self):
        return self.retention_days

    def set_retention_days(self, v):
        self.retention_days = v

    retentionDays = Property(int, get_retention_days, set_retention_days)

    # ---- auth status ----
    def get_youtube_auth_ok(self):
        return Path(self.yt_token_path).is_file()

    youtubeAuthOk = Property(bool, get_youtube_auth_ok, notify=authStatusChanged)

    def get_drive_auth_ok(self):
        return self.drive_enabled and Path(self.drive_token_path).is_file()

    driveAuthOk = Property(bool, get_drive_auth_ok, notify=authStatusChanged)

    def get_auth_busy(self):
        return self._oauth_worker is not None

    authBusy = Property(bool, get_auth_busy, notify=authBusyChanged)

    # ---- slots ----
    @Slot()
    def authYoutube(self):
        if self._oauth_worker is not None:
            return
        profile = YoutubeProfile(
            client_secret_path=Path(self.yt_secret_path), token_path=Path(self.yt_token_path)
        )
        self._start_oauth(run_youtube_oauth_flow, profile, "YouTube")

    @Slot()
    def authDrive(self):
        if self._oauth_worker is not None or not self.drive_enabled:
            return
        drive = DriveConfig(
            client_secret_path=Path(self.drive_secret_path),
            token_path=Path(self.drive_token_path),
            folder_id=self.drive_folder_id or None,
            subfolder_prefix=self.drive_subfolder_prefix or None,
        )
        self._start_oauth(run_gdrive_oauth_flow, drive, "Google Drive")

    def _start_oauth(self, flow_fn, arg, label: str):
        worker = _OAuthWorker(flow_fn, arg)
        worker.succeeded.connect(lambda: self._on_oauth_done(label, None))
        worker.failed.connect(lambda msg: self._on_oauth_done(label, msg))
        self._oauth_worker = worker
        self.authBusyChanged.emit()
        worker.start()

    def _on_oauth_done(self, label: str, error: str | None):
        self._oauth_worker = None
        self.authBusyChanged.emit()
        self.authStatusChanged.emit()
        if error:
            self.saved.emit(f"{label}の認証エラー: {error}")
        else:
            self.saved.emit(f"{label}の認証が完了しました。")

    @Slot()
    def save(self):
        # Keep a DriveConfig (fields intact, just enabled=False) rather than
        # discarding it back to None the moment the toggle goes off — a
        # previously-entered secret/token/folder must survive OFF+save, not
        # just OFF within the current session (self.drive_secret_path etc.
        # were never cleared either way; the risk was only ever this object
        # collapsing to None and _app_config_to_dict() then omitting the
        # whole google_drive section on write). None only for a config
        # that's never once had Drive enabled at all — no fields to lose.
        drive_config = None
        if self.drive_enabled or self.config.drive is not None:
            drive_config = DriveConfig(
                client_secret_path=Path(self.drive_secret_path or ""),
                token_path=Path(self.drive_token_path or ""),
                folder_id=self.drive_folder_id or None,
                subfolder_prefix=self.drive_subfolder_prefix or None,
                enabled=self.drive_enabled,
            )

        new_config = AppConfig(
            nas_video_folder=Path(self.nas_folder or ""),
            raw_folder=Path(self.raw_folder) if self.raw_folder else None,
            mp3_folder=Path(self.mp3_folder) if self.mp3_folder else None,
            youtube=YoutubeProfile(
                client_secret_path=Path(self.yt_secret_path or ""),
                token_path=Path(self.yt_token_path or ""),
            ),
            youtube_defaults=YoutubeDefaults(
                title_prefix=self.title_prefix or "",
                privacy_status=self.privacy_status or "unlisted",
                made_for_kids=self.made_for_kids,
                playlist_id=self.playlist_id or None,
            ),
            drive=drive_config,
            media_sdk=(
                MediaSdkConfig(
                    exe_path=Path(self.sdk_exe_path or ""),
                    model_root_dir=Path(self.sdk_model_dir or ""),
                )
                if self.sdk_exe_path or self.sdk_model_dir
                else None
            ),
            retention_days=int(self.retention_days or DEFAULT_RETENTION_DAYS),
        )
        save_app_config(new_config)
        self._load_from(new_config)
        self.authStatusChanged.emit()
        self.configSaved.emit(new_config)
        self.saved.emit("設定を保存しました。")

    def _start_cleanup_check(self, expired_only):
        if self._cleanup_worker is not None or self.config.nas_video_folder == Path(""):
            return
        self._pending_cleanup = ([], [])
        worker = _CleanupCheckWorker(self.config, self.store, expired_only)
        worker.result.connect(self._on_cleanup_checked)
        self._cleanup_worker = worker
        Thread(target=worker.run, daemon=True).start()

    @Slot()
    def checkStaleClips(self):
        self._start_cleanup_check(True)

    # ---- per-folder "clear everything in here" (unconditional, unlike
    # the verified-upload-only cleanup above) ----
    _CLEAR_FOLDER_LABELS = {"raw": "コピー先(raw)", "mp4": "映像抽出先(MP4)", "mp3": "音声抽出先(MP3)"}

    def _folder_for_clearing(self, which: str) -> Path | None:
        # Operates on the currently-*active* (saved) config, not unsaved
        # form edits — clearing must match what the app is actually using
        # right now, not a path the user just typed but hasn't saved yet.
        if which == "raw":
            return self.config.raw_folder
        if which == "mp4":
            return self.config.nas_video_folder
        if which == "mp3":
            return self.config.mp3_folder
        return None

    def get_clear_folder_files(self):
        return self._clear_folder_files

    clearFolderFiles = Property("QVariantList", get_clear_folder_files, notify=clearFolderFilesChanged)

    @Slot(str)
    def checkClearFolder(self, which: str):
        folder = self._folder_for_clearing(which)
        if folder is None:
            return
        files = cleanup.list_files(folder)
        if not files:
            self.saved.emit("削除できるファイルはありませんでした。")
            return
        self._pending_clear_folder = folder
        # Relative to folder (not just the bare filename) so a file sitting
        # inside a subfolder still shows where it actually is — clear_folder_
        # contents() below deletes subfolders recursively too, not just
        # top-level files.
        self._clear_folder_files = [str(p.relative_to(folder)) for p in files]
        self.clearFolderFilesChanged.emit()
        label = self._CLEAR_FOLDER_LABELS.get(which, which)
        self.clearFolderCandidate.emit(
            f"{label}内の{len(files)}件のファイルを完全に削除します。"
            "アップロード状況に関係なくフォルダ内を全て削除し、対象は以下の一覧の通りです。"
        )

    @Slot()
    def confirmClearFolder(self):
        folder = getattr(self, "_pending_clear_folder", None)
        if folder is None:
            return
        self._pending_clear_folder = None
        count = cleanup.clear_folder_contents(folder)
        self.clearFolderDone.emit(count)

    @Slot(object, object, str, bool)
    def _on_cleanup_checked(self, stale, orphaned, error, expired_only):
        self._cleanup_worker = None
        if error:
            self.saved.emit(f"削除候補の現物確認に失敗しました。削除は行いません。\n{error}")
            return
        self._pending_cleanup = (stale, orphaned)
        total_files = sum(len(c.files) for c in stale) + len(orphaned)
        if total_files:
            self.cleanupCandidates.emit(
                f"アップロード先を確認済みのクリップ{len(stale)}件・一時ファイル{len(orphaned)}件、"
                f"合計{total_files}件のファイルを削除しますか?"
            )
        elif not expired_only:
            self.cleanupNone.emit()

    @Slot()
    def confirmCleanup(self):
        stale, orphaned = getattr(self, "_pending_cleanup", ([], []))
        total = 0
        for clip in stale:
            total += len(cleanup.delete_files(clip.files))
        total += len(cleanup.delete_files(orphaned))
        self.cleanupDone.emit(total)
