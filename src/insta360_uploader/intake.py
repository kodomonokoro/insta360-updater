"""Front-half orchestration: copy raw .insv files off the camera to the NAS
`raw/` folder, then stitch them into the .mp4 that the existing back-half
pipeline (pipeline.py) already knows how to pick up from `processed/mp4/`.

Mirrors pipeline.py's process_videos/process_video shape (same Logger/
ProgressFn types, same "one failure doesn't abort the batch" behavior) and
shares the same ProcessedStore/ClipRecord — this is simply an earlier stage
of the same per-clip lifecycle, not a separate tracking system. Once a clip's
.mp4 lands in `processed/mp4/`, pipeline.process_videos's own upsert_pending
call (on its next scan) resets the record to STATUS_PENDING and takes over;
nothing here needs to hand that off explicitly.

Never touches the camera's own files (copy only, never delete from the
camera) — clearing the camera's storage for the next session is the user's
own manual step.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from insta360_uploader.config import AppConfig
from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.pipeline import Logger, ProgressFn
from insta360_uploader.processed_store import STATUS_COPYING_RAW, STATUS_STITCHING, ProcessedStore
from insta360_uploader.stitcher import StitchError, stitch_to_mp4


_COPY_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB — large enough to keep syscall overhead negligible even at Gigabit+ speeds


def _copy_raw_file(
    src: Path,
    dest: Path,
    progress_callback: Callable[[float], None] = lambda fraction: None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest.with_name(dest.name + ".part")
    total = src.stat().st_size
    copied = 0
    with src.open("rb") as fsrc, part_path.open("wb") as fdst:
        while chunk := fsrc.read(_COPY_CHUNK_SIZE):
            fdst.write(chunk)
            copied += len(chunk)
            progress_callback(copied / total if total else 1.0)
    part_path.replace(dest)
    return dest


def raw_chapter_paths(video: VideoFile, config: AppConfig) -> list[Path]:
    """Public (not just intake.py-internal) since the GUI backend also
    needs it — to check real copy-completion evidence on disk rather than
    trusting ClipRecord.status, which only ever marks a stage *starting*,
    never finishing.

    Requires `config.raw_folder` to already be set — callers that might
    see it unset (e.g. artifact_status.py's local_states(), which runs
    whenever the file table is displayed, independent of any particular
    run mode) must branch to an "unconfigured" state before ever calling
    this, rather than relying on this function to handle it."""
    assert config.raw_folder is not None
    return [config.raw_folder / f"{chapter.stem}.insv" for chapter in video.chapter_paths]


def _concat_chapters(chapter_mp4_paths: list[Path], output_path: Path, *, ffmpeg_path: str = "ffmpeg") -> Path:
    """Losslessly join sequential 360 mp4 chapters into one file via
    ffmpeg's concat demuxer (-c copy: remux only, no re-encode). Safe
    because chapters of one continuous camera recording always share the
    same codec/resolution/fps — they're one recording the camera itself
    split, not separately-shot clips."""
    if shutil.which(ffmpeg_path) is None:
        raise StitchError(f"ffmpeg not found on PATH (looked for '{ffmpeg_path}')")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    list_path = output_path.with_name(output_path.name + ".concat_list.txt")
    list_path.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in chapter_mp4_paths),
        encoding="utf-8",
    )
    try:
        command = [
            ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            # Without this, ffmpeg guesses the output container from
            # part_path's extension (".part", for atomic-write safety) and
            # fails with "unable to find a suitable output format" — it
            # never gets to look at the real ".mp4" further up the name.
            "-f",
            "mp4",
            str(part_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 or not part_path.is_file():
            part_path.unlink(missing_ok=True)
            raise StitchError(
                f"joining {len(chapter_mp4_paths)} chapters into {output_path} failed "
                f"(exit code {result.returncode}).\nstderr: {result.stderr}"
            )
    finally:
        list_path.unlink(missing_ok=True)

    part_path.replace(output_path)
    return output_path


def copy_raw(
    video: VideoFile,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    *,
    on_skip: Callable[[], None] | None = None,
) -> list[Path]:
    """Copy every chapter of this clip's raw .insv(s) off the camera to
    the NAS `raw/` folder — a long recording the camera split into several
    files becomes several raw copies, one per chapter — skipping whichever
    chapters are already copied. Returns every chapter's raw path."""
    raw_paths = raw_chapter_paths(video, config)
    missing = [(src, dest) for src, dest in zip(video.chapter_paths, raw_paths) if not dest.is_file()]

    if not missing:
        if on_skip:
            on_skip()
        log(f"[{video.key}] already copied, skipping")
        return raw_paths

    store.set_status(video.key, STATUS_COPYING_RAW)
    total = len(missing)
    for i, (src, dest) in enumerate(missing):
        log(f"[{video.key}] copying {src.name} to {dest}...")
        _copy_raw_file(src, dest, lambda fraction, i=i: report_progress((i + fraction) / total))
    # The GUI only re-reads a clip's row from the store when a *new* log
    # line mentions that clip's key — without this, a clip's row stays
    # showing "copying" until the *next* time its key shows up in the log
    # (i.e. not until it reaches the stitch stage), even though copying
    # genuinely finished right away.
    log(f"[{video.key}] copied")
    return raw_paths


