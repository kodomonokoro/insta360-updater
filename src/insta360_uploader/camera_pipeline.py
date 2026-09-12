"""Orchestrates the full camera-to-YouTube pipeline as five stages run in
wave-batched order across all selected clips: copy every clip off the
camera first, then stitch every clip, then extract every clip's audio,
then upload every clip's audio to Drive, then upload every clip's video to
YouTube — rather than running one clip through all five stages before
moving on to the next.

Wave-batched (not per-clip) so the copy stage finishes for the whole batch
before the much slower stitch stage begins: that's the point at which the
camera can safely be disconnected, since nothing left to do touches it
again. `on_camera_safe` fires exactly once, right after that.

Reuses pipeline.py's extract_audio/upload_audio_to_drive/upload_to_youtube
and intake.py's copy_raw/stitch — this module only sequences them. Each
stage's own "already done, skip" check (mp4_path.is_file(),
drive_file_exists(), youtube_video_exists(), etc.) is untouched and does
all the real work of making a rerun cheap.

A clip that fails a stage is dropped from every later stage but does not
abort the batch — mirrors pipeline.process_videos's "one video's failure
must not abort the batch" behavior.
"""
from __future__ import annotations

from typing import Callable

from insta360_uploader.config import AppConfig, ConfigError, validate_for_run
from insta360_uploader.intake import copy_raw, stitch
from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.pipeline import (
    Logger,
    ProgressFn,
    extract_audio,
    upload_audio_to_drive,
    upload_to_youtube,
)
from insta360_uploader.processed_store import ProcessedStore


def run_camera_pipeline(
    videos: list[VideoFile],
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    on_progress: ProgressFn | None = None,
    on_camera_safe: Callable[[], None] | None = None,
    stop_after_stitch: bool = False,
    *, skip_audio_drive: bool = False, on_state=None, should_cancel: Callable[[], bool] | None = None,
):
    """Run each stage across the selected clips, completely serially.

    `skip_audio_drive` is the "①②⑤のみ実施" mode: skip audio extraction/
    Drive upload for this run regardless of whether Drive is configured
    (distinct from Drive simply not being set up at all).

    `should_cancel` is checked between clips/stages, not during one — see
    serial_pipeline.execute()'s docstring comment for why a stop request
    isn't instant.

    Validates the same way the GUI's start button does before touching
    anything — every caller (CLI's `intake`, the GUI's camera worker) goes
    through this one entry point, so there's only one place this check
    needs to live."""
    error = validate_for_run(
        config, camera=True, stop_after_stitch=stop_after_stitch, skip_audio_drive=skip_audio_drive
    )
    if error:
        raise ConfigError(error)
    from .serial_pipeline import execute
    return execute(
        videos, config, store, log,
        {"copy": copy_raw, "stitch": stitch, "audio": extract_audio,
         "drive": upload_audio_to_drive, "youtube": upload_to_youtube},
        camera=True, stop_after_stitch=stop_after_stitch, skip_audio_drive=skip_audio_drive,
        on_progress=on_progress, on_state=on_state, on_camera_safe=on_camera_safe, should_cancel=should_cancel,
    )
