from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QPoint, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSizeGrip,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spotify_lrc_generator import __version__, media_session
from spotify_lrc_generator.lrc import (
    LyricLine,
    count_unstamped,
    export_lrc,
    format_position,
    parse_lrc,
    parse_plain_lyrics,
    shift_timestamp,
)
from spotify_lrc_generator.media_session import MediaState
from spotify_lrc_generator.resources import resource_path


class ClickableFrame(QFrame):
    def __init__(self, on_click, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class TitleBar(QFrame):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.drag_position: QPoint | None = None
        self.setObjectName("titleBar")
        self.setFixedHeight(42)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(6)

        title = QLabel("Spotify LRC Maker")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        layout.addStretch()

        self.minimize_button = self._window_button("icon_minimize.png", "Minimize")
        self.maximize_button = self._window_button("icon_maximize.png", "Maximize")
        self.close_button = self._window_button("icon_close.png", "Close")
        self.close_button.setObjectName("windowCloseButton")

        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(window.toggle_full_screen)
        self.close_button.clicked.connect(window.close)

    def refresh_maximize_icon(self) -> None:
        icon_name = (
            "icon_restore.png"
            if self.window.isMaximized() or self.window.isFullScreen()
            else "icon_maximize.png"
        )
        icon = self._icon(icon_name)
        self.maximize_button.setIcon(icon)
        self.maximize_button.setText("□" if icon.isNull() else "")
        self.maximize_button.setToolTip(
            "Restore" if self.window.isMaximized() or self.window.isFullScreen() else "Maximize"
        )

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.window.toggle_full_screen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton and self.drag_position is not None:
            if self.window.isMaximized():
                self.window.showNormal()
                self.refresh_maximize_icon()
                self.drag_position = QPoint(self.window.width() // 2, self.height() // 2)
            self.window.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.drag_position = None
        super().mouseReleaseEvent(event)

    def _window_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("windowControlButton")
        icon = self._icon(icon_name)
        button.setIcon(icon)
        if icon.isNull():
            button.setText(
                {
                    "icon_minimize.png": "-",
                    "icon_maximize.png": "□",
                    "icon_restore.png": "□",
                    "icon_close.png": "X",
                }.get(icon_name, "")
            )
        button.setToolTip(tooltip)
        button.setFixedSize(34, 30)
        return button

    def _icon(self, icon_name: str) -> QIcon:
        return QIcon(str(resource_path(f"images/{icon_name}")))


class MainWindow(QMainWindow):
    ADJUST_STEPS = (-1000, -100, 100, 1000)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Spotify LRC Maker")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        self.lines: list[LyricLine] = []
        self.loaded_lrc_lines: list[LyricLine] = []
        self.current_lrc_path: Path | None = None
        self.current_index = 0
        self.dragging_progress = False
        self.row_widgets: list[QFrame] = []
        self.time_labels: list[QLabel] = []
        self.last_state = MediaState(False, message="Waiting for Spotify media session...")
        self.poll_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-poll")
        self.command_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-command")
        self.pending_state: Future[MediaState] | None = None

        self._build_ui()
        self._sync_file_action_buttons()
        self._connect_actions()
        self._apply_styles()
        self._build_status_bar()

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(250)
        self.poll_timer.timeout.connect(self._poll_media_state)
        self.poll_timer.start()
        self._poll_media_state()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.poll_executor.shutdown(wait=False, cancel_futures=True)
        self.command_executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar.refresh_maximize_icon()

    def toggle_maximized(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        elif self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.title_bar.refresh_maximize_icon()

    def toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.title_bar.refresh_maximize_icon()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_F11 and not event.modifiers():
            self.toggle_full_screen()
            event.accept()
            return

        if self.stack.currentWidget() is not self.stamp_page:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Space and not event.modifiers():
            self.stamp_next_line()
            event.accept()
            return
        if event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            self.undo_stamp()
            event.accept()
            return
        if event.key() == Qt.Key_Up and not event.modifiers():
            self.move_active_line(-1)
            event.accept()
            return
        if event.key() == Qt.Key_Down and not event.modifiers():
            self.move_active_line(1)
            event.accept()
            return

        super().keyPressEvent(event)

    def _build_ui(self) -> None:
        self.stack = QStackedWidget(self)
        self.home_page = self._build_home_page()
        self.input_page = self._build_input_page()
        self.stamp_page = self._build_stamp_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.input_page)
        self.stack.addWidget(self.stamp_page)

        root = QWidget(self)
        root.setObjectName("windowRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(1, 1, 1, 1)
        root_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)
        root_layout.addWidget(self.stack, 1)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch()
        grip_row.addWidget(QSizeGrip(root))
        root_layout.addLayout(grip_row)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Create a new LRC or open an existing LRC to modify.")

    def _build_status_bar(self) -> None:
        self.statusBar().setObjectName("appStatusBar")
        self.status_version_label = QLabel(f"v{__version__}")
        self.status_version_label.setObjectName("statusVersionLabel")
        self.statusBar().addPermanentWidget(self.status_version_label)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(44, 42, 44, 42)
        layout.setSpacing(18)

        title = QLabel("Spotify LRC Maker")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Create a new synced lyric file or modify an existing .lrc.")
        subtitle.setObjectName("mutedText")

        actions = QHBoxLayout()
        actions.setSpacing(14)
        self.new_lrc_button = QPushButton("New LRC")
        self.new_lrc_button.setObjectName("primaryButton")
        self.open_lrc_button = QPushButton("Open / Modify LRC")
        self.open_lrc_button.setObjectName("secondaryButton")
        actions.addWidget(self.new_lrc_button)
        actions.addWidget(self.open_lrc_button)
        actions.addStretch()

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(14)
        layout.addLayout(actions)
        layout.addStretch(2)
        return page

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 30, 36, 28)
        layout.setSpacing(18)

        nav = QHBoxLayout()
        self.home_back_button = QPushButton("Back")
        self.home_back_button.setObjectName("ghostButton")
        nav.addWidget(self.home_back_button)
        nav.addStretch()

        header = QLabel("Input / Edit Lyrics")
        header.setObjectName("pageTitle")
        subheader = QLabel("Paste lyrics manually or edit lines loaded from an LRC file.")
        subheader.setObjectName("mutedText")

        self.raw_editor = QPlainTextEdit()
        self.raw_editor.setPlaceholderText("Paste plain lyrics here...")
        self.raw_editor.setObjectName("lyricInput")

        footer = QHBoxLayout()
        self.line_count_label = QLabel("0 lines")
        self.line_count_label.setObjectName("mutedText")
        self.clear_button = QPushButton("Clear")
        self.continue_button = QPushButton("Continue to Timestamp")
        self.continue_button.setObjectName("primaryButton")
        footer.addWidget(self.line_count_label)
        footer.addStretch()
        footer.addWidget(self.clear_button)
        footer.addWidget(self.continue_button)

        layout.addLayout(nav)
        layout.addWidget(header)
        layout.addWidget(subheader)
        layout.addWidget(self.raw_editor, 1)
        layout.addLayout(footer)
        return page

    def _build_stamp_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("trackHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 14)

        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("ghostButton")
        track_text = QVBoxLayout()
        self.title_label = QLabel("-")
        self.title_label.setObjectName("trackTitle")
        self.artist_label = QLabel("-")
        self.artist_label.setObjectName("trackArtist")
        track_text.addWidget(self.title_label)
        track_text.addWidget(self.artist_label)
        self.status_label = QLabel("Waiting")
        self.status_label.setObjectName("statusPill")
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("secondaryButton")
        self.save_as_button = QPushButton("Save As")
        self.save_as_button.setObjectName("secondaryButton")
        self.export_button = QPushButton("Export .lrc")
        self.export_button.setObjectName("primaryButton")

        header_layout.addWidget(self.back_button)
        header_layout.addSpacing(12)
        header_layout.addLayout(track_text, 1)
        header_layout.addWidget(self.status_label)
        header_layout.addWidget(self.save_button)
        header_layout.addWidget(self.save_as_button)
        header_layout.addWidget(self.export_button)
        layout.addWidget(header)

        self.message_label = QLabel("")
        self.message_label.setObjectName("warningText")
        self.message_label.setWordWrap(True)
        self.message_label.setContentsMargins(24, 2, 24, 4)
        layout.addWidget(self.message_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(14, 8, 14, 24)
        self.rows_layout.setSpacing(10)
        self.rows_layout.addStretch()
        self.scroll_area.setWidget(self.rows_container)
        layout.addWidget(self.scroll_area, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(360, 0, 360, 22)
        nav.setSpacing(12)
        self.prev_line_button = QPushButton("^")
        self.next_line_button = QPushButton("v")
        self.prev_line_button.setObjectName("navButton")
        self.next_line_button.setObjectName("navButtonLight")
        self.prev_line_button.setToolTip("Move to previous lyric line")
        self.next_line_button.setToolTip("Stamp the selected lyric, then target the next unstamped line")
        nav.addWidget(self.prev_line_button)
        nav.addWidget(self.next_line_button)
        layout.addLayout(nav)

        playback = QFrame()
        playback.setObjectName("playbackBar")
        playback_layout = QHBoxLayout(playback)
        playback_layout.setContentsMargins(14, 10, 14, 10)
        playback_layout.setSpacing(10)
        self.previous_button = QPushButton("<<")
        self.play_pause_button = QPushButton("Play")
        self.next_button = QPushButton(">>")
        self.position_label = QLabel("00:00")
        self.duration_label = QLabel("00:00")
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1)
        self.progress_slider.setEnabled(True)
        self.progress_slider.setTracking(True)
        self.progress_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.undo_button = QPushButton("Undo")
        self.clear_all_timestamps_button = QPushButton("Clear All")

        self.play_pause_button.setObjectName("playButton")
        self.undo_button.setObjectName("secondaryActionButton")
        self.clear_all_timestamps_button.setObjectName("dangerActionButton")
        for button in (self.previous_button, self.next_button):
            button.setObjectName("roundButton")

        playback_layout.addWidget(self.previous_button)
        playback_layout.addWidget(self.play_pause_button)
        playback_layout.addWidget(self.next_button)
        playback_layout.addSpacing(8)
        playback_layout.addWidget(self.position_label)
        playback_layout.addWidget(self.progress_slider, 1)
        playback_layout.addWidget(self.duration_label)
        playback_layout.addWidget(self.undo_button)
        playback_layout.addWidget(self.clear_all_timestamps_button)
        layout.addWidget(playback)
        return page

    def _connect_actions(self) -> None:
        self.new_lrc_button.clicked.connect(self.start_new_lrc)
        self.open_lrc_button.clicked.connect(self.open_lrc_file)
        self.home_back_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        self.raw_editor.textChanged.connect(self._update_line_count)
        self.clear_button.clicked.connect(self.clear_lyrics)
        self.continue_button.clicked.connect(self.go_to_stamp_page)
        self.back_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.input_page))
        self.undo_button.clicked.connect(self.undo_stamp)
        self.clear_all_timestamps_button.clicked.connect(self.clear_all_timestamps)
        self.save_button.clicked.connect(self.save_file)
        self.save_as_button.clicked.connect(self.save_file_as)
        self.export_button.clicked.connect(self.export_file)
        self.prev_line_button.clicked.connect(lambda: self.move_active_line(-1))
        self.next_line_button.clicked.connect(self.stamp_next_line)
        self.play_pause_button.clicked.connect(lambda: self._run_media_command(media_session.play_pause))
        self.next_button.clicked.connect(lambda: self._run_media_command(media_session.next_track))
        self.previous_button.clicked.connect(lambda: self._run_media_command(media_session.previous_track))
        self.progress_slider.sliderPressed.connect(self._begin_progress_drag)
        self.progress_slider.sliderMoved.connect(self._preview_progress_drag)
        self.progress_slider.sliderReleased.connect(self._seek_to_slider_position)

    def start_new_lrc(self) -> None:
        self.loaded_lrc_lines = []
        self.lines = []
        self.current_lrc_path = None
        self.current_index = 0
        self.raw_editor.clear()
        self._update_line_count()
        self._sync_file_action_buttons()
        self.stack.setCurrentWidget(self.input_page)
        self.statusBar().showMessage("Paste lyrics manually, then continue to timestamp mode.")

    def open_lrc_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open LRC",
            "",
            "LRC files (*.lrc);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        input_path = Path(path)
        parsed = parse_lrc(input_path.read_text(encoding="utf-8"))
        self.loaded_lrc_lines = parsed
        self.lines = [LyricLine(line.text, line.timestamp_ms) for line in parsed]
        self.current_lrc_path = input_path
        self.current_index = 0
        self.raw_editor.setPlainText("\n".join(line.text for line in parsed))
        self._update_line_count()
        self._sync_file_action_buttons()
        self.stack.setCurrentWidget(self.input_page)
        self.statusBar().showMessage(f"Loaded {len(parsed)} lines from {input_path.name}.")

    def _apply_styles(self) -> None:
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #101010;
                color: #e8f3ff;
            }
            #windowRoot {
                border: 1px solid #181818;
                background: #101010;
            }
            #titleBar {
                background: #101010;
                border-bottom: 1px solid #1a1a1a;
            }
            #appTitle {
                color: #8fbfff;
                font-size: 13px;
                font-weight: 700;
            }
            #windowControlButton, #windowCloseButton {
                background: transparent;
                border: 0;
                border-radius: 4px;
                padding: 5px;
            }
            #windowControlButton:hover {
                background: #202020;
            }
            #windowControlButton:pressed {
                background: #2d2d2d;
            }
            #windowCloseButton:hover {
                background: #c83f3f;
            }
            #windowCloseButton:pressed {
                background: #a82f2f;
            }
            #pageTitle {
                color: #4aa3ff;
                font-size: 32px;
                font-weight: 700;
            }
            #mutedText, #trackArtist {
                color: #8ba8c8;
            }
            #lyricInput {
                background: #151515;
                color: #d9e9ff;
                border: 1px solid #236dff;
                border-radius: 8px;
                padding: 14px;
                selection-background-color: #236dff;
            }
            QPushButton {
                background: #242424;
                color: #cfe6ff;
                border: 0;
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #303030;
            }
            QPushButton:pressed {
                background: #3a3a3a;
                padding-top: 10px;
                padding-bottom: 8px;
            }
            #primaryButton {
                background: #236dff;
                color: white;
            }
            #primaryButton:hover {
                background: #357cff;
            }
            #primaryButton:pressed {
                background: #1557d6;
            }
            #secondaryButton {
                background: #1e1e1e;
                color: #e8f3ff;
                border: 1px solid #343434;
            }
            #secondaryButton:hover {
                background: #292929;
                border: 1px solid #4a4a4a;
            }
            #secondaryButton:pressed {
                background: #151515;
            }
            #ghostButton {
                background: transparent;
                border: 1px solid #343434;
            }
            #ghostButton:hover {
                background: #1c1c1c;
                border: 1px solid #4d4d4d;
            }
            #ghostButton:pressed {
                background: #111111;
            }
            #trackHeader, #playbackBar {
                background: #101010;
                border: 0;
            }
            #trackTitle {
                color: #eef6ff;
                font-size: 16px;
                font-weight: 700;
            }
            #statusPill {
                background: #2a2a2a;
                color: #83bdff;
                border-radius: 14px;
                padding: 7px 13px;
                font-weight: 700;
            }
            #warningText {
                color: #7dbaff;
            }
            #versionLabel {
                color: #5f5f5f;
                font-size: 11px;
                font-weight: 700;
                padding-left: 8px;
            }
            QStatusBar#appStatusBar {
                background: #101010;
                color: #7a7a7a;
                border-top: 0;
            }
            #statusVersionLabel {
                color: #5f5f5f;
                font-size: 11px;
                font-weight: 700;
                padding-right: 8px;
            }
            #lyricRow {
                background: #101010;
                border: 0;
                border-radius: 6px;
            }
            #lyricRow[active="true"] {
                border: 1px solid #236dff;
                background: #101010;
            }
            #controlGroup {
                background: #2d2d2d;
                border-radius: 18px;
            }
            #timePill {
                background: transparent;
                color: #eef6ff;
                padding: 8px 10px;
                min-width: 74px;
                font-weight: 650;
            }
            #lyricText {
                color: #59aaff;
                font-size: 15px;
                font-weight: 650;
            }
            #smallButton {
                background: transparent;
                color: #edf6ff;
                min-width: 34px;
                max-width: 42px;
                border-radius: 14px;
                padding: 6px 6px;
            }
            #smallButton:hover {
                background: #3a3a3a;
            }
            #smallButton:pressed {
                background: #4a4a4a;
            }
            #iconButton, #playRowButton, #roundButton {
                background: #2a2a2a;
                color: #edf6ff;
                min-width: 38px;
                max-width: 44px;
                min-height: 34px;
                border-radius: 17px;
                padding: 6px 8px;
            }
            #playRowButton {
                min-width: 46px;
                max-width: 54px;
            }
            #iconButton:hover, #playRowButton:hover {
                background: #373737;
            }
            #iconButton:pressed, #playRowButton:pressed {
                background: #484848;
            }
            #playButton {
                background: #ffffff;
                color: #111111;
                min-width: 46px;
                max-width: 56px;
                min-height: 36px;
                border-radius: 18px;
                padding: 6px 10px;
            }
            #playButton:hover {
                background: #e8f3ff;
            }
            #playButton:pressed {
                background: #b9d8ff;
            }
            #roundButton {
                background: transparent;
                color: #f2f2f2;
            }
            #roundButton:hover {
                background: #252525;
            }
            #roundButton:pressed {
                background: #383838;
            }
            #secondaryActionButton, #dangerActionButton {
                min-width: 82px;
                min-height: 36px;
                border-radius: 8px;
                padding: 7px 14px;
                font-weight: 700;
            }
            #secondaryActionButton {
                background: #262626;
                color: #edf6ff;
                border: 1px solid #3a3a3a;
            }
            #secondaryActionButton:hover {
                background: #323232;
            }
            #secondaryActionButton:pressed {
                background: #1b1b1b;
            }
            #dangerActionButton {
                background: #331f1f;
                color: #ffdede;
                border: 1px solid #7a3434;
            }
            #dangerActionButton:hover {
                background: #4a2424;
            }
            #dangerActionButton:pressed {
                background: #5c2b2b;
            }
            #navButton, #navButtonLight {
                min-height: 48px;
                min-width: 190px;
                border-radius: 8px;
                font-size: 18px;
            }
            #navButton {
                background: #333333;
                color: #9a9a9a;
            }
            #navButton:hover {
                background: #414141;
                color: #c8c8c8;
            }
            #navButton:pressed {
                background: #262626;
            }
            #navButtonLight {
                background: #f5f5f5;
                color: #101010;
            }
            #navButtonLight:hover {
                background: #dceaff;
                color: #0d2b5c;
            }
            #navButtonLight:pressed {
                background: #aecaef;
            }
            QSlider::groove:horizontal {
                background: #303030;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #236dff;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            """
        )

    def _poll_media_state(self) -> None:
        if self.pending_state is None:
            self.pending_state = self.poll_executor.submit(media_session.get_media_state)
            return

        if not self.pending_state.done():
            return

        try:
            self.last_state = self.pending_state.result()
        except Exception as exc:
            self.last_state = MediaState(False, message=f"Media polling failed: {exc}")
        self.pending_state = None
        self._render_media_state()

    def _run_media_command(self, command) -> None:
        self.command_executor.submit(command)

    def _current_media_position_ms(self) -> int | None:
        position = self.last_state.position_ms
        if position is None:
            return None

        if self.last_state.playback_status.lower() == "playing" and self.last_state.sampled_at:
            elapsed_ms = int((monotonic() - self.last_state.sampled_at) * 1000)
            position += max(elapsed_ms, 0)

        if self.last_state.duration_ms:
            position = min(position, self.last_state.duration_ms)
        return max(position, 0)

    def _render_media_state(self) -> None:
        state = self.last_state
        self.title_label.setText(state.title or "-")
        artist_album = state.artist or "-"
        if state.album:
            artist_album = f"{artist_album} - {state.album}"
        self.artist_label.setText(artist_album)
        self.status_label.setText(state.playback_status)
        self.message_label.setText("" if state.available else state.message)

        position = self._current_media_position_ms() or 0
        duration = state.duration_ms or 0
        self.position_label.setText(format_position(position))
        self.duration_label.setText(format_position(duration))
        self.progress_slider.setRange(0, max(duration, 1))
        if not self.dragging_progress:
            self.progress_slider.setValue(min(position, max(duration, 1)))
        self.play_pause_button.setText("Pause" if state.playback_status.lower() == "playing" else "Play")

    def _begin_progress_drag(self) -> None:
        self.dragging_progress = True

    def _preview_progress_drag(self, value: int) -> None:
        self.position_label.setText(format_position(value))

    def _seek_to_slider_position(self) -> None:
        value = self.progress_slider.value()
        self.dragging_progress = False
        self.position_label.setText(format_position(value))
        self.command_executor.submit(media_session.seek_to, value)
        self.statusBar().showMessage(f"Seeking Spotify to {format_position(value)}.")

    def go_to_stamp_page(self) -> None:
        self.lines = self._lines_from_editor()
        self.current_index = 0
        if not self.lines:
            self.statusBar().showMessage("No lyric lines to timestamp.")
            return
        self._render_rows()
        self._sync_file_action_buttons()
        self.stack.setCurrentWidget(self.stamp_page)
        self.statusBar().showMessage("Press Space or the down button to timestamp the active lyric.")

    def _lines_from_editor(self) -> list[LyricLine]:
        plain_lines = parse_plain_lyrics(self.raw_editor.toPlainText())
        if not self.loaded_lrc_lines:
            return plain_lines

        merged: list[LyricLine] = []
        for index, line in enumerate(plain_lines):
            timestamp_ms = None
            if index < len(self.loaded_lrc_lines):
                timestamp_ms = self.loaded_lrc_lines[index].timestamp_ms
            merged.append(LyricLine(line.text, timestamp_ms))
        return merged

    def clear_lyrics(self) -> None:
        self.lines = []
        self.loaded_lrc_lines = []
        self.current_lrc_path = None
        self.current_index = 0
        self.raw_editor.clear()
        self._update_line_count()
        self._render_rows()
        self._sync_file_action_buttons()
        self.statusBar().showMessage("Cleared lyrics.")

    def stamp_next_line(self) -> None:
        if not self.lines:
            self.go_to_stamp_page()
        if not self.lines:
            return
        position_ms = self._current_media_position_ms()
        if position_ms is None:
            self.statusBar().showMessage("Spotify position is not available yet.")
            return

        index = self._stamp_target_index()
        if not 0 <= index < len(self.lines):
            self.statusBar().showMessage("No next lyric line to stamp.")
            return

        self.lines[index].timestamp_ms = position_ms
        self._refresh_row_timestamp(index)
        self._set_active_line(index)
        self._scroll_to_active_line()
        self.statusBar().showMessage(f"Stamped line {index + 1} at {format_position(position_ms)}.")

    def undo_stamp(self) -> None:
        stamped_indexes = [idx for idx, line in enumerate(self.lines) if line.timestamp_ms is not None]
        if not stamped_indexes:
            self.statusBar().showMessage("No timestamp to undo.")
            return
        index = stamped_indexes[-1]
        self.lines[index].timestamp_ms = None
        self._set_active_line(index)
        self._refresh_row_timestamp(index)
        self._scroll_to_active_line()
        self.statusBar().showMessage(f"Removed timestamp from line {index + 1}.")

    def clear_all_timestamps(self) -> None:
        cleared_count = sum(1 for line in self.lines if line.timestamp_ms is not None)
        if cleared_count == 0:
            self.statusBar().showMessage("No timestamps to clear.")
            return

        for line in self.lines:
            line.timestamp_ms = None
        for index in range(len(self.time_labels)):
            self._refresh_row_timestamp(index)
        self._set_active_line(0)
        self._scroll_to_active_line()
        self.statusBar().showMessage(f"Cleared {cleared_count} timestamp{'s' if cleared_count != 1 else ''}.")

    def move_active_line(self, delta: int) -> None:
        if not self.lines:
            return
        self._set_active_line(min(max(self.current_index + delta, 0), len(self.lines) - 1))
        self._scroll_to_active_line()

    def adjust_line(self, index: int, delta_ms: int) -> None:
        if not 0 <= index < len(self.lines):
            return
        self.lines[index].timestamp_ms = shift_timestamp(self.lines[index].timestamp_ms, delta_ms)
        self._set_active_line(index)
        self._refresh_row_timestamp(index)
        self._scroll_to_active_line()

    def clear_line_timestamp(self, index: int) -> None:
        if not 0 <= index < len(self.lines):
            return
        self.lines[index].timestamp_ms = None
        self._set_active_line(index)
        self._refresh_row_timestamp(index)
        self._scroll_to_active_line()

    def preview_line(self, index: int) -> None:
        if not 0 <= index < len(self.lines):
            return
        self._set_active_line(index)
        self._scroll_to_active_line()
        timestamp_ms = self.lines[index].timestamp_ms
        if timestamp_ms is None:
            self.statusBar().showMessage("Line has no timestamp to preview.")
            return
        self.command_executor.submit(media_session.play_from, timestamp_ms)
        self.statusBar().showMessage(f"Previewing line {index + 1} at {format_position(timestamp_ms)}.")

    def export_file(self) -> None:
        if not self.lines:
            self.statusBar().showMessage("No lyrics to export.")
            return

        if not self._confirm_incomplete_export("Export incomplete lyrics"):
            return

        suggested = str(self._documents_path() / self._suggested_filename())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export LRC",
            suggested,
            "LRC files (*.lrc);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return

        output_path = self._normalized_lrc_path(path)
        self._write_lrc_file(output_path)
        self.statusBar().showMessage(f"Exported {output_path}")

    def save_file(self) -> None:
        if self.current_lrc_path is None:
            self.save_file_as()
            return
        if not self._confirm_incomplete_export("Save incomplete lyrics"):
            return
        self._write_lrc_file(self.current_lrc_path)
        self.statusBar().showMessage(f"Saved {self.current_lrc_path}")

    def save_file_as(self) -> None:
        if not self.lines:
            self.statusBar().showMessage("No lyrics to save.")
            return
        if not self._confirm_incomplete_export("Save incomplete lyrics"):
            return

        suggested_name = self.current_lrc_path.name if self.current_lrc_path else self._suggested_filename()
        suggested = str(self._documents_path() / suggested_name)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save LRC As",
            suggested,
            "LRC files (*.lrc);;Text files (*.txt);;All files (*)",
        )
        if not path:
            return

        output_path = self._normalized_lrc_path(path)
        self._write_lrc_file(output_path)
        self.current_lrc_path = output_path
        self._sync_file_action_buttons()
        self.statusBar().showMessage(f"Saved {output_path}")

    def _confirm_incomplete_export(self, title: str) -> bool:
        unstamped = count_unstamped(self.lines)
        if not unstamped:
            return True
        answer = QMessageBox.question(
            self,
            title,
            f"{unstamped} lyric lines do not have timestamps and will be skipped. Continue?",
        )
        return answer == QMessageBox.Yes

    def _write_lrc_file(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(export_lrc(self.lines), encoding="utf-8")

    def _normalized_lrc_path(self, path: str | Path) -> Path:
        output_path = Path(path)
        if output_path.suffix.lower() != ".lrc":
            output_path = output_path.with_suffix(".lrc")
        return output_path

    def _documents_path(self) -> Path:
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        if documents:
            return Path(documents)
        return Path.home() / "Documents"

    def _sync_file_action_buttons(self) -> None:
        editing_existing = self.current_lrc_path is not None
        self.save_button.setVisible(editing_existing)
        self.save_as_button.setVisible(editing_existing)
        self.export_button.setVisible(not editing_existing)

    def _render_rows(self) -> None:
        self.row_widgets = []
        self.time_labels = []
        while self.rows_layout.count() > 0:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, line in enumerate(self.lines):
            row = self._build_lyric_row(index, line)
            self.row_widgets.append(row)
            self.rows_layout.addWidget(row)
        self.rows_layout.addStretch()

    def _refresh_row_timestamp(self, index: int) -> None:
        if 0 <= index < len(self.time_labels):
            self.time_labels[index].setText(format_position(self.lines[index].timestamp_ms))

    def _set_active_line(self, index: int) -> None:
        if not 0 <= index < len(self.lines):
            return

        previous_index = self.current_index
        self.current_index = index
        for row_index in {previous_index, index}:
            if 0 <= row_index < len(self.row_widgets):
                row = self.row_widgets[row_index]
                row.setProperty("active", row_index == self.current_index)
                row.style().unpolish(row)
                row.style().polish(row)
                row.update()

    def _scroll_to_active_line(self) -> None:
        if not 0 <= self.current_index < len(self.row_widgets):
            return

        def center_active_row() -> None:
            if not 0 <= self.current_index < len(self.row_widgets):
                return
            row = self.row_widgets[self.current_index]
            scrollbar = self.scroll_area.verticalScrollBar()
            viewport_height = self.scroll_area.viewport().height()
            target = row.y() - max((viewport_height - row.height()) // 2, 0)
            scrollbar.setValue(max(scrollbar.minimum(), min(target, scrollbar.maximum())))

        QTimer.singleShot(0, center_active_row)

    def _build_lyric_row(self, index: int, line: LyricLine) -> QFrame:
        row = ClickableFrame(lambda: self.select_line(index))
        row.setObjectName("lyricRow")
        row.setProperty("active", index == self.current_index)
        row.style().unpolish(row)
        row.style().polish(row)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 8, 14, 8)
        row_layout.setSpacing(12)

        delete_button = self._icon_button("X")
        delete_button.clicked.connect(lambda: self.clear_line_timestamp(index))

        minus_big = self._small_button("<<")
        minus_small = self._small_button("<")
        plus_small = self._small_button(">")
        plus_big = self._small_button(">>")
        minus_big.clicked.connect(lambda: self.adjust_line(index, self.ADJUST_STEPS[0]))
        minus_small.clicked.connect(lambda: self.adjust_line(index, self.ADJUST_STEPS[1]))
        plus_small.clicked.connect(lambda: self.adjust_line(index, self.ADJUST_STEPS[2]))
        plus_big.clicked.connect(lambda: self.adjust_line(index, self.ADJUST_STEPS[3]))

        time_label = QLabel(format_position(line.timestamp_ms))
        time_label.setObjectName("timePill")
        time_label.setAlignment(Qt.AlignCenter)
        self.time_labels.append(time_label)

        control_group = QFrame()
        control_group.setObjectName("controlGroup")
        control_layout = QHBoxLayout(control_group)
        control_layout.setContentsMargins(6, 0, 6, 0)
        control_layout.setSpacing(0)
        control_layout.addWidget(minus_big)
        control_layout.addWidget(minus_small)
        control_layout.addWidget(time_label)
        control_layout.addWidget(plus_small)
        control_layout.addWidget(plus_big)

        preview_button = QPushButton("Play")
        preview_button.setObjectName("playRowButton")
        preview_button.clicked.connect(lambda: self.preview_line(index))

        lyric_label = QLabel(line.text)
        lyric_label.setObjectName("lyricText")
        lyric_label.setWordWrap(True)

        row_layout.addWidget(delete_button)
        row_layout.addWidget(control_group)
        row_layout.addWidget(preview_button)
        row_layout.addWidget(lyric_label, 1)
        return row

    def select_line(self, index: int) -> None:
        if not 0 <= index < len(self.lines):
            return
        timestamp_ms = self.lines[index].timestamp_ms
        self._set_active_line(index)
        self._scroll_to_active_line()
        if timestamp_ms is None:
            self.statusBar().showMessage(f"Selected line {index + 1}.")
            return
        self.command_executor.submit(media_session.play_from, timestamp_ms)
        self.statusBar().showMessage(f"Previewing line {index + 1} at {format_position(timestamp_ms)}.")

    def _small_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("smallButton")
        return button

    def _icon_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("iconButton")
        return button

    def _next_unstamped_index(self) -> int | None:
        for index in range(self.current_index, len(self.lines)):
            if self.lines[index].timestamp_ms is None:
                return index
        for index, line in enumerate(self.lines):
            if line.timestamp_ms is None:
                return index
        return None

    def _stamp_target_index(self) -> int:
        if not 0 <= self.current_index < len(self.lines):
            return 0
        if self.lines[self.current_index].timestamp_ms is None:
            return self.current_index
        return min(self.current_index + 1, len(self.lines) - 1)

    def _update_line_count(self) -> None:
        count = len(parse_plain_lyrics(self.raw_editor.toPlainText()))
        self.line_count_label.setText(f"{count} line{'s' if count != 1 else ''}")

    def _suggested_filename(self) -> str:
        artist = self.last_state.artist.strip()
        title = self.last_state.title.strip()
        if artist and title:
            name = f"{artist} - {title}.lrc"
        elif title:
            name = f"{title}.lrc"
        else:
            name = "lyrics.lrc"
        return "".join(char for char in name if char not in '<>:"/\\|?*')
