"""Core domain models for slideshow generation and export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from typing import Optional


HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}){1,2}$")


class GenerationStatus(str, Enum):
    DRAFT = "draft"
    COLLECTING_IMAGES = "collecting_images"
    COMPOSING_SLIDES = "composing_slides"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorCategory(str, Enum):
    USER_INPUT = "user_input"
    NETWORK = "network"
    MEDIA = "media"
    SYSTEM = "system"


@dataclass(slots=True)
class AppError(Exception):
    """Structured error object for friendly failure reporting."""

    category: ErrorCategory
    message: str
    recovery_hint: str

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class ProgressEvent:
    """Real-time progress reporting hook payload."""

    phase: str
    message: str
    percent: Optional[float] = None


def _require_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _require_positive_int(value: int, field_name: str) -> int:
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return value


def _require_positive_float(value: float, field_name: str) -> float:
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return value


def _require_hex_color(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not HEX_COLOR_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a valid hex color")
    return normalized


@dataclass(slots=True)
class GenerationRequest:
    id: str
    search_term: str
    slide_count: int
    target_size_mb: float
    background_color: str
    output_format: str
    music_path: Optional[str] = None
    status: GenerationStatus = GenerationStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        self.search_term = _require_non_empty(self.search_term, "search_term")
        self.slide_count = _require_positive_int(self.slide_count, "slide_count")
        self.target_size_mb = _require_positive_float(self.target_size_mb, "target_size_mb")
        self.background_color = _require_hex_color(self.background_color, "background_color")
        self.output_format = _require_non_empty(self.output_format, "output_format")
        if self.music_path is not None:
            normalized_music_path = self.music_path.strip()
            self.music_path = normalized_music_path or None

    @property
    def opening_label(self) -> str:
        """Return the first-slide label in the required top-N format."""
        return f"top {self.slide_count} {self.search_term}"


@dataclass(slots=True)
class ImageAsset:
    id: str
    source_url: str
    source_name: str
    sha256: str
    cache_path: str
    width: int
    height: int
    selected_order: int
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        self.source_url = _require_non_empty(self.source_url, "source_url")
        self.source_name = _require_non_empty(self.source_name, "source_name")
        self.sha256 = _require_non_empty(self.sha256, "sha256")
        self.cache_path = _require_non_empty(self.cache_path, "cache_path")
        self.width = _require_positive_int(self.width, "width")
        self.height = _require_positive_int(self.height, "height")
        if self.selected_order < 0:
            raise ValueError("selected_order must be 0 or greater")


@dataclass(slots=True)
class Slide:
    index: int
    label_text: str
    image_asset_id: str
    duration_ms: int
    overlay_color: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("index must be 0 or greater")
        self.label_text = _require_non_empty(self.label_text, "label_text")
        self.image_asset_id = _require_non_empty(self.image_asset_id, "image_asset_id")
        self.duration_ms = _require_positive_int(self.duration_ms, "duration_ms")
        self.overlay_color = _require_hex_color(self.overlay_color, "overlay_color")


@dataclass(slots=True)
class AudioTrack:
    path: str
    duration_ms: int
    loop_count: int
    validated: bool

    def __post_init__(self) -> None:
        self.path = _require_non_empty(self.path, "path")
        self.duration_ms = _require_positive_int(self.duration_ms, "duration_ms")
        if self.loop_count < 0:
            raise ValueError("loop_count must be 0 or greater")


@dataclass(slots=True)
class ExportJob:
    id: str
    container: str
    codec: str
    encoder_mode: str
    target_bitrate_kbps: int
    output_path: str
    status: GenerationStatus = GenerationStatus.DRAFT
    actual_size_mb: Optional[float] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        self.container = _require_non_empty(self.container, "container")
        self.codec = _require_non_empty(self.codec, "codec")
        self.encoder_mode = _require_non_empty(self.encoder_mode, "encoder_mode")
        self.target_bitrate_kbps = _require_positive_int(self.target_bitrate_kbps, "target_bitrate_kbps")
        self.output_path = _require_non_empty(self.output_path, "output_path")
        if self.actual_size_mb is not None:
            self.actual_size_mb = _require_positive_float(self.actual_size_mb, "actual_size_mb")
