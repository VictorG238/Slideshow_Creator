from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from slideshow_creator.services.export_service import EncoderCapabilities, ExportService
from slideshow_creator.services.slideshow_builder import SlideFrame


def _caps(*, nvenc: bool = False, x264: bool = False, vp9: bool = False) -> EncoderCapabilities:
    encoders = []
    if nvenc:
        encoders.append("h264_nvenc")
    if x264:
        encoders.append("libx264")
    if vp9:
        encoders.append("libvpx-vp9")
    return EncoderCapabilities(
        ffmpeg_path="ffmpeg",
        has_nvenc=nvenc,
        has_libx264=x264,
        has_libvpx_vp9=vp9,
        available_encoders=tuple(encoders),
        probe_error=None,
    )


def test_plan_export_profile_uses_webm_when_preferred_and_available() -> None:
    service = ExportService()
    profile = service.plan_export_profile(
        slide_count=50,
        target_size_mb=10.0,
        prefer_webm=True,
        caps=_caps(vp9=True),
    )

    assert profile.container == "webm"
    assert profile.video_codec == "libvpx-vp9"
    assert profile.audio_codec == "libopus"
    assert profile.video_bitrate_kbps > 0
    assert profile.width > 0 and profile.height > 0


def test_plan_export_profile_falls_back_to_mp4_when_webm_unavailable() -> None:
    service = ExportService()
    profile = service.plan_export_profile(
        slide_count=50,
        target_size_mb=10.0,
        prefer_webm=True,
        caps=_caps(x264=True),
    )

    assert profile.container == "mp4"
    assert profile.video_codec == "libx264"
    assert profile.audio_codec == "aac"


def test_plan_export_profile_prefers_nvenc_for_mp4_when_available() -> None:
    service = ExportService()
    profile = service.plan_export_profile(
        slide_count=50,
        target_size_mb=10.0,
        prefer_webm=False,
        caps=_caps(nvenc=True, x264=True),
    )

    assert profile.container == "mp4"
    assert profile.video_codec == "h264_nvenc"
    assert profile.audio_codec == "aac"


@pytest.mark.parametrize(
    "slide_count,target_size_mb",
    [
        (0, 10.0),
        (10, 0.0),
    ],
)
def test_plan_export_profile_rejects_invalid_inputs(slide_count: int, target_size_mb: float) -> None:
    service = ExportService()

    with pytest.raises(RuntimeError):
        service.plan_export_profile(
            slide_count=slide_count,
            target_size_mb=target_size_mb,
            prefer_webm=False,
            caps=_caps(x264=True),
        )


def test_normalize_output_path_forces_selected_container_suffix() -> None:
    service = ExportService()

    out = service._normalize_output_path(Path("video.webm"), "mp4")
    assert out.suffix.lower() == ".mp4"
    assert out.name == "video.mp4"


def test_compact_ffmpeg_error_omits_banner_noise() -> None:
    service = ExportService()

    stderr = "\n".join(
        [
            "ffmpeg version 6.0",
            "configuration: lots of options",
            "libavutil 57.0.0",
            "[webm @ 000000] Only VP8 or VP9 are supported",
            "Could not write header for output file #0",
        ]
    )
    message = service._compact_ffmpeg_error(stderr, "")

    assert "ffmpeg version" not in message.lower()
    assert "configuration:" not in message.lower()
    assert "only vp8 or vp9 are supported" in message.lower()


def test_resolve_slide_image_uses_alternative_when_primary_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ExportService()

    def _fake_download(url: str, max_attempts: int = 4, timeout_seconds: float = 8.0) -> Image.Image | None:
        if url == "bad":
            return None
        return Image.new("RGB", (12, 12), (255, 0, 0))

    monkeypatch.setattr(service, "_download_image", _fake_download)

    slide = SlideFrame(
        index=0,
        countdown_value=9,
        label_text="9",
        image_ref="bad",
        overlay_color="#87CEEB",
    )

    resolved, resolved_ref = service._resolve_slide_image(
        slide,
        all_slide_refs=["bad", "good"],
        image_cache={},
    )

    assert resolved is not None
    assert resolved_ref == "good"
    assert resolved.getpixel((0, 0)) == (255, 0, 0)


