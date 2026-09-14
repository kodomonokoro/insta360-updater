"""Shared subprocess launch flags.

Every ffmpeg/ffprobe/MediaSDKTest.exe call in this app is spawned from a
windowed (console=False) GUI — without this, each one still opens its own
new console window on Windows, since a console-mode child doesn't inherit
"no console" from a windowed parent; it flashes open/closed for every
single call (reported: a console flash on every Settings save, since
saving triggers a refresh that ffprobes every listed file). subprocess's
own `creationflags=CREATE_NO_WINDOW` suppresses it. A no-op elsewhere."""
from __future__ import annotations

import subprocess
import sys

NO_WINDOW_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)
