# Insta360 Updater

Windows desktop app (Python + PySide6/QML) for camera footage:

1. Copy all selected INSV chapters to NAS `raw/`.
2. Stitch with Insta360 MediaSDK and join chapters into `processed/mp4/`.
3. Extract MP3 audio into `processed/mp3/`.
4. Upload audio to Google Drive (when configured).
5. Upload 360 video to YouTube.

The GUI supports the full pipeline, stopping after conversion, or starting
with already-converted NAS videos. Camera originals are copied, never deleted.

## Completion status

The file table checks actual artifacts on startup, refresh, and after processing:

- Copy: all known raw chapters exist in the raw folder (shown as
  unconfigured if no raw folder is set).
- Conversion: the final MP4 exists.
- Audio: the final MP3 exists (shown as unconfigured if no mp3 folder is
  set).
- Drive: a matching non-trashed file exists in the configured destination
  (shown as unconfigured if Drive isn't set up).
- YouTube: a matching video exists in the authenticated channel.

Run mode does not hide existing artifacts. Network checks happen in the
background. A failed check is shown as unknown, separately from missing.
Temporary `.part` files do not count as completed outputs.

**There is no persistent completion history.** `processed_store.py` retains
its legacy name but holds only in-memory execution progress and errors.
`data/processed.json` is no longer read or written. A new run checks actual
destinations before reusing files or uploads. Files missing from NAS do not
appear complete just because their uploads still exist.

Titles normally use `{prefix} - {YYYYMMDD} {HHMM}`, derived from the capture
filename. Matching depends on identity/names, not video content comparison.
Only names derived from the source and current naming settings are matched.
Legacy names and saved remote IDs are not used for completion checks.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Install ffmpeg/ffprobe on PATH and configure a local Insta360 MediaSDK
installation in Settings. Current stitch profiles are 8K at 154 Mbps and
6K at 50 Mbps, H.265. The 6K profile has limited validation; see
`analysis/insta360-studio-match/results/comparison.md`.

Configuration is JSON, not YAML, split across two files:

- `data/settings.json` — tracked in git, always blank. Exists so a fresh
  checkout has something to read; never accumulates real paths or IDs.
- `data/settings.local.json` — gitignored. This is where a real user's
  actual settings (paths, Drive folder ID, playlist ID — never secrets
  or OAuth tokens, which live under `secrets/` instead) live. Once this
  file exists, it's the only one read or written; a fresh setup seeds it
  once from the tracked template (or blank, if that's missing too) and
  never touches the tracked file again.

Saving GUI settings takes effect immediately — no restart needed.
Authenticate YouTube and optionally Google Drive through Settings or CLI.
NAS access uses the current Windows account's filesystem permissions.

Raw (①②) and mp3 (③④) folders have no automatic fallback — each is
required only for the run modes that actually reach it, checked when the
GUI's 開始 button or the CLI's `run`/`intake` commands are used
(`config.validate_for_run`), not merely to open Settings.

## Usage

```powershell
insta360-uploader-gui
# Equivalent:
python -m insta360_uploader.gui_qml

insta360-uploader scan
insta360-uploader status
insta360-uploader run --dry-run
insta360-uploader run
insta360-uploader intake --stop-after-stitch
insta360-uploader auth-youtube
insta360-uploader auth-gdrive
```

`scan` lists NAS videos; `status` checks local and remote artifacts.
`run` checks each operation's destination, with no history-based filter.

Cleanup candidates require verified YouTube presence and, when configured,
Drive presence. Retention uses the newest local artifact's modification
time. The GUI asks before deleting candidate files. A failed remote check
aborts candidate discovery.

The stop button's cancellation is cooperative, not instant: it's only
checked between clips/stages, so whatever single copy/stitch/upload is
already in flight always finishes on its own first before the run actually
stops.

## Building a distributable app

```powershell
.venv\Scripts\python -m pip install -e ".[build]"
.venv\Scripts\python build_exe.py
```

Produces `dist/Insta360Updater/` (a folder — copy the whole folder to
distribute, not just the .exe inside it; ~360MB). Uses PyInstaller
(`insta360-uploader.spec`) plus a post-build trim of Qt components this
app never uses (WebEngine, 3D, Multimedia, etc. — PySide6's own
PyInstaller hooks pull these in regardless of what the spec excludes, so
`build_exe.py` deletes them after the build rather than fighting the
hooks; always use this script instead of calling `pyinstaller` directly).
On first run, the built app creates its own blank `data/settings.local.json`
next to the .exe — same settings.json/settings.local.json behavior as
running from source (see Setup above), just rooted at the .exe's own
folder instead of the project root. A `secrets/` folder placed next to
the .exe works the same way too.

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

`src/spatialmedia/` is vendored from Google's spatial-media project
(Apache 2.0; see `src/spatialmedia/LICENSE`).
