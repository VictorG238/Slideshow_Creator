"""Main window scaffold for the slideshow creator app."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QFileInfo, Qt, QUrl, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QCheckBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QProgressBar,
    QMessageBox,
    QFileIconProvider,
    QSizePolicy,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QColorDialog,
    QFileDialog,
    QGraphicsDropShadowEffect,
)

from slideshow_creator import __version__
from slideshow_creator.ui.styles import (
    APP_MIN_HEIGHT, APP_MIN_WIDTH, DEFAULT_COUNTDOWN_BG, build_app_stylesheet,
    KPI_ACCENT_NEXT, KPI_ACCENT_SLIDES, KPI_ACCENT_IMAGES, KPI_ACCENT_EXPORT,
)

if TYPE_CHECKING:
    from slideshow_creator.services.slideshow_builder import BuildResult


class MainWindow(QMainWindow):
    """Base main window scaffold used by subsequent task phases."""

    generation_requested = Signal(str, int, str, object)
    export_requested = Signal(float, str, str)
    audio_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Search to Slideshow Creator")
        self.setMinimumSize(APP_MIN_WIDTH, APP_MIN_HEIGHT)
        self.setStyleSheet(build_app_stylesheet())
        self._selected_color = DEFAULT_COUNTDOWN_BG
        self._setup_ui()
        self._set_phase_status("idle", level="info")
        self.kpi_next_action_value.setText("Enter a search term and click Generate slideshow")
        self.statusBar().showMessage("Ready. Enter search term and slide count.")

    def _setup_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("rootContainer")
        root_layout = QVBoxLayout(root)

        scroll = QScrollArea(root)
        scroll.setObjectName("mainScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setObjectName("mainScrollViewport")

        content = QWidget(scroll)
        content.setObjectName("scrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)

        title = QLabel("Slideshow Creator", content)
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("title")

        subtitle = QLabel("Generate a countdown slideshow from internet images.", content)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("subtitle")

        badge = QLabel(f"DESKTOP  •  v{__version__}", content)
        badge.setAlignment(Qt.AlignCenter)
        badge.setObjectName("headerBadge")

        self.summary_strip = self._build_summary_strip(content)

        self.section_inputs = self._build_input_section(content)
        self.section_audio = self._build_audio_section(content)
        self.section_export = self._build_export_section(content)
        self.section_preview = self._build_preview_section(content)

        self.section_cards = [
            self.section_inputs,
            self.section_audio,
            self.section_export,
            self.section_preview,
        ]

        self.sections_grid = QGridLayout()
        self.sections_grid.setContentsMargins(0, 0, 0, 0)
        self.sections_grid.setHorizontalSpacing(12)
        self.sections_grid.setVerticalSpacing(12)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(badge)
        layout.addSpacing(4)
        layout.addWidget(self.summary_strip)
        layout.addSpacing(4)
        layout.addLayout(self.sections_grid)

        self._watermark_label = QLabel("Aquiles/VictorBaeza.", content)
        self._watermark_label.setObjectName("hiddenWatermark")
        self._watermark_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self._watermark_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._watermark_label.setMinimumHeight(10)
        self._watermark_label.setToolTip("")
        layout.addWidget(self._watermark_label)

        layout.addStretch(1)

        scroll.setWidget(content)
        root_layout.addWidget(scroll)
        self.setCentralWidget(root)

        def _apply_shadow(widget: QWidget, blur: int = 35, alpha: int = 110, y_off: int = 10) -> None:
            shadow = QGraphicsDropShadowEffect(widget)
            shadow.setBlurRadius(blur)
            shadow.setColor(QColor(0, 0, 0, alpha))
            shadow.setOffset(0, y_off)
            widget.setGraphicsEffect(shadow)

        _apply_shadow(self.summary_strip)
        for card in self.section_cards:
            _apply_shadow(card)
        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(250)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)

        self._reflow_sections(self.width())

    def _build_summary_strip(self, parent: QWidget) -> QFrame:
        strip = QFrame(parent)
        strip.setObjectName("summaryBar")
        grid = QGridLayout(strip)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.kpi_next_action_value = self._create_kpi_card(grid, 0, 0, "Next Action", "Waiting for input", KPI_ACCENT_NEXT)
        self.kpi_slides_value = self._create_kpi_card(grid, 0, 1, "Slides", "--", KPI_ACCENT_SLIDES)
        self.kpi_images_value = self._create_kpi_card(grid, 1, 0, "Images Found", "--", KPI_ACCENT_IMAGES)
        self.kpi_export_value = self._create_kpi_card(grid, 1, 1, "Export", "Not started", KPI_ACCENT_EXPORT)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return strip

    def _create_kpi_card(self, layout: QGridLayout, row: int, col: int, title: str, value: str, accent_color: str = "#6366f1") -> QLabel:
        card = QFrame(self)
        card.setObjectName("kpiCard")
        card.setStyleSheet(f"QFrame#kpiCard {{ border-top: 3px solid {accent_color}; background: rgba(17, 24, 39, 200); border-radius: 10px; border-left: none; border-right: none; border-bottom: none; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(4)

        title_label = QLabel(title, card)
        title_label.setObjectName("kpiTitle")
        value_label = QLabel(value, card)
        value_label.setObjectName("kpiValue")
        value_label.setWordWrap(True)

        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        layout.addWidget(card, row, col)
        return value_label

    def _reflow_sections(self, width: int) -> None:
        if width < 1080:
            self.sections_grid.addWidget(self.section_inputs, 0, 0)
            self.sections_grid.addWidget(self.section_audio, 1, 0)
            self.sections_grid.addWidget(self.section_export, 2, 0)
            self.sections_grid.addWidget(self.section_preview, 3, 0)
            self.sections_grid.setColumnStretch(0, 1)
            self.sections_grid.setColumnStretch(1, 0)
            return

        self.sections_grid.addWidget(self.section_inputs, 0, 0)
        self.sections_grid.addWidget(self.section_audio, 1, 0)
        self.sections_grid.addWidget(self.section_export, 0, 1)
        self.sections_grid.addWidget(self.section_preview, 1, 1)
        self.sections_grid.setColumnStretch(0, 1)
        self.sections_grid.setColumnStretch(1, 1)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reflow_sections(event.size().width())

    def _build_input_section(self, parent: QWidget) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)

        title = QLabel("Search", card)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        body = QLabel("Find images from the web and set the countdown style.", card)
        body.setObjectName("sectionBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        sep = QFrame(card)
        sep.setObjectName("sectionSep")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        form = QGridLayout()

        search_label = QLabel("Search term", card)
        search_label.setObjectName("fieldLabel")
        self.search_input = QLineEdit(card)
        self.search_input.setPlaceholderText("e.g. car")
        self.search_input.setToolTip("Search public image sources for this term.")

        count_label = QLabel("Slide count", card)
        count_label.setObjectName("fieldLabel")
        self.count_input = QSpinBox(card)
        self.count_input.setRange(1, 500)
        self.count_input.setValue(50)
        self.count_input.setToolTip("Number of slideshow slides to generate.")

        engines_label = QLabel("Search engines", card)
        engines_label.setObjectName("fieldLabel")
        engines_row = QHBoxLayout()
        self.engine_google_checkbox = QCheckBox("Google", card)
        self.engine_google_checkbox.setChecked(True)
        self.engine_google_checkbox.setToolTip("Use Google Images as a source.")
        self.engine_bing_checkbox = QCheckBox("Bing", card)
        self.engine_bing_checkbox.setChecked(True)
        self.engine_bing_checkbox.setToolTip("Use Bing Images as a source.")
        self.engine_duckduckgo_checkbox = QCheckBox("DuckDuckGo", card)
        self.engine_duckduckgo_checkbox.setChecked(True)
        self.engine_duckduckgo_checkbox.setToolTip("Use DuckDuckGo Images as a source.")
        engines_row.addWidget(self.engine_google_checkbox)
        engines_row.addWidget(self.engine_bing_checkbox)
        engines_row.addWidget(self.engine_duckduckgo_checkbox)
        engines_row.addStretch(1)

        color_label = QLabel("Countdown background", card)
        color_label.setObjectName("fieldLabel")
        color_row = QHBoxLayout()
        self.color_swatch = QLabel(card)
        self.color_swatch.setObjectName("colorSwatch")
        self.color_swatch.setMinimumWidth(120)
        self.color_swatch.setToolTip("Current countdown background color.")
        self._refresh_color_swatch()

        self.pick_color_button = QPushButton("Pick color", card)
        self.pick_color_button.clicked.connect(self._on_pick_color)
        self.pick_color_button.setToolTip("Choose the countdown background color.")
        color_row.addWidget(self.color_swatch)
        color_row.addWidget(self.pick_color_button)
        color_row.addStretch(1)

        self.generate_button = QPushButton("Generate slideshow", card)
        self.generate_button.clicked.connect(self._on_generate_clicked)
        self.generate_button.setToolTip("Search images and build the slideshow preview.")

        form.addWidget(search_label, 0, 0)
        form.addWidget(self.search_input, 0, 1)
        form.addWidget(engines_label, 1, 0)
        form.addLayout(engines_row, 1, 1)
        form.addWidget(count_label, 2, 0)
        form.addWidget(self.count_input, 2, 1)
        form.addWidget(color_label, 3, 0)
        form.addLayout(color_row, 3, 1)
        form.addWidget(self.generate_button, 4, 1)

        layout.addLayout(form)
        return card

    def _build_audio_section(self, parent: QWidget) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)

        title = QLabel("Media", card)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        body = QLabel("Optional background music. Leave it empty for a silent export.", card)
        body.setObjectName("sectionBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        sep = QFrame(card)
        sep.setObjectName("sectionSep")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        form = QGridLayout()

        audio_label = QLabel("MP3 file", card)
        audio_label.setObjectName("fieldLabel")
        audio_row = QHBoxLayout()
        self.audio_path_input = QLineEdit(card)
        self.audio_path_input.setPlaceholderText("Choose a background MP3...")
        self.audio_path_input.setReadOnly(True)
        self.audio_path_input.setToolTip("Optional local MP3 file used as background music.")
        self.audio_browse_button = QPushButton("Browse", card)
        self.audio_browse_button.setObjectName("secondaryButton")
        self.audio_browse_button.clicked.connect(self._on_browse_audio)
        self.audio_browse_button.setToolTip("Pick an MP3 file from disk.")
        self.audio_clear_button = QPushButton("Clear", card)
        self.audio_clear_button.setObjectName("secondaryButton")
        self.audio_clear_button.clicked.connect(self._on_clear_audio)
        self.audio_clear_button.setToolTip("Remove the selected MP3 file.")
        audio_row.addWidget(self.audio_path_input)
        audio_row.addWidget(self.audio_browse_button)
        audio_row.addWidget(self.audio_clear_button)

        status_label = QLabel("Audio status", card)
        status_label.setObjectName("fieldLabel")
        self.audio_status_label = QLabel("No MP3 selected.", card)
        self.audio_status_label.setObjectName("audioStatus")
        self.audio_status_label.setWordWrap(True)

        form.addWidget(audio_label, 0, 0)
        form.addLayout(audio_row, 0, 1)
        form.addWidget(status_label, 1, 0)
        form.addWidget(self.audio_status_label, 1, 1)

        layout.addLayout(form)
        return card

    def _build_export_section(self, parent: QWidget) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)

        title = QLabel("Export", card)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        body = QLabel("Choose the output size, format, and destination file.", card)
        body.setObjectName("sectionBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        sep = QFrame(card)
        sep.setObjectName("sectionSep")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        form = QGridLayout()

        size_label = QLabel("Target size (MB)", card)
        size_label.setObjectName("fieldLabel")
        self.target_size_input = QDoubleSpinBox(card)
        self.target_size_input.setRange(1.0, 1024.0)
        self.target_size_input.setDecimals(1)
        self.target_size_input.setSingleStep(0.5)
        self.target_size_input.setValue(10.0)
        self.target_size_input.setToolTip("Target maximum export size in megabytes.")

        format_label = QLabel("Preferred format", card)
        format_label.setObjectName("fieldLabel")
        self.format_input = QComboBox(card)
        self.format_input.addItems(["mp4", "webm"])
        self.format_input.setToolTip("Preferred export container. The app falls back to a playable alternative when needed.")

        output_label = QLabel("Output file", card)
        output_label.setObjectName("fieldLabel")
        output_row = QHBoxLayout()
        self.output_path_input = QLineEdit(card)
        self.output_path_input.setPlaceholderText("Choose output location...")
        self.output_path_input.setToolTip("Destination file path for the exported slideshow video.")
        self.output_browse_button = QPushButton("Browse", card)
        self.output_browse_button.setObjectName("secondaryButton")
        self.output_browse_button.clicked.connect(self._on_browse_output)
        self.output_browse_button.setToolTip("Choose where to save the exported video.")
        output_row.addWidget(self.output_path_input)
        output_row.addWidget(self.output_browse_button)

        encoder_label = QLabel("Encoding engine", card)
        encoder_label.setObjectName("fieldLabel")
        self.encoder_status_label = QLabel("Pending", card)
        self.encoder_status_label.setObjectName("encoderStatus")
        self.encoder_status_label.setWordWrap(True)
        self.encoder_status_label.setToolTip("Shows whether export used NVIDIA NVENC or CPU fallback.")

        self.export_button = QPushButton("Export video", card)
        self.export_button.clicked.connect(self._on_export_clicked)
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("Export the generated slideshow using the selected settings.")

        form.addWidget(size_label, 0, 0)
        form.addWidget(self.target_size_input, 0, 1)
        form.addWidget(format_label, 1, 0)
        form.addWidget(self.format_input, 1, 1)
        form.addWidget(output_label, 2, 0)
        form.addLayout(output_row, 2, 1)
        form.addWidget(encoder_label, 3, 0)
        form.addWidget(self.encoder_status_label, 3, 1)
        form.addWidget(self.export_button, 4, 1)

        layout.addLayout(form)
        return card

    def _build_preview_section(self, parent: QWidget) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(card)

        title = QLabel("Preview", card)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        body = QLabel("Generation progress, warnings, and a compact slide preview.", card)
        body.setObjectName("sectionBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        sep = QFrame(card)
        sep.setObjectName("sectionSep")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        self.progress_label = QLabel("Waiting for generation request.", card)
        self.progress_label.setObjectName("progressLabel")

        phase_row = QHBoxLayout()
        self.phase_icon_label = QLabel("[READY]", card)
        self.phase_icon_label.setObjectName("phaseStatusInfo")
        self.phase_text_label = QLabel("Idle", card)
        self.phase_text_label.setObjectName("phaseStatusInfo")
        phase_row.addWidget(self.phase_icon_label)
        phase_row.addWidget(self.phase_text_label)
        phase_row.addStretch(1)

        self.progress_bar = QProgressBar(card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

        self.preview_card = QFrame(card)
        self.preview_card.setObjectName("previewCard")
        preview_layout = QVBoxLayout(self.preview_card)
        self.preview_text = QPlainTextEdit(self.preview_card)
        self.preview_text.setObjectName("previewText")
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(220)
        self.preview_text.setPlaceholderText("Slide preview and warnings will appear here.")
        preview_layout.addWidget(self.preview_text)

        layout.addWidget(self.progress_label)
        layout.addLayout(phase_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.preview_card)
        return card

    def _set_phase_status(self, phase: str, level: str = "info") -> None:
        icon_map = {
            "idle": "READY",
            "image_search": "SEARCHING",
            "build": "BUILDING",
            "export": "EXPORTING",
            "done": "DONE",
            "error": "ERROR",
            "warn": "WARN",
        }
        text_map = {
            "idle": "Idle",
            "image_search": "Searching images",
            "build": "Building slideshow",
            "export": "Exporting video",
            "done": "Completed",
            "error": "Error",
            "warn": "Warning",
        }
        style_map = {
            "info": "phaseStatusInfo",
            "done": "phaseStatusDone",
            "error": "phaseStatusError",
            "warn": "phaseStatusWarn",
        }

        self.phase_icon_label.setText(icon_map.get(phase, "[INFO]"))
        self.phase_text_label.setText(text_map.get(phase, "In progress"))

        style_name = style_map.get(level, "phaseStatusInfo")
        self.phase_icon_label.setObjectName(style_name)
        self.phase_text_label.setObjectName(style_name)
        self.phase_icon_label.style().unpolish(self.phase_icon_label)
        self.phase_icon_label.style().polish(self.phase_icon_label)
        self.phase_text_label.style().unpolish(self.phase_text_label)
        self.phase_text_label.style().polish(self.phase_text_label)

    def _refresh_color_swatch(self) -> None:
        self.color_swatch.setText(self._selected_color)
        self.color_swatch.setAlignment(Qt.AlignCenter)
        self.color_swatch.setStyleSheet(
            f"background: {self._selected_color}; color: #0f1720; font-weight: 700;"
        )

    def _on_pick_color(self) -> None:
        selected = QColorDialog.getColor(QColor(self._selected_color), self, "Choose countdown color")
        if selected.isValid():
            self._selected_color = selected.name(QColor.HexRgb)
            self._refresh_color_swatch()

    def _on_generate_clicked(self) -> None:
        search_term = self.search_input.text().strip()
        count = int(self.count_input.value())
        selected_engines = self._selected_search_engines()
        if not search_term:
            self.show_error("Search term is required.")
            return
        if count <= 0:
            self.show_error("Slide count must be greater than 0.")
            return
        if not selected_engines:
            self.show_error("Select at least one search engine.")
            return

        self.show_progress("Preparing generation request...")
        self.kpi_next_action_value.setText("Collecting images and building slideshow")
        self.kpi_slides_value.setText(str(count))
        self.kpi_images_value.setText("Searching...")
        self.kpi_export_value.setText("Pending")
        self.generation_requested.emit(search_term, count, self._selected_color, selected_engines)

    def _selected_search_engines(self) -> list[str]:
        selected: list[str] = []
        if self.engine_google_checkbox.isChecked():
            selected.append("google")
        if self.engine_bing_checkbox.isChecked():
            selected.append("bing")
        if self.engine_duckduckgo_checkbox.isChecked():
            selected.append("duckduckgo")
        return selected

    def _on_browse_audio(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose MP3 background music",
            "",
            "MP3 files (*.mp3);;All files (*.*)",
        )
        if selected:
            self.audio_path_input.setText(selected)
            self.audio_changed.emit(selected)

    def _on_clear_audio(self) -> None:
        self.audio_path_input.clear()
        self.audio_changed.emit("")

    def _on_browse_output(self) -> None:
        preferred = self.format_input.currentText().strip().lower()
        suffix = "mp4" if preferred == "mp4" else "webm"
        file_filter = "Video files (*.mp4 *.webm);;All files (*.*)"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Choose output video",
            f"slideshow_output.{suffix}",
            file_filter,
        )
        if selected:
            self.output_path_input.setText(selected)

    def _on_export_clicked(self) -> None:
        output_path = self.output_path_input.text().strip()
        if not output_path:
            self.show_error("Select an output file before exporting.")
            return

        target_size_mb = float(self.target_size_input.value())
        preferred_format = self.format_input.currentText().strip().lower()
        self.show_progress("Preparing export request...")
        self.kpi_next_action_value.setText("Encoding and muxing video")
        self.kpi_export_value.setText(f"Target {target_size_mb:.1f} MB ({preferred_format.upper()})")
        self.set_encoder_status("Detecting encoder capabilities...")
        self.export_requested.emit(target_size_mb, preferred_format, output_path)

    def set_busy(self, busy: bool) -> None:
        self.generate_button.setDisabled(busy)
        self.pick_color_button.setDisabled(busy)
        self.search_input.setDisabled(busy)
        self.engine_google_checkbox.setDisabled(busy)
        self.engine_bing_checkbox.setDisabled(busy)
        self.engine_duckduckgo_checkbox.setDisabled(busy)
        self.count_input.setDisabled(busy)
        self.audio_path_input.setDisabled(busy)
        self.audio_browse_button.setDisabled(busy)
        self.audio_clear_button.setDisabled(busy)
        self.target_size_input.setDisabled(busy)
        self.format_input.setDisabled(busy)
        self.output_path_input.setDisabled(busy)
        self.output_browse_button.setDisabled(busy)
        self.export_button.setDisabled(busy or not self.export_button.isEnabled())
        if busy and self.progress_bar.value() >= 100:
            self.progress_bar.setValue(0)

    def set_export_ready(self, ready: bool) -> None:
        self.export_button.setEnabled(ready)

    def show_progress(self, message: str, percent: float | None = None, phase: str | None = None) -> None:
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.style().unpolish(self.progress_label)
        self.progress_label.style().polish(self.progress_label)
        self.progress_label.setText(message)
        self.statusBar().showMessage(message)
        self.kpi_next_action_value.setText(message)

        codec = self._extract_codec_from_progress_message(message)
        if codec is not None:
            self.set_encoder_status(self._friendly_encoder_label(codec))

        if phase:
            self._set_phase_status(phase, level="info")
        if percent is not None:
            value = int(percent * 100) if percent <= 1.0 else int(percent)
            value = max(0, min(100, value))
            self._progress_animation.stop()
            self._progress_animation.setStartValue(self.progress_bar.value())
            self._progress_animation.setEndValue(value)
            self._progress_animation.start()

    @staticmethod
    def _extract_codec_from_progress_message(message: str) -> str | None:
        prefix = "Using codec "
        if not message.startswith(prefix):
            return None
        codec = message[len(prefix) :].split(" ", 1)[0].strip().lower()
        return codec or None

    @staticmethod
    def _friendly_encoder_label(codec: str) -> str:
        mapping = {
            "h264_nvenc": "NVIDIA NVENC (GPU)",
            "libx264": "CPU (libx264)",
            "h264": "CPU (H.264)",
            "libvpx-vp9": "CPU (VP9/WebM)",
        }
        return mapping.get(codec.lower(), f"Custom ({codec})")

    def show_error(self, message: str, hint: str | None = None) -> None:
        self.progress_label.setObjectName("errorLabel")
        self.progress_label.style().unpolish(self.progress_label)
        self.progress_label.style().polish(self.progress_label)
        full_msg = f"{message}\n({hint})" if hint else message
        self.progress_label.setText(full_msg)
        self._set_phase_status("error", level="error")
        self.kpi_next_action_value.setText(hint or "Review the error details and retry")
        self.kpi_export_value.setText("Failed")
        self.statusBar().showMessage(message)
        if not self._is_inline_validation_error(message):
            self._show_error_dialog(message, hint)

    @staticmethod
    def _is_inline_validation_error(message: str) -> bool:
        lowered = message.lower()
        inline_markers = [
            "search term is required",
            "select at least one search engine",
            "slide count must be greater than 0",
            "select an output file",
        ]
        return any(marker in lowered for marker in inline_markers)

    @staticmethod
    def _classify_error(message: str) -> tuple[str, QMessageBox.Icon]:
        lowered = message.lower()
        if any(token in lowered for token in ["network", "internet", "timeout", "download"]):
            return "Network", QMessageBox.Warning
        if any(token in lowered for token in ["mp3", "audio", "media", "codec", "ffmpeg"]):
            return "Media", QMessageBox.Warning
        if any(token in lowered for token in ["path", "folder", "file", "writable", "permission", "disk"]):
            return "System", QMessageBox.Critical
        if any(token in lowered for token in ["required", "invalid", "must", "empty"]):
            return "Input", QMessageBox.Information
        return "Error", QMessageBox.Critical

    def _show_error_dialog(self, message: str, hint: str | None = None) -> None:
        category, icon = self._classify_error(message)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(f"{category} issue")
        dialog.setIcon(icon)
        dialog.setText(message)
        if hint:
            dialog.setInformativeText(hint)

        retry_btn = dialog.addButton("Retry", QMessageBox.AcceptRole)
        open_folder_btn = None
        output_path = self.output_path_input.text().strip()
        if output_path:
            open_folder_btn = dialog.addButton("Open Output Folder", QMessageBox.ActionRole)
        dialog.addButton("Close", QMessageBox.RejectRole)
        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == retry_btn:
            return
        if open_folder_btn is not None and clicked == open_folder_btn:
            folder = str(Path(output_path).resolve().parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def set_audio_status(self, message: str, error: bool = False) -> None:
        self.audio_status_label.setObjectName("errorLabel" if error else "audioStatus")
        self.audio_status_label.style().unpolish(self.audio_status_label)
        self.audio_status_label.style().polish(self.audio_status_label)
        self.audio_status_label.setText(message)
        self.statusBar().showMessage(message)

    def set_encoder_status(self, message: str, error: bool = False) -> None:
        self.encoder_status_label.setObjectName("errorLabel" if error else "encoderStatus")
        self.encoder_status_label.style().unpolish(self.encoder_status_label)
        self.encoder_status_label.style().polish(self.encoder_status_label)
        self.encoder_status_label.setText(message)

    def show_generation_result(self, result: BuildResult) -> None:
        """Render a compact preview of generated slides and warnings."""
        lines = [
            f"Requested slides: {result.summary.requested_count}",
            f"Unique images available: {result.summary.available_images}",
            f"Image slots reused: {result.summary.reused_images}",
            "",
            "Preview (first 5 slides):",
        ]
        for frame in result.slides[:5]:
            lines.append(
                f"- #{frame.index + 1} | countdown={frame.countdown_value} | "
                f"label='{frame.label_text}' | image='{frame.image_ref[:70]}'"
            )

        if result.summary.warning:
            lines.extend(["", f"Warning: {result.summary.warning}"])

        self.preview_text.setPlainText("\n".join(lines))
        self.set_export_ready(True)
        self.kpi_slides_value.setText(str(result.summary.requested_count))
        self.kpi_images_value.setText(
            f"{result.summary.available_images} found / {result.summary.reused_images} reused"
        )
        self.kpi_export_value.setText("Ready to export")
        self.kpi_next_action_value.setText("Choose output path and click Export video")
        self.set_encoder_status("Pending (export not started)")
        if result.summary.warning:
            self._set_phase_status("warn", level="warn")
            self.show_error(result.summary.warning)
        else:
            self.progress_bar.setValue(100)
            self._set_phase_status("done", level="done")
            self.show_progress("Slideshow preview generated successfully.")

    def show_export_result(self, output_path: str, size_mb: float, video_codec: str | None = None) -> None:
        self.progress_bar.setValue(100)
        self._set_phase_status("done", level="done")
        self.show_progress(f"Export complete: {size_mb:.2f} MB")
        if video_codec is not None:
            self.set_encoder_status(self._friendly_encoder_label(video_codec))
        self.kpi_export_value.setText(f"Completed ({size_mb:.2f} MB)")
        self.kpi_next_action_value.setText("Open folder, play video, or start another run")
        self.preview_text.appendPlainText(
            f"\nExported file:\n- Path: {output_path}\n- Size: {size_mb:.2f} MB\n- Encoder: {self.encoder_status_label.text()}"
        )
        self._show_success_dialog(output_path, size_mb)

    def _show_success_dialog(self, output_path: str, size_mb: float) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Video created")
        dialog.setIcon(QMessageBox.Information)
        dialog.setText(f"Export completed successfully ({size_mb:.2f} MB).")
        dialog.setInformativeText(output_path)

        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(output_path))
        pixmap = icon.pixmap(96, 96)
        if not pixmap.isNull():
            dialog.setIconPixmap(pixmap)

        open_folder_btn = dialog.addButton("Open Folder", QMessageBox.ActionRole)
        play_video_btn = dialog.addButton("Play Video", QMessageBox.ActionRole)
        dialog.addButton("Close", QMessageBox.RejectRole)
        dialog.exec()

        clicked = dialog.clickedButton()
        output_file = str(Path(output_path).resolve())
        output_folder = str(Path(output_file).parent)

        if clicked == open_folder_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_folder))
        elif clicked == play_video_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_file))
