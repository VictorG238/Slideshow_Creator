"""pytest-qt tests for MainWindow UI behavior.

Covers:
  T039 – MP3 selection, export status updates, destination path handling
  T042 – Grouped dashboard sections, placeholders, tooltips
  T043 – Unwritable export destination recovery guidance (UI side)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from slideshow_creator.ui.main_window import MainWindow
from slideshow_creator.models.domain import SearchRunSummary, ShortfallReason
from slideshow_creator.services.slideshow_builder import BuildResult, BuildSummary, SlideFrame

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def window(qtbot):
    """Create a MainWindow and register it with qtbot for cleanup."""
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win

def _dummy_build_result(count: int = 3, include_search_summary: bool = False) -> BuildResult:
    slides = [
        SlideFrame(
            index=i,
            countdown_value=count - i,
            label_text=f"top {count} car" if i == 0 else str(count - i),
            image_ref=f"https://example.com/img{i}.jpg",
            overlay_color="#87CEEB",
        )
        for i in range(count)
    ]
    
    search_summary = None
    if include_search_summary:
        reasons = [ShortfallReason.LOW_AVAILABILITY] if count < 10 else []
        search_summary=SearchRunSummary(
            requested=count,
            discovered=count + 5,
            invalid_removed=1,
            duplicate_removed=4,
            selected=count,
            provider_logs={"google": count},
            shortfall_reasons=reasons,
            retry_suggestions=["Try fewer slides"] if reasons else []
        )

    return BuildResult(
        slides=slides,
        summary=BuildSummary(
            requested_count=count,
            available_images=count,
            reused_images=0,
            warning=None,
        ),
        search_summary=search_summary,
    )


# ===========================================================================
# T039 – MP3 selection, export status updates, and destination path handling
# ===========================================================================


class TestMp3SelectionAndStatus:
    """T039: Verify audio selection controls and status label behaviour."""

    def test_audio_status_label_shows_default_text(self, window: MainWindow) -> None:
        assert "No MP3 selected" in window.audio_status_label.text()

    def test_audio_changed_signal_emits_on_clear(self, window: MainWindow, qtbot) -> None:
        with qtbot.waitSignal(window.audio_changed, timeout=1000):
            window._on_clear_audio()
        assert window.audio_path_input.text() == ""

    def test_set_audio_status_shows_message(self, window: MainWindow) -> None:
        window.set_audio_status("MP3 ready: song.mp3 • 3.50s")
        assert "song.mp3" in window.audio_status_label.text()
        assert window.audio_status_label.objectName() == "audioStatus"

    def test_set_audio_status_with_error_flag_uses_error_style(self, window: MainWindow) -> None:
        window.set_audio_status("Invalid file.", error=True)
        assert window.audio_status_label.objectName() == "errorLabel"

    def test_browse_audio_updates_path_input(self, window: MainWindow, qtbot, tmp_path: Path) -> None:
        mp3_file = tmp_path / "song.mp3"
        mp3_file.write_bytes(b"fake-mp3")
        with patch(
            "slideshow_creator.ui.main_window.QFileDialog.getOpenFileName",
            return_value=(str(mp3_file), ""),
        ):
            with qtbot.waitSignal(window.audio_changed, timeout=1000):
                window._on_browse_audio()
        assert window.audio_path_input.text() == str(mp3_file)


class TestExportStatusUpdates:
    """T039: Verify export status label and button lifecycle."""

    def test_export_button_starts_disabled(self, window: MainWindow) -> None:
        assert not window.export_button.isEnabled()

    def test_export_button_enabled_after_generation_result(self, window: MainWindow) -> None:
        window.show_generation_result(_dummy_build_result())
        assert window.export_button.isEnabled()

    def test_encoder_status_shows_pending_before_export(self, window: MainWindow) -> None:
        assert "Pending" in window.encoder_status_label.text()

    def test_set_encoder_status_updates_label(self, window: MainWindow) -> None:
        window.set_encoder_status("NVIDIA NVENC (GPU)")
        assert "NVENC" in window.encoder_status_label.text()

    def test_show_export_result_updates_kpi(self, window: MainWindow) -> None:
        window.show_generation_result(_dummy_build_result())
        window.show_export_result("/out/video.mp4", 8.5, "h264_nvenc")
        assert "8.5" in window.kpi_export_value.text()
        assert "Completed" in window.kpi_export_value.text()


class TestDestinationPathHandling:
    """T039: Verify output file path selection and validation."""

    def test_browse_output_sets_path(self, window: MainWindow, qtbot) -> None:
        with patch(
            "slideshow_creator.ui.main_window.QFileDialog.getSaveFileName",
            return_value=("C:/Exports/video.mp4", ""),
        ):
            window._on_browse_output()
        assert window.output_path_input.text() == "C:/Exports/video.mp4"

    def test_export_click_without_output_path_shows_error(self, window: MainWindow) -> None:
        window.show_generation_result(_dummy_build_result())
        window.output_path_input.setText("")
        # Patch the dialog that show_error triggers
        with patch.object(window, "_show_error_dialog"):
            window._on_export_clicked()
        assert "output file" in window.progress_label.text().lower()


# ===========================================================================
# T042 – Grouped dashboard sections, placeholders, and tooltips
# ===========================================================================


class TestDashboardSections:
    """T042: Verify dashboard layout and section structure."""

    def test_four_section_cards_exist(self, window: MainWindow) -> None:
        assert len(window.section_cards) == 4

    def test_section_order_matches_spec(self, window: MainWindow) -> None:
        labels = []
        for card in window.section_cards:
            title_widget = card.findChild(type(window.search_input).__mro__[1].__mro__[0])
            labels.append(card)
        # Verify the four cards point to the expected attributes
        assert window.section_cards[0] is window.section_inputs
        assert window.section_cards[1] is window.section_audio
        assert window.section_cards[2] is window.section_export
        assert window.section_cards[3] is window.section_preview

    def test_kpi_summary_strip_exists(self, window: MainWindow) -> None:
        assert window.summary_strip is not None
        assert window.summary_strip.objectName() == "summaryBar"

    def test_kpi_cards_have_initial_values(self, window: MainWindow) -> None:
        assert window.kpi_slides_value.text() == "--"
        assert window.kpi_images_value.text() == "--"
        assert "Not started" in window.kpi_export_value.text()

    def test_kpi_updates_after_generation(self, window: MainWindow) -> None:
        window.show_generation_result(_dummy_build_result(5))
        assert window.kpi_slides_value.text() == "5"
        assert "5" in window.kpi_images_value.text()
        assert "Ready" in window.kpi_export_value.text()


class TestPlaceholders:
    """T042: Verify placeholder text on input controls."""

    def test_search_input_has_placeholder(self, window: MainWindow) -> None:
        assert window.search_input.placeholderText() != ""

    def test_audio_path_has_placeholder(self, window: MainWindow) -> None:
        assert "MP3" in window.audio_path_input.placeholderText()

    def test_output_path_has_placeholder(self, window: MainWindow) -> None:
        assert window.output_path_input.placeholderText() != ""

    def test_preview_text_has_placeholder(self, window: MainWindow) -> None:
        assert window.preview_text.placeholderText() != ""


class TestTooltips:
    """T042: Verify interactive controls have tooltips for accessibility."""

    def test_search_input_has_tooltip(self, window: MainWindow) -> None:
        assert window.search_input.toolTip() != ""

    def test_count_input_has_tooltip(self, window: MainWindow) -> None:
        assert window.count_input.toolTip() != ""

    def test_generate_button_has_tooltip(self, window: MainWindow) -> None:
        assert window.generate_button.toolTip() != ""

    def test_export_button_has_tooltip(self, window: MainWindow) -> None:
        assert window.export_button.toolTip() != ""

    def test_audio_browse_has_tooltip(self, window: MainWindow) -> None:
        assert window.audio_browse_button.toolTip() != ""

    def test_engine_checkboxes_have_tooltips(self, window: MainWindow) -> None:
        assert window.engine_google_checkbox.toolTip() != ""
        assert window.engine_bing_checkbox.toolTip() != ""
        assert window.engine_duckduckgo_checkbox.toolTip() != ""
        assert window.engine_openverse_checkbox.toolTip() != ""

    def test_target_size_has_tooltip(self, window: MainWindow) -> None:
        assert window.target_size_input.toolTip() != ""

    def test_format_input_has_tooltip(self, window: MainWindow) -> None:
        assert window.format_input.toolTip() != ""


# ===========================================================================
# T043 – Unwritable export destination: UI recovery guidance
# ===========================================================================


class TestUnwritableDestinationUi:
    """T043: Verify show_error surfaces recovery guidance for path errors."""

    def test_show_error_displays_hint_in_progress_label(self, window: MainWindow) -> None:
        with patch.object(window, "_show_error_dialog"):
            window.show_error(
                "Cannot write to the export folder '/readonly'.",
                hint="Choose a different destination.",
            )
        assert "Choose a different destination" in window.progress_label.text()

    def test_show_error_categorizes_path_errors_as_system(self, window: MainWindow) -> None:
        category, icon = window._classify_error(
            "Cannot write to the export folder '/readonly'. Permission denied."
        )
        assert category == "System"

    def test_show_error_updates_phase_status_to_error(self, window: MainWindow) -> None:
        with patch.object(window, "_show_error_dialog"):
            window.show_error("Write failed.")
        assert window.phase_icon_label.text() == "ERROR"

    def test_inline_validation_errors_skip_dialog(self, window: MainWindow) -> None:
        """Inline validation messages like 'Search term is required' should NOT
        open a blocking modal dialog."""
        assert window._is_inline_validation_error("Search term is required.")
        assert window._is_inline_validation_error("Select at least one search engine.")
        assert not window._is_inline_validation_error("FFmpeg failed to initialise.")


class TestSearchEngineCheckboxes:
    """Additional T042 coverage: search-engine selector wiring."""

    def test_all_engines_checked_by_default(self, window: MainWindow) -> None:
        assert window.engine_google_checkbox.isChecked()
        assert window.engine_bing_checkbox.isChecked()
        assert window.engine_duckduckgo_checkbox.isChecked()
        assert window.engine_openverse_checkbox.isChecked()

    def test_selected_engines_returns_checked_only(self, window: MainWindow) -> None:
        window.engine_bing_checkbox.setChecked(False)
        window.engine_openverse_checkbox.setChecked(False)
        engines = window._selected_search_engines()
        assert "google" in engines
        assert "bing" not in engines
        assert "openverse" not in engines
        assert "duckduckgo" in engines

    def test_no_engines_returns_empty_list(self, window: MainWindow) -> None:
        window.engine_google_checkbox.setChecked(False)
        window.engine_bing_checkbox.setChecked(False)
        window.engine_duckduckgo_checkbox.setChecked(False)
        window.engine_openverse_checkbox.setChecked(False)
        assert window._selected_search_engines() == []


class TestProgressAndPhaseIndicators:
    """T042/T039: Verify progress bar and phase status indicators."""

    def test_progress_bar_starts_at_zero(self, window: MainWindow) -> None:
        assert window.progress_bar.value() == 0

    def test_show_progress_updates_bar(self, window: MainWindow, qtbot) -> None:
        window.show_progress("Working...", percent=0.5, phase="export")
        qtbot.waitUntil(lambda: window.progress_bar.value() == 50, timeout=1000)

    def test_show_progress_detects_codec_from_message(self, window: MainWindow) -> None:
        window.show_progress("Using codec h264_nvenc via ffmpeg.exe.", percent=0.48)
        assert "NVENC" in window.encoder_status_label.text()

    def test_phase_status_idle_on_init(self, window: MainWindow) -> None:
        assert window.phase_icon_label.text() == "READY"
        assert window.phase_text_label.text() == "Idle"

    def test_set_busy_disables_controls(self, window: MainWindow) -> None:
        window.set_busy(True)
        assert not window.generate_button.isEnabled()
        assert not window.search_input.isEnabled()
        assert not window.pick_color_button.isEnabled()
        window.set_busy(False)
        assert window.generate_button.isEnabled()


# ===========================================================================
# Phase 5 / US3: Shortfall summary rendering and plain-language guidance (T023)
# ===========================================================================


class TestShortfallSummaryRendering:
    """T023: Verify shortfall diagnostics appear in preview and use plain language."""

    def test_shortfall_line_in_preview_text(self, window: MainWindow) -> None:
        ss = SearchRunSummary(
            requested=50,
            discovered=20,
            invalid_removed=2,
            duplicate_removed=3,
            near_duplicate_removed=1,
            selected=14,
            provider_logs={"google": 12, "bing": 8},
            shortfall_reasons=[ShortfallReason.LOW_AVAILABILITY, ShortfallReason.FILTERED_DUPLICATES],
            retry_suggestions=["Try a broader search term", "Reduce slide count to 20 or fewer"],
            source_errors={"bing": "No results from bing for 'rareterm' after retry"},
        )
        result = BuildResult(
            slides=[
                SlideFrame(i, 3 - i, f"slide {i}", f"https://x.com/{i}.jpg", "#87CEEB")
                for i in range(3)
            ],
            summary=BuildSummary(3, 3, 0),
            search_summary=ss,
        )
        window.show_generation_result(result)
        preview = window.preview_text.toPlainText()
        assert "near-duplicates" in preview.lower()
        assert "Source failures" in preview
        assert "bing" in preview
        assert "Shortfall reasons" in preview
        assert "Recovery suggestions" in preview

    def test_source_errors_shown_when_present(self, window: MainWindow) -> None:
        ss = SearchRunSummary(
            requested=10,
            discovered=3,
            invalid_removed=0,
            duplicate_removed=1,
            near_duplicate_removed=0,
            selected=2,
            provider_logs={"google": 3},
            shortfall_reasons=[ShortfallReason.LOW_AVAILABILITY],
            retry_suggestions=["Try enabling more search engines"],
            source_errors={"google": "No results from google for 'xyz' after retry"},
        )
        result = BuildResult(
            slides=[SlideFrame(0, 1, "top 1 xyz", "https://x.com/0.jpg", "#87CEEB")],
            summary=BuildSummary(1, 1, 0),
            search_summary=ss,
        )
        window.show_generation_result(result)
        preview = window.preview_text.toPlainText()
        assert "Source failures" in preview

    def test_plain_language_shortfall_reason_labels(self, window: MainWindow) -> None:
        ss = SearchRunSummary(
            requested=20,
            discovered=5,
            invalid_removed=1,
            duplicate_removed=0,
            near_duplicate_removed=0,
            selected=4,
            provider_logs={"google": 5},
            shortfall_reasons=[ShortfallReason.LOW_AVAILABILITY],
            retry_suggestions=[],
            source_errors={},
        )
        result = BuildResult(
            slides=[SlideFrame(0, 3, "slide", "https://x.com/0.jpg", "#87CEEB")],
            summary=BuildSummary(1, 1, 0),
            search_summary=ss,
        )
        window.show_generation_result(result)
        preview = window.preview_text.toPlainText()
        assert "low_availability" in preview.lower() or "availability" in preview.lower()


# ===========================================================================
# Phase 5 / US3: Rerun interaction preserving prior inputs (T024)
# ===========================================================================


class TestRerunInteraction:
    """T024: Verify rerun preserves search term and count."""

    def test_rerun_trigger_exists_when_result_available(self, window: MainWindow) -> None:
        window.search_input.setText("cars")
        window.count_input.setValue(25)
        window.show_generation_result(_dummy_build_result(5, include_search_summary=True))
        assert hasattr(window, "rerun_button")
        assert window.rerun_button.isVisible()

    def test_rerun_signal_emits_with_stored_inputs(self, window: MainWindow, qtbot) -> None:
        window.search_input.setText("cars")
        window.count_input.setValue(25)
        window._last_rerun_term = "cars"
        window._last_rerun_count = 25
        window._last_rerun_engines = ["google", "bing", "duckduckgo", "openverse"]
        window.show_generation_result(_dummy_build_result(5, include_search_summary=True))

        signals_received = []

        def _on_rerun(term, count, color, engines):
            signals_received.append((term, count, color, engines))

        window.rerun_requested.connect(_on_rerun)

        with qtbot.waitSignal(window.rerun_requested, timeout=2000):
            window.rerun_button.click()

        assert len(signals_received) == 1
        assert signals_received[0][0] == "cars"
        assert signals_received[0][1] == 25
        assert signals_received[0][2] == window._selected_color
        assert isinstance(signals_received[0][3], list)

    def test_rerun_button_hidden_before_generation(self, window: MainWindow) -> None:
        assert hasattr(window, "rerun_button")
        assert not window.rerun_button.isVisible()
