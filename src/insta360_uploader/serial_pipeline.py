"""Shared serial execution for camera and already-converted inputs."""
from __future__ import annotations

from .lifecycle import SerialRun, enabled_stages
from .title_builder import title_for_video


def execute(videos, config, store, log, operations, *, camera=False,
            include_audio_drive=True, include_youtube=True, on_state=None, on_progress=None,
            on_camera_safe=None, should_cancel=None):
    stages = enabled_stages(camera=camera, drive=config.drive_active,
                             include_audio_drive=include_audio_drive, include_youtube=include_youtube)
    run = SerialRun([v.key for v in videos], stages, on_state, on_progress)
    for video in videos:
        try:
            title = title_for_video(config.youtube_defaults.title_prefix, video)
            store.upsert_pending(video.key, video.source_hash, video_title=title)
            if camera and config.media_sdk is None:
                raise RuntimeError("insta360_sdk is not configured")
        except Exception as exc:
            if store.get(video.key) is None:
                store.upsert_pending(video.key, "", video_title=video.key)
            store.mark_failed(video.key, str(exc))
            run.fail_clip(video.key, stages[0], str(exc))
            log(f"[{video.key}] FAILED: {exc}")

    mp3_paths = {}

    def perform(video, stage):
        def operation(progress, skip):
            if stage == "drive":
                operations[stage](video, mp3_paths[video.key], config, store, log, progress, on_skip=skip)
            else:
                result = operations[stage](video, config, store, log, progress, on_skip=skip)
                if stage == "audio":
                    mp3_paths[video.key] = result
        if not run.perform(video.key, stage, operation):
            task = next(t for t in run.snapshot().tasks if t.key == video.key and t.stage == stage)
            if task.state == "failed":
                store.mark_failed(video.key, task.reason)
                log(f"[{video.key}] FAILED at {stage}: {task.reason}")

    def cancelled():
        return should_cancel is not None and should_cancel()

    # Cooperative stop: checked only *between* perform() calls, never
    # during one — the operation already running for a clip/stage always
    # finishes on its own first (see SerialRun.cancel_remaining()). Worst
    # case, a stop request waits out whatever single copy/stitch/upload is
    # already in flight rather than taking effect instantly.
    if camera:
        for stage in stages:
            if cancelled():
                break
            for video in videos:
                if cancelled():
                    break
                perform(video, stage)
            if stage == "copy" and on_camera_safe and not cancelled():
                # The copy wave has ended; no later operation reads camera
                # data. Do not claim all files copied if a copy failed.
                copies = [t for t in run.snapshot().tasks if t.stage == "copy"]
                if copies and all(t.state in ("done", "skipped") and t.reason != "dependency" for t in copies):
                    on_camera_safe()
    else:
        for video in videos:
            if cancelled():
                break
            for stage in stages:
                if cancelled():
                    break
                perform(video, stage)

    if cancelled():
        run.cancel_remaining()
    run.finish()
    return run.snapshot()
