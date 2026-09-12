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


def _get_uploads_playlist_id(youtube) -> str:
    response = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise UploadError("could not find the authenticated channel")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _find_existing_video(youtube, title: str) -> str | None:
    """Look for an already-uploaded video with this exact title, by paging
    through the channel's own uploads — read-only, never creates or
    modifies anything. YouTube's search.list() only does fuzzy relevance
    search, so an exact-title check needs this instead (same idea as
    gdrive_uploader._find_existing_file, adapted to what the API offers)."""
    uploads_playlist_id = _get_uploads_playlist_id(youtube)
    page_token = None
    while True:
        response = (
            youtube.playlistItems()
            .list(
                playlistId=uploads_playlist_id,
                part="snippet",
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("items", []):
            snippet = item["snippet"]
            if snippet.get("title") == title:
                return snippet["resourceId"]["videoId"]
        page_token = response.get("nextPageToken")
        if not page_token:
            return None


def video_exists(profile: YoutubeProfile, video_id: str) -> bool:
    """False if the video was deleted or never existed.

    Used to double-check a previously-recorded youtube_video_id before
    skipping a re-upload — the local processed-store record alone can't
    tell if the video was since removed on YouTube's side.
    """
    creds = _load_credentials(profile)
    youtube = build("youtube", "v3", credentials=creds)
    response = youtube.videos().list(part="id", id=video_id).execute()
    return bool(response.get("items"))


def upload_video(
    profile: YoutubeProfile,
    video_path: Path,
    *,
    title: str,
    description: str = "",
    privacy_status: str = "private",
    made_for_kids: bool = False,
    progress_callback: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
    on_skip: Callable[[], None] | None = None,
) -> str:
    creds = _load_credentials(profile)
    youtube = build("youtube", "v3", credentials=creds)

    # Never re-upload a video that's already there under this exact title
    # — YouTube doesn't dedup by name itself, so without this a retry (or
    # a stale/missing local record) would create a duplicate video every
    # time. Mirrors gdrive_uploader.upload_file's own name-based
    # existing-file check.
    existing_id = _find_existing_video(youtube, title)
    if existing_id is not None:
        if on_skip:
            on_skip()
        if log:
            log(f"'{title}' already exists on YouTube, reusing it (skipped upload)")
        return existing_id

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
        # num_retries: the client library's own exponential-backoff retry
        # for transient errors (5xx, connection resets, etc.) on each
        # chunk — without it, a single transient error (seen in practice:
        # a Google-side 502) aborts the whole upload immediately.
        status, response = request.next_chunk(num_retries=5)
        if status and progress_callback:
            progress_callback(status.progress())

    video_id = response.get("id")
    if not video_id:
        raise UploadError(f"upload did not return a video id: {response}")
    return video_id


def _find_playlist_item(youtube, playlist_id: str, video_id: str) -> str | None:
    """Returns the existing playlistItem id if video_id is already in the
    playlist, else None — read-only, never creates or modifies anything."""
    page_token = None
    while True:
        response = (
            youtube.playlistItems()
            .list(playlistId=playlist_id, part="snippet", maxResults=50, pageToken=page_token)
            .execute()
        )
        for item in response.get("items", []):
            if item["snippet"]["resourceId"]["videoId"] == video_id:
                return item["id"]
        page_token = response.get("nextPageToken")
        if not page_token:
            return None


def add_video_to_playlist(
    profile: YoutubeProfile,
    video_id: str,
    playlist_id: str,
    log: Callable[[str], None] | None = None,
) -> None:
    """Purely additive (playlistItems().insert) — never removes anything
    from the playlist. Skips if the video is already in it, so re-running
    an already-added video doesn't create a duplicate playlist entry."""
    creds = _load_credentials(profile)
    youtube = build("youtube", "v3", credentials=creds)

    if _find_playlist_item(youtube, playlist_id, video_id) is not None:
        if log:
            log(f"video {video_id} already in playlist {playlist_id}, skipping")
        return

    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    youtube.playlistItems().insert(part="snippet", body=body).execute()
