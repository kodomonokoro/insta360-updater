from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from insta360_uploader import camera_pipeline, pipeline
from insta360_uploader.config import AppConfig, DriveConfig, MediaSdkConfig, YoutubeDefaults, YoutubeProfile
from insta360_uploader.gui_backend import pipeline_model as ui
from insta360_uploader.lifecycle import SerialRun, enabled_stages
from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.processed_store import ProcessedStore


@pytest.fixture
def config(tmp_path):
    # validate_for_run() now checks these actually exist (YouTube/Drive
    # auth tokens, MediaSDKTest.exe) before any stage runs — real, if
    # empty, files rather than bare directories so every run mode in
    # these tests passes validation and reaches the stage logic being
    # tested.
    (tmp_path / "yt_token.json").write_bytes(b"0")
    (tmp_path / "drive_token.json").write_bytes(b"0")
    (tmp_path / "MediaSDKTest.exe").write_bytes(b"0")
    return AppConfig(tmp_path / "processed" / "mp4",
                     YoutubeProfile(tmp_path, tmp_path / "yt_token.json"),
                     YoutubeDefaults("p", "unlisted", False, None),
                     DriveConfig(tmp_path, tmp_path / "drive_token.json", "folder", None),
                     MediaSdkConfig(tmp_path / "MediaSDKTest.exe", tmp_path), 14,
                     raw_folder=tmp_path / "raw", mp3_folder=tmp_path / "mp3")


@pytest.fixture
def videos(tmp_path):
    result = []
    for time in ("120000", "130000"):
        path = tmp_path / f"VID_20260905_{time}_00_001.insv"
        path.write_bytes(b"raw")
        result.append(VideoFile(path.stem, path, (path,)))
    return result


def task(snapshot, key, stage):
    return next(t for t in snapshot.tasks if t.key == key and t.stage == stage)


def test_transition_boundaries_monotonic_progress_and_no_late_updates():
    snapshots = []
    run = SerialRun(["a", "b"], ("copy",), snapshots.append)
    late = []
    def copy(progress, skip):
        assert snapshots[-1].active.key == "a"
        assert snapshots[-1].active.fraction == 0
        progress(.6)
        progress(.2)
        assert snapshots[-1].active.fraction == .6
        progress(1)
        assert snapshots[-1].completed == 0
        assert snapshots[-1].active.state == "current"
        late.append(progress)
    run.perform("a", "copy", copy)
    assert snapshots[-1].active is None
    assert snapshots[-1].completed == 1
    assert task(snapshots[-1], "a", "copy").state == "done"
    before = len(snapshots)
    late[0](.9)
    assert len(snapshots) == before
    run.perform("b", "copy", lambda progress, skip: skip())
    run.finish()
    assert snapshots[-1].fraction == 1
    assert snapshots[-1].completed_clips == 2
    assert task(snapshots[-1], "b", "copy").state == "skipped"
    assert task(snapshots[-1], "b", "copy").reason == "exists"
    assert all(sum(t.state == "current" for t in s.tasks) <= 1 for s in snapshots)


def test_failure_after_skip_signal_is_failure_and_dependencies_resolve():
    run = SerialRun(["a"], ("audio", "drive", "youtube"))
    def broken(progress, skip):
        skip()
        progress(.4)
        raise RuntimeError("disk failed")
    assert not run.perform("a", "audio", broken)
    snapshot = run.snapshot()
    assert task(snapshot, "a", "audio").state == "failed"
    assert task(snapshot, "a", "drive").reason == "dependency"
    assert snapshot.completed == snapshot.total == 3
    assert snapshot.failed_clips == 1
    assert snapshot.stage_state("audio") == "failed"
    assert not snapshot.active
    run.finish()


def test_cancel_remaining_skips_only_pending_tasks_and_finish_succeeds():
    run = SerialRun(["a", "b"], ("copy", "stitch"))
    assert run.perform("a", "copy", lambda progress, skip: None)
    run.cancel_remaining()
    snapshot = run.snapshot()
    assert task(snapshot, "a", "copy").state == "done"  # already-finished work is untouched
    assert task(snapshot, "a", "stitch").state == "skipped"
    assert task(snapshot, "a", "stitch").reason == "cancelled"
    assert task(snapshot, "b", "copy").state == "skipped"
    assert task(snapshot, "b", "copy").reason == "cancelled"
    run.finish()  # would raise if any task were left non-terminal
    assert run.snapshot().finished
    # Finishing the run only means every task has a final state.  The clip
    # was stopped before all required artifacts existed, so it is not a
    # successful completion.
    assert run.snapshot().terminal_clips == 2
    assert run.snapshot().completed_clips == 0
    assert run.snapshot().cancelled_clips == 2
    assert run.snapshot().stage_state("copy") == "partial"
    assert run.snapshot().stage_state("stitch") == "skipped"


