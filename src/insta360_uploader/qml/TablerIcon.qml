import QtQuick
import Qt5Compat.GraphicalEffects

// Tabler Icons (https://tabler.io/icons), outline set, as flat-colored SVGs
// under assets/icons/ — ColorOverlay recolors the (currentColor-stroked)
// source per state/usage rather than needing a separately-exported SVG per
// color. Shared by Main.qml and SettingsScreen.qml (a plain sibling .qml
// file, so no import needed).
//
// QtQuick.Effects' MultiEffect (colorization/colorizationColor) was tried
// first and loads/runs without error, but a grabWindow() pixel check
// showed it does NOT actually apply colorizationColor to these icons — the
// output stayed grayscale. Root cause not chased further; Qt5Compat's
// ColorOverlay was verified the same way (grabbed output pixels matched
// the requested color exactly) and is the one actually wired up below.
//
// A data-URI/XMLHttpRequest text-substitution approach (avoiding
// GraphicalEffects entirely) was also tried, to rule out an FBO/texture
// limit with many simultaneous ColorOverlay instances — but QML disables
// XMLHttpRequest GET on local files by default (QML_XHR_ALLOW_FILE_READ),
// so it never loaded anything at all in this app; reverted rather than
// requiring that env var.
Item {
    id: iconRoot
    property string name: ""
    property color iconColor: "#111827"
    property int size: 20
    property bool spinning: false
    implicitWidth: size
    implicitHeight: size

    NumberAnimation on rotation {
        from: 0
        to: 360
        duration: 900
        loops: Animation.Infinite
        running: iconRoot.spinning && iconRoot.visible
    }
    onSpinningChanged: if (!spinning) rotation = 0

    Image {
        id: iconSource
        anchors.fill: parent
        source: "../assets/icons/" + iconRoot.name + ".svg"
        sourceSize: Qt.size(iconRoot.size, iconRoot.size)
        smooth: true
        visible: false
    }
    ColorOverlay {
        anchors.fill: parent
        source: iconSource
        color: iconRoot.iconColor
    }
}
