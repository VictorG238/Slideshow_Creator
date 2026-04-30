"""Application bootstrap for the slideshow creator desktop app."""

import sys
from pathlib import Path
from typing import Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication

from slideshow_creator import APP_NAME, APP_ORGANIZATION, __version__
from slideshow_creator.models.domain import AppError, ProgressEvent
from slideshow_creator.services.audio_service import AudioService, AudioServiceError
from slideshow_creator.services.export_service import (
    DEFAULT_SLIDE_DURATION_SECONDS,
    ExportResult,
    ExportService,
    ExportServiceError,
)
from slideshow_creator.services.image_search import ImageSearchService
from slideshow_creator.services.slideshow_builder import (
    BuildResult,
    SlideshowBuilder,
)
from slideshow_creator.ui.main_window import MainWindow


class AppController(QObject):
    """Connect UI events to core services for US1 generation workflow."""

    def __init__(
        self,
        window: MainWindow,
        image_search_service: ImageSearchService,
        slideshow_builder: SlideshowBuilder,
        export_service: ExportService,
        audio_service: AudioService,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.image_search_service = image_search_service
        self.slideshow_builder = slideshow_builder
        self.export_service = export_service
        self.audio_service = audio_service
        self._latest_build_result: BuildResult | None = None
        self._selected_audio_path: str | None = None
        self._selected_audio_track = None
        self._generation_thread: QThread | None = None
        self._generation_worker: _BackgroundTaskWorker | None = None
        self._export_thread: QThread | None = None
        self._export_worker: _BackgroundTaskWorker | None = None
        self.window.generation_requested.connect(self._handle_generation_request)
        self.window.rerun_requested.connect(self._handle_generation_request)
        self.window.export_requested.connect(self._handle_export_request)
        self.window.audio_changed.connect(self._handle_audio_changed)
        
        # Pre-warm FFmpeg capabilities in the background so export shows up instantly.
        import threading
        threading.Thread(target=self.export_service.detect_capabilities, daemon=True).start()

    def _handle_generation_request(
        self,
        search_term: str,
        count: int,
        overlay_color: str,
        search_engines: object,
    ) -> None:
        if self._generation_thread is not None and self._generation_thread.isRunning():
            self.window.show_error("A generation is already running. Wait until it finishes.")
            return

        self.window.set_busy(True)
        self.window.set_export_ready(False)
        self._latest_build_result = None

        providers: list[str] = []
        if isinstance(search_engines, (list, tuple, set)):
            providers = [str(item).strip().lower() for item in search_engines if str(item).strip()]

        def _task(progress_cb: Callable[[ProgressEvent], None]) -> BuildResult:
            candidates, search_summary = self.image_search_service.probe(
                search_term=search_term,
                limit=count,
                providers=providers,
                progress_cb=progress_cb,
            )

            image_refs = [candidate.source_url for candidate in candidates]

            build_result = self.slideshow_builder.build(
                search_term=search_term,
                count=count,
                image_refs=image_refs,
                overlay_color=overlay_color,
                allow_reuse=True,
                progress_cb=progress_cb,
            )
            build_result.search_summary = search_summary
            return build_result

        self._start_generation_task(_task)

    def _start_generation_task(self, task: Callable[[Callable[[ProgressEvent], None]], BuildResult]) -> None:
        worker = _BackgroundTaskWorker(
            task=task,
            unexpected_error_hint="Try another search term or reduce slide count.",
        )
        thread = QThread(self.window)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self.window.show_progress)
        worker.succeeded.connect(self._handle_generation_success)
        worker.failed.connect(self._handle_generation_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_generation_task)
        thread.finished.connect(lambda: self.window.set_busy(False))

        self._generation_worker = worker
        self._generation_thread = thread
        thread.start()

    @Slot(object)
    def _handle_generation_success(self, result: object) -> None:
        if not isinstance(result, BuildResult):
            self._latest_build_result = None
            self.window.set_export_ready(False)
            self.window.show_error("Unexpected generation result from background task.")
            return

        self._latest_build_result = result
        self.window.show_generation_result(result)
        if self._selected_audio_path:
            self._refresh_audio_selection()

    @Slot(str, object)
    def _handle_generation_failure(self, message: str, hint: object) -> None:
        self._latest_build_result = None
        self.window.set_export_ready(False)
        self.window.show_error(message, hint if isinstance(hint, str) else None)

    @Slot()
    def _clear_generation_task(self) -> None:
        self._generation_worker = None
        self._generation_thread = None

    def _handle_export_request(self, target_size_mb: float, preferred_format: str, output_path: str) -> None:
        if self._latest_build_result is None:
            self.window.show_error("Generate a slideshow preview before exporting.")
            return

        if self._export_thread is not None and self._export_thread.isRunning():
            self.window.show_error("An export is already running. Wait until it finishes.")
            return

        audio_track = None
        if self._selected_audio_path:
            if self._selected_audio_track is None:
                self.window.show_error("Selected MP3 could not be validated. Choose a different file.")
                return

            video_seconds = len(self._latest_build_result.slides) * DEFAULT_SLIDE_DURATION_SECONDS
            try:
                audio_track = self.audio_service.inspect_mp3(self._selected_audio_path, video_seconds=video_seconds)
                self._selected_audio_track = audio_track
                self.window.set_audio_status(
                    f"MP3 ready: {Path(audio_track.path).name} • {audio_track.duration_ms / 1000:.2f}s • "
                    f"loops x{audio_track.loop_count + 1}"
                )
            except AudioServiceError as exc:
                self._selected_audio_track = None
                self.window.set_audio_status(str(exc), error=True)
                self.window.show_error(str(exc))
                return

        self.window.set_busy(True)

        def _task(progress_cb: Callable[[ProgressEvent], None]) -> ExportResult:
            return self.export_service.export_slideshow(
                slides=self._latest_build_result.slides,
                target_size_mb=target_size_mb,
                output_path=output_path,
                prefer_webm=(preferred_format == "webm"),
                audio_track=audio_track,
                progress_cb=progress_cb,
            )

        self._start_export_task(_task)

    def _start_export_task(self, task: Callable[[Callable[[ProgressEvent], None]], ExportResult]) -> None:
        worker = _BackgroundTaskWorker(
            task=task,
            unexpected_error_hint="Check your disk space or try another folder.",
        )
        thread = QThread(self.window)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self.window.show_progress)
        worker.succeeded.connect(self._handle_export_success)
        worker.failed.connect(self.window.show_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_export_task)
        thread.finished.connect(lambda: self.window.set_busy(False))

        self._export_worker = worker
        self._export_thread = thread
        thread.start()

    @Slot(object)
    def _handle_export_success(self, result: object) -> None:
        if isinstance(result, ExportResult):
            self.window.show_export_result(
                result.output_path,
                result.actual_size_mb,
                result.profile.video_codec,
            )
            return
        self.window.show_error("Unexpected export result from background task.")

    @Slot()
    def _clear_export_task(self) -> None:
        self._export_worker = None
        self._export_thread = None

    def _refresh_audio_selection(self) -> None:
        if not self._selected_audio_path:
            self._selected_audio_track = None
            self.window.set_audio_status("No MP3 selected.")
            return

        video_seconds = None
        if self._latest_build_result is not None:
            video_seconds = len(self._latest_build_result.slides) * DEFAULT_SLIDE_DURATION_SECONDS

        try:
            self._selected_audio_track = self.audio_service.inspect_mp3(self._selected_audio_path, video_seconds=video_seconds)
        except AudioServiceError as exc:
            self._selected_audio_track = None
            self.window.set_audio_status(str(exc), error=True)
            self.window.show_error(str(exc))
            return

        track = self._selected_audio_track
        if track is None:
            self.window.set_audio_status("No MP3 selected.")
            return

        duration_seconds = track.duration_ms / 1000
        if track.loop_count > 0:
            self.window.set_audio_status(
                f"MP3 ready: {Path(track.path).name} • {duration_seconds:.2f}s • loops x{track.loop_count + 1}"
            )
        else:
            self.window.set_audio_status(f"MP3 ready: {Path(track.path).name} • {duration_seconds:.2f}s")

    def _handle_audio_changed(self, audio_path: str) -> None:
        self._selected_audio_path = audio_path.strip() or None
        self._selected_audio_track = None
        if not self._selected_audio_path:
            self.window.set_audio_status("No MP3 selected.")
            return

        self._refresh_audio_selection()


