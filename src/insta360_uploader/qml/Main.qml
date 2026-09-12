import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: root
    visible: true
    width: 1330
    height: 760
    title: "Insta360 Updater"
    color: "#f5f6f8"

    Material.theme: Material.Light
    Material.accent: "#3b6fed"
    Material.background: "#f5f6f8"
    Material.foreground: "#1a1c22"

    // ---- light palette ----
    readonly property color bg: "#f5f6f8"
    readonly property color panel: "#ffffff"
    readonly property color panelAlt: "#eef0f4"
    readonly property color border: "#dde1e8"
    readonly property color text: "#1a1c22"
    readonly property color textDim: "#6b7080"
    readonly property color accent: "#3b6fed"
    readonly property color ok: "#2fa66a"
    readonly property color pending: "#aab0bb"
    readonly property color warn: "#c98a1f"
    readonly property color fail: "#d3453f"

    // File table column layout — checkbox/name/duration/resolution are
    // fixed-width (their content has a natural, roughly-fixed size), and
    // the 5 stage columns are Layout.fillWidth so they share whatever
    // width is actually left over. Declared on `root` (not the table's own
    // Rectangle) and always referenced as `root.xxx` below — bare
    // (unqualified) references to a non-root ancestor's custom properties
    // do not resolve inside Repeater/ListView delegate components in this
    // Qt/PySide6 version (confirmed via QQmlApplicationEngine.warnings:
    // "ReferenceError: ... is not defined" from every delegate that
    // referenced one unqualified) — root-qualifying everywhere sidesteps
    // that scoping gap entirely.
    //
    // This replaces an earlier version that hardcoded every column's exact
    // pixel width and derived a total table width from that sum — which
    // had to be hand-tuned against one specific window width and broke
    // (columns running past the panel's right edge) every time a column
    // was added or the window was resized. Making the header/body Rows
    // themselves Layout.fillWidth and only the stage columns
    // Layout.fillWidth *within* that means the table always exactly
    // matches its container's real width, at any window size, with no
    // separate width sum to keep in sync — the recurring bug's actual
    // root cause. A real Qt TableView + HorizontalHeaderView pair exists
    // and would handle this natively too, but wants a proper
    // row/column-shaped model behind it — worth it if this ever needs to
    // scale past a hand-rolled table; the production Flet app's own table
    // is hand-rolled for the same per-column-width-control reason.
    readonly property int checkboxColWidth: 36
    readonly property int nameColWidth: 220
    readonly property int durationColWidth: 55
    readonly property int resolutionColWidth: 130
    // Body cells here are a single small icon, not a text badge, so this
    // only needs to comfortably fit the *header* label wrapped to 2 lines —
    // narrower than an actual badge would need.
    readonly property int stageColMinWidth: 62
    readonly property var colHeaders: ["コピー", "変換", "音声抽出", "Drive\nアップロード", "YouTube\nアップロード"]
    readonly property int tableRowSpacing: 8
    // Below this, the table can no longer show every column at a readable
    // width — it switches from "stretch columns to fill the panel" to "fix
    // every column at its minimum and let the panel scroll horizontally"
    // (see the ScrollView wrapping headerRow/ListView below), rather than
    // letting columns run past the panel's edge.
    readonly property int minimumTableWidth: {
        const fixedCols = checkboxColWidth + nameColWidth + durationColWidth + resolutionColWidth
        const stageCols = colHeaders.length * stageColMinWidth
        const gapCount = 3 + colHeaders.length // checkbox+name+duration+resolution+stages = 4+N items = 3+N gaps
        return fixedCols + stageCols + gapCount * tableRowSpacing
    }

    // Tabler Icons state-color spec: base #111827, processing #2563EB,
    // done #16A34A, error #DC2626, idle/skipped #9CA3AF/#6B7280.
    function stageIconColor(status) {
        if (status === "unknown") return "#c98a1f"
        if (status === "checking") return "#6b7080"
        if (status === "done") return "#16A34A"
        if (status === "current") return "#2563EB"
        if (status === "failed") return "#DC2626"
        if (status === "partial") return "#c98a1f"
        if (status === "skipped") return "#6B7280"
        if (status === "excluded") return "#C7CBD1"
        return "#9CA3AF" // pending
    }
    function stageIconName(status) {
        if (status === "checking") return "refresh"
        if (status === "unknown") return "circle-x"
        if (status === "unconfigured") return "player-skip-forward"
        if (status === "done") return "circle-check"
        if (status === "current") return "loader-2"
        if (status === "failed") return "circle-x"
        if (status === "partial") return "circle"
        if (status === "skipped") return "player-skip-forward"
        return "circle"
    }

    function taskStateText(state) {
        return ({pending: "実行前", current: "仕掛中", done: "完了", failed: "失敗", skipped: "スキップ"})[state] || state
    }
    function skipReasonText(reason) {
        return ({exists: "現物が存在するため", mode: "今回の実行対象外", dependency: "前の工程が失敗したため", worker_error: "処理を継続できなかったため", cancelled: "停止操作により中断されたため"})[reason] || reason
    }

    property bool showSettings: false

    // Square hover/press highlight (radius 4, matching the settings
    // screen's CompactButton) shared by every plain icon/text ToolButton —
    // the round shape stays specific to the start/stop buttons only.
    component FlatToolButton: ToolButton {
        topInset: 0
        bottomInset: 0
        leftInset: 0
        rightInset: 0
        background: Rectangle {
            radius: 4
            color: parent.down ? "#d8dbe2" : (parent.hovered ? "#eef0f4" : "transparent")
        }
    }

    // Same squared-off language as the settings screen's CompactButton —
    // used for dialog buttons (OK/はい/いいえ), deliberately NOT round like
    // the main screen's start/stop buttons.
    component SquareDialogButton: Button {
        implicitHeight: 34
        padding: 8
        topInset: 0
        bottomInset: 0
        leftInset: 0
        rightInset: 0
        background: Rectangle {
            radius: 4
            color: parent.down ? "#d8dbe2" : (parent.hovered ? "#eef0f4" : "#e4e7ed")
        }
    }

    // Corners a little squarer than Material's own (large) default dialog
    // radius, but still rounded — matches the rest of the app's panel
    // language (Rectangle radius:8 elsewhere) rather than fully sharp.
    component CompactDialog: Dialog {
        modal: true
        anchors.centerIn: parent
        padding: 20
        background: Rectangle {
            radius: 8
            color: root.panel
            border.color: root.border
        }
    }

    // Explicit padding matching CompactDialog's own 20px content inset —
    // DialogButtonBox's own default padding is sized for Material's larger
    // standard buttons and looked mismatched (a big gap above a visibly
    // off-center button) once SquareDialogButton replaced them.
    component CompactDialogFooter: DialogButtonBox {
        padding: 0
        topPadding: 12
        bottomPadding: 20
        leftPadding: 20
        rightPadding: 20
        spacing: 8
        background: Rectangle { color: "transparent" }
    }

    // ---- settings screen (separate top-level page, swapped by visibility
    // rather than a full StackView — only 2 screens exist, doesn't need
    // navigation history/transitions) ----
    Item {
        anchors.fill: parent
        visible: root.showSettings
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                FlatToolButton {
                    onClicked: root.showSettings = false
                    contentItem: RowLayout {
                        spacing: 4
                        TablerIcon { name: "arrow-left"; iconColor: "#111827"; size: 18 }
                        Label { text: "戻る"; color: root.text }
                    }
                }
                Label { text: "設定"; color: root.text; font.pixelSize: 20; font.bold: true }
            }
            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                active: root.showSettings
                source: "SettingsScreen.qml"
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        // Top gets extra margin to visually balance the header row: the
        // gap below it is inflated by this ColumnLayout's own spacing
        // (12) plus the file panel's internal top margin (12) stacking
        // on top of the row's vertical-center slack, while above the row
        // there's only this margin — without the +8, the title logo reads
        // as pinned toward the top of its row instead of centered.
        anchors.topMargin: 24
        spacing: 12
        visible: !root.showSettings

        // ---- top: title + stage stepper + run-mode toggles, all in one
        // band (title left, stepper centered, mode toggles + settings
        // right) rather than stacked as separate rows ----
        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            Image {
                source: "../assets/title.png"
                fillMode: Image.PreserveAspectFit
                Layout.preferredHeight: 56
                Layout.preferredWidth: sourceSize.width * (56 / sourceSize.height)
                Layout.alignment: Qt.AlignVCenter
                smooth: true
                mipmap: true
            }

            Item { Layout.fillWidth: true }

            Row {
                Layout.alignment: Qt.AlignVCenter
                spacing: 0
                Repeater {
                    model: backend.stageNames
                    delegate: Row {
                        spacing: 0
                        property string runState: backend.stageRunStates[index]
                        property bool isSkipped: runState === "skipped"
                        // Driven by real per-stage completion (every
                        // selected row actually finished this stage), not
                        // just "currentStage moved past this index" — that
                        // alone can't tell a genuine completion from a
                        // stage everything failed at. Both also require
                        // `running` so the whole stepper goes back to a
                        // neutral/idle look — matching the right panel's
                        // own reset to "待機中" — instead of freezing on
                        // the last run's result once it's actually stopped.
                        property bool isDone: runState === "done"
                        property bool isCurrent: runState === "current"
                        property bool isFailed: runState === "failed"
                        property bool isPartial: runState === "partial"
                        // Distinct from isSkipped: this stage isn't part of
                        // the *selected run mode* at all (e.g. "①②のみ実施"
                        // on stages 3-5), shown before any run even starts —
                        // isSkipped instead means a real run actually
                        // decided, per clip, not to do it.
                        property bool isExcluded: runState === "excluded"

                        // Fixed-width slot per step (circle centered above,
                        // label centered below) so uneven Japanese label
                        // lengths never push the circles' spacing around —
                        // only the connecting line's length is elastic.
                        Column {
                            id: stepCol
                            width: 96
                            spacing: 6
                            property int stageDone: backend.stageCompletedCounts.length > index ? backend.stageCompletedCounts[index] : 0
                            property int stageTotal: backend.totalCount
                            property real stageFraction: backend.stageFractions[index]

                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: 34; height: 34; radius: 17
                                color: isFailed ? root.fail : (isSkipped ? "transparent" : (isPartial ? root.warn : (isCurrent ? root.accent : (isDone ? root.ok : root.pending))))
                                border.color: isCurrent ? root.accent : root.border
                                border.width: isSkipped ? 1 : (isCurrent ? 2 : 1)

                                TablerIcon {
                                    anchors.centerIn: parent
                                    visible: isDone
                                    name: "circle-check"
                                    iconColor: "#ffffff"
                                }
                                TablerIcon {
                                    anchors.centerIn: parent
                                    visible: isCurrent || isFailed || isPartial
                                    name: isCurrent ? "loader-2" : (isFailed ? "circle-x" : "circle")
                                    spinning: isCurrent
                                    iconColor: "#ffffff"
                                }
                                TablerIcon {
                                    anchors.centerIn: parent
                                    visible: isSkipped
                                    name: "player-skip-forward"
                                    iconColor: root.textDim
                                    size: 16
                                }
                                Label {
                                    anchors.centerIn: parent
                                    visible: isExcluded
                                    text: "―"
                                    color: "white"
                                    font.bold: true
                                    font.pixelSize: 13
                                    font.weight: Font.Black
                                }
                                Label {
                                    anchors.centerIn: parent
                                    visible: !isDone && !isSkipped && !isCurrent && !isFailed && !isPartial && !isExcluded
                                    text: String(index + 1)
                                    color: "white"
                                    font.bold: true
                                    font.pixelSize: 13
                                    font.weight: Font.Black
                                }
                            }
                            Label {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                text: modelData
                                color: (isSkipped || isExcluded) ? root.textDim : (isCurrent ? root.text : root.textDim)
                                font.bold: isCurrent
                                font.pixelSize: 12
                            }
                            Label {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                // Hidden once idle too — same reset-to-
                                // neutral reasoning as isDone/isCurrent
                                // above.
                                visible: !isSkipped && backend.hasRun
                                text: parent.stageDone + " / " + parent.stageTotal
                                color: root.textDim
                                font.pixelSize: 11
                            }
                        }
                        // The progress bar lives *between* consecutive
                        // circles (not floating under each one) — its fill
                        // is how many rows have finished this circle's
                        // stage and are on their way to the next.
                        Rectangle {
                            visible: index < backend.stageNames.length - 1
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.verticalCenterOffset: -21
                            width: 40; height: 4; radius: 2
                            color: root.panelAlt
                            Rectangle {
                                height: parent.height
                                radius: 2
                                // Only fills while running — once idle the
                                // whole stepper goes back to neutral rather
                                // than freezing on the last run's result.
                                width: backend.hasRun
                                       ? parent.width * Math.min(1, Math.max(0, stepCol.stageFraction)) : 0
                                // Blue while filling, green once this
                                // segment itself reaches 100% — tied to the
                                // bar's own fraction rather than the
                                // separately-tracked currentStage, so the
                                // color always matches what's actually
                                // filled in.
                                color: isFailed ? root.fail : (isSkipped ? root.pending : (isPartial ? root.warn : (isDone ? root.ok : root.accent)))
                            }
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true }

            ColumnLayout {
                Layout.alignment: Qt.AlignVCenter
                spacing: 4

                ComboBox {
                    id: runModeCombo
                    Layout.alignment: Qt.AlignRight
                    Layout.preferredWidth: 160
                    implicitHeight: 34
                    topInset: 0
                    bottomInset: 0
                    leftInset: 0
                    rightInset: 0
                    enabled: !backend.running
                    model: ["全行程実施", "①②⑤のみ実施", "①②のみ実施", "③④⑤のみ実施"]
                    // Index derives from backend state (not tracked locally)
                    // so it always reflects the true source of truth even if
                    // that state changes from elsewhere.
                    currentIndex: backend.skipAudioDrive ? 1 : (backend.stopAfterStitch ? 2 : (backend.skipIntake ? 3 : 0))
                    background: Rectangle {
                        implicitHeight: 34
                        radius: 4
                        color: "#ffffff"
                        border.color: root.border
                        border.width: 1
                    }
                    onActivated: {
                        backend.skipAudioDrive = (currentIndex === 1)
                        backend.stopAfterStitch = (currentIndex === 2)
                        backend.skipIntake = (currentIndex === 3)
                    }
                }
            }
        }

        // ---- camera-safe banner: inline, dismissible, never modal ----
        Rectangle {
            Layout.fillWidth: true
            visible: backend.cameraBanner.length > 0
            height: visible ? 40 : 0
            radius: 6
            color: "#e6f4ea"
            border.color: root.ok
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                TablerIcon { name: "circle-check"; iconColor: "#16A34A"; Layout.alignment: Qt.AlignVCenter }
                Label {
                    text: backend.cameraBanner
                    color: root.ok
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                ToolButton {
                    Layout.alignment: Qt.AlignVCenter
                    topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
                    padding: 4
                    // Material's default ToolButton background carries its own
                    // baked-in minimum width (touch-target sizing) even after
                    // insets/padding are zeroed, which left more space to the
                    // right of the glyph than the left. A plain background
                    // has no implicit size of its own, so implicitWidth
                    // collapses to a tight fit around contentItem + padding.
                    background: Rectangle { color: "transparent" }
                    contentItem: TablerIcon { name: "x"; iconColor: "#111827"; size: 16 }
                    onClicked: backend.dismiss_camera_banner()
                }
            }
        }

        // ---- middle: file table (left) + current-stage panel (right) ----
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            // left: file table
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: root.panel
                radius: 8
                border.color: root.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Label {
                            text: backend.skipIntake ? "ファイル一覧(MP4)" : "ファイル一覧(Insta360動画ファイル)"
                            color: root.text
                            font.bold: true
                        }
                        FlatToolButton {
                            enabled: !backend.running
                            onClicked: backend.refresh()
                            contentItem: RowLayout {
                                spacing: 4
                                TablerIcon { name: "refresh"; iconColor: "#111827"; size: 16 }
                                Label { text: "再読み込み"; color: root.text }
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Label { text: backend.totalCount + " / " + backend.rowsData.length + " 件選択"; color: root.textDim }
                    }

                    // Header is a non-interactive Flickable whose contentX
                    // mirrors the list's — it never scrolls on its own, it
                    // just visually tracks whatever the list below is doing,
                    // so the two stay aligned column-for-column.
                    Flickable {
                        id: headerFlick
                        Layout.fillWidth: true
                        Layout.preferredHeight: headerRow.implicitHeight
                        interactive: false
                        clip: true
                        contentWidth: Math.max(width, root.minimumTableWidth)
                        contentX: fileListView.contentX

                        RowLayout {
                            id: headerRow
                            width: headerFlick.contentWidth
                            spacing: root.tableRowSpacing
                            CheckBox {
                                Layout.preferredWidth: root.checkboxColWidth
                                checked: backend.allSelected
                                enabled: !backend.running
                                onToggled: backend.select_all(checked)
                            }
                            Label { text: "ファイル名"; color: root.textDim; Layout.preferredWidth: root.nameColWidth; font.pixelSize: 12 }
                            Label { text: "長さ"; color: root.textDim; Layout.preferredWidth: root.durationColWidth; font.pixelSize: 12 }
                            Label { text: "解像度"; color: root.textDim; Layout.preferredWidth: root.resolutionColWidth; font.pixelSize: 12 }
                            Repeater {
                                model: root.colHeaders
                                delegate: Label {
                                    text: modelData
                                    color: root.textDim
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: root.stageColMinWidth
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: root.border }

                    ListView {
                        id: fileListView
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: backend.rowsData
                        contentWidth: Math.max(width, root.minimumTableWidth)
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            id: fileRowDelegate
                            property var stageReasons: modelData.reasons
                            width: fileListView.contentWidth
                            height: 36
                            color: index % 2 === 0 ? "transparent" : "#08000000"

                            RowLayout {
                                // No leftMargin/rightMargin here — headerRow
                                // (in headerFlick) has none either, and any
                                // asymmetry between the two was exactly what
                                // put the checkbox column out of vertical
                                // alignment with the header above it.
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.right: parent.right
                                spacing: root.tableRowSpacing
                                CheckBox {
                                    Layout.preferredWidth: root.checkboxColWidth
                                    checked: modelData.selected
                                    enabled: !backend.running
                                    onToggled: backend.toggle_row_selected(index, checked)
                                }
                                Label { text: modelData.name; color: root.text; Layout.preferredWidth: root.nameColWidth; elide: Text.ElideMiddle }
                                Label { text: modelData.duration; color: root.textDim; Layout.preferredWidth: root.durationColWidth }
                                Label { text: modelData.resolution; color: root.textDim; Layout.preferredWidth: root.resolutionColWidth }
                                Repeater {
                                    model: modelData.stages
                                    delegate: Item {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: root.stageColMinWidth
                                        implicitHeight: 24
                                        HoverHandler { id: statusHover }
                                        // Only failed/skipped get a tooltip — those two carry a
                                        // *reason* the icon alone can't show; every other state
                                        // (done/pending/current/...) is already fully conveyed by
                                        // the icon itself, so a tooltip there was just noise.
                                        // Custom-styled (white panel, close to the icon) rather
                                        // than Qt's default dark/far-offset tooltip — matches the
                                        // header checkboxes' own tooltip treatment.
                                        ToolTip {
                                            visible: statusHover.hovered && (modelData === "skipped" || modelData === "failed" || modelData === "excluded")
                                            x: 0
                                            y: parent.height + 4
                                            delay: 200
                                            padding: 8
                                            background: Rectangle {
                                                color: root.panel
                                                border.color: root.border
                                                border.width: 1
                                                radius: 6
                                            }
                                            contentItem: Label {
                                                text: modelData === "failed"
                                                      ? "失敗：" + root.skipReasonText(fileRowDelegate.stageReasons[index])
                                                      : "スキップ：" + root.skipReasonText(fileRowDelegate.stageReasons[index])
                                                color: root.text
                                                wrapMode: Text.WordWrap
                                                width: 220
                                            }
                                        }
                                        Label {
                                            anchors.centerIn: parent
                                            visible: modelData === "excluded"
                                            text: "―"
                                            color: root.stageIconColor(modelData)
                                            font.pixelSize: 16
                                            font.bold: true
                                        }
                                        TablerIcon {
                                            anchors.centerIn: parent
                                            visible: modelData !== "excluded"
                                            name: root.stageIconName(modelData)
                                            iconColor: root.stageIconColor(modelData)
                                            spinning: modelData === "current"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // right: current-stage panel
            Rectangle {
                Layout.preferredWidth: 300
                Layout.fillHeight: true
                color: root.panel
                radius: 8
                border.color: root.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 14

                    Label { text: "現在の工程"; color: root.textDim; font.pixelSize: 12 }
                    Label {
                        text: backend.currentStage >= 0 ? backend.stageNames[backend.currentStage] : "待機中"
                        color: root.text
                        font.pixelSize: 20
                        font.bold: true
                    }
                    Label {
                        visible: backend.hasRun
                        text: root.taskStateText(backend.taskState)
                        color: root.stageIconColor(backend.taskState)
                        font.bold: true
                    }
                    Label {
                        visible: backend.taskReason.length > 0
                        text: root.skipReasonText(backend.taskReason)
                        color: root.textDim
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    ColumnLayout {
                        spacing: 4
                        // The current *file's* progress through its current
                        // operation (this one copy, this one upload, ...) —
                        // not a batch-wide count, so it actually moves
                        // smoothly while one file is mid-transfer.
                        Label { text: "工程進捗"; color: root.textDim; font.pixelSize: 12 }
                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0; to: 1
                            value: backend.currentFileFraction
                        }
                        Label {
                            text: Math.round(backend.currentFileFraction * 100) + "%"
                            color: root.text
                        }
                    }

                    ColumnLayout {
                        spacing: 2
                        // Same count shown under the current stage's circle
                        // in the stepper above — "how many selected files
                        // have finished *this* stage".
                        Label {
                            text: "この工程の終了件数（失敗・スキップ含む）"
                            color: root.textDim
                            font.pixelSize: 12
                        }
                        Label {
                            text: (backend.currentStage >= 0 && backend.stageCompletedCounts.length > backend.currentStage
                                   ? backend.stageCompletedCounts[backend.currentStage] : 0) + " / " + backend.totalCount
                            color: root.text
                            font.pixelSize: 18
                            font.bold: true
                        }
                    }

                    ColumnLayout {
                        spacing: 4
                        Label { text: "対象タスク"; color: root.textDim; font.pixelSize: 12 }
                        Label {
                            text: backend.currentTask.length ? backend.currentTask : "—"
                            color: root.text
                            // Wrap at word boundaries where possible, but
                            // break mid-word when a single token (e.g. a
                            // long filename with no spaces) is wider than
                            // the panel — Text.WordWrap alone can't break
                            // those and overflows instead.
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }

                    Item { Layout.fillHeight: true }

                    // Relocated from the top header band — full-width so
                    // it reads as this panel's own entry point rather than
                    // competing with 開始/停止 for attention, and disabled
                    // while running (can't touch settings mid-run, same as
                    // 開始 — only 停止 stays enabled then).
                    Button {
                        id: settingsButton
                        Layout.fillWidth: true
                        implicitHeight: 34
                        enabled: !backend.running
                        // On the whole button, not just background — icon
                        // + label were staying full-opacity while disabled,
                        // so the button read as clickable even though it
                        // wasn't.
                        opacity: enabled ? 1.0 : 0.5
                        onClicked: root.showSettings = true
                        padding: 0
                        topInset: 0
                        bottomInset: 0
                        leftInset: 0
                        rightInset: 0
                        background: Rectangle {
                            radius: 4
                            color: settingsButton.down ? "#d8dbe2" : (settingsButton.hovered ? "#eef0f4" : "#e4e7ed")
                        }
                        // A plain Item filling the full button + anchors.
                        // centerIn, rather than trusting RowLayout's own
                        // implicit (content-hugging) height to end up
                        // centered by Material's padding math — that left
                        // icon+label sitting low, not vertically centered.
                        contentItem: Item {
                            implicitWidth: settingsRow.implicitWidth
                            implicitHeight: settingsRow.implicitHeight
                            RowLayout {
                                id: settingsRow
                                anchors.centerIn: parent
                                spacing: 4
                                TablerIcon { name: "settings"; iconColor: "#111827"; size: 18 }
                                Label { text: "設定"; color: root.text }
                            }
                        }
                    }

                    RowLayout {
                        id: startStopRow
                        Layout.fillWidth: true
                        spacing: 8
                        // Square (matches every other button in the app)
                        // and colored as the primary action — 停止 stays
                        // neutral since it's the secondary/rare action.
                        // Roughly a 2:1 split: 停止 gets a fixed width, 開始
                        // fills whatever remains. (An earlier attempt bound
                        // both to fractions of startStopRow's own width —
                        // a self-referential binding loop that Qt resolved
                        // to the wrong, near-equal sizes instead of 2:1.)
                        Button {
                            id: startButton
                            Layout.fillWidth: true
                            implicitHeight: 40
                            enabled: !backend.running
                            onClicked: backend.start()
                            padding: 0
                            topInset: 0
                            bottomInset: 0
                            leftInset: 0
                            rightInset: 0
                            background: Rectangle {
                                radius: 4
                                color: !startButton.enabled
                                       ? "#9fb4ee"
                                       : (startButton.down ? Qt.darker(root.accent, 1.3) : (startButton.hovered ? Qt.darker(root.accent, 1.1) : root.accent))
                            }
                            contentItem: Item {
                                implicitWidth: startRow.implicitWidth
                                implicitHeight: startRow.implicitHeight
                                RowLayout {
                                    id: startRow
                                    anchors.centerIn: parent
                                    spacing: 4
                                    TablerIcon { name: "player-play"; iconColor: "#ffffff"; size: 18 }
                                    Label { text: "開始"; color: "#ffffff"; font.bold: true }
                                }
                            }
                        }
                        Button {
                            id: stopButton
                            Layout.preferredWidth: 90
                            implicitHeight: 40
                            enabled: backend.running
                            opacity: enabled ? 1.0 : 0.5
                            onClicked: stopConfirmDialog.open()
                            padding: 0
                            topInset: 0
                            bottomInset: 0
                            leftInset: 0
                            rightInset: 0
                            background: Rectangle {
                                radius: 4
                                color: stopButton.down ? "#d8dbe2" : (stopButton.hovered ? "#eef0f4" : "#e4e7ed")
                            }
                            contentItem: Item {
                                implicitWidth: stopRow.implicitWidth
                                implicitHeight: stopRow.implicitHeight
                                RowLayout {
                                    id: stopRow
                                    anchors.centerIn: parent
                                    spacing: 4
                                    TablerIcon { name: "square"; iconColor: "#111827"; size: 18 }
                                    Label { text: "停止"; color: root.text }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- bottom: collapsible log ----
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                FlatToolButton {
                    onClicked: logArea.visible = !logArea.visible
                    contentItem: RowLayout {
                        spacing: 4
                        TablerIcon {
                            name: logArea.visible ? "chevron-down" : "chevron-right"
                            iconColor: "#111827"
                            size: 16
                        }
                        Label { text: "ログ"; color: root.text }
                    }
                }
            }

            Rectangle {
                id: logArea
                visible: false
                Layout.fillWidth: true
                Layout.preferredHeight: 160
                color: root.panelAlt
                radius: 6
                border.color: root.border

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 8
                    TextArea {
                        readOnly: true
                        text: backend.logText
                        color: root.text
                        font.family: "Consolas"
                        font.pixelSize: 12
                        wrapMode: TextArea.NoWrap
                        background: null
                    }
                }
            }
        }
    }

    CompactDialog {
        id: batchFinishedDialog
        title: "完了"
        property string messageText: ""
        Label { text: batchFinishedDialog.messageText }
        footer: CompactDialogFooter {
            SquareDialogButton { text: "OK"; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
    }
    CompactDialog {
        id: startBlockedDialog
        title: "実行できません"
        property string messageText: ""
        Label {
            text: startBlockedDialog.messageText
            wrapMode: Text.WordWrap
            width: 280
        }
        footer: CompactDialogFooter {
            SquareDialogButton { text: "OK"; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
    }
    Connections {
        target: backend
        function onBatchFinished(message) {
            batchFinishedDialog.messageText = message
            batchFinishedDialog.open()
        }
        function onStartBlocked(message) {
            startBlockedDialog.messageText = message
            startBlockedDialog.open()
        }
    }

    CompactDialog {
        id: stopConfirmDialog
        title: "処理を停止しますか?"
        onAccepted: backend.stop()

        Label {
            text: "現在実行中の処理を停止します。よろしいですか?\n(実行中のファイルは、現在の工程が終わるまで停止しません)"
        }
        footer: CompactDialogFooter {
            SquareDialogButton { text: "いいえ"; DialogButtonBox.buttonRole: DialogButtonBox.NoRole }
            SquareDialogButton { text: "はい"; DialogButtonBox.buttonRole: DialogButtonBox.YesRole }
        }
    }

    // ---- settings save/auth/cleanup dialogs — live here (not inside
    // SettingsScreen.qml) since settingsBackend.checkStaleClips() fires
    // once at app startup, before the user has necessarily ever opened the
    // settings screen (Loader-loaded, not always instantiated) ----
    CompactDialog {
        id: settingsMessageDialog
        property string messageText: ""
        title: "設定"
        Label { text: settingsMessageDialog.messageText }
        footer: CompactDialogFooter {
            SquareDialogButton { text: "OK"; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
    }
    CompactDialog {
        id: cleanupConfirmDialog
        title: "削除の確認"
        property string messageText: ""
        onAccepted: settingsBackend.confirmCleanup()
        Label { text: cleanupConfirmDialog.messageText }
        footer: CompactDialogFooter {
            SquareDialogButton { text: "いいえ"; DialogButtonBox.buttonRole: DialogButtonBox.NoRole }
            SquareDialogButton { text: "はい"; DialogButtonBox.buttonRole: DialogButtonBox.YesRole }
        }
    }
    CompactDialog {
        id: clearFolderConfirmDialog
        title: "削除の確認"
        property string messageText: ""
        onAccepted: settingsBackend.confirmClearFolder()
        Label { text: clearFolderConfirmDialog.messageText }
        footer: CompactDialogFooter {
            SquareDialogButton { text: "いいえ"; DialogButtonBox.buttonRole: DialogButtonBox.NoRole }
            SquareDialogButton { text: "はい"; DialogButtonBox.buttonRole: DialogButtonBox.YesRole }
        }
    }
    Connections {
        target: settingsBackend
        function onSaved(message) {
            settingsMessageDialog.messageText = message
            settingsMessageDialog.open()
        }
        function onCleanupNone() {
            settingsMessageDialog.messageText = "削除できる一時ファイルはありませんでした。"
            settingsMessageDialog.open()
        }
        function onCleanupDone(total) {
            backend.refresh()
            settingsMessageDialog.messageText = total + "件のファイルを削除しました。"
            settingsMessageDialog.open()
        }
        function onCleanupCandidates(message) {
            cleanupConfirmDialog.messageText = message
            cleanupConfirmDialog.open()
        }
        function onClearFolderCandidate(message) {
            clearFolderConfirmDialog.messageText = message
            clearFolderConfirmDialog.open()
        }
        function onClearFolderDone(total) {
            backend.refresh()
            settingsMessageDialog.messageText = total + "件のファイルを削除しました。"
            settingsMessageDialog.open()
        }
    }
}