def test_existing_artifacts_are_successes_but_cancelled_work_is_not():
    run = SerialRun(["already-there", "stopped"], ("audio",))
    run.perform("already-there", "audio", lambda progress, skip: skip())
    run.cancel_remaining()
    run.finish()

    snapshot = run.snapshot()
    assert snapshot.completed_clips == 1
    assert snapshot.cancelled_clips == 1
    assert snapshot.failed_clips == 0
    # One successful row and one stopped row makes the shared stage partial.
    assert snapshot.stage_state("audio") == "partial"


def test_enabled_stages_skip_audio_drive_keeps_youtube():
    # "YouTube出力" — skips audio/drive even though Drive IS configured,
    # unlike drive=False (Drive simply not set up) which does the same
    # thing for a different reason.
    assert enabled_stages(camera=True, drive=True, include_audio_drive=False) == ("copy", "stitch", "youtube")


def test_enabled_stages_skip_audio_drive_with_stop_after_stitch_is_still_copy_stitch_only():
    assert enabled_stages(
        camera=True, drive=True, include_audio_drive=False, include_youtube=False
    ) == ("copy", "stitch")


def test_enabled_stages_youtube_only_without_camera():
    # "デバッグ：YouTube取り込み" — audio/drive skipped, no camera source,
    # just the upload stage in isolation.
    assert enabled_stages(camera=False, drive=True, include_audio_drive=False) == ("youtube",)


def test_enabled_stages_audio_drive_only_without_camera_or_youtube():
    # "デバッグ：音声出力" — the reverse: audio/drive alone, no upload.
    assert enabled_stages(camera=False, drive=True, include_youtube=False) == ("audio", "drive")


@pytest.mark.parametrize("camera,drive,stop", [(True, True, False), (True, False, False),
                                               (True, True, True), (False, True, False)])
def test_pipeline_order_and_every_boundary(config, videos, monkeypatch, camera, drive, stop):
    # (camera=False, drive=False) isn't exercised here with include_audio_
    # drive=True (this test always passes process_videos() its default
    # True/True) — only the camera path exercises skipping audio/drive on
    # purpose (the (True, False, False) case below, "YouTube出力").
    if not drive:
        config = replace(config, drive=None)
    # Real callers reach "no audio/drive stages" either by configuring
    # Drive and explicitly asking to skip it (skip_audio_drive) or by
    # simply never configuring Drive at all — validate_for_run() only
    # requires Drive when include_audio_drive is True, so the drive=False
    # case here needs skip_audio_drive=True (run_camera_pipeline's own
    # preset flag) to still pass validation.
    skip_audio_drive = not drive
    snapshots, calls, camera_safe = [], [], []
    stages = enabled_stages(camera=camera, drive=drive, include_audio_drive=not stop, include_youtube=not stop)
    def operation(stage):
        def perform(video, *args, on_skip=None):
            progress = args[-1]
            assert snapshots[-1].active.key == video.key
            assert snapshots[-1].active.stage == stage
            assert snapshots[-1].active.fraction == 0
            calls.append((video.key, stage))
            progress(.5)
            assert snapshots[-1].active.fraction == .5
            # One clip is already present at every destination.
            if video == videos[0]:
                on_skip()
            return Path("audio.mp3")
        return perform
    names = {"copy": "copy_raw", "stitch": "stitch", "audio": "extract_audio",
             "drive": "upload_audio_to_drive", "youtube": "upload_to_youtube"}
    module = camera_pipeline if camera else pipeline
    for stage in stages:
        monkeypatch.setattr(module, names[stage], operation(stage))
    if camera:
        result = module.run_camera_pipeline(videos, config, ProcessedStore(), lambda _: None,
                                            on_state=snapshots.append, stop_after_stitch=stop,
                                            skip_audio_drive=skip_audio_drive,
                                            on_camera_safe=lambda: camera_safe.append(list(calls)))
    else:
        result = module.process_videos(videos, config, ProcessedStore(), lambda _: None, on_state=snapshots.append)
    expected = ([(v.key, s) for s in stages for v in videos] if camera else
                [(v.key, s) for v in videos for s in stages])
    assert calls == expected
    assert result.finished and result.active is None
    assert result.completed == result.total == len(videos) * len(stages)
    assert result.fraction == 1 and result.failed_clips == 0
    assert all(sum(t.state == "current" for t in s.tasks) <= 1 for s in snapshots)
    # Every operation has exactly one current->terminal transition.
    transitions = []
    for before, after in zip(snapshots, snapshots[1:]):
        if before.active and after.active is None:
            transitions.append((before.active.key, before.active.stage))
    assert transitions == calls
    if camera:
        assert camera_safe == [[(v.key, "copy") for v in videos]]


