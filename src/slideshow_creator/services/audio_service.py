"""Audio validation and loop planning scaffold."""

from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess
from typing import Optional

from slideshow_creator.models.domain import AudioTrack


class AudioServiceError(RuntimeError):
    """Raised when MP3 validation or inspection fails."""


class AudioService:
    """Validate MP3 inputs and determine loop counts."""

    SAMPLE_RATE_TABLE = {
        1: (44100, 48000, 32000),
        2: (22050, 24000, 16000),
        25: (11025, 12000, 8000),
    }

    BITRATE_TABLES = {
        (1, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0),
        (1, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0),
        (1, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
        (2, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0),
        (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
        (2, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
        (25, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0),
        (25, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
        (25, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    }

    def validate_mp3(self, path: str) -> bool:
        """Return True when the selected file is an existing MP3 path."""
        try:
            self.inspect_mp3(path)
            return True
        except AudioServiceError:
            return False

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    @staticmethod
    def _syncsafe_to_int(data: bytes) -> int:
        value = 0
        for byte in data:
            value = (value << 7) | (byte & 0x7F)
        return value

    def _skip_id3v2(self, data: bytes) -> int:
        if not data.startswith(b"ID3") or len(data) < 10:
            return 0

        tag_size = self._syncsafe_to_int(data[6:10])
        return min(len(data), 10 + tag_size)

    def _parse_mp3_frame_header(self, data: bytes, position: int) -> tuple[int, int, int] | None:
        if position + 4 > len(data):
            return None

        byte1, byte2, byte3, _byte4 = data[position : position + 4]
        if byte1 != 0xFF or (byte2 & 0xE0) != 0xE0:
            return None

        version_bits = (byte2 >> 3) & 0x03
        layer_bits = (byte2 >> 1) & 0x03
        bitrate_index = (byte3 >> 4) & 0x0F
        sample_rate_index = (byte3 >> 2) & 0x03
        padding = (byte3 >> 1) & 0x01

        if version_bits == 0b01 or layer_bits == 0b00 or bitrate_index in {0, 15} or sample_rate_index == 3:
            return None

        version = {0b11: 1, 0b10: 2, 0b00: 25}.get(version_bits)
        layer = {0b11: 1, 0b10: 2, 0b01: 3}.get(layer_bits)
        if version is None or layer is None:
            return None

        sample_rates = self.SAMPLE_RATE_TABLE.get(version)
        if not sample_rates:
            return None

        bitrates = self.BITRATE_TABLES.get((version, layer))
        if not bitrates:
            return None

        sample_rate = sample_rates[sample_rate_index]
        bitrate_kbps = bitrates[bitrate_index]
        if sample_rate <= 0 or bitrate_kbps <= 0:
            return None

        if layer == 1:
            frame_length = int((((12 * bitrate_kbps * 1000) / sample_rate) + padding) * 4)
            samples_per_frame = 384
        else:
            factor = 144000 if version == 1 else 72000
            frame_length = int((factor * bitrate_kbps / sample_rate) + padding)
            samples_per_frame = 1152 if layer in {1, 2} or version == 1 else 576

        if frame_length <= 0:
            return None

        return frame_length, samples_per_frame, sample_rate

    def _duration_from_mp3_frames(self, target: Path) -> float:
        data = target.read_bytes()
        start = self._skip_id3v2(data)
        limit = len(data)
        if limit >= 128 and data[-128:-125] == b"TAG":
            limit -= 128

        position = start
        frames = 0
        total_samples = 0
        sample_rate = 0

        while position + 4 <= limit:
            header = self._parse_mp3_frame_header(data, position)
            if header is None:
                position += 1
                continue

            frame_length, samples_per_frame, frame_sample_rate = header
            if position + frame_length > limit:
                position += 1
                continue

            frames += 1
            total_samples += samples_per_frame
            sample_rate = frame_sample_rate
            position += frame_length

        if frames == 0 or sample_rate <= 0:
            raise AudioServiceError("Unable to inspect MP3 duration.")

        return total_samples / sample_rate

    def _duration_from_ffprobe(self, target: Path) -> Optional[float]:
        if not target.exists():
            raise AudioServiceError("MP3 file does not exist.")
        if target.suffix.lower() != ".mp3":
            raise AudioServiceError("Selected audio must be an MP3 file.")

        env_path = os.getenv("SLIDESHOW_FFPROBE_PATH")
        candidate_paths = [env_path] if env_path else []
        bundled_dir = self._project_root() / "assets" / "ffmpeg"
        candidate_paths.extend(
            [
                str(bundled_dir / "ffprobe.exe"),
                str(bundled_dir / "ffprobe"),
            ]
        )

        import shutil
        system_ffprobe = shutil.which("ffprobe")
        if system_ffprobe:
            candidate_paths.append(system_ffprobe)

        if os.name == "nt":
            candidate_paths.extend([
                r"C:\ffmpeg\bin\ffprobe.exe",
                r"C:\ffmpeg\ffprobe.exe",
                r"C:\Program Files\ffmpeg\bin\ffprobe.exe"
            ])

        candidate_paths = list(dict.fromkeys([p for p in candidate_paths if p]))

        for executable in candidate_paths:
            if not executable or not Path(executable).exists():
                continue

            try:
                result = subprocess.run(
                    [
                        executable,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(target),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    value = result.stdout.strip()
                    if value:
                        return max(float(value), 0.0)
            except (OSError, subprocess.SubprocessError, ValueError):
                continue

        return None

    def _duration_seconds(self, target: Path) -> float:
        if not target.exists():
            raise AudioServiceError("MP3 file does not exist.")
        if target.suffix.lower() != ".mp3":
            raise AudioServiceError("Selected audio must be an MP3 file.")

        ffprobe_duration = self._duration_from_ffprobe(target)
        if ffprobe_duration is not None:
            return ffprobe_duration

        try:
            return self._duration_from_mp3_frames(target)
        except AudioServiceError as exc:
            raise AudioServiceError(str(exc) or "Unable to inspect MP3 duration.") from exc

    def required_loops(self, track_seconds: float, video_seconds: float) -> int:
        """Calculate additional loop count required to cover the video duration."""
        if track_seconds <= 0:
            return 0
        if video_seconds <= 0:
            return 0
        plays = math.ceil(video_seconds / track_seconds)
        return max(plays - 1, 0)

    def inspect_mp3(self, path: str, video_seconds: float | None = None) -> AudioTrack:
        """Validate an MP3 and return duration plus optional loop planning."""
        target = Path(path)
        duration_seconds = self._duration_seconds(target)
        loop_count = self.required_loops(duration_seconds, video_seconds or 0.0)
        return AudioTrack(
            path=str(target),
            duration_ms=max(int(duration_seconds * 1000), 1),
            loop_count=loop_count,
            validated=True,
        )