def stitch(
    video: VideoFile,
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    report_progress: Callable[[float], None] = lambda fraction: None,
    *,
    on_skip: Callable[[], None] | None = None,
) -> Path:
    """Stitch this clip's raw .insv chapter(s) (already copied by
    copy_raw) into the single .mp4 that pipeline.py picks up from
    `processed/mp4/`, or return the existing .mp4's path if it's already
    stitched.

    A single-chapter clip stitches directly, as before. A multi-chapter
    clip (a long recording the camera split into several .insv files) is
    stitched chapter-by-chapter into temporary per-chapter mp4s in the mp4
    folder (not the raw folder — that's raw .insv only, mixing in
    converted mp4s there even temporarily is the wrong place for them),
    then losslessly joined into the final .mp4 — MediaSDK has no built-in
    way to turn several chapters into one stitched output in a single call
    (confirmed unsupported: an open feature request with no built-in
    workaround, per Insta360's own MediaSDK-Cpp issue tracker, issue #49),
    so the join happens afterward via ffmpeg instead.
    """
    assert config.media_sdk is not None
    raw_paths = raw_chapter_paths(video, config)
    mp4_path = config.nas_video_folder / f"{video.key}.mp4"

    if mp4_path.is_file():
        if on_skip:
            on_skip()
        log(f"[{video.key}] already stitched, skipping")
        return mp4_path

    store.set_status(video.key, STATUS_STITCHING)

    if len(raw_paths) == 1:
        log(f"[{video.key}] stitching to {mp4_path}...")
        stitch_to_mp4(
            raw_paths[0],
            mp4_path,
            media_sdk=config.media_sdk,
            progress_callback=report_progress,
            log=lambda msg: log(f"[{video.key}] {msg}"),
        )
        log(f"[{video.key}] stitched -> {mp4_path}")
        return mp4_path

    total = len(raw_paths)
    chapter_mp4_paths = []
    for i, raw_path in enumerate(raw_paths):
        chapter_mp4_path = config.nas_video_folder / f"{raw_path.stem}.mp4"
        log(f"[{video.key}] stitching chapter {i + 1}/{total} ({raw_path.name})...")
        stitch_to_mp4(
            raw_path,
            chapter_mp4_path,
            media_sdk=config.media_sdk,
            progress_callback=lambda fraction, i=i: report_progress((i + fraction) / total),
            log=lambda msg: log(f"[{video.key}] {msg}"),
        )
        chapter_mp4_paths.append(chapter_mp4_path)

    log(f"[{video.key}] joining {total} chapters into {mp4_path}...")
    _concat_chapters(chapter_mp4_paths, mp4_path)
    for chapter_mp4_path in chapter_mp4_paths:
        chapter_mp4_path.unlink(missing_ok=True)
    log(f"[{video.key}] stitched -> {mp4_path}")
    return mp4_path


def run_intake(
    videos: list[VideoFile],
    config: AppConfig,
    store: ProcessedStore,
    log: Logger,
    on_progress: ProgressFn | None = None,
) -> None:
    """Two-stage (copy + stitch) entry point used by the CLI's `intake`
    subcommand. camera_pipeline.py's run_camera_pipeline() calls
    copy_raw/stitch directly instead, as two of five stages run in
    wave-batched order across many clips at once, continuing on into
    audio extraction and upload."""
    if config.media_sdk is None:
        raise RuntimeError("insta360_sdk is not configured — set it up in Settings first")

    total = len(videos)
    completed = 0

    def report(fraction: float) -> None:
        if on_progress:
            on_progress(completed, total, fraction)

    if on_progress:
        on_progress(0, total, 0.0)

    for video in videos:
        log(f"[{video.key}] found on camera: {video.path}")
        mp4_path = config.nas_video_folder / f"{video.key}.mp4"

        if mp4_path.is_file():
            log(f"[{video.key}] already stitched, skipping")
            completed += 1
            report(0.0)
            continue

        store.upsert_pending(video.key, video.source_hash)
        try:
            copy_raw(video, config, store, log, report)
            stitch(video, config, store, log, report)
        except Exception as exc:  # one clip's failure must not abort the batch
            store.mark_failed(video.key, str(exc))
            log(f"[{video.key}] FAILED: {exc}")

        completed += 1
        report(0.0)
