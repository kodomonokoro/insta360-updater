import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: settingsRoot

    // Same palette as Main.qml — duplicated rather than shared via a
    // singleton for now (small, low-risk; worth factoring out to a
    // Theme.qml if a third screen ever needs it too).
    readonly property color panel: "#ffffff"
    readonly property color panelAlt: "#eef0f4"
    readonly property color border: "#dde1e8"
    readonly property color text: "#1a1c22"
    readonly property color textDim: "#6b7080"
    readonly property color ok: "#2fa66a"
    readonly property color fail: "#d3453f"

    readonly property int controlHeight: 34

    function authColor(ok) { return ok ? settingsRoot.ok : settingsRoot.fail }

    // Material's default TextField/Button both carry their own baked-in
    // minimum height via their `background` delegate's own implicitHeight
    // (measured: TextField's background=56, Button's=40) — a Math.max()
    // inside Material's control templates means overriding just
    // `implicitHeight` (or padding, which that same Math.max also factors
    // in) on the control itself can't shrink it below that floor. Supplying
    // a plain custom `background` sidesteps the floor entirely, which is
    // what these two do — used everywhere below instead of raw
    // TextField/Button so every field and button share one real height.
    component CompactTextField: TextField {
        id: control
        implicitHeight: settingsRoot.controlHeight
        verticalAlignment: Text.AlignVCenter
        padding: 8
        background: Rectangle {
            implicitHeight: settingsRoot.controlHeight
            radius: 4
            color: "#ffffff"
            border.color: settingsRoot.border
            border.width: 1
        }
        // Material's TextField renders `placeholderText` as an animated
        // "floating label" — it jumps above the field and turns
        // accent-blue on focus. That's Material Design form language,
        // but reads as broken on a plain single-line settings field
        // (reported: clicking raw/mp3 turned the hint blue and split it
        // onto its own line above an apparently-empty box). Routing the
        // hint through a plain static overlay label instead of the real
        // placeholderText property bypasses that animation entirely.
        property string hintText: ""
        placeholderText: ""
        Label {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: control.leftPadding
            anchors.rightMargin: control.rightPadding
            visible: control.text.length === 0 && control.hintText.length > 0
            text: control.hintText
            color: settingsRoot.textDim
            elide: Text.ElideMiddle
        }
    }
    component CompactButton: Button {
        implicitHeight: settingsRoot.controlHeight
        padding: 8
        topInset: 0
        bottomInset: 0
        leftInset: 0
        rightInset: 0
        // enabled gated first — same rule as Main.qml's FlatToolButton/
        // SquareDialogButton/start-stop buttons: a disabled button must
        // never visibly react to hover, since Control.hovered keeps
        // tracking the pointer regardless of enabled.
        background: Rectangle {
            implicitHeight: settingsRoot.controlHeight
            radius: 4
            color: !parent.enabled ? "#e4e7ed" : (parent.down ? "#d8dbe2" : (parent.hovered ? "#eef0f4" : "#e4e7ed"))
        }
    }
    component CompactComboBox: ComboBox {
        id: control
        implicitHeight: settingsRoot.controlHeight
        topInset: 0
        bottomInset: 0
        leftInset: 0
        rightInset: 0
        background: Rectangle {
            implicitHeight: settingsRoot.controlHeight
            radius: 4
            color: "#ffffff"
            border.color: settingsRoot.border
            border.width: 1
        }
        // Same root cause as the popup's own lopsided padding below:
        // Material's default contentItem/indicator size themselves off
        // Material's own assumed control height, not this control's
        // overridden implicitHeight, so the label/arrow sat visibly
        // off-center within it.
        contentItem: Label {
            text: control.displayText
            color: settingsRoot.text
            verticalAlignment: Text.AlignVCenter
            leftPadding: 12
            rightPadding: 30
            elide: Text.ElideRight
        }
        indicator: TablerIcon {
            x: control.width - width - 10
            anchors.verticalCenter: parent.verticalCenter
            name: "chevron-down"
            iconColor: settingsRoot.textDim
            size: 16
        }
        // Material's own default popup delegate is sized for a touch
        // target (tall rows, generous padding) — every other control in
        // this app is deliberately dense, so the dropdown looked oversized
        // next to it. Rows match the closed control's own controlHeight.
        delegate: ItemDelegate {
            width: control.width
            implicitHeight: settingsRoot.controlHeight
            highlighted: control.highlightedIndex === index
            contentItem: Label {
                // Plain-string models (公開範囲) have no textRole set, so
                // modelData itself is the text; object models (デバッグモード's
                // debugModeOptions) need textRole to pick which field.
                text: control.textRole ? modelData[control.textRole] : modelData
                color: settingsRoot.text
                verticalAlignment: Text.AlignVCenter
                leftPadding: 12
            }
            background: Rectangle {
                color: highlighted ? settingsRoot.panelAlt : "transparent"
            }
        }
        // Overriding just popup.topPadding/bottomPadding left a lopsided
        // gap under the last row — Material's own Popup reserves extra
        // bottom space for its drop-shadow elevation regardless, not
        // counted as plain padding. Owning the popup outright sizes it to
        // exactly the list's real content height, no hidden margin either
        // side.
        popup: Popup {
            // Opens upward instead when there isn't room below — this
            // ComboBox can sit right at the bottom of the scroll area
            // (the デバッグモード section is the last thing on the page),
            // where opening downward as usual would render the popup
            // partly or fully below the window and make it unreachable.
            y: {
                var win = control.Window.window
                if (!win) return control.height + 2
                var belowY = control.mapToItem(win.contentItem, 0, control.height).y
                return (belowY + implicitHeight > win.height) ? -implicitHeight - 2 : control.height + 2
            }
            width: control.width
            implicitHeight: comboList.contentHeight
            padding: 0
            background: Rectangle {
                radius: 4
                color: "#ffffff"
                border.color: settingsRoot.border
                border.width: 1
            }
            contentItem: ListView {
                id: comboList
                clip: true
                implicitHeight: contentHeight
                model: control.popup.visible ? control.delegateModel : null
                currentIndex: control.highlightedIndex
            }
        }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: 16

            // ---- フォルダ設定 ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Label { text: "フォルダ設定"; color: settingsRoot.text; font.bold: true; font.pixelSize: 14 }

                Label { text: "Insta360ファイルコピー先(raw) — カメラ取り込み時のみ必須"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        id: rawField
                        Layout.fillWidth: true
                        text: settingsBackend.rawFolder
                        // No fallback exists if left blank — required only
                        // for run modes that include ①コピー/②変換, checked
                        // at 開始-press time (config.validate_for_run).
                        onTextChanged: settingsBackend.rawFolder = text
                    }
                    CompactButton {
                        text: "参照..."
                        onClicked: rawFolderDialog.open()
                    }
                    CompactButton {
                        text: "フォルダ内を削除"
                        onClicked: settingsBackend.checkClearFolder("raw")
                    }
                }

                Label { text: "映像抽出先(MP4)"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        id: nasField
                        Layout.fillWidth: true
                        text: settingsBackend.nasFolder
                        onTextChanged: settingsBackend.nasFolder = text
                    }
                    CompactButton {
                        id: nasBrowseBtn
                        text: "参照..."
                        onClicked: nasFolderDialog.open()
                    }
                    CompactButton {
                        text: "フォルダ内を削除"
                        onClicked: settingsBackend.checkClearFolder("mp4")
                    }
                }

                Label { text: "音声抽出先(MP3) — 音声抽出・Driveアップロード実行時のみ必須"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        id: mp3Field
                        Layout.fillWidth: true
                        text: settingsBackend.mp3Folder
                        // No fallback exists if left blank — required only
                        // for run modes that include ③音声抽出/④Drive,
                        // checked at 開始-press time (config.validate_for_run).
                        onTextChanged: settingsBackend.mp3Folder = text
                    }
                    CompactButton {
                        text: "参照..."
                        onClicked: mp3FolderDialog.open()
                    }
                    CompactButton {
                        text: "フォルダ内を削除"
                        onClicked: settingsBackend.checkClearFolder("mp3")
                    }
                }

                Label { text: "ファイル保持日数(完了後この日数を過ぎたら次回起動時に削除の確認が表示されます)"; color: settingsRoot.textDim; font.pixelSize: 12 }
                CompactTextField {
                    Layout.preferredWidth: 100
                    text: String(settingsBackend.retentionDays)
                    validator: IntValidator { bottom: 1 }
                    onTextChanged: if (text.length) settingsBackend.retentionDays = parseInt(text)
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: settingsRoot.border }

            // ---- Insta360 SDK ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Label { text: "Insta360 SDK"; color: settingsRoot.text; font.bold: true; font.pixelSize: 14 }

                Label { text: "MediaSDKTest.exe — カメラ取り込み時のみ必須"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.sdkExePath
                        onTextChanged: settingsBackend.sdkExePath = text
                    }
                    CompactButton { text: "参照..."; onClicked: sdkExeDialog.open() }
                }

                Label { text: "モデルフォルダ — カメラ取り込み時のみ必須"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.sdkModelDir
                        onTextChanged: settingsBackend.sdkModelDir = text
                    }
                    CompactButton { text: "参照..."; onClicked: sdkModelDialog.open() }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: settingsRoot.border }

            // ---- 認証 ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Label { text: "認証"; color: settingsRoot.text; font.bold: true; font.pixelSize: 14 }
                RowLayout {
                    spacing: 12
                    CompactButton {
                        enabled: !settingsBackend.authBusy
                        onClicked: settingsBackend.authYoutube()
                        padding: 0
                        // A plain Item + anchors.centerIn, rather than
                        // trusting a bare RowLayout's implicit height to
                        // end up vertically centered by Material's own
                        // padding math — that left icon+label sitting low.
                        // The Item must repeat the RowLayout's own implicit
                        // size (Item doesn't inherit it automatically) —
                        // without that the button collapses to ~0 width
                        // since nothing else here constrains it.
                        contentItem: Item {
                            implicitWidth: ytAuthRow.implicitWidth
                            implicitHeight: ytAuthRow.implicitHeight
                            RowLayout {
                                id: ytAuthRow
                                anchors.centerIn: parent
                                spacing: 4
                                TablerIcon {
                                    name: settingsBackend.youtubeAuthOk ? "circle-check" : "circle-x"
                                    iconColor: settingsBackend.youtubeAuthOk ? "#16A34A" : "#DC2626"
                                    size: 16
                                }
                                Label { text: "YouTube認証"; color: settingsRoot.text }
                            }
                        }
                    }
                    CompactButton {
                        enabled: !settingsBackend.authBusy && settingsBackend.driveEnabled
                        onClicked: settingsBackend.authDrive()
                        padding: 0
                        contentItem: Item {
                            implicitWidth: driveAuthRow.implicitWidth
                            implicitHeight: driveAuthRow.implicitHeight
                            RowLayout {
                                id: driveAuthRow
                                anchors.centerIn: parent
                                spacing: 4
                                TablerIcon {
                                    name: settingsBackend.driveAuthOk ? "circle-check" : "circle-x"
                                    iconColor: settingsBackend.driveAuthOk ? "#16A34A" : "#DC2626"
                                    size: 16
                                }
                                Label { text: "Google Drive認証"; color: settingsRoot.text }
                            }
                        }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: settingsRoot.border }

            // ---- YouTube ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Label { text: "YouTube"; color: settingsRoot.text; font.bold: true; font.pixelSize: 14 }

                Label { text: "クライアントシークレット"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.ytSecretPath
                        onTextChanged: settingsBackend.ytSecretPath = text
                    }
                    CompactButton { text: "参照..."; onClicked: ytSecretDialog.open() }
                }

                Label { text: "トークンファイル"; color: settingsRoot.textDim; font.pixelSize: 12 }
                CompactTextField {
                    Layout.fillWidth: true
                    text: settingsBackend.ytTokenPath
                    onTextChanged: settingsBackend.ytTokenPath = text
                }

                Label { text: "タイトル接頭辞"; color: settingsRoot.textDim; font.pixelSize: 12 }
                CompactTextField {
                    Layout.fillWidth: true
                    text: settingsBackend.titlePrefix
                    onTextChanged: settingsBackend.titlePrefix = text
                }

                Label { text: "公開範囲"; color: settingsRoot.textDim; font.pixelSize: 12 }
                CompactComboBox {
                    Layout.preferredWidth: 200
                    model: settingsBackend.privacyOptions
                    currentIndex: model.indexOf(settingsBackend.privacyStatus)
                    onActivated: settingsBackend.privacyStatus = currentText
                }

                RowLayout {
                    spacing: 8
                    Label { text: "子ども向けとして設定"; color: settingsRoot.text }
                    Switch {
                        implicitHeight: settingsRoot.controlHeight
                        checked: settingsBackend.madeForKids
                        onToggled: settingsBackend.madeForKids = checked
                    }
                }

                Label { text: "再生リストID(任意)"; color: settingsRoot.textDim; font.pixelSize: 12 }
                CompactTextField {
                    Layout.fillWidth: true
                    text: settingsBackend.playlistId
                    onTextChanged: settingsBackend.playlistId = text
                }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: settingsRoot.border }

            // ---- Google Drive ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Label { text: "Google Drive"; color: settingsRoot.text; font.bold: true; font.pixelSize: 14 }
                RowLayout {
                    spacing: 8
                    Label { text: "GoogleドライブにMP3ファイルを格納する"; color: settingsRoot.text }
                    Switch {
                        implicitHeight: settingsRoot.controlHeight
                        checked: settingsBackend.driveEnabled
                        onToggled: settingsBackend.driveEnabled = checked
                    }
                }

                ColumnLayout {
                    visible: settingsBackend.driveEnabled
                    Layout.fillWidth: true
                    spacing: 6

                    Label { text: "クライアントシークレット"; color: settingsRoot.textDim; font.pixelSize: 12 }
                    RowLayout {
                        Layout.fillWidth: true
                        CompactTextField {
                            Layout.fillWidth: true
                            text: settingsBackend.driveSecretPath
                            onTextChanged: settingsBackend.driveSecretPath = text
                        }
                        CompactButton { text: "参照..."; onClicked: driveSecretDialog.open() }
                    }

                    Label { text: "トークンファイル"; color: settingsRoot.textDim; font.pixelSize: 12 }
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.driveTokenPath
                        onTextChanged: settingsBackend.driveTokenPath = text
                    }

                    Label { text: "フォルダID"; color: settingsRoot.textDim; font.pixelSize: 12 }
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.driveFolderId
                        onTextChanged: settingsBackend.driveFolderId = text
                    }

                    Label { text: "サブフォルダ接頭辞(任意)"; color: settingsRoot.textDim; font.pixelSize: 12 }
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.driveSubfolderPrefix
                        onTextChanged: settingsBackend.driveSubfolderPrefix = text
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                CompactButton { text: "保存"; onClicked: settingsBackend.save() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: settingsRoot.border }

            // ---- デバッグモード (メイン画面のログ欄と同じく、既定で折りたたみ) ----
            // Lives on `backend` (PipelineModel), not `settingsBackend` —
            // it drives the main screen's mode label, not anything saved
            // to settings.local.json. Deliberately session-only: every
            // debug flag always starts false on a fresh launch, so a
            // debug-only run mode can never linger silently selected.
            ColumnLayout {
                id: debugSection
                Layout.fillWidth: true
                spacing: 6
                property bool expanded: false
                // One dropdown, one explicit flag combination per entry
                // (not "set one flag, leave the rest alone") — no way to
                // land on a combination nothing here intends. "通常" is
                // every flag false — the everyday mode, purely derived from
                // the "GoogleドライブにMP3ファイルを格納する" toggle above
                // (see Main.qml's currentModeLabel) rather than a fixed
                // preset of its own.
                readonly property var debugModeOptions: [
                    { label: "通常",
                      skipIntake: false, stopAfterStitch: false, skipAudioDrive: false, skipYoutube: false },
                    { label: "デバッグ：動画取り込み ①②",
                      skipIntake: false, stopAfterStitch: true, skipAudioDrive: false, skipYoutube: false },
                    { label: "デバッグ：YouTube取り込み ⑤",
                      skipIntake: true, stopAfterStitch: false, skipAudioDrive: true, skipYoutube: false },
                    { label: "デバッグ：音声出力 ③④",
                      skipIntake: true, stopAfterStitch: false, skipAudioDrive: false, skipYoutube: true },
                ]

                RowLayout {
                    spacing: 4
                    MouseArea {
                        implicitWidth: debugHeaderRow.implicitWidth
                        implicitHeight: debugHeaderRow.implicitHeight
                        cursorShape: Qt.PointingHandCursor
                        onClicked: debugSection.expanded = !debugSection.expanded
                        RowLayout {
                            id: debugHeaderRow
                            spacing: 4
                            TablerIcon {
                                name: debugSection.expanded ? "chevron-down" : "chevron-right"
                                iconColor: "#111827"
                                size: 16
                            }
                            Label { text: "デバッグモード"; color: settingsRoot.text; font.bold: true; font.pixelSize: 14 }
                        }
                    }
                }

                ColumnLayout {
                    visible: debugSection.expanded
                    Layout.fillWidth: true
                    spacing: 8

                    Label {
                        text: "デバッグモード選択"
                        color: settingsRoot.textDim
                        font.pixelSize: 12
                    }
                    CompactComboBox {
                        Layout.preferredWidth: 260
                        model: debugSection.debugModeOptions
                        textRole: "label"
                        // Matched against backend's own flags (not tracked
                        // locally) so this always reflects the true source
                        // of truth even when it changes from elsewhere.
                        // Always lands on a real entry — "通常" is every
                        // flag false, same as the other 3 presets, so there
                        // is no blank/unmatched state to fall back on.
                        currentIndex: {
                            const modes = debugSection.debugModeOptions
                            for (let i = 0; i < modes.length; i++) {
                                const m = modes[i]
                                if (m.skipIntake === backend.skipIntake && m.stopAfterStitch === backend.stopAfterStitch
                                    && m.skipAudioDrive === backend.skipAudioDrive && m.skipYoutube === backend.skipYoutube) {
                                    return i
                                }
                            }
                            return 0
                        }
                        onActivated: {
                            const m = debugSection.debugModeOptions[currentIndex]
                            backend.skipIntake = m.skipIntake
                            backend.stopAfterStitch = m.stopAfterStitch
                            backend.skipAudioDrive = m.skipAudioDrive
                            backend.skipYoutube = m.skipYoutube
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 20 }
        }
    }

    // ---- file/folder pickers ----
    FolderDialog {
        id: nasFolderDialog
        title: "監視フォルダを選択"
        onAccepted: settingsBackend.nasFolder = String(selectedFolder).replace("file:///", "")
    }
    FolderDialog {
        id: rawFolderDialog
        title: "カメラ生ファイルのコピー先を選択"
        onAccepted: settingsBackend.rawFolder = String(selectedFolder).replace("file:///", "")
    }
    FolderDialog {
        id: mp3FolderDialog
        title: "音声抽出先を選択"
        onAccepted: settingsBackend.mp3Folder = String(selectedFolder).replace("file:///", "")
    }
    FileDialog {
        id: ytSecretDialog
        title: "YouTubeクライアントシークレットを選択"
        nameFilters: ["JSON files (*.json)"]
        onAccepted: settingsBackend.ytSecretPath = String(selectedFile).replace("file:///", "")
    }
    FileDialog {
        id: driveSecretDialog
        title: "Google Driveクライアントシークレットを選択"
        nameFilters: ["JSON files (*.json)"]
        onAccepted: settingsBackend.driveSecretPath = String(selectedFile).replace("file:///", "")
    }
    FileDialog {
        id: sdkExeDialog
        title: "MediaSDKTest.exeを選択"
        nameFilters: ["Executable (*.exe)"]
        onAccepted: settingsBackend.sdkExePath = String(selectedFile).replace("file:///", "")
    }
    FolderDialog {
        id: sdkModelDialog
        title: "モデルフォルダを選択"
        onAccepted: settingsBackend.sdkModelDir = String(selectedFolder).replace("file:///", "")
    }

    // Save/auth confirmation and cleanup-confirmation dialogs live in
    // Main.qml, not here — settingsBackend.checkStaleClips() fires once at
    // app startup (Main.qml, before the user has necessarily ever opened
    // this screen), so the dialogs that respond to its signals need to
    // exist regardless of whether this Loader-loaded screen is active.
}
