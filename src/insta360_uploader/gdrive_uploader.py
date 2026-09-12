"""Google Drive upload for extracted audio, using the same OAuth pattern
as youtube_uploader.py.

Uses the full `drive` scope rather than the narrower `drive.file` — the
target folder (and the dated subfolders under it) are pre-existing,
manually-created folders, and `drive.file` only grants access to files/
folders the app itself created or the user opened with the app via a
Picker. Full `drive` is the pragmatic choice for a personal single-user
tool; it's not something to widen lightly for a multi-user app.

HARD RULE, from the user directly, not up for "cleanup": this module may
only ever CREATE new files/folders on Drive. Never delete, never trash,
never overwrite an existing file's content (files().update() with new
media is exactly as destructive as delete, from the user's point of
view — the old content is gone for good either way). If a name collision
is found, the only acceptable responses are to reuse the existing file
untouched (see _find_existing_file / upload_file) or to do nothing —
never rename around it or overwrite it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from insta360_uploader.config import DriveConfig

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveError(RuntimeError):
    pass


def run_oauth_flow(config: DriveConfig) -> None:
    if not config.client_secret_path.is_file():
        raise DriveError(f"client secret file not found: {config.client_secret_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(config.client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    config.token_path.parent.mkdir(parents=True, exist_ok=True)
    config.token_path.write_text(creds.to_json(), encoding="utf-8")


def _load_credentials(config: DriveConfig) -> Credentials:
    if not config.token_path.is_file():
        raise DriveError(
            "no saved Google Drive credentials; run 'insta360-uploader auth-gdrive' first"
        )

    creds = Credentials.from_authorized_user_file(str(config.token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            config.token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise DriveError(
                "stored Google Drive credentials are invalid; run "
                "'insta360-uploader auth-gdrive' again"
            )
    return creds


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_or_create_subfolder(drive, parent_id: str, name: str) -> str:
    query = (
        f"name = '{_escape_query_value(name)}' and mimeType = '{FOLDER_MIME_TYPE}' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    response = drive.files().list(q=query, fields="files(id)", spaces="drive").execute()
    matches = response.get("files", [])
    if matches:
        return matches[0]["id"]

    created = (
        drive.files()
        .create(
            body={"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]},
            fields="id",
        )
        .execute()
    )
    return created["id"]


def _find_existing_file(drive, parent_id: str | None, name: str) -> str | None:
    """Look for a file with this exact name (not in trash) — read-only,
    never creates or modifies anything."""
    query_parts = [f"name = '{_escape_query_value(name)}'", "trashed = false"]
    if parent_id:
        query_parts.append(f"'{parent_id}' in parents")
    query = " and ".join(query_parts)
    response = drive.files().list(q=query, fields="files(id)", spaces="drive").execute()
    matches = response.get("files", [])
    return matches[0]["id"] if matches else None


def file_exists(config: DriveConfig, file_id: str) -> bool:
    """False if the file was deleted, is in the trash, or was never there.

    Used to double-check a previously-recorded drive_file_id before
    skipping a re-upload — the local processed-store record alone can't
    tell if the user has since removed the file on Drive's side.
    """
    creds = _load_credentials(config)
    drive = build("drive", "v3", credentials=creds)
    try:
        meta = drive.files().get(fileId=file_id, fields="id,trashed").execute()
    except HttpError as exc:
        if exc.resp.status == 404:
            return False
        raise DriveError(f"could not check Google Drive file {file_id}: {exc}") from exc
    return not meta.get("trashed", False)


def upload_file(
    config: DriveConfig,
    file_path: Path,
    *,
    name: str | None = None,
    subfolder: str | None = None,
    progress_callback: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
    on_skip: Callable[[], None] | None = None,
) -> str:
    creds = _load_credentials(config)
    drive = build("drive", "v3", credentials=creds)

    parent_id = config.folder_id
    if subfolder:
        if not parent_id:
            raise DriveError("google_drive.folder_id must be set to use a dated subfolder")
        parent_id = _find_or_create_subfolder(drive, parent_id, subfolder)

    file_name = name or Path(file_path).name

    # Never overwrite or rename around an existing file — if one with this
    # exact name is already here, leave it untouched and reuse its id.
    # (Renaming to disambiguate is also not an option: the name matching
    # the video's title is what matters.)
    existing_id = _find_existing_file(drive, parent_id, file_name)
    if existing_id is not None:
        if on_skip:
            on_skip()
        if log:
            log(f"'{file_name}' already exists on Google Drive, reusing it (skipped upload)")
        return existing_id

    body: dict = {"name": file_name}
    if parent_id:
        body["parents"] = [parent_id]

    # Explicit chunksize (rather than the client's single-shot default) so
    # next_chunk() reports incremental progress — mp3s are small enough
    # that this will usually still complete in one chunk, but it costs
    # nothing to support it properly.
    media = MediaFileUpload(
        str(file_path), mimetype="audio/mpeg", chunksize=5 * 1024 * 1024, resumable=True
    )
    request = drive.files().create(body=body, media_body=media, fields="id")

    response = None
    while response is None:
        # num_retries: the client library's own exponential-backoff retry
        # for transient errors (5xx, connection resets, etc.) on each
        # chunk — without it, a single transient error (seen in practice:
        # a Google-side 502) aborts the whole upload immediately.
        status, response = request.next_chunk(num_retries=5)
        if status and progress_callback:
            progress_callback(status.progress())

    file_id = response.get("id")
    if not file_id:
        raise DriveError(f"upload did not return a file id: {response}")
    return file_id
