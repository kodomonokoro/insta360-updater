"""QML pipeline UI: completion is a fresh artifact observation, not history."""
from __future__ import annotations

from dataclasses import replace
import time
from threading import Thread

from PySide6.QtCore import QObject, Property, Signal, Slot, QThread

from insta360_uploader import pipeline
from insta360_uploader.lifecycle import RunSnapshot, SerialRun, TERMINAL, enabled_stages
from insta360_uploader.camera_pipeline import run_camera_pipeline
from insta360_uploader.camera_scanner import find_camera_drive, scan_camera_folder
from insta360_uploader.stitcher import detect_profile_label
from insta360_uploader.config import AppConfig, validate_for_run
from insta360_uploader.artifact_status import make_target, local_states, RemoteArtifacts
from insta360_uploader.nas_scanner import VideoFile, scan_video_folder
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.video_info import format_duration, format_resolution, probe_duration_seconds, probe_resolution_fps

STAGES = ["コピー", "変換", "音声抽出", "Driveアップロード", "YouTubeアップロード"]
STAGE_KEYS = ["copy", "stitch", "audio", "drive", "youtube"]

STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"

class FileRow(QObject):
    def __init__(self, key: str, name: str, duration: str, video: VideoFile | None = None):
        super().__init__()
        self.key = key
        self.name = name
        self.duration = duration
        self.resolution = "—"  # no resolution-probing exists yet — separate backlog item
        self.selected = False
        self.video = video
        self.stage_status = {k: STATUS_PENDING for k in STAGE_KEYS}
        self.remote_states = {"drive": "checking", "youtube": "checking"}
        self.run_states = {}

    def to_qml(self, excluded_stages: frozenset[str] = frozenset()) -> dict:
        def status(key: str) -> str:
            if key in self.run_states:
                return self.run_states[key].state
            if key in excluded_stages:
                return "excluded"
            return self.stage_status[key]

        def reason(key: str) -> str:
            if key in self.run_states:
                return self.run_states[key].reason
            if key in excluded_stages:
                return "mode"
            return ""

        return {
            "name": self.name,
            "duration": self.duration,
            "resolution": self.resolution,
            "selected": self.selected,
            "stages": [status(k) for k in STAGE_KEYS],
            "reasons": [reason(k) for k in STAGE_KEYS],
        }

    def refresh_artifacts(self, config: AppConfig) -> None:
        """Refresh this row from its actual local artifacts only."""
        if self.video is None:
            return
        target = make_target(self.video, config)
        try:
            self.stage_status.update(local_states(target, config))
        except OSError:
            self.stage_status.update({key: "unknown" for key in ("copy", "stitch", "audio")})
        self.stage_status.update(self.remote_states)
        if config.drive is None:
            self.stage_status["drive"] = "unconfigured"


class ArtifactCheckWorker(QObject):
    result = Signal(int, str, str, str, str)
    finished = Signal()

    def __init__(self, generation, targets, config):
        super().__init__()
        self.generation = generation
        self.targets = targets
        self.config = config

    def run(self):
        try:
            remote = RemoteArtifacts(self.config)
            for target in self.targets:
                for stage, check in (("drive", remote.drive_exists), ("youtube", remote.youtube_exists)):
                    error = ""
                    try:
                        state = "unconfigured" if stage == "drive" and self.config.drive is None else (
                            "done" if check(target) else "pending"
                        )
                    except Exception as exc:
                        state, error = "unknown", str(exc)
                    self.result.emit(self.generation, target.video.key, stage, state, error)
        except RuntimeError:
            # The application may close while a daemon network check ends.
            pass
        finally:
            try:
                self.finished.emit()
            except RuntimeError:
                pass


