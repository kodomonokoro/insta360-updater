from __future__ import annotations

import argparse
import sys

from insta360_uploader.camera_pipeline import run_camera_pipeline
from insta360_uploader.camera_scanner import find_camera_drive, scan_camera_folder
from insta360_uploader.config import ConfigError
from insta360_uploader.gdrive_uploader import DriveError
from insta360_uploader.gdrive_uploader import run_oauth_flow as run_gdrive_oauth_flow
from insta360_uploader.nas_scanner import scan_video_folder
from insta360_uploader.pipeline import run_pipeline
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.settings_store import load_app_config
from insta360_uploader.stitcher import StitchError
from insta360_uploader.youtube_uploader import UploadError
from insta360_uploader.youtube_uploader import run_oauth_flow as run_youtube_oauth_flow


def cmd_scan(args: argparse.Namespace) -> int:
    config = load_app_config()
    videos = scan_video_folder(config.nas_video_folder)
    print(f"Found {len(videos)} video(s) in NAS folder:\n")
    for video in videos:
        print(f"  {video.key}  <- {video.path}")
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    config = load_app_config()
    if config.media_sdk is None:
        print("error: insta360_sdk is not configured (see the Settings screen)", file=sys.stderr)
        return 1

    drive = find_camera_drive()
    if drive is None:
        print("error: Insta360 camera not found (check the USB connection)", file=sys.stderr)
        return 1

    store = ProcessedStore()
    videos = scan_camera_folder(drive)
    if not videos:
        print("No .insv files found on the camera.")
        return 0

    try:
        run_camera_pipeline(
            videos,
            config,
            store,
            print,
            on_camera_safe=lambda: print("-> NAS copy complete, camera can now be disconnected."),
            stop_after_stitch=args.stop_after_stitch,
        )
    except (StitchError, UploadError, DriveError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_app_config()
    try:
        run_pipeline(config, dry_run=args.dry_run)
    except (ConfigError, UploadError, DriveError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_app_config()
    from insta360_uploader.artifact_status import make_target, local_states, RemoteArtifacts
    remote = RemoteArtifacts(config)
    for video in scan_video_folder(config.nas_video_folder):
        target = make_target(video, config)
        states = local_states(target, config)
        for stage, check in (("drive", remote.drive_exists), ("youtube", remote.youtube_exists)):
            try:
                states[stage] = "unconfigured" if stage == "drive" and config.drive is None else (
                    "done" if check(target) else "pending"
                )
            except Exception as exc:
                states[stage] = "unknown"
                print(f"{video.key} {stage}: {exc}", file=sys.stderr)
        print(f"{video.key}: " + ", ".join(f"{key}={state}" for key, state in states.items()))
    return 0


def cmd_auth_youtube(args: argparse.Namespace) -> int:
    config = load_app_config()
    try:
        run_youtube_oauth_flow(config.youtube)
    except UploadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Saved YouTube credentials to {config.youtube.token_path}")
    return 0


def cmd_auth_gdrive(args: argparse.Namespace) -> int:
    config = load_app_config()
    if config.drive is None:
        print("error: Google Drive is not configured (see the Settings screen)", file=sys.stderr)
        return 1
    try:
        run_gdrive_oauth_flow(config.drive)
    except DriveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Saved Google Drive credentials to {config.drive.token_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insta360-uploader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_scan = subparsers.add_parser("scan", help="list videos in the NAS folder")
    p_scan.set_defaults(func=cmd_scan)

    p_intake = subparsers.add_parser(
        "intake",
        help="copy new .insv files from the camera, stitch, and upload (mp3 to Drive, video to YouTube)",
    )
    p_intake.add_argument(
        "--stop-after-stitch",
        action="store_true",
        help="stop after stitching to mp4, skipping audio extraction and both uploads (for testing)",
    )
    p_intake.set_defaults(func=cmd_intake)

    p_run = subparsers.add_parser(
        "run", help="upload new videos to YouTube (and audio to Drive, if configured)"
    )
    p_run.add_argument("--dry-run", action="store_true", help="only show what would be processed")
    p_run.set_defaults(func=cmd_run)

    p_status = subparsers.add_parser("status", help="check actual local and remote artifacts")
    p_status.set_defaults(func=cmd_status)

    p_auth_yt = subparsers.add_parser(
        "auth-youtube", help="run the one-time YouTube OAuth consent flow"
    )
    p_auth_yt.set_defaults(func=cmd_auth_youtube)

    p_auth_drive = subparsers.add_parser(
        "auth-gdrive", help="run the one-time Google Drive OAuth consent flow"
    )
    p_auth_drive.set_defaults(func=cmd_auth_gdrive)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
