# insta360-uploader

A GUI app that lists videos in a NAS folder that Insta360 Studio exports
finished 360 videos into, lets you pick which ones to process, and on
"実行" (run):

1. extracts the audio as mp3, archives it next to the source folder
   (`.../mp3`), and uploads it to Google Drive (optional step, skipped if
   `google_drive` isn't configured) — done first since it's quick
2. uploads the video to YouTube, with an auto-generated title
   (`"{title_prefix} - {YYYYMMDD} {NN}"`, numbered by capture time within
   a day) and fixed default privacy/made-for-kids settings from
   `config.yaml`

**Nothing on the NAS is ever modified or deleted** by this tool (the
extracted mp3s are new files it creates, not source footage). Cleaning up
old exports is entirely up to you. **Nothing this tool creates ever touches
local disk, either** — mp3 extraction and the (rare) metadata safety-net
copy both write straight to the NAS, since these are 360 videos and can be
several GB each.

This is one half of a larger plan: eventually a second program will handle
Insta360 SD-card ingestion + stitching directly (blocked on Insta360
MediaSDK developer access). This tool's GUI (`VideoBrowserFrame` in
`gui.py`) is written generically — a folder-scan function + an execute
function — so that program can reuse the same "list, select, run" screen
as a second tab later, without replacing this one.

## How footage gets here

This tool does not do any stitching itself. The actual pipeline is:

1. Read the Insta360 microSD card with a card reader.
2. In **Insta360 Studio**, select the new clips and use **Batch Export**,
   choosing **"360 Panorama"** format (not "reframed"/flat) at the highest
   resolution/bitrate available, with the export destination set to the NAS
   folder this tool watches (`source.nas_video_folder` in `config.yaml`).
   Studio's 360 Panorama export already embeds the Spherical Video metadata
   YouTube needs — no separate metadata-injection step is normally required.
3. Run `insta360-uploader run` to pick up anything new in that folder.

## Install

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

`ffmpeg` must be on PATH if you want the Google Drive / audio step (used to
extract mp3 from the uploaded video). `ffprobe` (bundled with most ffmpeg
distributions) is used by the GUI to show each video's duration — if it's
missing, duration just shows as "—" rather than failing anything.

## One-time setup

### 1. YouTube OAuth

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project, enable **YouTube Data API v3**, and create an **OAuth client ID**
   of type "Desktop app". Download its JSON, e.g. as
   `secrets/youtube_client_secret.json`.
2. Copy `config.example.yaml` to `config.yaml` and fill in the paths.
3. Run `insta360-uploader auth-youtube` — a browser window opens for
   consent, then a refresh token is cached to `token_path`.

This tool only uploads to a single YouTube channel (set once under
`youtube:` in `config.yaml`) — there's no multi-channel switching.

### 2. Google Drive (optional — for the extracted-audio step)

1. In the same or a different Cloud project, enable **Google Drive API** and
   create another OAuth client ID (Desktop app). Save its JSON as e.g.
   `secrets/gdrive_client_secret.json`.
2. Add the `google_drive` section to `config.yaml` (see
   `config.example.yaml`). Set `folder_id` to a Drive folder ID if you want
   the mp3s to land in a specific folder, or leave it empty for Drive root.
3. Run `insta360-uploader auth-gdrive` once.

If you don't want this feature, just omit the `google_drive` section — the
tool then stops after the YouTube upload.

### 3. NAS

`source.nas_video_folder` is a plain UNC path (e.g.
`\\NAS\insta360-exports`). This assumes Windows already has authenticated
access to it (saved credentials via `net use`, or domain membership) — the
tool does no SMB auth of its own, it just reads and writes files.
Extracted mp3s are written to the sibling `mp3` folder next to it
(`nas_video_folder.parent / "mp3"`), created automatically if missing.

### 4. Video titles and upload defaults

Set in `config.yaml` under `youtube_defaults`:

```yaml
youtube_defaults:
  title_prefix: "crotchet rest 360"
  privacy_status: unlisted   # public | unlisted | private
  made_for_kids: false
```

Titles are generated as `"{title_prefix} - {YYYYMMDD} {NN}"`, e.g.
`crotchet rest 360 - 20260905 01`. `NN` numbers same-day videos by capture
time (extracted from the Insta360 filename pattern if present, otherwise
the file's modification time) and never reuses a number already recorded
for that date — so numbering stays correct even across separate runs.
A title, once assigned to a video, doesn't change on retry.

## Usage

### GUI (primary way to run this)

```
insta360-uploader-gui [path/to/config.yaml]   # defaults to ./config.yaml
```

Shows the videos found in `nas_video_folder` as a table (status, filename,
duration via `ffprobe`, file size). Check the ones you want (click a row's
checkbox, or click the column header to select/deselect all) and press
"実行". An overall progress bar (files completed) and a per-file progress
bar are shown above the list, and details stream into the log pane below;
the list refreshes when done.

The "YouTube認証"/"Google Drive認証" buttons at the top show whether each
is already authenticated, and can be used instead of the CLI `auth-*`
commands below.

### CLI (for scripting/automation)

```
insta360-uploader scan              # list what would be processed
insta360-uploader run               # process everything pending
insta360-uploader run --dry-run     # same, without doing anything
insta360-uploader status            # see done/pending/failed videos
```

Re-running `run` (or re-selecting a failed video in the GUI) only retries
videos that aren't marked `done` in the processed store
(`data/processed.json`, auto-created next to this package — not
configurable, so nothing here needs an absolute path).

## Safety net

If a video in the NAS folder is somehow missing Spherical Video metadata
(e.g. Studio was accidentally set to export flat), the tool detects this
and injects it into a copy under `nas_video_folder.parent / "_retagged"`
before uploading, rather than silently uploading a flat-looking 360 video.
This copy is full video size, but it's written to the NAS, never to local
disk — and it should be rare in practice, since Studio's own 360 Panorama
export already embeds this metadata.

## Third-party code

`src/spatialmedia/` is vendored from Google's
[spatial-media](https://github.com/google/spatial-media) (Apache 2.0, see
`src/spatialmedia/LICENSE`) — it does the actual MP4 box-level metadata
inspection/injection used by the safety net above.
