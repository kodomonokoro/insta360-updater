"""YouTube OAuth profile handling and resumable video upload.

360-ness is detected by YouTube purely from the Spherical Video metadata
already injected into the mp4 (see metadata.py) — there is no separate
"this is a 360 video" flag to set via the Data API.

Uses the full `youtube` scope (not just `youtube.upload`) since it's a
strict superset that also covers playlist management (adding an uploaded
video to a members-only unlisted playlist) without needing a second scope.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from insta360_uploader.config import YoutubeProfile

SCOPES = ["https://www.googleapis.com/auth/youtube"]


class UploadError(RuntimeError):
    pass


def run_oauth_flow(profile: YoutubeProfile) -> None:
    """One-time interactive consent flow; caches a refresh token to disk."""
    if not profile.client_secret_path.is_file():
        raise UploadError(f"client secret file not found: {profile.client_secret_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(profile.client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    profile.token_path.parent.mkdir(parents=True, exist_ok=True)
    profile.token_path.write_text(creds.to_json(), encoding="utf-8")


def _load_credentials(profile: YoutubeProfile) -> Credentials:
    if not profile.token_path.is_file():
        raise UploadError(
            "no saved YouTube credentials; run 'insta360-uploader auth-youtube' first"
        )

    creds = Credentials.from_authorized_user_file(str(profile.token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            profile.token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise UploadError(
                "stored YouTube credentials are invalid; run "
                "'insta360-uploader auth-youtube' again"
            )
    return creds


def upload_video(
    profile: YoutubeProfile,
    video_path: Path,
    *,
    title: str,
    description: str = "",
    privacy_status: str = "private",
    made_for_kids: bool = False,
    progress_callback: Callable[[float], None] | None = None,
) -> str:
    creds = _load_credentials(profile)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {"title": title, "description": description},
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    # chunksize=-1 would send the whole file as one request — for a
    # multi-GB 360 video that means no progress callback until it's fully
    # done. Chunking (here, 50MB) gives real incremental progress.
    media = MediaFileUpload(
        str(video_path), chunksize=50 * 1024 * 1024, resumable=True, mimetype="video/mp4"
    )
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            progress_callback(status.progress())

    video_id = response.get("id")
    if not video_id:
        raise UploadError(f"upload did not return a video id: {response}")
    return video_id


def add_video_to_playlist(profile: YoutubeProfile, video_id: str, playlist_id: str) -> None:
    """Purely additive (playlistItems().insert) — never removes anything
    from the playlist."""
    creds = _load_credentials(profile)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    youtube.playlistItems().insert(part="snippet", body=body).execute()