def test_resolve_slide_image_skips_failed_url_and_uses_next_consecutive(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ExportService()

    def _fake_download(url: str, max_attempts: int = 4, timeout_seconds: float = 8.0) -> Image.Image | None:
        if url == "bad":
            return None
        if url == "next":
            return Image.new("RGB", (10, 10), (0, 255, 0))
        return Image.new("RGB", (10, 10), (255, 0, 0))

    monkeypatch.setattr(service, "_download_image", _fake_download)

    slide = SlideFrame(
        index=1,
        countdown_value=4,
        label_text="4",
        image_ref="bad",
        overlay_color="#87CEEB",
    )

    resolved, resolved_ref = service._resolve_slide_image(
        slide,
        all_slide_refs=["first", "bad", "next", "last"],
        image_cache={},
    )

    assert resolved is not None
    assert resolved_ref == "next"
    assert resolved.getpixel((0, 0)) == (0, 255, 0)


def test_resolve_slide_image_prefers_different_than_previous_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ExportService()

    def _fake_download(url: str, max_attempts: int = 4, timeout_seconds: float = 8.0) -> Image.Image | None:
        if url == "first":
            return Image.new("RGB", (10, 10), (255, 0, 0))
        if url == "next":
            return Image.new("RGB", (10, 10), (0, 255, 0))
        return None

    monkeypatch.setattr(service, "_download_image", _fake_download)

    slide = SlideFrame(
        index=0,
        countdown_value=3,
        label_text="3",
        image_ref="first",
        overlay_color="#87CEEB",
    )

    resolved, resolved_ref = service._resolve_slide_image(
        slide,
        all_slide_refs=["first", "next", "first"],
        image_cache={},
        previous_ref="first",
    )

    assert resolved is not None
    assert resolved_ref == "next"
    assert resolved.getpixel((0, 0)) == (0, 255, 0)


def test_resolve_slide_image_prefers_unseen_visual_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ExportService()

    def _fake_download(url: str, max_attempts: int = 4, timeout_seconds: float = 8.0) -> Image.Image | None:
        if url in {"dup-a", "dup-b"}:
            return Image.new("RGB", (10, 10), (255, 0, 0))
        if url == "unique":
            return Image.new("RGB", (10, 10), (0, 255, 0))
        return None

    monkeypatch.setattr(service, "_download_image", _fake_download)

    slide = SlideFrame(
        index=0,
        countdown_value=3,
        label_text="3",
        image_ref="dup-a",
        overlay_color="#87CEEB",
    )

    red_sig = service._image_signature(Image.new("RGB", (10, 10), (255, 0, 0)))

    resolved, resolved_ref = service._resolve_slide_image(
        slide,
        all_slide_refs=["dup-b", "unique", "dup-a"],
        image_cache={},
        previous_ref="dup-a",
        previous_signature=red_sig,
        used_signatures={red_sig},
    )

    assert resolved is not None
    assert resolved_ref == "unique"
    assert resolved.getpixel((0, 0)) == (0, 255, 0)


def test_resolve_slide_image_prefers_non_avoided_signature_when_all_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ExportService()

    def _fake_download(url: str, max_attempts: int = 4, timeout_seconds: float = 8.0) -> Image.Image | None:
        if url == "first":
            return Image.new("RGB", (10, 10), (255, 0, 0))
        if url == "other":
            return Image.new("RGB", (10, 10), (0, 255, 0))
        return None

    monkeypatch.setattr(service, "_download_image", _fake_download)

    slide = SlideFrame(
        index=0,
        countdown_value=3,
        label_text="3",
        image_ref="first",
        overlay_color="#87CEEB",
    )

    first_sig = service._image_signature(Image.new("RGB", (10, 10), (255, 0, 0)))
    other_sig = service._image_signature(Image.new("RGB", (10, 10), (0, 255, 0)))

    resolved, resolved_ref = service._resolve_slide_image(
        slide,
        all_slide_refs=["first", "other"],
        image_cache={},
        used_signatures={first_sig, other_sig},
        avoid_signatures={first_sig},
    )

    assert resolved is not None
    assert resolved_ref == "other"
    assert resolved.getpixel((0, 0)) == (0, 255, 0)


def test_build_variant_image_changes_pixels() -> None:
    service = ExportService()

    base = Image.new("RGB", (2, 1))
    base.putpixel((0, 0), (255, 0, 0))
    base.putpixel((1, 0), (0, 0, 255))

    variant = service._build_variant_image(base, variant_seed=0)

    assert variant.getpixel((0, 0)) == (0, 0, 255)
    assert variant.getpixel((1, 0)) == (255, 0, 0)


def test_placeholder_image_is_not_black() -> None:
    service = ExportService()
    profile = service.plan_export_profile(
        slide_count=1,
        target_size_mb=10.0,
        prefer_webm=False,
        caps=_caps(x264=True),
    )
    slide = SlideFrame(
        index=0,
        countdown_value=4,
        label_text="4",
        image_ref="missing",
        overlay_color="#87CEEB",
    )

    placeholder = service._build_placeholder_image(profile, slide)
    assert placeholder.getpixel((0, 0)) != (0, 0, 0)


# ===========================================================================
# T043 – Unwritable export destination validation (unit-level)
# ===========================================================================


def test_validate_output_destination_rejects_existing_directory(tmp_path: Path) -> None:
    service = ExportService()
    # tmp_path itself is a directory
    with pytest.raises(RuntimeError, match="folder"):
        service._validate_output_destination(tmp_path)


def test_validate_output_destination_creates_missing_parent(tmp_path: Path) -> None:
    service = ExportService()
    deep_path = tmp_path / "a" / "b" / "c" / "video.mp4"
    # Should NOT raise – it creates intermediate dirs
    service._validate_output_destination(deep_path)
    assert deep_path.parent.exists()


def test_validate_output_destination_accepts_writable_path(tmp_path: Path) -> None:
    service = ExportService()
    output = tmp_path / "video.mp4"
    # Should succeed silently
    service._validate_output_destination(output)


def test_validate_output_destination_accepts_existing_writable_file(tmp_path: Path) -> None:
    service = ExportService()
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"dummy")
    # Should succeed because the file is writable
    service._validate_output_destination(output)

