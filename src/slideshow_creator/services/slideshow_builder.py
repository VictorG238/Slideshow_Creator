"""Slideshow assembly service scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

from slideshow_creator.models.domain import AppError, ErrorCategory, ProgressEvent, SearchRunSummary


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
    search_summary: Optional[SearchRunSummary] = None


class SlideshowBuilder:
    """Build countdown slide metadata from image references."""

    @staticmethod
    def _build_interleaved_assignment(
        refs: Sequence[str], count: int, search_term: str
    ) -> List[str]:
        """Assign images to slide slots using stride-based interleaving.

        Given N unique images and C slots, each image is placed at
        positions ``i, i+N, i+2N, ...`` which guarantees a minimum
        spacing of N between repeated uses.  A deterministic shuffle
        of the image order per cycle adds visual variety while keeping
        the result reproducible for the same search term.
        """
        import hashlib as _hl, random as _rng

        n = len(refs)
        seed = int(_hl.sha256(search_term.encode()).hexdigest(), 16)
        rng = _rng.Random(seed)

        # Build full cycles, each independently shuffled.
        full_cycles = count // n
        remainder = count % n
        assignment: List[str] = []

        for _ in range(full_cycles):
            cycle = list(refs)
            rng.shuffle(cycle)
            assignment.extend(cycle)

        if remainder:
            tail = list(refs)
            rng.shuffle(tail)
            assignment.extend(tail[:remainder])

        # Final pass: fix any adjacent duplicates at cycle boundaries.
        SlideshowBuilder._fix_adjacent_duplicates(assignment)

        # Ensure last few slides don't reuse the same images as the first few.
        SlideshowBuilder._fix_tail_head_overlap(assignment)

        return assignment

    @staticmethod
    def _fix_tail_head_overlap(assignment: List[str], window: int = 5) -> None:
        """Swap tail slots that duplicate head slots with safe mid-range slots."""
        if len(assignment) <= window * 2:
            return
        head_refs = set(assignment[:window])
        tail_start = len(assignment) - window
        for tail_idx in range(tail_start, len(assignment)):
            if assignment[tail_idx] not in head_refs:
                continue
            # Find a mid-range element not in head_refs that won't create adjacent dup.
            for mid_idx in range(window, tail_start):
                candidate = assignment[mid_idx]
                if candidate in head_refs:
                    continue
                prev_tail = assignment[tail_idx - 1] if tail_idx > 0 else None
                next_tail = assignment[tail_idx + 1] if tail_idx + 1 < len(assignment) else None
                if candidate == prev_tail or candidate == next_tail:
                    continue
                left_mid = assignment[mid_idx - 1] if mid_idx > 0 else None
                right_mid = assignment[mid_idx + 1] if mid_idx + 1 < len(assignment) else None
                if assignment[tail_idx] == left_mid or assignment[tail_idx] == right_mid:
                    continue
                assignment[tail_idx], assignment[mid_idx] = assignment[mid_idx], assignment[tail_idx]
                break

    @staticmethod
    def _fix_adjacent_duplicates(assignment: List[str]) -> None:
        """Swap to break adjacent duplicates, especially at cycle boundaries."""
        length = len(assignment)
        for idx in range(1, length):
            if assignment[idx] != assignment[idx - 1]:
                continue
            # Search for the nearest different-valued element to swap with.
            best = -1
            best_dist = length
            for swap_idx in range(length):
                if swap_idx == idx or swap_idx == idx - 1:
                    continue
                candidate = assignment[swap_idx]
                if candidate == assignment[idx]:
                    continue
                # Ensure the swap doesn't create a new adjacent dup.
                left = assignment[swap_idx - 1] if swap_idx > 0 else None
                right = assignment[swap_idx + 1] if swap_idx + 1 < length else None
                if assignment[idx] == left or assignment[idx] == right:
                    continue
                dist = abs(swap_idx - idx)
                if dist < best_dist:
                    best_dist = dist
                    best = swap_idx
            if best >= 0:
                assignment[idx], assignment[best] = assignment[best], assignment[idx]

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

        # Build assignment: direct slice when enough unique images,
        # otherwise stride-interleave to maximize spacing between repeats.
        if count <= len(refs):
            assignment = list(refs[:count])
        else:
            assignment = self._build_interleaved_assignment(refs, count, normalized_term)

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
