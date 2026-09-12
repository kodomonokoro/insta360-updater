# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec — onedir distribution of the PySide6/QML GUI.

Bundles all of PySide6's QML plugins via collect_all() rather than relying
on PyInstaller's static import analysis to find them: QML files import
modules (QtQuick, QtQuick.Controls.Material, Qt5Compat.GraphicalEffects)
by string inside .qml text, which Python-level analysis can't see at all.
Missing any of these would fail silently at runtime (a blank window or a
QML "module not found" error), not at build time, so collect_all is the
safe default for a first working build even though it makes the bundle
bigger than a hand-tuned hiddenimports list would.

Build: pyinstaller insta360-uploader.spec
Output: dist/Insta360Updater/Insta360Updater.exe (a folder — copy the
whole Insta360Updater folder to distribute, not just the .exe).
"""
import re

from PyInstaller.utils.hooks import collect_all

# collect_all() grabs a PySide6 subpackage's entire contents indiscriminately
# (it has to — QML modules are loaded by string from .qml files, invisible
# to normal Python import analysis, so under-collecting risks a silent
# runtime failure). This app only ever uses QtQuick/QtQuick.Controls
# (.Material)/QtQuick.Layouts/Qt5Compat.GraphicalEffects — the rest of
# PySide6_Addons (WebEngine alone is ~195MB, plus Designer/Pdf/3D/Quick3D/
# Graphs/Multimedia/Charts/Bluetooth/Nfc/Sensors/SerialPort/etc.) is pure
# dead weight for this app specifically. Filtering by path substring after
# collect_all (rather than trying to hand-pick what to include) means a
# real dependency is never silently dropped — only known-unused components
# are removed.
_EXCLUDE_PATTERNS = [
    r"webengine", r"pdf", r"quick3d", r"3drender", r"3dcore", r"3dinput",
    r"3dlogic", r"3danimation", r"3dextras", r"designer", r"multimedia",
    r"spatialaudio", r"charts", r"datavis", r"bluetooth", r"nfc", r"sensors",
    r"serialport", r"serialbus", r"positioning", r"location", r"texttospeech",
    r"webview", r"remoteobjects", r"scxml", r"statemachine", r"graphs",
    r"networkauth", r"help[/\\]", r"uitools", r"quicktimeline", r"quick3druntimerender",
    r"quick3dassetimport", r"quick3dutils", r"quick3dphysics", r"avcodec",
    r"avformat", r"avutil", r"swresample", r"swscale",
]
_EXCLUDE_RE = re.compile("|".join(_EXCLUDE_PATTERNS), re.IGNORECASE)


def _filtered(entries):
    return [e for e in entries if not _EXCLUDE_RE.search(e[0])]


datas = []
binaries = []
hiddenimports = []

for pkg in ("PySide6", "PySide6_Addons", "PySide6_Essentials"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += _filtered(pkg_datas)
    binaries += _filtered(pkg_binaries)
    hiddenimports += [
        h for h in pkg_hiddenimports if not _EXCLUDE_RE.search(h.replace(".", "/"))
    ]

datas += [
    ("src/insta360_uploader/qml", "insta360_uploader/qml"),
    ("src/insta360_uploader/assets", "insta360_uploader/assets"),
]

a = Analysis(
    ["src/insta360_uploader/gui_qml.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Insta360Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="src/insta360_uploader/assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Insta360Updater",
)
