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
        background: Rectangle {
            implicitHeight: settingsRoot.controlHeight
            radius: 4
            color: parent.down ? "#d8dbe2" : (parent.hovered ? "#eef0f4" : "#e4e7ed")
        }
    }
    component CompactComboBox: ComboBox {
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
                        text: "フォルダ内をクリア"
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
                        text: "フォルダ内をクリア"
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
                        text: "フォルダ内をクリア"
                        onClicked: settingsBackend.checkClearFolder("mp3")
                    }
                }

                Label { text: "ファイル保持日数(完了後この日数を過ぎたら次回起動時に削除)"; color: settingsRoot.textDim; font.pixelSize: 12 }
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

                Label { text: "MediaSDKTest.exe"; color: settingsRoot.textDim; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true
                    CompactTextField {
                        Layout.fillWidth: true
                        text: settingsBackend.sdkExePath
                        onTextChanged: settingsBackend.sdkExePath = text
                    }
                    CompactButton { text: "参照..."; onClicked: sdkExeDialog.open() }
                }

                Label { text: "モデルフォルダ"; color: settingsRoot.textDim; font.pixelSize: 12 }
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
