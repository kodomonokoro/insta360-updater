"""PySide6/QML GUI entry point with live artifact status checks."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Must be set before QGuiApplication is created — QtQuick.Controls.Basic's
# default (unstyled) look ignores QML-side Material.theme properties.
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from insta360_uploader.gui_backend.pipeline_model import PipelineModel
from insta360_uploader.gui_backend.settings_model import SettingsModel
from insta360_uploader.processed_store import ProcessedStore
from insta360_uploader.settings_store import load_app_config

_QML_DIR = Path(__file__).parent / "qml"

# Terminal stdout/stderr capture proved unreliable for this GUI subprocess
# in this dev environment (Git Bash + Windows console redirection), so Qt
# warnings/errors (including QML binding errors and console.log) are routed
# straight to a file instead — kept as an ongoing diagnostic aid for the
# rest of this migration, not just a one-off debug session.
_DEBUG_LOG = Path(__file__).parent.parent.parent / "gui_qml_debug.log"


def _debug_message_handler(msg_type, context, message):
    with _DEBUG_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{QtMsgType(msg_type).name}] {message}\n")


def main() -> int:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    qInstallMessageHandler(_debug_message_handler)

    app = QGuiApplication(sys.argv)
    app.setWindowIcon(QIcon(str(_QML_DIR.parent / "assets" / "icon.png")))
    engine = QQmlApplicationEngine()
    engine.warnings.connect(
        lambda errs: [
            _debug_message_handler(QtMsgType.QtWarningMsg, None, str(e)) for e in errs
        ]
    )

    config = load_app_config()
    store = ProcessedStore()
    backend = PipelineModel(config, store)
    settings_backend = SettingsModel(config, store)
    # Saving Settings takes effect immediately — no restart needed.
    settings_backend.configSaved.connect(backend.apply_new_config)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("settingsBackend", settings_backend)

    engine.load(str(_QML_DIR / "Main.qml"))
    if not engine.rootObjects():
        return -1

    # Same "confirm before deleting anything on the NAS" startup check
    # gui.py does right after building its main window.
    settings_backend.checkStaleClips()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
