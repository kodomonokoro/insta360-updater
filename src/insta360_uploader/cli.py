from __future__ import annotations

import argparse
import sys

from insta360_uploader.config import ConfigError, load_config
from insta360_uploader.gdrive_uploader import DriveError
from insta360_uploader.gdrive_uploader import run_oauth_flow as run_gdrive_oauth_flow
from insta360_uploader.nas_scanner import scan_video_folder
from insta360_uploader.pipeline import run_pipeline
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.youtube_uploader import UploadError
from insta360_uploader.youtube_uploader import run_oauth_flow as run_youtube_oauth_flow


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", default="config.yaml", help="path to config.yaml (default: ./config.yaml)"
    )


def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = ProcessedStore()
    videos = scan_video_folder(config.nas_video_folder)

    pending = [v for v in videos if not store.is_done(v.key, v.source_hash)]
    print(f"Found {len(videos)} video(s) in NAS folder, {len(pending)} not yet processed:\n")
    for video in pending:
        print(f"  {video.key}  <- {video.path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    try:
        run_pipeline(config, dry_run=args.dry_run)
    except (ConfigError, UploadError, DriveError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = ProcessedStore()
    records = store.list_all()
    if not records:
        print("No videos recorded yet.")
        return 0

    for r in records:
        extra = f" -> {r.youtube_video_id}" if r.youtube_video_id else ""
        extra += f" (drive: {r.drive_file_id})" if r.drive_file_id else ""
        extra += f" ({r.error})" if r.error else ""
        print(f"{r.status:>18}  {r.clip_key}{extra}")
    return 0


def cmd_auth_youtube(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    try:
        run_youtube_oauth_flow(config.youtube)
    except UploadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Saved YouTube credentials to {config.youtube.token_path}")
    return 0


def cmd_auth_gdrive(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if config.drive is None:
        print("error: no 'google_drive' section in config.yaml", file=sys.stderr)
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

    p_scan = subparsers.add_parser("scan", help="list unprocessed videos in the NAS folder")
    _add_config_arg(p_scan)
    p_scan.set_defaults(func=cmd_scan)

    p_run = subparsers.add_parser(
        "run", help="upload new videos to YouTube (and audio to Drive, if configured)"
    )
    _add_config_arg(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="only show what would be processed")
    p_run.set_defaults(func=cmd_run)

    p_status = subparsers.add_parser("status", help="show processed/pending/failed videos")
    _add_config_arg(p_status)
    p_status.set_defaults(func=cmd_status)

    p_auth_yt = subparsers.add_parser(
        "auth-youtube", help="run the one-time YouTube OAuth consent flow"
    )
    _add_config_arg(p_auth_yt)
    p_auth_yt.set_defaults(func=cmd_auth_youtube)

    p_auth_drive = subparsers.add_parser(
        "auth-gdrive", help="run the one-time Google Drive OAuth consent flow"
    )
    _add_config_arg(p_auth_drive)
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
