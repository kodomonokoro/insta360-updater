"""Build the distributable Windows app (onedir) and strip unused Qt
components PyInstaller's PySide6 hooks pull in regardless of the spec
file's collect_all() filtering (WebEngine, 3D/Quick3D, Multimedia,
Designer, etc. — this app only ever uses QtQuick/QtQuick.Controls
(.Material)/QtQuick.Layouts/Qt5Compat.GraphicalEffects). Cuts the build
from ~790MB to ~360MB. Re-run this after any pyproject.toml/dependency
change instead of calling pyinstaller directly, so the trim always
happens.

Usage: .venv\\Scripts\\python build_exe.py
Output: dist/Insta360Updater/Insta360Updater.exe (copy the whole
Insta360Updater folder to distribute — not just the .exe).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_PYSIDE6 = PROJECT_ROOT / "dist" / "Insta360Updater" / "_internal" / "PySide6"
DIST_PLUGINS = DIST_PYSIDE6 / "plugins"

# DLL filename globs (relative to the PySide6 folder itself).
_UNUSED_DLL_GLOBS = [
    "Qt6WebEngine*.dll", "Qt6Pdf*.dll", "Qt6Designer*.dll", "Qt6Quick3D*.dll",
    "Qt63D*.dll", "Qt6Graphs*.dll", "Qt6Multimedia*.dll", "Qt6Charts.dll",
    "Qt6DataVisualization.dll", "Qt6Bluetooth.dll", "Qt6Nfc.dll",
    "Qt6Sensors*.dll", "Qt6SerialPort.dll", "Qt6SerialBus.dll",
    "Qt6Positioning*.dll", "Qt6Location.dll", "Qt6TextToSpeech.dll",
    "Qt6WebView.dll", "Qt6RemoteObjects*.dll", "Qt6Scxml*.dll",
    "Qt6StateMachine*.dll", "Qt6Sql.dll",
    "avcodec-*.dll", "avformat-*.dll", "avutil-*.dll", "swresample-*.dll", "swscale-*.dll",
]

# QML module folders (relative to PySide6/qml/) that are never imported by
# any .qml file in this app.
_UNUSED_QML_DIRS = [
    "QtWebEngine", "QtQuick3D", "Qt3D", "QtGraphs", "QtMultimedia",
    "QtCharts", "QtDataVisualization", "QtPositioning", "QtLocation",
    "QtSensors", "QtBluetooth", "QtNfc", "QtSerialPort", "QtWebView",
    "QtRemoteObjects", "QtScxml", "QtStateMachine",
]

# Qt plugin folders (relative to PySide6/plugins/) for backends this app
# never uses (no QtSql/QtMultimedia/QtPositioning/QtSensors/etc. anywhere).
_UNUSED_PLUGIN_DIRS = [
    "sqldrivers", "position", "sensors", "geoservices", "multimedia", "webview",
]


def _trim_pyside6() -> None:
    if not DIST_PYSIDE6.is_dir():
        print(f"warning: {DIST_PYSIDE6} not found, skipping trim step", file=sys.stderr)
        return

    for pattern in _UNUSED_DLL_GLOBS:
        for path in DIST_PYSIDE6.glob(pattern):
            path.unlink()

    for name in _UNUSED_QML_DIRS:
        shutil.rmtree(DIST_PYSIDE6 / "qml" / name, ignore_errors=True)

    for name in _UNUSED_PLUGIN_DIRS:
        shutil.rmtree(DIST_PLUGINS / name, ignore_errors=True)


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "insta360-uploader.spec", "--noconfirm"],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        return result.returncode

    _trim_pyside6()
    print("Build + trim complete: dist/Insta360Updater/Insta360Updater.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
