"""Orchestrates, per video: extract audio -> archive it to NAS -> upload it
to Google Drive (all optional, only if google_drive is configured) -> check
spherical metadata -> upload video to YouTube.

Audio-then-video because the YouTube upload is the slow part; doing the
quick audio/Drive step first means it's done even while a long video
upload is still running.

`process_videos` is the shared core used by both the CLI (`run_pipeline`,
which processes everything pending) and the GUI (which processes whatever
subset the user selected). One video failing does not abort the rest of
the batch — failures are recorded in the processed store, so a rerun only
retries what's left. Nothing on the NAS is ever modified or deleted (mp3s
are new files this tool creates, not source footage).

If a video's Drive step already succeeded on a prior (partially-failed)
attempt — `record.drive_file_id` is already set — it's skipped on retry,
but only after confirming via the Drive API that the file is still there
and not trashed. Google Drive allows duplicate filenames, so blindly
trusting the local record would either leave an orphaned duplicate mp3
behind (if redone) or silently skip re-uploading something the user
deleted on Drive's side (if not re-checked). See ClipRecord's docstring
in processed_store.py for why `drive_file_id` exists at all despite this
— it's a cache to avoid redundant work and API calls, not the source of
truth for whether the file is really there.

Separately, when the local record has *no* drive_file_id yet,
gdrive_uploader.upload_file() still checks by filename before creating
anything, and — if a same-named file is already on Drive — reuses it
rather than uploading. It must never overwrite or rename around an
existing file on Drive: this app is only ever allowed to create new Drive
files, never delete or modify existing ones. That constraint came from
the user directly; do not "simplify" it back to an overwrite-in-place fix.

The YouTube video upload mirrors this same two-layer dedup, since
YouTube's Data API has no dedup of its own and would otherwise happily
create a duplicate video every time an already-succeeded upload is
retried (e.g. the user re-selecting a done video in the GUI): a cheap
`record.youtube_video_id` recheck via youtube_uploader.video_exists()
here, plus upload_video()'s own by-title existing-video check as a
fallback for when there's no local record to trust. add_video_to_playlist()
likewise skips if the video is already in the target playlist, so a
retry never adds a duplicate playlist entry either.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from insta360_uploader.audio_extractor import extract_mp3
from insta360_uploader.config import AppConfig, ConfigError, validate_for_run
from insta360_uploader.gdrive_uploader import file_exists as drive_file_exists
from insta360_uploader.gdrive_uploader import upload_file as upload_to_drive
from insta360_uploader.metadata import has_spherical_metadata, inject_spherical_metadata
from insta360_uploader.nas_scanner import VideoFile, scan_video_folder
from insta360_uploader.processed_store import (
    STATUS_DONE,
    STATUS_EXTRACTING_AUDIO,
    STATUS_UPLOADING_AUDIO,
    STATUS_UPLOADING_VIDEO,
    ProcessedStore,
)
from insta360_uploader.title_builder import extract_capture_datetime
from insta360_uploader.youtube_uploader import add_video_to_playlist, upload_video
from insta360_uploader.youtube_uploader import video_exists as youtube_video_exists

Logger = Callable[[str], None]
# (completed_ops, total_ops, current_file_fraction_0_to_1)
ProgressFn = Callable[[int, int, float], None]


def run_pipeline(
    config: AppConfig,
    *,
    dry_run: bool = False,
    log: Logger = print,
) -> None:
    """CLI entry point: process everything pending in the NAS folder."""
    store = ProcessedStore()

    videos = scan_video_folder(config.nas_video_folder)
    pending = videos  # Each operation checks its actual destination; no history filter.

    if not pending:
        log("No new videos to process.")
        return

    if dry_run:
        # Pure preview, no side effects — deliberately not validated, so
        # it stays usable to see what's pending even before auth/config
        # is finished. process_videos() below validates for real.
        for video in pending:
            log(f"[{video.key}] would process {video.path}")
        return

    process_videos(pending, config, store, log)


def process_videos(
    videos: list[VideoFile], config: AppConfig, store: ProcessedStore, log: Logger,
    on_progress: ProgressFn | None = None, *, on_state=None, should_cancel: Callable[[], bool] | None = None,
    include_audio_drive: bool = True, include_youtube: bool = True,
):
    """Serial per-video execution with a separate lifecycle for every stage.

    `include_audio_drive`/`include_youtube` back the debug-only "デバッグ：
    YouTube取り込み"(youtube only) and "デバッグ：音声出力"(audio+drive
    only) run modes — same split as lifecycle.enabled_stages()/
    config.validate_for_run(); default True/True is the ordinary
    "③④⑤のみ実施"-equivalent full run against already-stitched NAS mp4s.

    Validates the same way the GUI's start button does before touching
    anything — every caller (CLI's `run`, the GUI's skip-intake worker)
    goes through this one entry point, so there's only one place this
    check needs to live."""
    error = validate_for_run(
        config, camera=False, include_audio_drive=include_audio_drive, include_youtube=include_youtube
    )
    if error:
        raise ConfigError(error)
    from .serial_pipeline import execute
    return execute(videos, config, store, log,
                   {"audio": extract_audio, "drive": upload_audio_to_drive, "youtube": upload_to_youtube},
                   include_audio_drive=include_audio_drive, include_youtube=include_youtube,
                   on_progress=on_progress, on_state=on_state, should_cancel=should_cancel)


def _resolve_video_path(video: VideoFile, config: AppConfig) -> Path:
    """The already-stitched .mp4 to actually operate on for every stage
    from here on (audio extraction, YouTube upload).

    `video.path` is only reliable for this when nas_scanner.py produced
    `video` (it already points straight at the stitched file sitting in
    `nas_video_folder`). When camera_scanner.py produced it instead,
    `video.path` is just the *raw* first camera chapter — VideoFile's own
    docstring says it's "kept for display purposes (capture date etc.)"
    only, and intake.py's copy_raw/stitch already know to use
    `chapter_paths` instead of `.path` for that reason. This function used
    to be missing here, which meant extract_audio/upload_to_youtube were
    reading the *raw camera .insv* for every camera-intake clip instead of
    the stitched NAS .mp4 — audio extraction "worked" by accident (a raw
    .insv still has a normal AAC audio track), but the spherical-metadata
    check could never find anything on a raw file and endlessly, correctly
    reported none — no amount of retrying could have fixed that.
    `chapter_paths` is non-empty exactly when `video` came from
    camera_scanner.py (see VideoFile's own docstring), which is the
    reliable signal to redirect here rather than guessing from the path.
    """
    if video.chapter_paths:
        return config.nas_video_folder / f"{video.key}.mp4"
    return video.path


def extract_audio(
    video: VideoFile,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    *,
    on_skip: Callable[[], None] | None = None,
) -> Path:
    """Extract this video's audio to the mp3 folder, or return the
    existing mp3's path if it's already there from a prior run.

    Requires `config.mp3_folder` to already be set — validate_for_run()
    guarantees this for any mode that reaches this stage at all."""
    assert config.mp3_folder is not None
    record = store.get(video.key)
    title = record.video_title if record else video.key
    nas_mp3_folder = config.mp3_folder
    mp3_path = nas_mp3_folder / f"{title}.mp3"
    video_path = _resolve_video_path(video, config)

    if mp3_path.is_file():
        if on_skip:
            on_skip()
        log(f"[{video.key}] audio already extracted, skipping")
        return mp3_path

    # Clear any stale drive_file_id from a prior attempt (e.g. the file was
    # since removed from Drive) — otherwise it lingers while this new
    # upload is in progress and the GUI shows Drive as already done when
    # it isn't.
    store.set_status(video.key, STATUS_EXTRACTING_AUDIO, clear_drive_file_id=True)
    log(f"[{video.key}] extracting audio to {nas_mp3_folder}...")
    # ffmpeg writes straight to the NAS folder — no local copy of a
    # multi-GB 360 video, ever, even transiently.
    return extract_mp3(
        video_path,
        nas_mp3_folder,
        output_stem=title,
        progress_callback=report_progress,
        log=lambda msg: log(f"[{video.key}] {msg}"),
    )


def upload_audio_to_drive(
    video: VideoFile,
    mp3_path: Path,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    *,
    on_skip: Callable[[], None] | None = None,
) -> None:
    assert config.drive is not None
    record = store.get(video.key)
    title = record.video_title if record else video.key

    already_on_drive = (
        record is not None
        and record.drive_file_id is not None
        and drive_file_exists(config.drive, record.drive_file_id)
    )
    if already_on_drive:
        if on_skip:
            on_skip()
        log(f"[{video.key}] audio already on Google Drive, skipping re-upload")
        return

    store.set_status(video.key, STATUS_UPLOADING_AUDIO)
    subfolder = None
    if config.drive.subfolder_prefix:
        date_str = extract_capture_datetime(_resolve_video_path(video, config)).strftime("%Y%m%d")
        subfolder = f"{config.drive.subfolder_prefix}_{date_str}"
    log(f"[{video.key}] uploading audio to Google Drive (folder={subfolder})...")
    drive_file_id = upload_to_drive(
        config.drive,
        mp3_path,
        name=f"{title}.mp3",
        subfolder=subfolder,
        progress_callback=report_progress,
        log=lambda msg: log(f"[{video.key}] {msg}"),
        on_skip=on_skip,
    )
    store.set_status(video.key, STATUS_UPLOADING_AUDIO, drive_file_id=drive_file_id)
    # Same reason as copy_raw()'s trailing log: the GUI only re-reads a
    # clip's row when a *new* log line mentions its key, and
    # gdrive_uploader.upload_file() itself never logs anything for a real
    # (non-skipped) upload — without this, the row stays showing
    # "uploading" until this clip's key shows up again at the YouTube
    # stage, even though the Drive upload genuinely finished right away.
    log(f"[{video.key}] uploaded to Google Drive")


def _has_spherical_metadata_with_retry(
    path: Path, log: Logger, *, attempts: int = 20, delay_seconds: float = 3.0
) -> bool:
    """A file MediaSDKTest.exe (stitcher.py) just finished writing can
    briefly read back as missing metadata that's genuinely already there.

    Ruled out by direct repro before landing this: our own read code and
    generic NAS/SMB write settling are NOT the cause — copying this exact
    file with shutil.copyfile (or writing to a .part path and
    Path.replace()-ing it, exactly like stitcher.py does) and reading it
    back immediately always succeeds, even simulating a long-running
    process that had already read the same path many times before the
    overwrite. The failure only reproduces right after a real
    MediaSDKTest.exe stitch. Its log output shows several background
    threads still doing "Deinit"/"FinishWriting again, warning" cleanup
    *after* it reports "process = 100%"/exit — strong evidence its own
    (closed-source) file finalization is still finishing asynchronously
    after the process we waited on already exited. Nothing on our side can
    fix that directly, so this waits it out: up to attempts*delay_seconds
    (default 60s) before concluding the metadata is genuinely absent. A
    Studio-exported file (already fully settled by the time this app ever
    sees it) will never hit more than the first attempt."""
    for attempt in range(attempts):
        time.sleep(delay_seconds)
        if has_spherical_metadata(path):
            return True
        log(
            f"spherical metadata check found none on attempt {attempt + 1}/{attempts}, "
            "retrying (may just be a fresh network write settling)..."
        )
    return False


def upload_to_youtube(
    video: VideoFile,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    *,
    on_skip: Callable[[], None] | None = None,
) -> None:
    record = store.get(video.key)
    title = record.video_title if record else video.key

    upload_path = _resolve_video_path(video, config)
    if not _has_spherical_metadata_with_retry(upload_path, log):
        # Rare (Studio's export should already be tagged): write the
        # re-tagged copy to NAS too, never to local disk — these are
        # full-size video files.
        retagged_dir = config.nas_video_folder / "_retagged"
        tagged_path = retagged_dir / f"{video.key}_360.mp4"
        log(f"[{video.key}] no spherical metadata found, injecting as a safety net into {tagged_path}...")
        inject_spherical_metadata(upload_path, tagged_path)
        upload_path = tagged_path

    def on_video_upload_progress(fraction: float) -> None:
        log(f"[{video.key}] upload progress: {fraction:.0%}")
        report_progress(fraction)

    already_on_youtube = (
        record is not None
        and record.youtube_video_id is not None
        and youtube_video_exists(config.youtube, record.youtube_video_id)
    )
    if already_on_youtube:
        if on_skip:
            on_skip()
        video_id = record.youtube_video_id
        log(f"[{video.key}] already uploaded to YouTube, skipping re-upload")
    else:
        # Clear any stale youtube_video_id from a prior attempt (e.g. the
        # video was since deleted from YouTube) — otherwise it lingers
        # while this new upload is in progress and the GUI shows YouTube
        # as already done when it isn't.
        store.set_status(video.key, STATUS_UPLOADING_VIDEO, clear_youtube_video_id=True)
        log(f"[{video.key}] uploading '{title}' to YouTube...")
        # upload_video() also does its own name-based existing-video check
        # (a second safety net for when there's no local record to trust
        # at all, e.g. a lost/reset processed-store) before it uploads
        # anything — see its docstring.
        video_id = upload_video(
            config.youtube,
            upload_path,
            title=title,
            description="Uploaded automatically by insta360-uploader.",
            privacy_status=config.youtube_defaults.privacy_status,
            made_for_kids=config.youtube_defaults.made_for_kids,
            progress_callback=on_video_upload_progress,
            log=lambda msg: log(f"[{video.key}] {msg}"),
            on_skip=on_skip,
        )

    store.set_status(video.key, STATUS_UPLOADING_VIDEO, youtube_video_id=video_id)

    if config.youtube_defaults.playlist_id:
        # Best-effort: the video itself already succeeded, so a playlist
        # hiccup must not fail (and thus retry-reupload) the whole video.
        try:
            add_video_to_playlist(
                config.youtube,
                video_id,
                config.youtube_defaults.playlist_id,
                log=lambda msg: log(f"[{video.key}] {msg}"),
            )
            log(f"[{video.key}] added to playlist {config.youtube_defaults.playlist_id}")
        except Exception as exc:
            log(f"[{video.key}] could not add to playlist (video upload still succeeded): {exc}")

    store.set_status(video.key, STATUS_DONE)
    log(f"[{video.key}] done -> https://youtu.be/{video_id}")


def process_video(
    video: VideoFile,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    mark_operation_done: Callable[[], None] = lambda: None,
) -> None:
    """Per-clip entry point used by process_videos/run_pipeline (the
    360°ファイル取り込み tab + CLI): runs every stage for one clip, start to
    finish. camera_pipeline.py's run_camera_pipeline() calls
    extract_audio/upload_audio_to_drive/upload_to_youtube directly instead,
    in stage-batched (wave) order across many clips at once."""
    if config.drive is not None:
        mp3_path = extract_audio(video, config, store, log, report_progress)
        upload_audio_to_drive(video, mp3_path, config, store, log, report_progress)
        mark_operation_done()

    upload_to_youtube(video, config, store, log, report_progress)
    mark_operation_done()
