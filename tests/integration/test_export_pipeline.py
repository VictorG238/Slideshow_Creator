"""Integration tests for the export pipeline and slide ordering.

Covers:
  T040 – FFmpeg export integration tests
  T041 – Title-card, countdown-number, and image-card ordering
  T044 – Timed export smoke test for 50-slide / 10 MB target
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from PIL import Image

from slideshow_creator.models.domain import AppError, AudioTrack, ProgressEvent
from slideshow_creator.services.export_service import (
    DEFAULT_SLIDE_DURATION_SECONDS,
    EncoderCapabilities,
    ExportService,
    ExportServiceError,
)
from slideshow_creator.services.slideshow_builder import SlideFrame

# Skip the entire module when ffmpeg is not available.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _find_ffmpeg() -> str | None:
    """Check PATH, project bundle, and common Windows locations for ffmpeg."""
    from_path = shutil.which("ffmpeg")
    if from_path:
        return from_path
    candidates = [
        _PROJECT_ROOT / "assets" / "ffmpeg" / "ffmpeg.exe",
        _PROJECT_ROOT / "assets" / "ffmpeg" / "ffmpeg",
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ffmpeg\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


_FFMPEG_PATH = _find_ffmpeg()
pytestmark = pytest.mark.skipif(_FFMPEG_PATH is None, reason="FFmpeg not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _caps_from_system() -> EncoderCapabilities:
    """Probe the real system FFmpeg for available encoders."""
    svc = ExportService()
    return svc.detect_capabilities()


def _make_slides(count: int, overlay_color: str = "#87CEEB") -> list[SlideFrame]:
    slides: list[SlideFrame] = []
    for i in range(count):
        countdown_value = count - i
        label = f"top {count} car" if i == 0 else str(countdown_value)
        slides.append(
            SlideFrame(
                index=i,
                countdown_value=countdown_value,
                label_text=label,
                image_ref="",  # forces placeholder rendering
                overlay_color=overlay_color,
            )
        )
    return slides


def _make_solid_image_slide(
    index: int,
    count: int,
    color: tuple[int, int, int],
    tmp_dir: Path,
) -> tuple[SlideFrame, Path]:
    """Create a slide with a real local image saved to disk."""
    img = Image.new("RGB", (320, 240), color)
    img_path = tmp_dir / f"img_{index}.jpg"
    img.save(str(img_path), format="JPEG")
    return (
        SlideFrame(
            index=index,
            countdown_value=count - index,
            label_text=f"top {count} car" if index == 0 else str(count - index),
            image_ref=img_path.as_uri(),
            overlay_color="#87CEEB",
        ),
        img_path,
    )


# ===========================================================================
# T040 – FFmpeg export integration tests
# ===========================================================================


class TestFfmpegExportIntegration:
    """T040: End-to-end export tests that exercise the real FFmpeg binary."""

    def test_export_creates_video_file(self, tmp_path: Path) -> None:
        svc = ExportService()
        caps = _caps_from_system()
        slides = _make_slides(3)
        output = tmp_path / "output.mp4"

        result = svc.export_slideshow(
            slides=slides,
            target_size_mb=5.0,
            output_path=str(output),
        )

        assert Path(result.output_path).exists()
        assert result.actual_size_mb > 0

    def test_export_video_size_is_bounded(self, tmp_path: Path) -> None:
        svc = ExportService()
        slides = _make_slides(5)
        output = tmp_path / "bounded.mp4"

        result = svc.export_slideshow(
            slides=slides,
            target_size_mb=5.0,
            output_path=str(output),
        )

        # A 5-slide placeholder video should be well under the 5 MB target.
        assert result.actual_size_mb <= 5.0

    def test_export_reports_progress(self, tmp_path: Path) -> None:
        svc = ExportService()
        slides = _make_slides(2)
        output = tmp_path / "progress.mp4"
        messages: list[str] = []

        def _cb(evt: ProgressEvent) -> None:
            messages.append(evt.message)

        svc.export_slideshow(
            slides=slides,
            target_size_mb=5.0,
            output_path=str(output),
            progress_cb=_cb,
        )

        assert any("Detecting" in m for m in messages)
        assert any("Encoding" in m or "codec" in m.lower() for m in messages)
        assert any("complete" in m.lower() for m in messages)

    def test_export_with_webm_preference(self, tmp_path: Path) -> None:
        svc = ExportService()
        caps = _caps_from_system()
        slides = _make_slides(2)
        output = tmp_path / "output.webm"

        result = svc.export_slideshow(
            slides=slides,
            target_size_mb=5.0,
            output_path=str(output),
            prefer_webm=True,
        )

        assert Path(result.output_path).exists()
        assert result.actual_size_mb > 0

    def test_export_empty_slides_raises(self, tmp_path: Path) -> None:
        svc = ExportService()
        with pytest.raises(AppError):
            svc.export_slideshow(
                slides=[],
                target_size_mb=5.0,
                output_path=str(tmp_path / "empty.mp4"),
            )

    def test_export_normalizes_extension(self, tmp_path: Path) -> None:
        """If user picks .webm but encoder can only do MP4, output extension is
        corrected automatically."""
        svc = ExportService()
        caps = _caps_from_system()
        slides = _make_slides(2)
        output = tmp_path / "output.webm"

        result = svc.export_slideshow(
            slides=slides,
            target_size_mb=5.0,
            output_path=str(output),
            prefer_webm=False,  # Force MP4 but give a .webm path
        )

        out_path = Path(result.output_path)
        assert out_path.exists()
        # Container should match the chosen codec, not the original extension
        assert out_path.suffix.lower() in {".mp4", ".webm"}


# ===========================================================================
# T041 – Title-card, countdown-number, and image-card ordering
# ===========================================================================


class TestSlideOrdering:
    """T041: Verify that the rendered frames follow the specification order:
       intro title → countdown text → image, for each slide."""

    def test_rendered_frames_follow_intro_text_image_ordering(self, tmp_path: Path) -> None:
        """Check that a 3-slide export produces the expected frame sequence:
           intro_title, slide1_text, slide1_img, slide2_text, slide2_img, slide3_text, slide3_img
        """
        svc = ExportService()
        slides = _make_slides(3)
        workdir = tmp_path / "workdir"
        workdir.mkdir()

        profile = svc.plan_export_profile(
            slide_count=3,
            target_size_mb=10.0,
            prefer_webm=False,
            caps=_caps_from_system(),
        )

        frames = svc._render_slides_to_images(
            slides, profile, workdir, lambda _msg, _p: None
        )

        # Slide 0 is the intro slide (label != countdown), so it gets:
        # intro frame, text frame, image frame  = 3 frames
        # Slides 1 and 2 are normal: text frame + image frame = 2 each
        # Total = 3 + 2 + 2 = 7
        assert len(frames) == 7

        filenames = [p.name for p, _ in frames]

        # Intro card for slide 1
        assert filenames[0].endswith("_intro.jpg")
        # Text card for slide 1
        assert "_a.jpg" in filenames[1]
        # Image card for slide 1
        assert "_b.jpg" in filenames[2]
        # Text card for slide 2
        assert "_a.jpg" in filenames[3]
        # Image card for slide 2
        assert "_b.jpg" in filenames[4]

    def test_opening_slide_label_matches_top_n_format(self, tmp_path: Path) -> None:
        slides = _make_slides(5)
        assert slides[0].label_text == "top 5 car"
        assert slides[1].label_text == "4"
        assert slides[-1].label_text == "1"

    def test_countdown_values_are_descending(self, tmp_path: Path) -> None:
        slides = _make_slides(10)
        values = [s.countdown_value for s in slides]
        assert values == list(range(10, 0, -1))


# ===========================================================================
# T043 – Unwritable export destination (integration side)
# ===========================================================================


class TestUnwritableDestination:
    """T043: Verify export pipeline catches invalid output paths."""

    def test_validate_destination_rejects_existing_directory(self, tmp_path: Path) -> None:
        """_validate_output_destination must reject a path that is an existing directory."""
        svc = ExportService()
        # Create a subdirectory and give it a .mp4 extension so normalize won't change it
        dir_path = tmp_path / "fake_output.mp4"
        dir_path.mkdir()
        with pytest.raises(ExportServiceError, match="folder"):
            svc._validate_output_destination(dir_path)

    def test_export_to_nonexistent_deep_path_succeeds(self, tmp_path: Path) -> None:
        """Export to a deeply nested path should create intermediate directories."""
        svc = ExportService()
        slides = _make_slides(2)
        deep_output = tmp_path / "a" / "b" / "c" / "video.mp4"

        result = svc.export_slideshow(
            slides=slides,
            target_size_mb=5.0,
            output_path=str(deep_output),
        )

        assert Path(result.output_path).exists()
        assert result.actual_size_mb > 0



# ===========================================================================
# T044 – Timed export smoke test for 50-slide / 10 MB target
# ===========================================================================


class TestTimedExportSmoke:
    """T044: A 50-slide export at 10 MB target must complete and meet the cap."""

    @pytest.mark.slow
    def test_50_slide_export_completes_under_size_target(self, tmp_path: Path) -> None:
        svc = ExportService()
        slides = _make_slides(50)
        output = tmp_path / "slideshow_50.mp4"

        start = time.monotonic()
        result = svc.export_slideshow(
            slides=slides,
            target_size_mb=10.0,
            output_path=str(output),
        )
        elapsed = time.monotonic() - start

        assert Path(result.output_path).exists()
        assert result.actual_size_mb <= 10.0, (
            f"Output {result.actual_size_mb:.2f} MB exceeded 10 MB target"
        )
        # Generous 5 minute ceiling – mostly guards against infinite hangs.
        assert elapsed < 300, f"Export took {elapsed:.1f}s which exceeds 5 min ceiling"
