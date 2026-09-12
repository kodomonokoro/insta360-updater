from pathlib import Path

from insta360_uploader import intake
from insta360_uploader.config import AppConfig, MediaSdkConfig, YoutubeDefaults, YoutubeProfile
from insta360_uploader.nas_scanner import VideoFile
from insta360_uploader.processed_store import STATUS_COPYING_RAW, STATUS_STITCHING, ProcessedStore


def _config(tmp_path) -> AppConfig:
    nas = tmp_path / "crotchet rest" / "processed" / "mp4"
    return AppConfig(
        nas_video_folder=nas,
        youtube=YoutubeProfile(client_secret_path=Path(""), token_path=Path("")),
        youtube_defaults=YoutubeDefaults(
            title_prefix="p", privacy_status="unlisted", made_for_kids=False, playlist_id=None
        ),
        drive=None,
        media_sdk=MediaSdkConfig(exe_path=tmp_path / "MediaSDKTest.exe", model_root_dir=tmp_path / "models"),
        retention_days=14,
        raw_folder=tmp_path / "crotchet rest" / "raw",
    )


def _touch(path: Path, size: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)


def _camera_file(tmp_path, name: str) -> Path:
    p = tmp_path / "camera" / name
    _touch(p)
    return p


def test_copy_raw_copies_every_chapter(tmp_path):
    config = _config(tmp_path)
    store = ProcessedStore()
    chapters = (
        _camera_file(tmp_path, "VID_20260906_131910_00_005.insv"),
        _camera_file(tmp_path, "VID_20260906_131910_00_006.insv"),
    )
    video = VideoFile(key="VID_20260906_131910", path=chapters[0], chapter_paths=chapters)
    store.upsert_pending(video.key, video.source_hash)

    raw_paths = intake.copy_raw(video, config, store, print)

    assert [p.name for p in raw_paths] == [
        "VID_20260906_131910_00_005.insv",
        "VID_20260906_131910_00_006.insv",
    ]
    assert all(p.is_file() for p in raw_paths)
    assert store.get(video.key).status == STATUS_COPYING_RAW


def test_copy_raw_skips_chapters_already_copied(tmp_path):
    config = _config(tmp_path)
    store = ProcessedStore()
    chapters = (_camera_file(tmp_path, "VID_20260906_131910_00_005.insv"),)
    video = VideoFile(key="VID_20260906_131910_00_005", path=chapters[0], chapter_paths=chapters)
    store.upsert_pending(video.key, video.source_hash)

    raw_path = config.raw_folder / "VID_20260906_131910_00_005.insv"
    _touch(raw_path, size=99)

    logs: list[str] = []
    intake.copy_raw(video, config, store, logs.append)

    assert raw_path.stat().st_size == 99  # untouched, not re-copied
    assert any("already copied" in line for line in logs)
    assert store.get(video.key).status != STATUS_COPYING_RAW  # never transitioned


def test_stitch_single_chapter_unchanged_behavior(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = ProcessedStore()
    chapters = (_camera_file(tmp_path, "clip.insv"),)
    video = VideoFile(key="clip", path=chapters[0], chapter_paths=chapters)
    store.upsert_pending(video.key, video.source_hash)
    raw_path = config.raw_folder / "clip.insv"
    _touch(raw_path)

    calls = []

    def fake_stitch_to_mp4(insv_path, output_path, *, media_sdk, progress_callback=None, log=None):
        calls.append((insv_path, output_path))
        _touch(output_path)
        if progress_callback:
            progress_callback(1.0)
        return output_path

    monkeypatch.setattr(intake, "stitch_to_mp4", fake_stitch_to_mp4)

    progress_values: list[float] = []
    result = intake.stitch(video, config, store, print, progress_values.append)

    assert result == config.nas_video_folder / "clip.mp4"
    assert result.is_file()
    assert calls == [(raw_path, result)]
    assert progress_values == [1.0]
    assert store.get(video.key).status == STATUS_STITCHING


def test_stitch_skips_when_mp4_already_exists(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = ProcessedStore()
    chapters = (_camera_file(tmp_path, "clip.insv"),)
    video = VideoFile(key="clip", path=chapters[0], chapter_paths=chapters)
    store.upsert_pending(video.key, video.source_hash)
    _touch(config.nas_video_folder / "clip.mp4")

    def fail_stitch(*args, **kwargs):
        raise AssertionError("stitch_to_mp4 must not be called when already stitched")

    monkeypatch.setattr(intake, "stitch_to_mp4", fail_stitch)

    result = intake.stitch(video, config, store, print)

    assert result == config.nas_video_folder / "clip.mp4"


def test_stitch_multi_chapter_stitches_each_then_joins(tmp_path, monkeypatch):
    config = _config(tmp_path)
    store = ProcessedStore()
    chapters = (
        _camera_file(tmp_path, "VID_20260906_131910_00_005.insv"),
        _camera_file(tmp_path, "VID_20260906_131910_00_006.insv"),
    )
    video = VideoFile(key="VID_20260906_131910", path=chapters[0], chapter_paths=chapters)
    store.upsert_pending(video.key, video.source_hash)
    raw_folder = config.raw_folder
    raw_paths = [raw_folder / c.name for c in chapters]
    for p in raw_paths:
        _touch(p)

    stitched_inputs = []

    def fake_stitch_to_mp4(insv_path, output_path, *, media_sdk, progress_callback=None, log=None):
        stitched_inputs.append(insv_path)
        _touch(output_path, size=10)
        if progress_callback:
            progress_callback(1.0)
        return output_path

    concat_commands = []

    def fake_run(command, **kwargs):
        concat_commands.append(command)
        output_path = Path(command[-1])
        _touch(output_path, size=20)

        class _Result:
            returncode = 0
            stderr = ""

        return _Result()

    monkeypatch.setattr(intake, "stitch_to_mp4", fake_stitch_to_mp4)
    monkeypatch.setattr(intake.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(intake.subprocess, "run", fake_run)

    progress_values: list[float] = []
    result = intake.stitch(video, config, store, print, progress_values.append)

    assert result == config.nas_video_folder / "VID_20260906_131910.mp4"
    assert result.is_file()
    assert stitched_inputs == raw_paths
    # Per-chapter progress is scaled into this clip's overall [0, 1] range.
    assert progress_values == [0.5, 1.0]
    assert len(concat_commands) == 1
    # Intermediate per-chapter mp4s live in the mp4 folder (raw stays
    # .insv-only) and are cleaned up after the join succeeds.
    assert not any((config.nas_video_folder / f"{p.stem}.mp4").exists() for p in raw_paths)
    assert not any(p.with_suffix(".mp4").exists() for p in raw_paths)  # never written next to the raw .insv