@pytest.mark.parametrize("camera", [True, False])
def test_should_cancel_stops_after_the_in_flight_operation_finishes(config, videos, monkeypatch, camera):
    # Cooperative stop: should_cancel is only checked *between* perform()
    # calls. The operation already dispatched for the first clip/stage
    # runs to completion regardless; nothing after that starts.
    module = camera_pipeline if camera else pipeline
    calls = []
    cancel_requested = False

    def operation(stage):
        def perform(video, *args, on_skip=None):
            nonlocal cancel_requested
            calls.append((video.key, stage))
            cancel_requested = True  # take effect only from the *next* call onward
            return Path("audio.mp3")
        return perform

    names = {"copy": "copy_raw", "stitch": "stitch", "audio": "extract_audio",
             "drive": "upload_audio_to_drive", "youtube": "upload_to_youtube"}
    for stage, name in names.items():
        if hasattr(module, name):
            monkeypatch.setattr(module, name, operation(stage))
    fn = module.run_camera_pipeline if camera else module.process_videos
    result = fn(videos, config, ProcessedStore(), lambda _: None, should_cancel=lambda: cancel_requested)

    assert calls == [(videos[0].key, "copy" if camera else "audio")]  # exactly the one in-flight operation
    assert result.finished  # cancel_remaining() resolved every leftover task, so finish() didn't raise
    assert all(t.state == "skipped" and t.reason == "cancelled"
               for t in result.tasks if t.enabled and (t.key, t.stage) not in calls)


@pytest.mark.parametrize("camera", [True, False])
def test_failure_does_not_stall_progress_or_run_dependents(config, videos, monkeypatch, camera):
    module = camera_pipeline if camera else pipeline
    calls, snapshots = [], []
    def operation(stage):
        def perform(video, *args, on_skip=None):
            calls.append((video.key, stage))
            if video == videos[0] and stage == "audio":
                raise RuntimeError("extract failed")
            return Path("audio.mp3")
        return perform
    names = {"copy": "copy_raw", "stitch": "stitch", "audio": "extract_audio",
             "drive": "upload_audio_to_drive", "youtube": "upload_to_youtube"}
    for stage, name in names.items():
        if hasattr(module, name):
            monkeypatch.setattr(module, name, operation(stage))
    fn = module.run_camera_pipeline if camera else module.process_videos
    result = fn(videos, config, ProcessedStore(), lambda _: None, on_state=snapshots.append)
    assert (videos[0].key, "drive") not in calls
    assert (videos[0].key, "youtube") not in calls
    assert (videos[1].key, "youtube") in calls
    assert result.completed == result.total
    assert result.fraction == 1 and result.failed_clips == 1
    assert result.stage_state("audio") == "failed"


