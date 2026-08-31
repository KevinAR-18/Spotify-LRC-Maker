from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spotify_lrc_generator import __version__, lrclib, media_session
from spotify_lrc_generator.lrc import (
    LyricLine,
    ValidationIssue,
    clone_lines,
    count_unstamped,
    format_position,
    merge_editor_lines,
    parse_lrc,
    validate_lines,
)
from spotify_lrc_generator.media_session import MediaState
from spotify_lrc_generator.storage import RecoveryStore, read_lrc_file, write_lrc_file


class MainWindow(QMainWindow):
    ADJUST_STEPS = (-1000, -100, 100, 1000)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Spotify LRC Maker")
        self.setMinimumSize(760, 560)
        self.setAcceptDrops(True)
        self.lines: list[LyricLine] = []
        self.current_lrc_path: Path | None = None
        self.current_index = 0
        self.capture_offset_ms = 0
        self.locked_track: tuple[str, str, int | None] | None = None
        self.history: list[tuple[list[LyricLine], int, int]] = []
        self.history_index = -1
        self.clean_history_index = -1
        self.editor_syncing = False
        self.dragging_progress = False
        self.row_widgets: list[QFrame] = []
        self.time_labels: list[QLabel] = []
        self.last_state = MediaState(False, message="Waiting for Spotify media session...")
        self.poll_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-poll")
        self.command_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-command")
        self.pending_state: Future[MediaState] | None = None
        self.settings = QSettings()
        data_root = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        self.recovery_store = RecoveryStore(data_root)
        self._build_ui()
        self._connect_actions()
        self._apply_styles()
        self._restore_recovery()
        self._poll_media_state()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(250)
        self.poll_timer.timeout.connect(self._poll_media_state)
        self.poll_timer.start()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(1500)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._autosave)
        self._refresh_document_ui()

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.home_page = self._build_home_page()
        self.editor_page = self._build_editor_page()
        self.stamp_page = self._build_stamp_page()
        for page in (self.home_page, self.editor_page, self.stamp_page):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)
        self.statusBar().showMessage("Create a new LRC, open a file, or recover a draft.")
        version = QLabel(f"v{__version__}")
        version.setObjectName("muted")
        self.statusBar().addPermanentWidget(version)
        self._build_menu()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._add_action(file_menu, "New", QKeySequence.New, self.start_new_lrc)
        self._add_action(file_menu, "Open...", QKeySequence.Open, self.open_lrc_file)
        self._add_action(file_menu, "Save", QKeySequence.Save, self.save_file)
        self._add_action(file_menu, "Save As...", QKeySequence.SaveAs, self.save_file_as)
        file_menu.addSeparator()
        self._add_action(file_menu, "Import from LRCLIB...", "Ctrl+I", self.import_from_lrclib)
        edit_menu = self.menuBar().addMenu("Edit")
        self.undo_action = self._add_action(edit_menu, "Undo", QKeySequence.Undo, self.undo)
        self.redo_action = self._add_action(edit_menu, "Redo", QKeySequence.Redo, self.redo)
        self._add_action(edit_menu, "Quality Check", "Ctrl+Shift+Q", self.quality_check)

    def _add_action(self, menu, text: str, shortcut, handler) -> QAction:
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 44, 48, 44)
        title = QLabel("Spotify LRC Maker")
        title.setObjectName("title")
        subtitle = QLabel("Create accurate, line-synced lyric files from Spotify Desktop playback.")
        subtitle.setObjectName("muted")
        self.new_button = QPushButton("New LRC")
        self.open_button = QPushButton("Open LRC...")
        self.new_button.setObjectName("primary")
        actions = QHBoxLayout()
        actions.addWidget(self.new_button)
        actions.addWidget(self.open_button)
        actions.addStretch()
        recent_title = QLabel("Recent files")
        recent_title.setObjectName("section")
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(190)
        self.recent_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(18)
        layout.addLayout(actions)
        layout.addSpacing(28)
        layout.addWidget(recent_title)
        layout.addWidget(self.recent_list)
        layout.addStretch(2)
        return page

    def _build_editor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        nav = QHBoxLayout()
        back = QPushButton("Home")
        back.clicked.connect(lambda: self._navigate_home())
        nav.addWidget(back)
        nav.addStretch()
        self.import_button = QPushButton("Import from LRCLIB")
        nav.addWidget(self.import_button)
        header = QLabel("Lyrics")
        header.setObjectName("title")
        hint = QLabel("Edit lines freely. Existing timestamps stay attached to their matching lyric lines.")
        hint.setObjectName("muted")
        self.raw_editor = QPlainTextEdit()
        self.raw_editor.setPlaceholderText("Paste plain lyrics here, one line per lyric.")
        footer = QHBoxLayout()
        self.line_count_label = QLabel("0 lines")
        self.line_count_label.setObjectName("muted")
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(-5000, 5000)
        self.offset_spin.setSingleStep(10)
        self.offset_spin.setSuffix(" ms capture offset")
        self.continue_button = QPushButton("Continue to Timestamp")
        self.continue_button.setObjectName("primary")
        footer.addWidget(self.line_count_label)
        footer.addStretch()
        footer.addWidget(self.offset_spin)
        footer.addWidget(self.continue_button)
        layout.addLayout(nav)
        layout.addWidget(header)
        layout.addWidget(hint)
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
        self.track_label = QLabel("Waiting for Spotify")
        self.track_label.setObjectName("trackTitle")
        self.track_status = QLabel("Unavailable")
        self.track_status.setObjectName("trackArtist")
        track_text.addWidget(self.track_label)
        track_text.addWidget(self.track_status)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("secondaryButton")
        self.save_as_button = QPushButton("Save As")
        self.save_as_button.setObjectName("secondaryButton")
        self.quality_button = QPushButton("Quality Check")
        self.quality_button.setObjectName("secondaryButton")
        self.shift_all_button = QPushButton("Shift All")
        self.shift_all_button.setObjectName("secondaryButton")
        header_layout.addWidget(self.back_button)
        header_layout.addSpacing(12)
        header_layout.addLayout(track_text, 1)
        header_layout.addWidget(self.quality_button)
        header_layout.addWidget(self.shift_all_button)
        header_layout.addWidget(self.save_button)
        header_layout.addWidget(self.save_as_button)
        self.message_label = QLabel()
        self.message_label.setObjectName("warningText")
        self.message_label.setWordWrap(True)
        self.message_label.setContentsMargins(24, 2, 24, 4)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(14, 8, 14, 24)
        self.rows_layout.setSpacing(10)
        self.scroll_area.setWidget(self.rows_container)
        stamp_controls = QHBoxLayout()
        stamp_controls.setContentsMargins(160, 0, 160, 22)
        stamp_controls.setSpacing(12)
        self.previous_line_button = QPushButton("^")
        self.previous_line_button.setObjectName("navButton")
        self.previous_line_button.setToolTip("Move to previous lyric line")
        self.stamp_button = QPushButton("v")
        self.stamp_button.setObjectName("navButtonLight")
        self.stamp_button.setToolTip("Stamp the selected lyric, then target the next unstamped line")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.clear_all_button = QPushButton("Clear all")
        self.undo_button.setObjectName("secondaryActionButton")
        self.redo_button.setObjectName("secondaryActionButton")
        self.clear_all_button.setObjectName("dangerActionButton")
        stamp_controls.addWidget(self.previous_line_button)
        stamp_controls.addWidget(self.stamp_button)
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
        self.progress_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.play_pause_button.setObjectName("playButton")
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
        playback_layout.addWidget(self.redo_button)
        playback_layout.addWidget(self.clear_all_button)
        layout.addWidget(header)
        layout.addWidget(self.message_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(stamp_controls)
        layout.addWidget(playback)
        return page

    def _connect_actions(self) -> None:
        self.new_button.clicked.connect(self.start_new_lrc)
        self.open_button.clicked.connect(self.open_lrc_file)
        self.recent_list.itemActivated.connect(lambda item: self._open_path(Path(item.data(Qt.UserRole))))
        self.raw_editor.textChanged.connect(self._editor_changed)
        self.offset_spin.valueChanged.connect(self._offset_changed)
        self.continue_button.clicked.connect(self.go_to_stamp_page)
        self.import_button.clicked.connect(self.import_from_lrclib)
        self.back_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.editor_page))
        self.save_button.clicked.connect(self.save_file)
        self.save_as_button.clicked.connect(self.save_file_as)
        self.quality_button.clicked.connect(self.quality_check)
        self.previous_line_button.clicked.connect(lambda: self.move_active_line(-1))
        self.stamp_button.clicked.connect(self.stamp_next_line)
        self.shift_all_button.clicked.connect(self.shift_all_timestamps)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.clear_all_button.clicked.connect(self.clear_all_timestamps)
        self.play_pause_button.clicked.connect(lambda: self._run_media_command(media_session.play_pause, "Play/pause"))
        self.previous_button.clicked.connect(lambda: self._run_media_command(media_session.previous_track, "Previous track"))
        self.next_button.clicked.connect(lambda: self._run_media_command(media_session.next_track, "Next track"))
        self.progress_slider.sliderPressed.connect(lambda: setattr(self, "dragging_progress", True))
        self.progress_slider.sliderReleased.connect(self._seek_to_slider_position)

    def start_new_lrc(self) -> None:
        if not self._confirm_discard("start a new document"):
            return
        self.lines, self.current_lrc_path, self.current_index = [], None, 0
        self.locked_track = None
        self._reset_history(clean=True)
        self._set_editor_text("")
        self.stack.setCurrentWidget(self.editor_page)

    def open_lrc_file(self) -> None:
        if not self._confirm_discard("open another file"):
            return
        start_dir = self.settings.value("last_directory", str(self._documents_path()))
        path, _ = QFileDialog.getOpenFileName(self, "Open LRC", start_dir, "LRC and text files (*.lrc *.txt);;All files (*)")
        if path:
            self._open_path(Path(path))

    def _open_path(self, path: Path) -> None:
        try:
            lines = read_lrc_file(path)
        except OSError as exc:
            self._show_error("Open failed", f"Could not open {path.name}: {exc}")
            return
        except UnicodeError as exc:
            self._show_error("Open failed", str(exc))
            return
        self.lines, self.current_lrc_path, self.current_index = lines, path, 0
        self.locked_track = None
        self._reset_history(clean=True)
        self._set_editor_text("\n".join(line.text for line in lines))
        self._remember_path(path)
        self.stack.setCurrentWidget(self.editor_page)
        self.statusBar().showMessage(f"Loaded {len(lines)} lyric lines from {path.name}.")

    def go_to_stamp_page(self) -> None:
        self._apply_editor_text()
        if not self.lines:
            self.statusBar().showMessage("Add at least one lyric line first.")
            return
        self.current_index = self._next_unstamped_index() or min(self.current_index, len(self.lines) - 1)
        self.locked_track = self._track_key() if self.last_state.available else None
        self._render_rows()
        self.stack.setCurrentWidget(self.stamp_page)
        self.statusBar().showMessage("Press Space to stamp the selected or next unstamped lyric.")

    def _editor_changed(self) -> None:
        if self.editor_syncing:
            return
        self._apply_editor_text()

    def _apply_editor_text(self) -> None:
        updated = merge_editor_lines(self.lines, self.raw_editor.toPlainText())
        if [(line.text, line.timestamp_ms, line.line_id) for line in updated] != [(line.text, line.timestamp_ms, line.line_id) for line in self.lines]:
            self.lines = updated
            self.current_index = min(self.current_index, max(len(self.lines) - 1, 0))
            self._record_state()
            self._refresh_document_ui()

    def _set_editor_text(self, text: str) -> None:
        self.editor_syncing = True
        self.raw_editor.setPlainText(text)
        self.editor_syncing = False
        self._refresh_document_ui()

    def _offset_changed(self, value: int) -> None:
        self.capture_offset_ms = value
        if not self.editor_syncing:
            self._record_state()

    def _record_state(self) -> None:
        snapshot = (clone_lines(self.lines), self.current_index, self.capture_offset_ms)
        if self.history_index >= 0 and self.history[self.history_index] == snapshot:
            return
        self.history = self.history[: self.history_index + 1]
        self.history.append(snapshot)
        self.history_index += 1
        self._schedule_autosave()
        self._refresh_document_ui()

    def _reset_history(self, clean: bool) -> None:
        self.history = [(clone_lines(self.lines), self.current_index, self.capture_offset_ms)]
        self.history_index = 0
        self.clean_history_index = 0 if clean else -1
        self._refresh_document_ui()

    def undo(self) -> None:
        if self.history_index <= 0:
            return
        self.history_index -= 1
        self._restore_history_state()

    def redo(self) -> None:
        if self.history_index >= len(self.history) - 1:
            return
        self.history_index += 1
        self._restore_history_state()

    def _restore_history_state(self) -> None:
        self.lines, self.current_index, self.capture_offset_ms = self.history[self.history_index]
        self.lines = clone_lines(self.lines)
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(self.capture_offset_ms)
        self.offset_spin.blockSignals(False)
        self._set_editor_text("\n".join(line.text for line in self.lines))
        self._render_rows()
        self._schedule_autosave()
        self._refresh_document_ui()

    def stamp_next_line(self) -> None:
        if not self._track_is_safe():
            return
        position = self._current_media_position_ms()
        if position is None:
            self.statusBar().showMessage("Spotify position is not available yet.")
            return
        index = self._next_unstamped_index()
        if index is None:
            self.statusBar().showMessage("All lyric lines are timestamped.")
            return
        self.lines[index].timestamp_ms = max(0, position + self.capture_offset_ms)
        self.current_index = index
        self._record_state()
        self._refresh_row_timestamp(index)
        self._set_active_line(index)
        self.statusBar().showMessage(f"Stamped line {index + 1} at {format_position(self.lines[index].timestamp_ms)}.")

    def adjust_line(self, index: int, delta_ms: int) -> None:
        if not 0 <= index < len(self.lines) or self.lines[index].timestamp_ms is None:
            self.statusBar().showMessage("Stamp this line before adjusting it.")
            return
        self.lines[index].timestamp_ms = max(0, self.lines[index].timestamp_ms + delta_ms)
        self.current_index = index
        self._record_state()
        self._refresh_row_timestamp(index)
        self._set_active_line(index)

    def clear_line_timestamp(self, index: int) -> None:
        if not 0 <= index < len(self.lines) or self.lines[index].timestamp_ms is None:
            return
        self.lines[index].timestamp_ms = None
        self.current_index = index
        self._record_state()
        self._refresh_row_timestamp(index)

    def clear_all_timestamps(self) -> None:
        if not any(line.timestamp_ms is not None for line in self.lines):
            return
        if QMessageBox.question(self, "Clear all timestamps", "Remove every timestamp? This can be undone.") != QMessageBox.Yes:
            return
        for line in self.lines:
            line.timestamp_ms = None
        self.current_index = 0
        self._record_state()
        self._render_rows()

    def shift_all_timestamps(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Shift timestamps")
        form = QFormLayout(dialog)
        amount = QSpinBox()
        amount.setRange(-60000, 60000)
        amount.setSingleStep(10)
        amount.setSuffix(" ms")
        form.addRow("Shift all stamped lines:", amount)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted or amount.value() == 0:
            return
        for line in self.lines:
            if line.timestamp_ms is not None:
                line.timestamp_ms = max(0, line.timestamp_ms + amount.value())
        self._record_state()
        self._render_rows()

    def move_active_line(self, delta: int) -> None:
        if self.lines:
            self._set_active_line(max(0, min(self.current_index + delta, len(self.lines) - 1)))

    def preview_line(self, index: int) -> None:
        if not 0 <= index < len(self.lines) or self.lines[index].timestamp_ms is None:
            return
        self.current_index = index
        self._set_active_line(index)
        self._run_media_command(lambda: media_session.play_from(self.lines[index].timestamp_ms or 0), f"Preview line {index + 1}")

    def quality_check(self) -> bool:
        issues = validate_lines(self.lines, self.last_state.duration_ms if self.last_state.available else None)
        errors = [issue for issue in issues if issue.severity == "error"]
        message = "No issues found. This LRC is ready to save." if not issues else "\n".join(self._format_issue(issue) for issue in issues)
        box = QMessageBox(self)
        box.setWindowTitle("Quality Check")
        box.setIcon(QMessageBox.Warning if issues else QMessageBox.Information)
        box.setText(message)
        box.setDetailedText("\n".join(f"{format_position(line.timestamp_ms)} {line.text}" for line in self.lines if line.timestamp_ms is not None))
        box.exec()
        if errors:
            self._select_issue(errors[0])
        return not errors

    def _format_issue(self, issue: ValidationIssue) -> str:
        location = f"Line {issue.line_index + 1}: " if issue.line_index is not None else ""
        return f"{location}{issue.message}"

    def _select_issue(self, issue: ValidationIssue) -> None:
        if issue.line_index is not None:
            self.current_index = issue.line_index
            self._set_active_line(issue.line_index)

    def save_file(self) -> None:
        if self.current_lrc_path is None:
            self.save_file_as()
            return
        self._save_to_path(self.current_lrc_path)

    def save_file_as(self) -> None:
        if not self.lines:
            self.statusBar().showMessage("There are no lyrics to save.")
            return
        initial = str(self.current_lrc_path or self._documents_path() / self._suggested_filename())
        path, _ = QFileDialog.getSaveFileName(self, "Save LRC As", initial, "LRC files (*.lrc)")
        if path:
            output = Path(path).with_suffix(".lrc")
            self._save_to_path(output)

    def _save_to_path(self, path: Path) -> None:
        if not self.quality_check():
            return
        if count_unstamped(self.lines) and QMessageBox.question(self, "Save incomplete lyrics", "Unstamped lines are skipped in the exported LRC. Continue?") != QMessageBox.Yes:
            return
        try:
            write_lrc_file(path, self.lines)
        except OSError as exc:
            self._show_error("Save failed", f"Could not save {path.name}: {exc}")
            return
        self.current_lrc_path = path
        self.clean_history_index = self.history_index
        self.recovery_store.clear()
        self._remember_path(path)
        self._refresh_document_ui()
        self.statusBar().showMessage(f"Saved {path}")

    def import_from_lrclib(self) -> None:
        title = self.last_state.title.strip()
        artist = self.last_state.artist.strip()
        if not title:
            self._show_error("LRCLIB import", "Play a Spotify track first so LRCLIB can search by title and artist.")
            return
        self.statusBar().showMessage("Searching LRCLIB...")
        future = self.command_executor.submit(lrclib.search, title, artist, (self.last_state.duration_ms or 0) / 1000)
        QTimer.singleShot(100, lambda: self._finish_lrclib_search(future))

    def _finish_lrclib_search(self, future: Future) -> None:
        if not future.done():
            QTimer.singleShot(100, lambda: self._finish_lrclib_search(future))
            return
        try:
            candidates = future.result()
        except lrclib.LrcLibError as exc:
            self._show_error("LRCLIB import", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - network library may expose platform-specific errors.
            self._show_error("LRCLIB import", f"Unexpected LRCLIB error: {exc}")
            return
        if not candidates:
            self.statusBar().showMessage("LRCLIB found no lyrics for this track.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Choose lyrics from LRCLIB")
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        for candidate in candidates:
            kind = "Synced" if candidate.is_synced else "Plain"
            item = QListWidgetItem(f"{candidate.artist_name} - {candidate.track_name} ({candidate.duration_seconds:.0f}s, {kind})")
            item.setData(Qt.UserRole, candidate)
            choices.addItem(item)
        choices.setCurrentRow(0)
        layout.addWidget(QLabel("Choose a result. Importing replaces the current draft after confirmation."))
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted or choices.currentItem() is None:
            return
        if not self._confirm_discard("replace the current draft"):
            return
        selected = choices.currentItem().data(Qt.UserRole)
        lyrics = selected.synced_lyrics or selected.plain_lyrics or ""
        self.lines = parse_lrc(lyrics) if selected.synced_lyrics else merge_editor_lines([], lyrics)
        self.current_index = 0
        self.current_lrc_path = None
        self._reset_history(clean=False)
        self._set_editor_text("\n".join(line.text for line in self.lines))
        self.stack.setCurrentWidget(self.editor_page)
        self.statusBar().showMessage("Imported lyrics from LRCLIB. Review them before saving.")

    def _poll_media_state(self) -> None:
        if self.pending_state is None:
            self.pending_state = self.poll_executor.submit(media_session.get_media_state)
            return
        if not self.pending_state.done():
            return
        try:
            self.last_state = self.pending_state.result()
        except Exception as exc:  # noqa: BLE001 - worker exceptions must not terminate the UI loop.
            self.last_state = MediaState(False, message=f"Media polling failed: {exc}")
        self.pending_state = None
        self._render_media_state()

    def _render_media_state(self) -> None:
        state = self.last_state
        self.track_label.setText(f"{state.title or 'No Spotify track'} - {state.artist or 'Waiting for media session'}")
        self.track_status.setText(state.playback_status)
        self.message_label.setText("" if state.available else state.message)
        position = self._current_media_position_ms() or 0
        duration = state.duration_ms or 0
        self.position_label.setText(format_position(position))
        self.duration_label.setText(format_position(duration))
        self.progress_slider.setRange(0, max(duration, 1))
        if not self.dragging_progress:
            self.progress_slider.setValue(min(position, max(duration, 1)))
        available = state.available
        for widget in (self.play_pause_button, self.previous_button, self.next_button, self.progress_slider):
            widget.setEnabled(available)
        self.play_pause_button.setText("Pause" if state.playback_status.lower() == "playing" else "Play")

    def _current_media_position_ms(self) -> int | None:
        if self.last_state.position_ms is None:
            return None
        position = self.last_state.position_ms
        if self.last_state.playback_status.lower() == "playing":
            position += max(0, int((monotonic() - self.last_state.sampled_at) * 1000))
        return min(position, self.last_state.duration_ms) if self.last_state.duration_ms else position

    def _track_key(self) -> tuple[str, str, int | None]:
        return (self.last_state.title.strip().casefold(), self.last_state.artist.strip().casefold(), self.last_state.duration_ms)

    def _track_is_safe(self) -> bool:
        current = self._track_key()
        if not self.last_state.available:
            self.statusBar().showMessage("Spotify is not available.")
            return False
        if self.locked_track is None:
            self.locked_track = current
            return True
        if current == self.locked_track:
            return True
        if QMessageBox.question(self, "Track changed", "Spotify changed tracks. Relock this draft to the new track?") == QMessageBox.Yes:
            self.locked_track = current
            return True
        return False

    def _run_media_command(self, command, action: str) -> None:
        future = self.command_executor.submit(command)
        QTimer.singleShot(100, lambda: self._finish_media_command(future, action))

    def _finish_media_command(self, future: Future, action: str) -> None:
        if not future.done():
            QTimer.singleShot(100, lambda: self._finish_media_command(future, action))
            return
        result = future.result()
        self.statusBar().showMessage(f"{action} completed." if result.success else result.message)

    def _seek_to_slider_position(self) -> None:
        self.dragging_progress = False
        self._run_media_command(lambda: media_session.seek_to(self.progress_slider.value()), "Seek")

    def _render_rows(self) -> None:
        self.row_widgets, self.time_labels = [], []
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, line in enumerate(self.lines):
            row = self._build_lyric_row(index, line)
            self.rows_layout.addWidget(row)
            self.row_widgets.append(row)
        self.rows_layout.addStretch()

    def _build_lyric_row(self, index: int, line: LyricLine) -> QFrame:
        row = QFrame()
        row.setObjectName("lyricRow")
        row.setProperty("active", index == self.current_index)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 8, 14, 8)
        row_layout.setSpacing(12)

        clear = QPushButton("X")
        clear.setObjectName("iconButton")
        clear.setToolTip("Remove this line timestamp")
        clear.setAccessibleName("Clear timestamp")
        clear.clicked.connect(lambda _=False: self.clear_line_timestamp(index))

        minus_big, minus, plus, plus_big = (self._small_button(text) for text in ("<<", "<", ">", ">>"))
        for button, tooltip in zip((minus_big, minus, plus, plus_big), ("Subtract one second", "Subtract 100 milliseconds", "Add 100 milliseconds", "Add one second")):
            button.setToolTip(tooltip)
        minus_big.clicked.connect(lambda _=False: self.adjust_line(index, -1000))
        minus.clicked.connect(lambda _=False: self.adjust_line(index, -100))
        plus.clicked.connect(lambda _=False: self.adjust_line(index, 100))
        plus_big.clicked.connect(lambda _=False: self.adjust_line(index, 1000))

        time = QLabel(format_position(line.timestamp_ms))
        time.setObjectName("timePill")
        time.setAlignment(Qt.AlignCenter)
        self.time_labels.append(time)
        controls = QFrame()
        controls.setObjectName("controlGroup")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(6, 0, 6, 0)
        controls_layout.setSpacing(0)
        for widget in (minus_big, minus, time, plus, plus_big):
            controls_layout.addWidget(widget)

        preview = QPushButton("Play")
        preview.setObjectName("playRowButton")
        preview.setToolTip("Preview this timestamp")
        preview.clicked.connect(lambda _=False: self.preview_line(index))
        lyric = QLabel(line.text)
        lyric.setObjectName("lyricText")
        lyric.setWordWrap(True)
        for widget in (clear, controls, preview, lyric):
            row_layout.addWidget(widget)
        row_layout.setStretch(3, 1)
        return row

    def _small_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("smallButton")
        return button

    def _refresh_row_timestamp(self, index: int) -> None:
        if 0 <= index < len(self.time_labels):
            self.time_labels[index].setText(format_position(self.lines[index].timestamp_ms))

    def _set_active_line(self, index: int) -> None:
        if not 0 <= index < len(self.lines):
            return
        self.current_index = index
        for row_index, row in enumerate(self.row_widgets):
            row.setProperty("active", row_index == index)
            row.style().unpolish(row)
            row.style().polish(row)

    def _next_unstamped_index(self) -> int | None:
        for index in range(self.current_index, len(self.lines)):
            if self.lines[index].timestamp_ms is None:
                return index
        return next((index for index, line in enumerate(self.lines) if line.timestamp_ms is None), None)

    def _refresh_document_ui(self) -> None:
        count = len(self.lines)
        self.line_count_label.setText(f"{count} line{'s' if count != 1 else ''}, {count_unstamped(self.lines)} unstamped")
        self.undo_button.setEnabled(self.history_index > 0)
        self.redo_button.setEnabled(self.history_index < len(self.history) - 1)
        self.undo_action.setEnabled(self.undo_button.isEnabled())
        self.redo_action.setEnabled(self.redo_button.isEnabled())
        dirty = self.history_index != self.clean_history_index
        label = self.current_lrc_path.name if self.current_lrc_path else "Untitled LRC"
        self.setWindowTitle(f"{'* ' if dirty else ''}{label} - Spotify LRC Maker")
        self._refresh_recent_files()

    def _confirm_discard(self, action: str) -> bool:
        if self.history_index == self.clean_history_index:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f"Save changes before you {action}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Save:
            self.save_file()
            return self.history_index == self.clean_history_index
        return answer == QMessageBox.Discard

    def _navigate_home(self) -> None:
        if self._confirm_discard("return home"):
            self.stack.setCurrentWidget(self.home_page)

    def _schedule_autosave(self) -> None:
        if self.history_index != self.clean_history_index:
            self.autosave_timer.start()

    def _autosave(self) -> None:
        if self.history_index != self.clean_history_index:
            try:
                self.recovery_store.save(self.lines, self.current_lrc_path, self.current_index, self.capture_offset_ms)
            except OSError:
                self.statusBar().showMessage("Could not save recovery draft.")

    def _restore_recovery(self) -> None:
        recovery = self.recovery_store.load()
        if recovery is None:
            self._reset_history(clean=True)
            return
        if QMessageBox.question(self, "Recover draft", "Recover the unsaved draft from the previous session?") != QMessageBox.Yes:
            self.recovery_store.clear()
            self._reset_history(clean=True)
            return
        self.lines, self.current_lrc_path, self.current_index, self.capture_offset_ms = recovery
        self.offset_spin.setValue(self.capture_offset_ms)
        self._reset_history(clean=False)
        self._set_editor_text("\n".join(line.text for line in self.lines))
        self.stack.setCurrentWidget(self.editor_page)

    def _remember_path(self, path: Path) -> None:
        self.settings.setValue("last_directory", str(path.parent))
        recent = [item for item in self.settings.value("recent_files", [], type=list) if item != str(path)]
        self.settings.setValue("recent_files", [str(path), *recent][:5])

    def _refresh_recent_files(self) -> None:
        self.recent_list.clear()
        existing = [path for item in self.settings.value("recent_files", [], type=list) if (path := Path(item)).exists()]
        self.settings.setValue("recent_files", [str(path) for path in existing])
        for path in existing:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.UserRole, str(path))
            self.recent_list.addItem(item)

    def _documents_path(self) -> Path:
        return Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or Path.home() / "Documents")

    def _suggested_filename(self) -> str:
        name = " - ".join(part for part in (self.last_state.artist.strip(), self.last_state.title.strip()) if part) or "lyrics"
        return "".join(character for character in name if character not in '<>:"/\\|?*').rstrip(". ") + ".lrc"

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def dragEnterEvent(self, event) -> None:
        has_lyrics = event.mimeData().hasUrls() and any(
            url.toLocalFile().lower().endswith((".lrc", ".txt"))
            for url in event.mimeData().urls()
        )
        if has_lyrics:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths and self._confirm_discard("open a dropped file"):
            self._open_path(paths[0])
            event.acceptProposedAction()

    def keyPressEvent(self, event) -> None:
        if self.stack.currentWidget() is self.stamp_page and event.key() == Qt.Key_Space and not event.modifiers():
            self.stamp_next_line()
            event.accept()
            return
        if event.key() == Qt.Key_F11 and not event.modifiers():
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if not self._confirm_discard("close the application"):
            event.ignore()
            return
        self._autosave()
        self.poll_executor.shutdown(wait=False, cancel_futures=True)
        self.command_executor.shutdown(wait=False, cancel_futures=True)
        event.accept()

    def _apply_styles(self) -> None:
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #101010; color: #e8f3ff; }
            QMenuBar, QMenu, QStatusBar { background: #151515; color: #d6e7ff; }
            QMenu { border: 1px solid #3a3a3a; padding: 6px; }
            QMenu::item { padding: 8px 32px 8px 12px; min-height: 22px; border-radius: 4px; }
            QMenu::item:selected { background: #236dff; color: white; }
            QMenu::item:disabled { color: #777; }
            QMenu::separator { height: 1px; background: #383838; margin: 6px 4px; }
            #title { color: #58a6ff; font-size: 30px; font-weight: 700; }
            #section { color: #d6e7ff; font-size: 16px; font-weight: 700; }
            #muted { color: #91a8c1; }
            #warning { color: #8fc5ff; min-height: 20px; }
            #trackHeader, #playbackBar { background: #101010; border: 0; }
            #trackTitle { color: #eef6ff; font-size: 16px; font-weight: 700; }
            #trackArtist { color: #8ba8c8; }
            #warningText { color: #7dbaff; }
            QPushButton { background: #292929; border: 1px solid #414141; border-radius: 6px; padding: 7px 11px; color: #e8f3ff; }
            QPushButton:hover { background: #363636; } QPushButton:disabled { color: #777; background: #1a1a1a; }
            #primary { background: #236dff; border-color: #4b90ff; color: white; font-weight: 700; }
            #primary:hover { background: #357cff; }
            #secondaryButton { background: #1e1e1e; border-color: #343434; }
            #ghostButton { background: transparent; border-color: #343434; }
            QPlainTextEdit, QListWidget, QScrollArea { background: #161616; border: 1px solid #343434; border-radius: 6px; }
            QSpinBox { background: #202020; border: 1px solid #444; border-radius: 5px; padding: 5px; }
            #lyricRow { background: #101010; border: 0; border-radius: 6px; }
            #lyricRow[active="true"] { border: 1px solid #236dff; background: #101010; }
            #controlGroup { background: #2d2d2d; border-radius: 18px; }
            #timePill { color: #eef6ff; min-width: 74px; padding: 8px 10px; font-weight: 650; }
            #lyricText { color: #59aaff; font-size: 15px; font-weight: 650; }
            #smallButton { background: transparent; border: 0; color: #edf6ff; min-width: 34px; max-width: 42px; padding: 6px; border-radius: 14px; }
            #smallButton:hover { background: #3a3a3a; }
            #iconButton, #playRowButton, #roundButton { background: #2a2a2a; color: #edf6ff; min-width: 38px; max-width: 54px; min-height: 34px; border: 0; border-radius: 17px; padding: 6px 8px; }
            #playRowButton { min-width: 46px; }
            #iconButton:hover, #playRowButton:hover { background: #373737; }
            #playButton { background: white; color: #111; min-width: 46px; max-width: 56px; min-height: 36px; border: 0; border-radius: 18px; padding: 6px 10px; }
            #roundButton { background: transparent; }
            #roundButton:hover { background: #252525; }
            #secondaryActionButton, #dangerActionButton { min-width: 72px; min-height: 36px; border-radius: 8px; padding: 7px 10px; font-weight: 700; }
            #secondaryActionButton { background: #262626; border-color: #3a3a3a; }
            #dangerActionButton { background: #331f1f; color: #ffdede; border-color: #7a3434; }
            #navButton, #navButtonLight { min-height: 48px; min-width: 150px; border: 0; border-radius: 8px; font-size: 18px; }
            #navButton { background: #333; color: #9a9a9a; }
            #navButtonLight { background: #f5f5f5; color: #101010; }
            #navButtonLight:hover { background: #dceaff; }
            QSlider::groove:horizontal { height: 5px; background: #353535; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #236dff; } QSlider::handle:horizontal { width: 15px; margin: -5px 0; background: white; border-radius: 7px; }
        """)
