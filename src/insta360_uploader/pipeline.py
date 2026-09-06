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
"""
from __future__ import annotations

from typing import Callable

from insta360_uploader.audio_extractor import extract_mp3
from insta360_uploader.config import AppConfig
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
from insta360_uploader.title_builder import assign_titles, extract_capture_datetime
from insta360_uploader.youtube_uploader import add_video_to_playlist, upload_video

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
    pending = [v for v in videos if not store.is_done(v.key, v.source_hash)]

    if not pending:
        log("No new videos to process.")
        return

    if dry_run:
        for video in pending:
            log(f"[{video.key}] would process {video.path}")
        return

    process_videos(pending, config, store, log)


def process_videos(
    videos: list[VideoFile],
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    on_progress: ProgressFn | None = None,
) -> None:
    """Shared core: title-assign, then process each video, one at a time.

    Used by both `run_pipeline` (CLI, all pending) and the GUI (whatever
    subset the user selected).
    """
    brand_new = [v for v in videos if store.get(v.key) is None]
    new_titles = assign_titles(config.youtube_defaults.title_prefix, store, brand_new)

    # Each video is 1 upload (YouTube) or 2 (YouTube + Drive audio) worth of
    # progress, whether or not the Drive half ends up being skipped as
    # already-done on a retry — that keeps the total stable across retries.
    total_ops = len(videos) * (2 if config.drive is not None else 1)
    completed = 0

    def mark_operation_done() -> None:
        nonlocal completed
        completed += 1
        if on_progress:
            on_progress(completed, total_ops, 0.0)

    def report_progress(fraction: float) -> None:
        if on_progress:
            on_progress(completed, total_ops, fraction)

    if on_progress:
        on_progress(0, total_ops, 0.0)

    for video in videos:
        log(f"[{video.key}] found {video.path}")
        existing = store.get(video.key)
        title = new_titles.get(video.key) or (existing.video_title if existing else None)
        store.upsert_pending(video.key, video.source_hash, video_title=title)
        try:
            process_video(video, config, store, log, report_progress, mark_operation_done)
        except Exception as exc:  # one video's failure must not abort the batch
            store.mark_failed(video.key, str(exc))
            log(f"[{video.key}] FAILED: {exc}")


def process_video(
    video: VideoFile,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    mark_operation_done: Callable[[], None] = lambda: None,
) -> None:
    record = store.get(video.key)
    title = record.video_title if record else video.key

    if config.drive is not None:
        already_on_drive = (
            record is not None
            and record.drive_file_id is not None
            and drive_file_exists(config.drive, record.drive_file_id)
        )
        if already_on_drive:
            log(f"[{video.key}] audio already on Google Drive, skipping re-upload")
            mark_operation_done()
        else:
            nas_mp3_folder = config.nas_video_folder.parent / "mp3"
            store.set_status(video.key, STATUS_EXTRACTING_AUDIO)
            log(f"[{video.key}] extracting audio to {nas_mp3_folder}...")
            # ffmpeg writes straight to the NAS folder — no local copy of a
            # multi-GB 360 video, ever, even transiently.
            mp3_path = extract_mp3(video.path, nas_mp3_folder, output_stem=title)

            store.set_status(video.key, STATUS_UPLOADING_AUDIO)
            subfolder = None
            if config.drive.subfolder_prefix:
                date_str = extract_capture_datetime(video.path).strftime("%Y%m%d")
                subfolder = f"{config.drive.subfolder_prefix}_{date_str}"
            log(f"[{video.key}] uploading audio to Google Drive (folder={subfolder})...")
            drive_file_id = upload_to_drive(
                config.drive,
                mp3_path,
                name=f"{title}.mp3",
                subfolder=subfolder,
                progress_callback=report_progress,
                log=lambda msg: log(f"[{video.key}] {msg}"),
            )
            store.set_status(video.key, STATUS_UPLOADING_AUDIO, drive_file_id=drive_file_id)
            mark_operation_done()

    upload_path = video.path
    if not has_spherical_metadata(video.path):
        # Rare (Studio's export should already be tagged): write the
        # re-tagged copy to NAS too, never to local disk — these are
        # full-size video files.
        retagged_dir = config.nas_video_folder.parent / "_retagged"
        tagged_path = retagged_dir / f"{video.key}_360.mp4"
        log(f"[{video.key}] no spherical metadata found, injecting as a safety net into {tagged_path}...")
        inject_spherical_metadata(video.path, tagged_path)
        upload_path = tagged_path

    def on_video_upload_progress(fraction: float) -> None:
        log(f"[{video.key}] upload progress: {fraction:.0%}")
        report_progress(fraction)

    store.set_status(video.key, STATUS_UPLOADING_VIDEO)
    log(f"[{video.key}] uploading '{title}' to YouTube...")
    video_id = upload_video(
        config.youtube,
        upload_path,
        title=title,
        description="Uploaded automatically by insta360-uploader.",
        privacy_status=config.youtube_defaults.privacy_status,
        made_for_kids=config.youtube_defaults.made_for_kids,
        progress_callback=on_video_upload_progress,
    )
    store.set_status(video.key, STATUS_UPLOADING_VIDEO, youtube_video_id=video_id)
    mark_operation_done()

    if config.youtube_defaults.playlist_id:
        # Best-effort: the video itself already succeeded, so a playlist
        # hiccup must not fail (and thus retry-reupload) the whole video.
        try:
            add_video_to_playlist(config.youtube, video_id, config.youtube_defaults.playlist_id)
            log(f"[{video.key}] added to playlist {config.youtube_defaults.playlist_id}")
        except Exception as exc:
            log(f"[{video.key}] could not add to playlist (video upload still succeeded): {exc}")

    store.set_status(video.key, STATUS_DONE)
    log(f"[{video.key}] done -> https://youtu.be/{video_id}")