class CameraPipelineWorker(QThread):
    """Runs the real camera_pipeline.run_camera_pipeline() off the GUI
    thread — same log/on_progress-callables-become-Qt-signals shape as
    ProcessVideosWorker below (verified safe in the migration plan's Step
    2/3 standalone scripts before either was wired in for real)."""

    logLine = Signal(str)
    stateChanged = Signal(object)
    cameraSafe = Signal()
    finished_ = Signal()

    def __init__(
        self,
        rows: list[FileRow],
        config: AppConfig,
        store: ProcessedStore,
        stop_after_stitch: bool,
        skip_audio_drive: bool = False,
    ):
        super().__init__()
        self.rows = rows
        self.config = config
        self.store = store
        self.stop_after_stitch = stop_after_stitch
        self.skip_audio_drive = skip_audio_drive
        # Cooperative: checked between clips/stages only, not during one
        # already in flight — see serial_pipeline.execute()'s docstring.
        self.cancel_requested = False

    def request_stop(self):
        self.cancel_requested = True

    def run(self):
        try:
            videos = [r.video for r in self.rows]
            run_camera_pipeline(
                videos,
                self.config,
                self.store,
                log=lambda msg: self.logLine.emit(msg),
                on_state=self.stateChanged.emit,
                on_camera_safe=lambda: self.cameraSafe.emit(),
                stop_after_stitch=self.stop_after_stitch,
                skip_audio_drive=self.skip_audio_drive,
                should_cancel=lambda: self.cancel_requested,
            )
        except Exception as exc:
            for row in self.rows:
                if self.store.get(row.key) is None:
                    self.store.upsert_pending(row.key, "")
                self.store.mark_failed(row.key, str(exc))
                self.logLine.emit(f"[{row.key}] FAILED: {exc}")
        finally:
            self.finished_.emit()


class ProcessVideosWorker(QThread):
    """Runs the real pipeline.process_videos() (skipIntake path) off the
    GUI thread."""

    logLine = Signal(str)
    stateChanged = Signal(object)
    finished_ = Signal()

    def __init__(
        self, rows: list[FileRow], config: AppConfig, store: ProcessedStore,
        include_audio_drive: bool = True, include_youtube: bool = True,
    ):
        super().__init__()
        self.rows = rows
        self.config = config
        self.store = store
        self.include_audio_drive = include_audio_drive
        self.include_youtube = include_youtube
        # Cooperative: checked between clips/stages only, not during one
        # already in flight — see serial_pipeline.execute()'s docstring.
        self.cancel_requested = False

    def request_stop(self):
        self.cancel_requested = True

    def run(self):
        try:
            videos = [r.video for r in self.rows]
            pipeline.process_videos(
                videos,
                self.config,
                self.store,
                log=lambda msg: self.logLine.emit(msg),
                on_state=self.stateChanged.emit,
                should_cancel=lambda: self.cancel_requested,
                include_audio_drive=self.include_audio_drive,
                include_youtube=self.include_youtube,
            )
        except Exception as exc:
            for row in self.rows:
                if self.store.get(row.key) is None:
                    self.store.upsert_pending(row.key, "")
                self.store.mark_failed(row.key, str(exc))
                self.logLine.emit(f"[{row.key}] FAILED: {exc}")
        finally:
            self.finished_.emit()


