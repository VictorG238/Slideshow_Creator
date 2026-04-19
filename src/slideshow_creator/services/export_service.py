"""Export service with MB-target planning and FFmpeg pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from slideshow_creator.models.domain import AppError, AudioTrack, ErrorCategory, ProgressEvent
from slideshow_creator.services.slideshow_builder import SlideFrame


DEFAULT_SLIDE_DURATION_SECONDS = 5.0


class ExportServiceError(RuntimeError):
    """Raised when export preparation or rendering fails."""


@dataclass(slots=True)
class EncoderCapabilities:
    """Detected FFmpeg encoder availability."""

    ffmpeg_path: Optional[str]
    has_nvenc: bool
    has_libx264: bool
    has_libvpx_vp9: bool
    available_encoders: tuple[str, ...]
    probe_error: Optional[str] = None


@dataclass(slots=True)
class ExportProfile:
    """Resolved export settings for size-targeted output."""

    container: str
    width: int
    height: int
    fps: int
    slide_duration_seconds: float
    duration_seconds: float
    video_codec: str
    audio_codec: str
    video_bitrate_kbps: int
    audio_bitrate_kbps: int


@dataclass(slots=True)
class ExportResult:
    """Export result details surfaced back to UI/app."""

    output_path: str
    actual_size_mb: float
    profile: ExportProfile


class ExportService:
    """Plan and execute exports with hardware-or-cpu fallback."""

    def __init__(
        self,
        ffmpeg_path_override: Optional[str] = None,
        bundled_ffmpeg_dir: Optional[Path] = None,
    ) -> None:
        self.ffmpeg_path_override = ffmpeg_path_override
        self.bundled_ffmpeg_dir = bundled_ffmpeg_dir
        self.http = requests.Session()
        self.http.headers.setdefault("User-Agent", "slideshow-creator/0.1 (+desktop)")
        self._cached_capabilities: Optional[EncoderCapabilities] = None

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _ffmpeg_candidates(self) -> list[str]:
        candidates: list[str] = []
        if self.ffmpeg_path_override:
            candidates.append(self.ffmpeg_path_override)

        env_path = os.getenv("SLIDESHOW_FFMPEG_PATH")
        if env_path:
            candidates.append(env_path)

        bundled_dir = self.bundled_ffmpeg_dir or self._project_root() / "assets" / "ffmpeg"
        candidates.extend([str(bundled_dir / "ffmpeg.exe"), str(bundled_dir / "ffmpeg")])

        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            candidates.append(system_ffmpeg)

        if os.name == "nt":
            # Extra robust detection for common Windows unpacked directories
            candidates.extend([
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\ffmpeg\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
            ])

        return list(dict.fromkeys(candidates))

    @staticmethod
    def _extract_encoders(encoders_stdout: str) -> tuple[str, ...]:
        names: list[str] = []
        for raw in encoders_stdout.splitlines():
            parts = raw.split()
            if len(parts) >= 2 and parts[0].startswith("V"):
                names.append(parts[1])
        return tuple(sorted(set(names)))

    def _probe_capabilities_for_path(self, ffmpeg_path: str) -> EncoderCapabilities:
        try:
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return EncoderCapabilities(ffmpeg_path, False, False, False, (), str(exc))

        if result.returncode != 0:
            return EncoderCapabilities(
                ffmpeg_path,
                False,
                False,
                False,
                (),
                (result.stderr or result.stdout).strip() or "ffmpeg encoder probe failed",
            )

        encoders = self._extract_encoders(result.stdout)
        return EncoderCapabilities(
            ffmpeg_path=ffmpeg_path,
            has_nvenc="h264_nvenc" in encoders,
            has_libx264="libx264" in encoders,
            has_libvpx_vp9="libvpx-vp9" in encoders,
            available_encoders=encoders,
        )

    def detect_capabilities(self) -> EncoderCapabilities:
        """Detect FFmpeg path and available encoders (NVENC/CPU)."""
        if self._cached_capabilities is not None:
            return self._cached_capabilities

        candidates = [candidate for candidate in self._ffmpeg_candidates() if Path(candidate).exists()]
        if not candidates:
            return EncoderCapabilities(None, False, False, False, (), "ffmpeg executable not found")

        probed = [self._probe_capabilities_for_path(path) for path in candidates]

        for caps in probed:
            if caps.probe_error is None and caps.has_nvenc:
                self._cached_capabilities = caps
                return caps
        for caps in probed:
            if caps.probe_error is None and caps.has_libx264:
                self._cached_capabilities = caps
                return caps
        for caps in probed:
            if caps.probe_error is None:
                self._cached_capabilities = caps
                return caps
        self._cached_capabilities = probed[0]
        return probed[0]

    def preferred_video_codec(self, prefer_webm: bool, caps: EncoderCapabilities) -> str:
        """Choose the best available codec for the requested container preference."""
        if prefer_webm and caps.has_libvpx_vp9:
            return "libvpx-vp9"

        if caps.has_nvenc:
            return "h264_nvenc"
        if caps.has_libx264:
            return "libx264"
        if caps.has_libvpx_vp9:
            return "libvpx-vp9"
        return "h264"

    def preferred_container_and_codecs(self, prefer_webm: bool, caps: EncoderCapabilities) -> tuple[str, str, str]:
        """Choose a valid container and video/audio codec pair for the export request."""
        if prefer_webm and caps.has_libvpx_vp9:
            return "webm", "libvpx-vp9", "libopus"

        if prefer_webm:
            if caps.has_nvenc:
                return "mp4", "h264_nvenc", "aac"
            if caps.has_libx264:
                return "mp4", "libx264", "aac"
            return "mp4", "h264", "aac"

        if caps.has_nvenc:
            return "mp4", "h264_nvenc", "aac"
        if caps.has_libx264:
            return "mp4", "libx264", "aac"
        if caps.has_libvpx_vp9:
            return "webm", "libvpx-vp9", "libopus"
        return "mp4", "h264", "aac"

    @staticmethod
    def _resolution_for_bitrate(video_bitrate_kbps: int) -> tuple[int, int]:
        if video_bitrate_kbps >= 3000:
            return 1920, 1080
        if video_bitrate_kbps >= 1600:
            return 1280, 720
        if video_bitrate_kbps >= 900:
            return 960, 540
        return 854, 480

    def plan_export_profile(
        self,
        slide_count: int,
        target_size_mb: float,
        prefer_webm: bool,
        caps: EncoderCapabilities,
        slide_duration_seconds: float = DEFAULT_SLIDE_DURATION_SECONDS,
        fps: int = 30,
    ) -> ExportProfile:
        """Plan bitrate and resolution to target a max output size in MB."""
        if slide_count <= 0:
            raise ExportServiceError("Cannot plan export for zero slides.")
        if target_size_mb <= 0:
            raise ExportServiceError("Target size in MB must be greater than 0.")

        duration_seconds = max(slide_count * slide_duration_seconds, slide_duration_seconds)
        container, video_codec, audio_codec = self.preferred_container_and_codecs(prefer_webm, caps)
        audio_bitrate_kbps = 96 if container == "webm" else 128

        budget_kbits = target_size_mb * 8192 * 0.95
        target_total_bitrate = max(int(budget_kbits / duration_seconds), 300)
        video_bitrate_kbps = max(target_total_bitrate - audio_bitrate_kbps, 200)
        width, height = self._resolution_for_bitrate(video_bitrate_kbps)
        return ExportProfile(
            container=container,
            width=width,
            height=height,
            fps=fps,
            slide_duration_seconds=slide_duration_seconds,
            duration_seconds=duration_seconds,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate_kbps=video_bitrate_kbps,
            audio_bitrate_kbps=audio_bitrate_kbps,
        )

    @staticmethod
    def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
        color = hex_color.strip().lstrip("#")
        if len(color) == 3:
            color = "".join(ch * 2 for ch in color)
        if len(color) != 6:
            return 135, 206, 235
        try:
            return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        except ValueError:
            return 135, 206, 235

    def _download_image(
        self,
        url: str,
        max_attempts: int = 4,
        timeout_seconds: float = 8.0,
    ) -> Optional[Image.Image]:
        import time
        from io import BytesIO

        for attempt in range(max_attempts):
            try:
                response = self.http.get(url, timeout=timeout_seconds)
                response.raise_for_status()
                image = Image.open(BytesIO(response.content)).convert("RGB")
                return image
            except Exception:
                if attempt < max_attempts - 1:
                    # Short capped backoff keeps rendering responsive on bad URLs.
                    sleep_time = min(2.5, 0.5 * (2**attempt))
                    time.sleep(sleep_time)
                continue
        return None

    def _download_cached_image(
        self,
        url: str,
        image_cache: dict[str, Optional[Image.Image]],
    ) -> Optional[Image.Image]:
        if url in image_cache:
            cached = image_cache[url]
            return cached.copy() if cached is not None else None

        downloaded = self._download_image(url)
        image_cache[url] = downloaded
        return downloaded.copy() if downloaded is not None else None

    @staticmethod
    def _image_signature(image: Image.Image) -> str:
        """Build a small perceptual signature to detect same-content images across different URLs."""
        thumb = image.convert("L").resize((16, 16), Image.Resampling.BILINEAR)
        return hashlib.sha256(thumb.tobytes()).hexdigest()

    def _resolve_slide_image(
        self,
        slide: SlideFrame,
        all_slide_refs: list[str],
        image_cache: dict[str, Optional[Image.Image]],
        previous_ref: Optional[str] = None,
        previous_signature: Optional[str] = None,
        used_signatures: Optional[set[str]] = None,
        avoid_signatures: Optional[set[str]] = None,
    ) -> tuple[Optional[Image.Image], Optional[str]]:
        if not all_slide_refs:
            return None, None

        start_index = slide.index if 0 <= slide.index < len(all_slide_refs) else 0
        fallback_image: Optional[Image.Image] = None
        fallback_ref: Optional[str] = None
        best_unseen_not_avoided: tuple[Image.Image, str] | None = None
        best_not_previous_not_avoided: tuple[Image.Image, str] | None = None
        best_not_avoided: tuple[Image.Image, str] | None = None
        best_unseen_signature: tuple[Image.Image, str] | None = None
        best_not_previous: tuple[Image.Image, str] | None = None

        for offset in range(len(all_slide_refs)):
            ref = all_slide_refs[(start_index + offset) % len(all_slide_refs)]
            if not ref.strip():
                continue
            image = self._download_cached_image(ref, image_cache)
            if image is not None:
                signature = self._image_signature(image)
                if fallback_image is None:
                    fallback_image = image
                    fallback_ref = ref

                signature_seen = used_signatures is not None and signature in used_signatures
                same_as_previous_signature = previous_signature is not None and signature == previous_signature
                same_as_previous_ref = previous_ref is not None and ref == previous_ref
                signature_avoided = avoid_signatures is not None and signature in avoid_signatures

                # Strongest preference: brand-new image content and not equal to previous slide content.
                if (
                    not signature_seen
                    and not same_as_previous_signature
                    and not same_as_previous_ref
                    and not signature_avoided
                ):
                    return image, ref

                if best_unseen_not_avoided is None and not signature_seen and not signature_avoided:
                    best_unseen_not_avoided = (image, ref)

                if (
                    best_not_previous_not_avoided is None
                    and not same_as_previous_signature
                    and not same_as_previous_ref
                    and not signature_avoided
                ):
                    best_not_previous_not_avoided = (image, ref)

                if best_not_avoided is None and not signature_avoided:
                    best_not_avoided = (image, ref)

                # Next best: unseen image content even if previous content also matched.
                if best_unseen_signature is None and not signature_seen:
                    best_unseen_signature = (image, ref)

                # Last preference before fallback: avoid exact same URL and same visual content consecutively.
                if best_not_previous is None and not same_as_previous_signature and not same_as_previous_ref:
                    best_not_previous = (image, ref)

        if best_unseen_not_avoided is not None:
            return best_unseen_not_avoided
        if best_not_previous_not_avoided is not None:
            return best_not_previous_not_avoided
        if best_not_avoided is not None:
            return best_not_avoided
        if best_unseen_signature is not None:
            return best_unseen_signature
        if best_not_previous is not None:
            return best_not_previous

        return fallback_image, fallback_ref

    def _build_variant_image(self, image: Image.Image, variant_seed: int) -> Image.Image:
        """Create a lightweight visual variation when only one source image is available."""
        transformed = image.copy()
        mode = variant_seed % 3
        if mode == 0:
            transformed = ImageOps.mirror(transformed)
        elif mode == 1:
            transformed = ImageEnhance.Brightness(transformed).enhance(1.12)
        else:
            transformed = ImageEnhance.Brightness(transformed).enhance(0.88)
        return transformed

    def _build_placeholder_image(self, profile: ExportProfile, slide: SlideFrame) -> Image.Image:
        bg = self._parse_hex_color(slide.overlay_color)
        placeholder = Image.new("RGB", (profile.width, profile.height), bg)
        draw = ImageDraw.Draw(placeholder)

        message = "Image unavailable"
        subtitle = f"Top {slide.countdown_value}"
        try:
            title_font = ImageFont.load_default(size=max(22, profile.height // 24))
            subtitle_font = ImageFont.load_default(size=max(16, profile.height // 36))
        except TypeError:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()

        title_box = draw.textbbox((0, 0), message, font=title_font)
        subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)

        title_w = title_box[2] - title_box[0]
        title_h = title_box[3] - title_box[1]
        subtitle_w = subtitle_box[2] - subtitle_box[0]

        center_x = profile.width // 2
        center_y = profile.height // 2

        draw.text((center_x - (title_w // 2), center_y - title_h), message, fill=(255, 255, 255), font=title_font)
        draw.text(
            (center_x - (subtitle_w // 2), center_y + max(8, profile.height // 80)),
            subtitle,
            fill=(230, 238, 248),
            font=subtitle_font,
        )
        return placeholder

    def _render_slides_to_images(
        self,
        slides: list[SlideFrame],
        profile: ExportProfile,
        workdir: Path,
        progress: Callable[[str, float], None],
    ) -> list[tuple[Path, float]]:
        rendered: list[tuple[Path, float]] = []
        image_cache: dict[str, Optional[Image.Image]] = {}
        total = len(slides)
        all_slide_refs = [slide.image_ref for slide in slides if slide.image_ref.strip()]
        last_resolved_ref: Optional[str] = None
        last_resolved_signature: Optional[str] = None
        first_resolved_signature: Optional[str] = None
        used_signatures: set[str] = set()

        text_dur = profile.slide_duration_seconds * 0.4
        img_dur = profile.slide_duration_seconds * 0.6
        title_dur = profile.slide_duration_seconds * 0.5

        for idx, slide in enumerate(slides, start=1):
            progress(f"Rendering slide {idx}/{total}...", idx / total)
            color = self._parse_hex_color(slide.overlay_color)
            
            is_intro = slide.label_text != str(slide.countdown_value)
            
            if is_intro:
                # --- Frame 0: Global Title card ---
                title_frame = Image.new("RGB", (profile.width, profile.height), color)
                draw_title = ImageDraw.Draw(title_frame)
                try:
                    font_title = ImageFont.load_default(size=max(32, profile.height // 10))
                except TypeError:
                    font_title = ImageFont.load_default()
                text_t = slide.label_text
                bbox_t = draw_title.textbbox((0, 0), text_t, font=font_title)
                t_w, t_h = bbox_t[2] - bbox_t[0], bbox_t[3] - bbox_t[1]
                draw_title.text(((profile.width - t_w) // 2, (profile.height - t_h) // 2), text_t, fill=(255, 255, 255), font=font_title)
                out_title = workdir / f"frame_{idx:04d}_intro.jpg"
                title_frame.save(out_title, format="JPEG", quality=92)
                rendered.append((out_title, title_dur))

            # --- Frame 1: Text ---
            text_frame = Image.new("RGB", (profile.width, profile.height), color)
            draw_text = ImageDraw.Draw(text_frame)
            
            try:
                font_size = max(24, profile.height // 12)
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()

            text_n = str(slide.countdown_value)
            bbox = draw_text.textbbox((0, 0), text_n, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            
            x = (profile.width - text_w) // 2
            y = (profile.height - text_h) // 2
            
            # Draw text centered
            draw_text.text((x, y), text_n, fill=(255, 255, 255), font=font)
            
            out_text = workdir / f"frame_{idx:04d}_a.jpg"
            text_frame.save(out_text, format="JPEG", quality=92)
            rendered.append((out_text, text_dur))

            # --- Frame 2: Image ---
            avoid_signatures: set[str] | None = None
            if idx == total and first_resolved_signature is not None:
                avoid_signatures = {first_resolved_signature}

            resolved, resolved_ref = self._resolve_slide_image(
                slide,
                all_slide_refs,
                image_cache,
                previous_ref=last_resolved_ref,
                previous_signature=last_resolved_signature,
                used_signatures=used_signatures,
                avoid_signatures=avoid_signatures,
            )
            if resolved is None:
                progress(f"Slide {idx}/{total}: source unavailable, using placeholder.", idx / total)
                img = self._build_placeholder_image(profile, slide)
                last_resolved_ref = None
                last_resolved_signature = None
            else:
                img = resolved
                signature = self._image_signature(img)

                repeated_signature = (
                    (last_resolved_signature is not None and signature == last_resolved_signature)
                    or signature in used_signatures
                )

                if repeated_signature:
                    retry_avoid = {signature}
                    if idx == total and first_resolved_signature is not None:
                        retry_avoid.add(first_resolved_signature)
                    alt_img, alt_ref = self._resolve_slide_image(
                        slide,
                        all_slide_refs,
                        image_cache,
                        previous_ref=last_resolved_ref,
                        previous_signature=last_resolved_signature,
                        used_signatures=None,
                        avoid_signatures=retry_avoid,
                    )
                    if alt_img is not None:
                        alt_signature = self._image_signature(alt_img)
                        if alt_signature != signature:
                            img = alt_img
                            resolved_ref = alt_ref
                            signature = alt_signature
                            repeated_signature = (
                                (last_resolved_signature is not None and signature == last_resolved_signature)
                                or signature in used_signatures
                            )

                if repeated_signature:
                    progress(
                        f"Slide {idx}/{total}: repeated image unavoidable, keeping original image.",
                        idx / total,
                    )

                if first_resolved_signature is None:
                    first_resolved_signature = signature
                used_signatures.add(signature)
                last_resolved_signature = signature
                last_resolved_ref = resolved_ref
            img_frame = ImageOps.pad(img, (profile.width, profile.height), method=Image.Resampling.LANCZOS, color=(0, 0, 0))

            out_img = workdir / f"frame_{idx:04d}_b.jpg"
            img_frame.save(out_img, format="JPEG", quality=92)
            rendered.append((out_img, img_dur))

        return rendered

    @staticmethod
    def _write_concat_file(frames: list[tuple[Path, float]], workdir: Path) -> Path:
        concat = workdir / "frames.txt"
        lines: list[str] = []
        for path, dur in frames:
            lines.append(f"file '{path.as_posix()}'")
            lines.append(f"duration {dur:.3f}")
        # ffmpeg concat demuxer requires last frame without a duration line.
        lines.append(f"file '{frames[-1][0].as_posix()}'")
        concat.write_text("\n".join(lines), encoding="utf-8")
        return concat

    @staticmethod
    def _compact_ffmpeg_error(stderr: str, stdout: str) -> str:
        raw = (stderr or stdout or "").strip()
        if not raw:
            return "ffmpeg command failed"

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        noisy_prefixes = (
            "ffmpeg version",
            "built with",
            "configuration:",
            "libavutil",
            "libavcodec",
            "libavformat",
            "libavdevice",
            "libavfilter",
            "libswscale",
            "libswresample",
            "libpostproc",
        )
        filtered = [line for line in lines if not line.lower().startswith(noisy_prefixes)]
        useful = filtered or lines
        summary = " | ".join(useful[-6:])
        if len(summary) > 700:
            summary = summary[:700] + "..."
        return summary

    def _run(self, cmd: list[str]) -> None:
        run_cmd = list(cmd)
        if "-hide_banner" not in run_cmd:
            run_cmd.insert(1, "-hide_banner")
        if "-loglevel" not in run_cmd:
            run_cmd.insert(2, "-loglevel")
            run_cmd.insert(3, "error")

        proc = subprocess.run(run_cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            detail = self._compact_ffmpeg_error(proc.stderr, proc.stdout)
            raise ExportServiceError(detail)

    @staticmethod
    def _normalize_output_path(output: Path, container: str) -> Path:
        expected_suffix = f".{container.lower()}"
        if output.suffix.lower() == expected_suffix:
            return output
        return output.with_suffix(expected_suffix)

    def _validate_output_destination(self, output: Path) -> None:
        if output.exists() and output.is_dir():
            raise ExportServiceError(f"'{output}' is a folder, not a file. Choose a file name in a writable folder.")

        parent = output.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportServiceError(
                f"Cannot create the export folder '{parent}'. Choose a writable location or a different file name."
            ) from exc

        try:
            with tempfile.NamedTemporaryFile(dir=parent, prefix=".slideshow-write-check-", delete=True):
                pass
        except OSError as exc:
            raise ExportServiceError(
                f"Cannot write to the export folder '{parent}'. Choose a different destination."
            ) from exc

        if output.exists():
            try:
                with output.open("ab"):
                    pass
            except OSError as exc:
                raise ExportServiceError(
                    f"The selected export file '{output}' is not writable. Choose a different file name."
                ) from exc

    def export_slideshow(
        self,
        slides: list[SlideFrame],
        target_size_mb: float,
        output_path: str,
        prefer_webm: bool = False,
        audio_track: Optional[AudioTrack] = None,
        audio_path: Optional[str] = None,
        progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    ) -> ExportResult:
        """Export slideshow to video respecting size target and codec fallback."""
        def _report(msg: str, percent: float = 0.0) -> None:
            if progress_cb:
                progress_cb(ProgressEvent("export", msg, percent))

        if not slides:
            raise AppError(ErrorCategory.USER_INPUT, "No slides available for export.", "Generate a slideshow preview before exporting.")

        _report("Detecting FFmpeg capabilities...", 0.0)
        caps = self.detect_capabilities()
        if not caps.ffmpeg_path:
            raise AppError(
                ErrorCategory.SYSTEM,
                "FFmpeg executable not found or failed to load.",
                "Ensure FFmpeg is installed and added to your system path."
            )

        profile = self.plan_export_profile(
            slide_count=len(slides),
            target_size_mb=target_size_mb,
            prefer_webm=prefer_webm,
            caps=caps,
        )

        if prefer_webm and profile.container != "webm":
            _report(f"Preferred WebM export was unavailable; falling back to {profile.container.upper()}.", 0.05)
        elif not prefer_webm and profile.container != "mp4":
            _report(f"Preferred MP4 export was unavailable; falling back to {profile.container.upper()}.", 0.05)

        output = Path(output_path)
        normalized_output = self._normalize_output_path(output, profile.container)
        if normalized_output != output:
            _report(
                f"Output extension adjusted to {normalized_output.suffix.upper()} to match {profile.container.upper()} container.",
                0.07,
            )
        output = normalized_output
        self._validate_output_destination(output)

        with tempfile.TemporaryDirectory(prefix="slideshow-export-") as tmp:    
            workdir = Path(tmp)
            _report("Preparing slide images...", 0.1)
            def _img_stage_progress(msg: str, p: float) -> None:
                _report(msg, 0.1 + (p * 0.4))
            frames_and_durations = self._render_slides_to_images(slides, profile, workdir, _img_stage_progress)
            concat_file = self._write_concat_file(frames_and_durations, workdir)

            silent_video = workdir / f"silent.{profile.container}"
            _report(f"Using codec {profile.video_codec} via {Path(caps.ffmpeg_path).name}.", 0.48)
            _report("Encoding slideshow video (this may take a while)...", 0.5)

            def _encode_cmd(codec: str) -> list[str]:
                cmd = [
                    caps.ffmpeg_path,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-r",
                    str(profile.fps),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:v",
                    codec,
                    "-b:v",
                    f"{profile.video_bitrate_kbps}k",
                    "-an",
                    str(silent_video),
                ]
                if codec == "libvpx-vp9":
                    cmd.extend(["-deadline", "good", "-cpu-used", "2"])
                return cmd

            selected_codec = profile.video_codec
            try:
                self._run(_encode_cmd(selected_codec))
            except ExportServiceError as nvenc_error:
                if selected_codec == "h264_nvenc":
                    fallback_codec = "libx264" if caps.has_libx264 else "h264"
                    _report("NVENC failed on this machine. Falling back to CPU encoder...", 0.55)
                    try:
                        self._run(_encode_cmd(fallback_codec))
                    except ExportServiceError as fallback_error:
                        raise ExportServiceError(
                            f"NVENC and CPU fallback failed. NVENC error: {nvenc_error}. "
                            f"CPU fallback error: {fallback_error}"
                        ) from fallback_error
                    selected_codec = fallback_codec
                else:
                    raise
            profile.video_codec = selected_codec

            audio_source_path: Optional[str] = None
            stream_loop: Optional[int] = None
            if audio_track is not None:
                audio_source_path = audio_track.path
                stream_loop = audio_track.loop_count
            elif audio_path and Path(audio_path).exists():
                audio_source_path = audio_path
                stream_loop = -1

            if audio_source_path and Path(audio_source_path).exists():
                loop_label = "until video end"
                if stream_loop is not None and stream_loop >= 0:
                    loop_label = f"{stream_loop + 1} play(s)"
                _report(f"Looping and muxing audio ({loop_label})...", 0.8)
                mux_cmd = [
                    caps.ffmpeg_path,
                    "-y",
                    "-i",
                    str(silent_video),
                ]
                if stream_loop is not None:
                    mux_cmd.extend(["-stream_loop", str(stream_loop)])
                mux_cmd.extend(
                    [
                    "-i",
                    str(audio_source_path),
                    "-shortest",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    profile.audio_codec,
                    "-b:a",
                    f"{profile.audio_bitrate_kbps}k",
                    str(output),
                    ]
                )
                self._run(mux_cmd)
            else:
                shutil.copyfile(silent_video, output)

        actual_size_mb = output.stat().st_size / (1024 * 1024)
        _report(f"Export complete: {actual_size_mb:.2f} MB", 1.0)
        return ExportResult(output_path=str(output), actual_size_mb=actual_size_mb, profile=profile)