class _BackgroundTaskWorker(QObject):
    """Run a long-running task in a worker thread and report Qt-safe progress."""

    progress = Signal(str, object, object)
    succeeded = Signal(object)
    failed = Signal(str, object)
    finished = Signal()

    def __init__(
        self,
        task: Callable[[Callable[[ProgressEvent], None]], object],
        unexpected_error_hint: str,
    ) -> None:
        super().__init__()
        self._task = task
        self._unexpected_error_hint = unexpected_error_hint

    @Slot()
    def run(self) -> None:
        try:
            result = self._task(self._emit_progress)
            self.succeeded.emit(result)
        except AppError as exc:
            self.failed.emit(str(exc), exc.recovery_hint)
        except ExportServiceError as exc:
            self.failed.emit(str(exc), None)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Unexpected export error: {exc}", self._unexpected_error_hint)
        finally:
            self.finished.emit()

    def _emit_progress(self, evt: ProgressEvent) -> None:
        self.progress.emit(evt.message, evt.percent, evt.phase)


def main() -> int:
    """Start the Qt application and show the main window."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_ORGANIZATION)

    window = MainWindow()
    controller = AppController(
        window=window,
        image_search_service=ImageSearchService(validate_candidates=True),
        slideshow_builder=SlideshowBuilder(),
        export_service=ExportService(),
        audio_service=AudioService(),
    )
    # Keep controller alive for the full app lifecycle.
    window._controller = controller  # type: ignore[attr-defined]
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