class PipelineModel(QObject):
    rowsChanged = Signal()
    sourceMissingMessageChanged = Signal()
    driveActiveChanged = Signal()
    stageChanged = Signal()
    progressChanged = Signal()
    logChanged = Signal()
    cameraBannerChanged = Signal()
    runningChanged = Signal()
    selectionChanged = Signal()
    skipIntakeChanged = Signal()
    stopAfterStitchChanged = Signal()
    skipAudioDriveChanged = Signal()
    skipYoutubeChanged = Signal()
    batchFinished = Signal(str)
    startBlocked = Signal(str)  # validation error — 開始 was refused

    def __init__(self, config: AppConfig, store: ProcessedStore):
        super().__init__()
        self.config = config
        self.store = store
        self.rows: list[FileRow] = []
        self._current_stage = -1
        self._skip_intake = False
        self._stop_after_stitch = False
        self._skip_audio_drive = False
        self._skip_youtube = False
        self._completed_ops = 0
        self._total_ops = 0
        self._current_file_fraction = 0.0
        self._run_snapshot = None
        self._display_task = None
        self._current_task = ""
        self._log_lines: list[str] = []
        self._camera_banner = ""
        self._worker: QThread | None = None
        self._running = False
        self._check_generation = 0
        self._check_worker = None
        self._check_pending = False
        self._source_missing_message = ""
        self.refresh()

    @Slot(object)
    def apply_new_config(self, config: AppConfig):
        """Wired (gui_qml.py) to SettingsModel.configSaved — picks up a
        just-saved settings change immediately instead of needing a
        restart. Safe unconditionally: AppConfig is frozen, so an
        in-flight worker (constructed with the *old* config object by
        value) is completely unaffected by swapping this reference; only
        code that reads self.config from here on sees the new one.
        refresh() itself already no-ops while a run is in progress, so a
        save mid-run just waits — it isn't lost, it takes effect (via
        this same self.config) the next time refresh() actually runs."""
        self.config = config
        self.driveActiveChanged.emit()
        self.refresh()

    # ---- scanning ----
    @Slot()
    def refresh(self):
        if self._running:
            return
        self._clear_run_display()
        new_rows: list[FileRow] = []
        missing_message = ""
        if self._skip_intake:
            try:
                videos = scan_video_folder(self.config.nas_video_folder)
            except FileNotFoundError as exc:
                self._log(str(exc))
                videos = []
                missing_message = "フォルダが見つかりません"
            for video in videos:
                seconds = probe_duration_seconds(video.path)
                duration = format_duration(seconds) if seconds is not None else "—"
                row = FileRow(video.key, video.key, duration, video)
                info = probe_resolution_fps(video.path)
                if info is not None:
                    row.resolution = format_resolution(*info)
                row.refresh_artifacts(self.config)
                new_rows.append(row)
        else:
            drive = find_camera_drive()
            if drive is None:
                self._log("Insta360カメラが見つかりません(USB接続を確認してください)")
                videos = []
                missing_message = "フォルダが見つかりません"
            else:
                try:
                    videos = scan_camera_folder(drive)
                except FileNotFoundError as exc:
                    self._log(str(exc))
                    videos = []
                    missing_message = "フォルダが見つかりません"
            for video in videos:
                chapter_paths = video.chapter_paths or (video.path,)
                total_seconds = 0.0
                known = False
                for p in chapter_paths:
                    s = probe_duration_seconds(p)
                    if s is not None:
                        total_seconds += s
                        known = True
                duration = format_duration(total_seconds) if known else "—"
                row = FileRow(video.key, video.key, duration, video)
                # This row's source of truth is always the camera's raw
                # .insv, never a pre-existing NAS mp4 under the same name —
                # running always (re-)derives from the .insv, so the
                # displayed resolution/fps must reflect what running would
                # actually produce. video.path's own width doesn't
                # correspond to any equirect "K" bucket directly (e.g. a
                # 3840px lens track stitches to 8K, not 4K), so
                # resolution_label() can't be reused — detect_profile_label
                # does the real per-lens-width lookup instead. Fps IS
                # knowable pre-stitch: stitcher.py never overrides it, so
                # the raw file's own rate is what the output will actually
                # have (confirmed against a real clip: raw and stitched
                # r_frame_rate matched exactly, 30000/1001 both times).
                label = detect_profile_label(video.path)
                if label is not None:
                    info = probe_resolution_fps(video.path)
                    fps = info[2] if info else None
                    row.resolution = format_resolution(0, 0, fps, label=label)
                row.refresh_artifacts(self.config)
                new_rows.append(row)

        self.rows = new_rows
        self._source_missing_message = missing_message
        self.sourceMissingMessageChanged.emit()
        self.rowsChanged.emit()
        self.selectionChanged.emit()
        self._request_artifact_check()

    def _refresh_row(self, row):
        row.refresh_artifacts(self.config)

    def _request_artifact_check(self):
        self._check_generation += 1
        self._check_pending = True
        for row in self.rows:
            row.remote_states = {"drive": "checking", "youtube": "checking"}
            self._refresh_row(row)
        self.rowsChanged.emit()
        self._launch_artifact_check()

    def _launch_artifact_check(self):
        if self._check_worker is not None or not self._check_pending:
            return
        self._check_pending = False
        targets = [make_target(row.video, self.config) for row in self.rows if row.video]
        if not targets:
            return
        worker = ArtifactCheckWorker(self._check_generation, targets, self.config)
        worker.result.connect(self._on_artifact_result)
        worker.finished.connect(self._on_artifact_check_finished)
        self._check_worker = worker
        Thread(target=worker.run, daemon=True).start()

    @Slot(int, str, str, str, str)
    def _on_artifact_result(self, generation, key, stage, state, error):
        if self._running or generation != self._check_generation:
            return
        for row in self.rows:
            if row.key == key:
                row.remote_states[stage] = state
                self._refresh_row(row)
                break
        if error:
            self._log(f"[{key}] {stage}: 現物を確認できません: {error}")
        self.rowsChanged.emit()

    @Slot()
    def _on_artifact_check_finished(self):
        self._check_worker = None
        self._launch_artifact_check()

    def _stage_group_inclusion(self) -> tuple[bool, bool]:
        """(include_audio_drive, include_youtube) for the *currently
        selected* run mode — the one place `_stop_after_stitch`/
        `_skip_audio_drive`/`_skip_youtube` (this model's own UI-facing
        preset flags) get translated into lifecycle.enabled_stages()'s
        more general include_audio_drive/include_youtube split. Both
        `_excluded_stage_keys()` (display) and `start()` (the real run)
        call this so the two can never disagree about what a given
        combination of flags actually means."""
        return (
            not self._stop_after_stitch and not self._skip_audio_drive,
            not self._stop_after_stitch and not self._skip_youtube,
        )

    def _excluded_stage_keys(self) -> frozenset[str]:
        """Stages the *currently selected run mode* won't touch — shown as
        a dash in the table even though the row itself hasn't started
        (and possibly already has a real artifact from a past run in a
        different mode). Independent of `stage_status`/`run_states`,
        which answer "does the artifact exist" / "what happened this
        run" — this answers "would this mode even attempt it"."""
        include_audio_drive, include_youtube = self._stage_group_inclusion()
        included = enabled_stages(
            camera=not self._skip_intake,
            drive=self.config.drive_active,
            include_audio_drive=include_audio_drive,
            include_youtube=include_youtube,
        )
        return frozenset(STAGE_KEYS) - frozenset(included)

    # ---- properties exposed to QML ----
    def get_rows(self):
        excluded = self._excluded_stage_keys()
        return [r.to_qml(excluded) for r in self.rows]

    rowsData = Property("QVariantList", get_rows, notify=rowsChanged)

    def get_source_missing_message(self):
        return self._source_missing_message

    sourceMissingMessage = Property(str, get_source_missing_message, notify=sourceMissingMessageChanged)

    def get_drive_active(self):
        return self.config.drive_active

    # Whether Drive is configured *and* enabled right now — drives the
    # main screen's mode label when no debug-only mode is selected (see
    # Main.qml's currentModeLabel): "YouTube・音声出力" if this is true,
    # "YouTube出力" otherwise. No separate flag needed for that choice any
    # more since AppConfig.drive_active already carries it.
    driveActive = Property(bool, get_drive_active, notify=driveActiveChanged)

    @Slot(int, bool)
    def toggle_row_selected(self, index: int, value: bool):
        if self._running:
            return
        self._clear_run_display()
        if 0 <= index < len(self.rows):
            self.rows[index].selected = value
            self.rowsChanged.emit()
            self.selectionChanged.emit()

    @Slot(bool)
    def select_all(self, value: bool):
        if self._running:
            return
        self._clear_run_display()
        for row in self.rows:
            row.selected = value
        self.rowsChanged.emit()
        self.selectionChanged.emit()

    def get_all_selected(self):
        return bool(self.rows) and all(r.selected for r in self.rows)

    allSelected = Property(bool, get_all_selected, notify=selectionChanged)

    def get_stage_names(self):
        return STAGES

    stageNames = Property("QVariantList", get_stage_names, constant=True)

    def get_current_stage(self):
        return self._current_stage

    currentStage = Property(int, get_current_stage, notify=stageChanged)

    def get_progress_fraction(self):
        return self._run_snapshot.fraction if self._run_snapshot else 0.0

    progressFraction = Property(float, get_progress_fraction, notify=progressChanged)

    def get_current_file_fraction(self):
        return self._current_file_fraction

    # How far the *current* file's *current* operation (this one copy, this
    # one upload, ...) has gotten — not the batch-wide op count above.
    currentFileFraction = Property(float, get_current_file_fraction, notify=progressChanged)

    def get_completed_count(self):
        return self._run_snapshot.completed_clips if self._run_snapshot else 0

    completedCount = Property(int, get_completed_count, notify=progressChanged)

    def get_total_count(self):
        return sum(1 for r in self.rows if r.selected)

    totalCount = Property(int, get_total_count, notify=selectionChanged)

    def get_stage_completed_counts(self):
        if self._run_snapshot is None:
            return [0] * len(STAGE_KEYS)
        return [sum(t.stage == stage and t.enabled and t.state in TERMINAL
                    for t in self._run_snapshot.tasks) for stage in STAGE_KEYS]

    stageCompletedCounts = Property("QVariantList", get_stage_completed_counts, notify=rowsChanged)

    def get_stage_run_states(self):
        if self._run_snapshot:
            return [self._run_snapshot.stage_state(stage) for stage in STAGE_KEYS]
        excluded = self._excluded_stage_keys()
        return ["excluded" if stage in excluded else "pending" for stage in STAGE_KEYS]

    stageRunStates = Property("QVariantList", get_stage_run_states, notify=progressChanged)

    def get_stage_fractions(self):
        return [self._run_snapshot.stage_fraction(stage) if self._run_snapshot else 0.0 for stage in STAGE_KEYS]

    stageFractions = Property("QVariantList", get_stage_fractions, notify=progressChanged)
    hasRun = Property(bool, lambda self: self._run_snapshot is not None, notify=progressChanged)
    completedOperations = Property(int, lambda self: self._completed_ops, notify=progressChanged)
    totalOperations = Property(int, lambda self: self._total_ops, notify=progressChanged)
    taskState = Property(str, lambda self: self._display_task.state if self._display_task else "pending", notify=stageChanged)
    taskReason = Property(str, lambda self: self._display_task.reason if self._display_task else "", notify=stageChanged)

    def get_current_task(self):
        return self._current_task

    currentTask = Property(str, get_current_task, notify=stageChanged)

    def get_log_text(self):
        return "\n".join(self._log_lines[-200:])

    logText = Property(str, get_log_text, notify=logChanged)

    def get_camera_banner(self):
        return self._camera_banner

    cameraBanner = Property(str, get_camera_banner, notify=cameraBannerChanged)

    def get_skip_intake(self):
        return self._skip_intake

    def set_skip_intake(self, value: bool):
        if self._running:
            return
        if value != self._skip_intake:
            self._skip_intake = value
            self.skipIntakeChanged.emit()
            self.refresh()

    skipIntake = Property(bool, get_skip_intake, set_skip_intake, notify=skipIntakeChanged)

    def get_stop_after_stitch(self):
        return self._stop_after_stitch

    def set_stop_after_stitch(self, value: bool):
        if self._running:
            return
        if value != self._stop_after_stitch:
            self._stop_after_stitch = value
            self._clear_run_display()
            self.stopAfterStitchChanged.emit()

    stopAfterStitch = Property(bool, get_stop_after_stitch, set_stop_after_stitch, notify=stopAfterStitchChanged)

    def get_skip_audio_drive(self):
        return self._skip_audio_drive

    def set_skip_audio_drive(self, value: bool):
        if self._running:
            return
        if value != self._skip_audio_drive:
            self._skip_audio_drive = value
            self._clear_run_display()
            self.skipAudioDriveChanged.emit()

    skipAudioDrive = Property(bool, get_skip_audio_drive, set_skip_audio_drive, notify=skipAudioDriveChanged)

    def get_skip_youtube(self):
        return self._skip_youtube

    def set_skip_youtube(self, value: bool):
        if self._running:
            return
        if value != self._skip_youtube:
            self._skip_youtube = value
            self._clear_run_display()
            self.skipYoutubeChanged.emit()

    skipYoutube = Property(bool, get_skip_youtube, set_skip_youtube, notify=skipYoutubeChanged)

    def get_running(self):
        return self._running

    running = Property(bool, get_running, notify=runningChanged)

    # ---- shared mutation helpers ----
    def _log(self, line: str):
        self._log_lines.append(f"{time.strftime('%H:%M:%S')}  {line}")
        self.logChanged.emit()

    def _clear_run_display(self):
        self._run_snapshot = None
        self._display_task = None
        self._current_stage = -1
        self._current_task = ""
        self._current_file_fraction = 0.0
        self._completed_ops = self._total_ops = 0
        for row in self.rows:
            row.run_states = {}
        self.rowsChanged.emit()
        self.stageChanged.emit()
        self.progressChanged.emit()

    @Slot(str)
    def _on_real_log_line(self, line: str):
        # Logs are only logs. Lifecycle is delivered on stateChanged.
        self._log(line)

    @Slot(object)
    def _on_run_state(self, snapshot: RunSnapshot):
        previous = self._run_snapshot
        previous_states = {(t.key, t.stage): (t.state, t.reason) for t in previous.tasks} if previous else {}
        states = {(t.key, t.stage): (t.state, t.reason) for t in snapshot.tasks}
        self._run_snapshot = snapshot
        task = snapshot.active
        if task is None and self._display_task is not None:
            task = next((t for t in snapshot.tasks if (t.key, t.stage) ==
                         (self._display_task.key, self._display_task.stage)), None)
        if task is None:
            task = next((t for t in snapshot.tasks if t.enabled and t.state == "failed"), None)
        self._display_task = task
        self._current_stage = STAGE_KEYS.index(task.stage) if task else -1
        self._current_task = task.key if task else ""
        self._current_file_fraction = task.fraction if task else 0.0
        self._completed_ops = snapshot.completed
        self._total_ops = snapshot.total
        for row in self.rows:
            row.run_states = {t.stage: t for t in snapshot.tasks if t.key == row.key}
        # Do not rebuild the ListView on each percent change; that would
        # recreate the spinning icon and restart its animation repeatedly.
        if states != previous_states:
            self.rowsChanged.emit()
        self.stageChanged.emit()
        self.progressChanged.emit()

    # ---- slots callable from QML ----
    @Slot()
    def start(self):
        if self._running:
            return
        selected = [r for r in self.rows if r.selected]
        if not selected:
            self._log("選択なし: 処理対象の動画を選んでください")
            return

        include_audio_drive, include_youtube = self._stage_group_inclusion()
        error = validate_for_run(
            self.config,
            camera=not self._skip_intake,
            include_audio_drive=include_audio_drive,
            include_youtube=include_youtube,
        )
        if error:
            self.startBlocked.emit(error)
            return

        self.store.clear()
        self._clear_run_display()
        self._camera_banner = ""
        self.cameraBannerChanged.emit()
        # Invalidate pre-run observations. They cannot overwrite run events.
        self._check_generation += 1
        self._check_pending = False
        self._running = True
        self.runningChanged.emit()
        stages = enabled_stages(camera=not self._skip_intake, drive=self.config.drive_active,
                                include_audio_drive=include_audio_drive,
                                include_youtube=include_youtube)
        initial = SerialRun([row.key for row in selected], stages).snapshot()
        self._on_run_state(initial)
        if self._skip_intake:
            worker = ProcessVideosWorker(
                selected, self.config, self.store,
                include_audio_drive=include_audio_drive, include_youtube=include_youtube,
            )
        else:
            worker = CameraPipelineWorker(
                selected, self.config, self.store, self._stop_after_stitch, self._skip_audio_drive
            )
            worker.cameraSafe.connect(self._on_camera_safe)
        worker.logLine.connect(self._on_real_log_line)
        worker.stateChanged.connect(self._on_run_state)
        worker.finished_.connect(self._on_finished)
        self._worker = worker
        self._worker.start()

    @Slot()
    def stop(self):
        if self._worker:
            self._worker.request_stop()
            self._log("停止をリクエストしました。現在処理中の項目が完了し次第、停止します")

    def _on_camera_safe(self):
        self._camera_banner = "NASへのコピーが完了しました。カメラを取り外しても処理は続行されます。"
        self.cameraBannerChanged.emit()

    @Slot()
    def dismiss_camera_banner(self):
        self._camera_banner = ""
        self.cameraBannerChanged.emit()

    def _on_finished(self):
        snapshot = self._run_snapshot
        if snapshot is not None and not snapshot.finished:
            # Unexpected errors outside an operation still resolve the run.
            # Never report pending tasks as successes or leave a spinner on.
            failed_keys = set()
            tasks = []
            for task in snapshot.tasks:
                if task.state not in TERMINAL:
                    state = "failed" if task.key not in failed_keys else "skipped"
                    failed_keys.add(task.key)
                    task = replace(task, state=state, reason="worker_error")
                tasks.append(task)
            snapshot = RunSnapshot(tuple(tasks), finished=True)
            self._on_run_state(snapshot)
        failed = snapshot.failed_clips if snapshot else len([r for r in self.rows if r.selected])
        succeeded = snapshot.completed_clips if snapshot else 0
        cancelled = snapshot.cancelled_clips if snapshot else 0
        outcomes = [f"{succeeded}件成功"]
        if failed:
            outcomes.append(f"{failed}件失敗")
        if cancelled:
            outcomes.append(f"{cancelled}件停止")
        message = f"{'処理を停止しました' if cancelled else '処理が完了しました'}（{' / '.join(outcomes)}）"

        self._running = False
        self.runningChanged.emit()
        self.stageChanged.emit()
        self.progressChanged.emit()
        # Preserve this run's terminal results. Refresh resets them and
        # shows artifact existence alone, without any persistent history.
        self._request_artifact_check()
        self._log("--- 完了 ---")
        self.batchFinished.emit(message)