def test_all_three_ui_displays_follow_one_snapshot(config, videos, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(ui.PipelineModel, "refresh", lambda self: None)
    model = ui.PipelineModel(config, ProcessedStore())
    model.rows = [ui.FileRow(v.key, v.key, "", v) for v in videos]
    model._running = True
    updates = []
    model.rowsChanged.connect(lambda: updates.append(True))
    run = SerialRun([v.key for v in videos], ("audio", "drive"), model._on_run_state)
    def audio(progress, skip):
        before = len(updates)
        progress(.5)
        assert len(updates) == before  # Spinner delegate is not recreated.
        assert model.get_progress_fraction() == .5 / 4
        assert model.get_current_file_fraction() == .5
        assert model.get_stage_fractions()[2] == .25
        assert model.get_rows()[0]["stages"][2] == "current"
        assert sum(state == "current" for row in model.get_rows() for state in row["stages"]) == 1
        model._on_real_log_line(f"[{videos[1].key}] uploading to YouTube")
        assert model.get_current_stage() == 2  # Log prose cannot move state.
        model._on_artifact_result(model._check_generation, videos[0].key, "audio", "done", "")
        assert model.get_rows()[0]["stages"][2] == "current"
    run.perform(videos[0].key, "audio", audio)
    assert model.get_rows()[0]["stages"][2] == "done"
    assert model.get_current_file_fraction() == 1
    assert model.get_stage_completed_counts()[2] == 1
    assert model.get_progress_fraction() == .25
    def drive(progress, skip):
        assert model.get_current_file_fraction() == 0
        assert model.get_current_stage() == 3
        assert model.get_rows()[0]["stages"][2] == "done"
        skip()
    run.perform(videos[0].key, "drive", drive)
    assert model.get_rows()[0]["stages"][3] == "skipped"
    assert model.get_completed_count() == 1
    assert model.get_progress_fraction() == .5
    model._running = False
    model.select_all(True)
    assert model.get_progress_fraction() == 0
    assert not any(row.run_states for row in model.rows)


def test_finished_dialog_does_not_count_cancelled_clips_as_success(config, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(ui.PipelineModel, "refresh", lambda self: None)
    model = ui.PipelineModel(config, ProcessedStore())
    model.rows = [ui.FileRow("a", "a", "", None), ui.FileRow("b", "b", "", None)]
    model._request_artifact_check = lambda: None
    messages = []
    model.batchFinished.connect(messages.append)

    run = SerialRun(["a", "b"], ("youtube",))
    run.cancel_remaining()
    run.finish()
    model._run_snapshot = run.snapshot()
    model._on_finished()

    assert messages == ["処理を停止しました（0件成功 / 2件停止）"]


def test_background_worker_delivers_lifecycle_snapshot_to_gui_thread(config, videos, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    row = ui.FileRow(videos[0].key, videos[0].key, "", videos[0])
    worker = ui.ProcessVideosWorker([row], config, ProcessedStore())
    snapshot = SerialRun([row.key], ("youtube",)).snapshot()
    received, finished = [], []

    def fake_process(items, worker_config, store, log, on_state, should_cancel,
                      include_audio_drive, include_youtube):
        assert items == [videos[0]]
        assert should_cancel() is False
        assert include_audio_drive is True and include_youtube is True
        on_state(snapshot)
        log("worker ran")
        return snapshot

    monkeypatch.setattr(ui.pipeline, "process_videos", fake_process)
    worker.stateChanged.connect(received.append)
    worker.finished_.connect(lambda: finished.append(True))
    loop = QEventLoop()
    worker.finished_.connect(loop.quit)
    QTimer.singleShot(1000, loop.quit)
    worker.start()
    loop.exec()
    worker.wait(1000)

    assert finished == [True]
    assert received == [snapshot]


def test_stages_the_current_run_mode_wont_touch_show_excluded_before_any_run(config, videos, monkeypatch):
    # Requested after a user report: previously, picking a run mode that
    # skips some stages (e.g. "①②のみ実施") marked those columns as
    # not-applicable at rest, before the row's own real artifact status
    # (stage_status) had any say — that preview got lost somewhere and
    # needed restoring, distinct from a *run's* own "skipped" reason.
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(ui.PipelineModel, "refresh", lambda self: None)
    model = ui.PipelineModel(config, ProcessedStore())
    model.rows = [ui.FileRow(v.key, v.key, "", v) for v in videos]

    stages = model.get_rows()[0]["stages"]
    assert "excluded" not in stages  # 全行程実施: nothing excluded

    model._stop_after_stitch = True
    row = model.get_rows()[0]
    assert row["stages"] == ["pending", "pending", "excluded", "excluded", "excluded"]
    assert row["reasons"][2:] == ["mode", "mode", "mode"]
    model._stop_after_stitch = False

    model._skip_audio_drive = True
    assert model.get_rows()[0]["stages"] == ["pending", "pending", "excluded", "excluded", "pending"]
    model._skip_audio_drive = False

    model._skip_intake = True
    assert model.get_rows()[0]["stages"] == ["excluded", "excluded", "pending", "pending", "pending"]
    model._skip_intake = False

    # The top stepper circles (independent of any specific row) mirror
    # the same excluded/pending split before a run starts.
    assert model.get_stage_run_states() == ["pending"] * 5
    model._stop_after_stitch = True
    assert model.get_stage_run_states() == ["pending", "pending", "excluded", "excluded", "excluded"]


