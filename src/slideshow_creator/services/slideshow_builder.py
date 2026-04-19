"""Slideshow assembly service scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

from slideshow_creator.models.domain import AppError, ErrorCategory, ProgressEvent


class SlideshowBuildError(ValueError):
    """Base validation error for slideshow generation."""


class NotEnoughImagesError(SlideshowBuildError):
    """Raised when there are no usable images for slideshow generation."""


@dataclass(slots=True)
class SlideFrame:
    """Represents one slide in the countdown sequence."""

    index: int
    countdown_value: int
    label_text: str
    image_ref: str
    overlay_color: str


@dataclass(slots=True)
class BuildSummary:
    """Describes how the slideshow build was satisfied."""

    requested_count: int
    available_images: int
    reused_images: int
    warning: str | None = None


@dataclass(slots=True)
class BuildResult:
    """Structured slideshow build response."""

    slides: List[SlideFrame]
    summary: BuildSummary


class SlideshowBuilder:
    """Build countdown slide metadata from image references."""

    @staticmethod
    def _find_insert_position(assignment: List[str], image_ref: str, target_index: int) -> int:
        """Pick an insertion slot near target_index that avoids adjacent duplicates when possible."""
        if not assignment:
            return 0

        target = max(1, min(len(assignment), target_index))
        for delta in range(0, len(assignment) + 1):
            for candidate in (target - delta, target + delta):
                if candidate < 1 or candidate > len(assignment):
                    continue
                prev_ref = assignment[candidate - 1] if candidate - 1 >= 0 else None
                next_ref = assignment[candidate] if candidate < len(assignment) else None
                if image_ref != prev_ref and image_ref != next_ref:
                    return candidate
        return target

    @staticmethod
    def _separate_adjacent_duplicates(assignment: List[str]) -> None:
        """Swap elements in-place to reduce adjacent duplicate image refs."""
        for idx in range(1, len(assignment)):
            if assignment[idx] != assignment[idx - 1]:
                continue

            swapped = False
            for swap_idx in range(idx + 1, len(assignment)):
                candidate = assignment[swap_idx]
                left_neighbor = assignment[idx - 1]
                right_neighbor = assignment[idx + 1] if idx + 1 < len(assignment) else None
                if candidate == left_neighbor or candidate == right_neighbor:
                    continue
                assignment[idx], assignment[swap_idx] = assignment[swap_idx], assignment[idx]
                swapped = True
                break

            if not swapped:
                continue

    @staticmethod
    def _avoid_cyclic_duplicate(assignment: List[str]) -> None:
        """Avoid using the same image on both first and last slide when alternatives exist."""
        if len(assignment) < 2 or assignment[0] != assignment[-1]:
            return

        for swap_idx in range(len(assignment) - 2, 0, -1):
            candidate = assignment[swap_idx]
            if candidate == assignment[0]:
                continue
            if candidate == assignment[-2]:
                continue
            assignment[-1], assignment[swap_idx] = assignment[swap_idx], assignment[-1]
            return

    def build(
        self,
        search_term: str,
        count: int,
        image_refs: Iterable[str],
        overlay_color: str,
        allow_reuse: bool = True,
        progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    ) -> BuildResult:
        """Create a countdown slideshow from N to 1 with a top-N opening slide label."""
        def _report(msg: str, percent: float) -> None:
            if progress_cb:
                progress_cb(ProgressEvent("build", msg, percent))

        _report("Validating input values...", 0.0)
        normalized_term = search_term.strip()
        if not normalized_term:
            raise AppError(ErrorCategory.USER_INPUT, "Search term is required.", "Enter a word or phrase.")
        if count <= 0:
            raise AppError(ErrorCategory.USER_INPUT, "Slide count must be greater than 0.", "Increase the slide count.")

        refs = self._normalize_refs(image_refs)
        if not refs:
            raise AppError(
                ErrorCategory.MEDIA,
                "No usable images were found for the selected search term.",
                "Try a different search term or check internet access."
            )
        if len(refs) < count and not allow_reuse:
            raise AppError(
                ErrorCategory.MEDIA,
                f"Requested {count} slides but only {len(refs)} unique images are available.",
                "Decrease the slide count or enable image reuse."
            )

        slides: List[SlideFrame] = []

        # Build an assignment list that avoids consecutive repeats.
        # First pass: one unique image per slide (up to len(refs)).
        # Second pass: fill remaining slots from a reshuffled copy,
        # skipping any image that would repeat the previous slide.
        import hashlib as _hl, random as _rng

        assignment: List[str] = list(refs[:count])
        if count > len(refs):
            pool_seed = int(_hl.sha256(search_term.encode()).hexdigest(), 16)
            pool_rng = _rng.Random(pool_seed)
            extras_needed = count - len(refs)
            extras: List[str] = []
            while len(extras) < extras_needed:
                bag = list(refs)
                pool_rng.shuffle(bag)
                for img in bag:
                    extras.append(img)
                    if len(extras) >= extras_needed:
                        break

            # Spread reuse across the full countdown instead of concentrating it at the end.
            for extra_index, image_ref in enumerate(extras):
                target_index = int(round(((extra_index + 1) * count) / (extras_needed + 1)))
                insert_at = self._find_insert_position(assignment, image_ref, target_index)
                assignment.insert(insert_at, image_ref)

            self._separate_adjacent_duplicates(assignment)
            self._avoid_cyclic_duplicate(assignment)

        for idx in range(count):
            if idx % max(1, count // 10) == 0:
                _report(f"Composing slide {idx + 1} of {count}...", idx / count)

            countdown_value = count - idx
            label = f"top {count} {normalized_term}" if idx == 0 else str(countdown_value)
            ref = assignment[idx]
            slides.append(
                SlideFrame(
                    index=idx,
                    countdown_value=countdown_value,
                    label_text=label,
                    image_ref=ref,
                    overlay_color=overlay_color,
                )
            )

        reused_images = max(0, count - len(refs))
        warning = None
        if reused_images > 0:
            warning = (
                f"Only {len(refs)} unique images were found. "
                f"Reused {reused_images} image slots to complete {count} slides."
            )

        summary = BuildSummary(
            requested_count=count,
            available_images=len(refs),
            reused_images=reused_images,
            warning=warning,
        )
        
        _report("Composition complete.", 1.0)
        return BuildResult(slides=slides, summary=summary)

    @staticmethod
    def _normalize_refs(image_refs: Iterable[str]) -> Sequence[str]:
        seen = set()
        normalized: List[str] = []
        for ref in image_refs:
            cleaned = ref.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized
