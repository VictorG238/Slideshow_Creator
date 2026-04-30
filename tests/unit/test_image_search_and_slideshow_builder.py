from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest
from PIL import Image

from slideshow_creator.models.domain import AppError
from slideshow_creator.services.image_search import ImageCandidate, ImageSearchService
from slideshow_creator.services.slideshow_builder import SlideshowBuilder


def _make_candidate_pool(size: int, term: str = "test", provider: str = "google", valid: bool = True) -> list[ImageCandidate]:
    return [
        ImageCandidate(
            source_url=f"https://images.example.com/{term}-{i}.jpg",
            source_name=provider,
            title=f"{term} {i}",
            width=1024 if valid else 0,
            height=768 if valid else 0,
        )
        for i in range(1, size + 1)
    ]

def _make_provider_stub(pool: list[ImageCandidate]):
    return lambda term, limit: pool[:limit]

def test_image_search_probe_enforces_request_bounds() -> None:
    service = ImageSearchService()
    with pytest.raises(AppError) as exc:
        service.probe("cats", 0)
    assert "between 1 and" in str(exc.value)

    with pytest.raises(AppError) as exc:
        service.probe("cats", 2001)
    assert "between 1 and" in str(exc.value)

def test_image_search_probe_enforces_source_selection() -> None:
    service = ImageSearchService()
    with pytest.raises(AppError) as exc:
        service.probe("cats", 5, providers=[])
    assert "Select at least one search engine" in str(exc.value)


def test_image_search_probe_normalizes_and_deduplicates_candidates() -> None:
    service = ImageSearchService()

    service._probe_openverse = lambda term, limit: [
        ImageCandidate("https://images.example.com/owl.jpg?size=large", "openverse:tester", term, 0, 0),
    ]
    service._probe_google = lambda term, limit: [
        ImageCandidate("https://images.example.com/cat.jpg?size=large", "google", term, 0, 0),
        ImageCandidate("https://images.example.com/dog.jpg", "google", term, 0, 0),
    ]
    service._probe_bing = lambda term, limit: [
        ImageCandidate("https://images.example.com/cat.jpg?size=thumb", "bing", term, 0, 0),
    ]
    service._probe_duckduckgo = lambda term, limit: []

    results, summary = service.probe("cats", 5)

    assert len(results) == 3
    assert {candidate.source_url for candidate in results} == {
        "https://images.example.com/owl.jpg",
        "https://images.example.com/cat.jpg",
        "https://images.example.com/dog.jpg",
    }
    assert all(candidate.source_name in {"openverse:tester", "google", "bing"} for candidate in results)


def test_image_search_probe_returns_empty_when_all_providers_fail() -> None:
    service = ImageSearchService()
    service._probe_openverse = lambda term, limit: []
    service._probe_google = lambda term, limit: []
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []

    with pytest.raises(AppError):
        service.probe("car", 3)


def test_image_search_probe_respects_selected_providers_only() -> None:
    service = ImageSearchService()

    service._probe_openverse = lambda term, limit: [
        ImageCandidate("https://images.example.com/openverse.jpg", "openverse", term, 0, 0),
    ]
    service._probe_google = lambda term, limit: [
        ImageCandidate("https://images.example.com/google.jpg", "google", term, 0, 0),
    ]
    service._probe_bing = lambda term, limit: [
        ImageCandidate("https://images.example.com/bing.jpg", "bing", term, 0, 0),
    ]
    service._probe_duckduckgo = lambda term, limit: [
        ImageCandidate("https://images.example.com/ddg.jpg", "duckduckgo", term, 0, 0),
    ]

    results, summary = service.probe("cats", 10, providers=["bing"])

    assert len(results) == 1
    result_urls = {r.source_url for r in results}
    assert "https://images.example.com/bing.jpg" in result_urls


def test_image_search_probe_requires_at_least_one_selected_provider() -> None:
    service = ImageSearchService()

    with pytest.raises(AppError):
        service.probe("cats", 10, providers=[])


def test_image_search_probe_falls_back_when_selected_engine_returns_no_results() -> None:
    service = ImageSearchService()

    service._probe_openverse = lambda term, limit: []
    service._probe_google = lambda term, limit: [
        ImageCandidate("https://images.example.com/fallback-google.jpg", "google", term, 0, 0),
    ]
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []

    results, summary = service.probe("cats", 5, providers=["openverse"])

    assert len(results) == 1
    assert results[0].source_url == "https://images.example.com/fallback-google.jpg"


def test_canonical_url_keeps_identity_query_for_bing_thumbnail_urls() -> None:
    first = "https://tse4.mm.bing.net/th?id=OIP.AAA111&pid=Api&w=320&h=180"
    second = "https://tse4.mm.bing.net/th?id=OIP.BBB222&pid=Api&w=320&h=180"

    first_canonical = ImageSearchService._canonical_url(first)
    second_canonical = ImageSearchService._canonical_url(second)

    assert first_canonical != second_canonical
    assert "id=OIP.AAA111" in first_canonical
    assert "id=OIP.BBB222" in second_canonical
    assert "pid=" not in first_canonical
    assert "w=" not in first_canonical
    assert "h=" not in first_canonical


def test_probe_can_filter_for_downloadable_unique_candidates() -> None:
    service = ImageSearchService(validate_candidates=True, validation_pool_factor=1, max_validation_checks=10)
    service._probe_openverse = lambda term, limit: []
    service._probe_google = lambda term, limit: [
        ImageCandidate("https://images.example.com/a.jpg", "google", term, 0, 0),
        ImageCandidate("https://images.example.com/b.jpg", "google", term, 0, 0),
        ImageCandidate("https://images.example.com/c.jpg", "google", term, 0, 0),
    ]
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []

    signatures = {
        "https://images.example.com/a.jpg": "sig-red",
        "https://images.example.com/b.jpg": "sig-red",  # duplicate content
        "https://images.example.com/c.jpg": "sig-green",
    }
    service._probe_image_signature = lambda url: signatures.get(url, "")

    results, summary = service.probe("cats", 2, providers=["google"])

    assert len(results) >= 2
    assert {item.source_url for item in results[:2]} == {
        "https://images.example.com/c.jpg",
        "https://images.example.com/a.jpg",
    }


def test_visual_signature_is_stable_for_same_image_with_different_jpeg_quality(tmp_path) -> None:
    service = ImageSearchService()

    image = Image.new("RGB", (48, 48), (120, 190, 35))
    high_quality = tmp_path / "high.jpg"
    low_quality = tmp_path / "low.jpg"
    image.save(high_quality, format="JPEG", quality=95)
    image.save(low_quality, format="JPEG", quality=45)

    sig_high = service._visual_signature(high_quality.read_bytes())
    sig_low = service._visual_signature(low_quality.read_bytes())

    assert sig_high
    assert sig_low
    assert sig_high == sig_low


def test_downloadable_unique_backfill_stops_at_limit() -> None:
    service = ImageSearchService(validate_candidates=True, validation_pool_factor=3, max_validation_checks=20)
    candidates = [
        ImageCandidate("https://images.example.com/a.jpg", "google", "cats", 0, 0),
        ImageCandidate("https://images.example.com/b.jpg", "google", "cats", 0, 0),
        ImageCandidate("https://images.example.com/c.jpg", "google", "cats", 0, 0),
        ImageCandidate("https://images.example.com/d.jpg", "google", "cats", 0, 0),
    ]

    signatures = {
        "https://images.example.com/a.jpg": "sig-1",
        "https://images.example.com/b.jpg": "sig-1",  # duplicate content
        "https://images.example.com/c.jpg": "",       # invalid
        "https://images.example.com/d.jpg": "",       # invalid
    }
    service._probe_image_signature = lambda url: signatures.get(url, "")

    selected = service._select_downloadable_unique_candidates(candidates, limit=2)

    assert len(selected) == 2
    assert selected[0].source_url == "https://images.example.com/a.jpg"


def test_downloadable_unique_candidates_caps_validation_scans_for_large_factor() -> None:
    service = ImageSearchService(validate_candidates=True, validation_pool_factor=10, max_validation_checks=500)
    candidates = [
        ImageCandidate(f"https://images.example.com/{idx}.jpg", "google", "cats", 0, 0)
        for idx in range(1, 101)
    ]

    call_count = 0

    def _signature(url: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"sig-{url}"

    service._probe_image_signature = _signature

    selected = service._select_downloadable_unique_candidates(candidates, limit=10)

    assert len(selected) >= 10
    assert len(selected) <= 15
    assert call_count <= 30


def test_probe_google_falls_back_to_openverse_when_ddgs_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ImageSearchService()

    # Stub DDGS so it raises, forcing the Openverse fallback path
    class _FailingDDGS:
        def __init__(self, **kwargs):
            pass
        def images(self, *args, **kwargs):
            raise RuntimeError("DDGS unavailable")

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=_FailingDDGS))
    monkeypatch.setattr(
        service,
        "_probe_openverse",
        lambda term, limit: [
            ImageCandidate(
                "https://images.example.com/fallback.jpg",
                "openverse:tester",
                term,
                1200,
                800,
            )
        ],
    )

    results = service._probe_google("cats", 5)

    assert len(results) == 1
    assert results[0].source_url == "https://images.example.com/fallback.jpg"
    assert results[0].source_name == "google-fallback:openverse"



def test_probe_duckduckgo_uses_ddgs_backend_auto_when_primary_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ImageSearchService()

    class _FakeDDGS:
        def __init__(self, timeout: int = 5) -> None:
            self.timeout = timeout

        @staticmethod
        def images(search_term: str, max_results: int, backend: str, region: str = "us-en"):
            if backend == "duckduckgo":
                return []
            return [
                {
                    "image": "https://images.example.com/ddg-auto.jpg",
                    "title": f"{search_term} from auto",
                    "width": "1024",
                    "height": "768",
                }
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=_FakeDDGS))

    results = service._probe_duckduckgo("cats", 5)

    assert len(results) == 1
    assert results[0].source_url == "https://images.example.com/ddg-auto.jpg"
    assert results[0].source_name == "duckduckgo-images"
    assert results[0].width == 1024
    assert results[0].height == 768


def test_slideshow_builder_generates_countdown_with_opening_label() -> None:
    builder = SlideshowBuilder()
    refs = [
        "https://images.example.com/one.jpg",
        "https://images.example.com/two.jpg",
        "https://images.example.com/three.jpg",
    ]

    result = builder.build(
        search_term="car",
        count=3,
        image_refs=refs,
        overlay_color="#87CEEB",
    )

    assert [slide.countdown_value for slide in result.slides] == [3, 2, 1]
    assert result.slides[0].label_text == "top 3 car"
    assert result.slides[1].label_text == "2"
    assert result.slides[2].label_text == "1"
    assert result.summary.requested_count == 3
    assert result.summary.available_images == 3
    assert result.summary.reused_images == 0
    assert result.summary.warning is None


def test_slideshow_builder_reuses_images_and_reports_warning_when_needed() -> None:
    builder = SlideshowBuilder()

    result = builder.build(
        search_term="car",
        count=5,
        image_refs=["https://images.example.com/one.jpg", "https://images.example.com/two.jpg"],
        overlay_color="#87CEEB",
    )

    assert len(result.slides) == 5
    assert result.summary.available_images == 2
    assert result.summary.reused_images == 3
    assert result.summary.warning is not None
    assert result.slides[-1].countdown_value == 1


def test_slideshow_builder_avoids_same_image_for_first_and_last_when_reusing() -> None:
    builder = SlideshowBuilder()

    result = builder.build(
        search_term="cats",
        count=5,
        image_refs=["https://images.example.com/a.jpg", "https://images.example.com/b.jpg"],
        overlay_color="#87CEEB",
    )

    refs = [slide.image_ref for slide in result.slides]
    assert len(refs) == 5
    assert refs[0] != refs[-1]


def test_slideshow_builder_avoids_adjacent_duplicates_in_long_reuse_sequence() -> None:
    builder = SlideshowBuilder()

    result = builder.build(
        search_term="nature",
        count=12,
        image_refs=[
            "https://images.example.com/1.jpg",
            "https://images.example.com/2.jpg",
            "https://images.example.com/3.jpg",
        ],
        overlay_color="#87CEEB",
    )

    refs = [slide.image_ref for slide in result.slides]
    assert len(refs) == 12
    for idx in range(1, len(refs)):
        assert refs[idx] != refs[idx - 1]


def test_slideshow_builder_rejects_empty_search_term() -> None:
    builder = SlideshowBuilder()

    with pytest.raises(AppError):
        builder.build("   ", 3, ["https://images.example.com/one.jpg"], "#87CEEB")


def test_slideshow_builder_rejects_when_reuse_disallowed_and_images_are_insufficient() -> None:
    builder = SlideshowBuilder()

    with pytest.raises(AppError):
        builder.build(
            search_term="car",
            count=3,
            image_refs=["https://images.example.com/one.jpg"],
            overlay_color="#87CEEB",
            allow_reuse=False,
        )


def test_slideshow_builder_tail_does_not_repeat_head_images_on_large_reuse() -> None:
    """Regression: 100 slides from 82 images must not mirror first slides at the end."""
    builder = SlideshowBuilder()
    refs = [f"https://images.example.com/{i}.jpg" for i in range(82)]

    result = builder.build(
        search_term="countdown",
        count=100,
        image_refs=refs,
        overlay_color="#87CEEB",
    )

    assigned = [slide.image_ref for slide in result.slides]
    assert len(assigned) == 100

    head = set(assigned[:5])
    tail = assigned[95:]
    overlap = [ref for ref in tail if ref in head]
    assert len(overlap) == 0, (
        f"Tail slides 95-99 share {len(overlap)} images with head slides 0-4: {overlap}"
    )

def test_image_search_query_variants() -> None:
    service = ImageSearchService()
    variants = service._generate_query_variants("car")
    assert "car" in variants
    assert "cars" in variants
    assert len(variants) <= service.EXPANSION_BUDGET_FACTOR
    
    variants_plural = service._generate_query_variants("cats")
    assert "cats" in variants_plural
    assert "cat" in variants_plural

def test_image_search_adaptive_retrieval_stop_conditions() -> None:
    service = ImageSearchService()
    service._probe_google = _make_provider_stub(_make_candidate_pool(10, "car", "google"))
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []
    
    results, summary = service.probe("car", 15, providers=["google"])
    assert summary.requested == 15
    assert summary.numeric_shortfall <= 5

def test_image_search_shortfall_reporting() -> None:
    service = ImageSearchService()
    service._probe_google = _make_provider_stub(_make_candidate_pool(2, "rareterm", "google"))
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("rareterm", 50, providers=["google"])
    assert summary.numeric_shortfall > 0
    assert not summary.is_complete
    assert len(summary.shortfall_reasons) > 0
    assert summary.shortfall_reasons[0].value == "low_availability"


def test_source_failure_retry_succeeds_on_second_attempt() -> None:
    service = ImageSearchService(retry_backoff_seconds=0)

    call_count = {"count": 0}

    def _flaky_probe(term: str, limit: int) -> list[ImageCandidate]:
        call_count["count"] += 1
        if call_count["count"] == 1:
            return []
        return [ImageCandidate("https://images.example.com/recovered.jpg", "google", term, 0, 0)]

    service._probe_google = _flaky_probe
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("test", 5, providers=["google"])

    assert call_count["count"] >= 2
    assert len(results) >= 1
    assert "google" not in summary.source_errors


def test_source_failure_retry_fails_and_reports_error() -> None:
    service = ImageSearchService(retry_backoff_seconds=0)

    service._probe_google = lambda term, limit: []
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    with pytest.raises(AppError):
        service.probe("test", 5, providers=["google"])


def test_source_failure_reports_error_in_summary_for_mixed_results() -> None:
    service = ImageSearchService(retry_backoff_seconds=0)

    service._probe_google = _make_provider_stub(_make_candidate_pool(5, "test", "google"))
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("test", 10, providers=["google", "bing"])

    assert len(results) >= 1
    assert "google" not in summary.source_errors
    assert "bing" in summary.source_errors
    assert "No results from bing" in summary.source_errors["bing"]


# ---------------------------------------------------------------------------
# Phase 4 / US2: Near-duplicate detection and relevance/diversity tests
# ---------------------------------------------------------------------------

_NR_SAMPLE_BYTES = 2048  # Small sample for stub signatures


def test_exact_duplicate_removal_by_canonical_url() -> None:
    service = ImageSearchService()
    candidates = [
        ImageCandidate("https://example.com/a.jpg?w=800", "google", "cat", 800, 600),
        ImageCandidate("https://example.com/a.jpg?w=400", "google", "cat", 400, 300),
        ImageCandidate("https://example.com/b.jpg", "google", "cat", 800, 600),
    ]
    result = service._randomized_unique_candidates("cat", 10, candidates)
    urls = {c.source_url for c in result}
    # After canonicalization, the two a.jpg URLs should merge into one
    assert len(urls) == 2


def test_near_duplicate_detection_by_url_stem() -> None:
    service = ImageSearchService()
    candidates = [
        ImageCandidate("https://example.com/photos/cat_800x600.jpg", "google", "cat", 800, 600),
        ImageCandidate("https://example.com/photos/cat_1200x900.jpg", "google", "cat", 1200, 900),
        ImageCandidate("https://example.com/photos/dog.jpg", "google", "dog", 800, 600),
        ImageCandidate("https://other.example.com/cat.jpg", "bing", "cat", 800, 600),
    ]
    near_dupes = service._detect_near_duplicate_urls(candidates)
    # cat_800x600 and cat_1200x900 share same domain + path stem → near-duplicate
    assert len(near_dupes) >= 1


def test_near_duplicate_phash_grouping() -> None:
    service = ImageSearchService()
    candidates = [
        ImageCandidate("https://a.example.com/1.jpg", "google", "cat", 800, 600),
        ImageCandidate("https://b.example.com/2.jpg", "google", "cat", 800, 600),
        ImageCandidate("https://c.example.com/3.jpg", "bing", "cat", 800, 600),
    ]

    # Same visual signature for first two → near-duplicates
    sigs = {
        "https://a.example.com/1.jpg": "abc123",
        "https://b.example.com/2.jpg": "abc123",  # same visual content
        "https://c.example.com/3.jpg": "def456",
    }
    service._probe_image_signature = lambda url: sigs.get(url, "")

    kept, removed = service._filter_near_duplicates_by_signature(candidates)
    assert len(kept) >= 2
    assert removed >= 1


def test_near_duplicate_ratio_stays_under_10_percent() -> None:
    """With 50 candidates, at most 5 should be near-duplicates."""
    service = ImageSearchService()
    candidates = []
    for i in range(50):
        candidates.append(
            ImageCandidate(f"https://example.com/img_{i:04d}.jpg", "google", f"cat {i}", 800, 600)
        )
    # No near-duplicates in this pool
    near_dupes = service._detect_near_duplicate_urls(candidates)
    near_dupe_ratio = len(near_dupes) / max(1, len(candidates))
    assert near_dupe_ratio <= 0.10


def test_relevance_scoring_prefers_term_in_title() -> None:
    service = ImageSearchService()
    relevant = ImageCandidate("https://example.com/1.jpg", "google", "cute cat photo", 1024, 768)
    irrelevant = ImageCandidate("https://example.com/2.jpg", "google", "random image", 1024, 768)
    no_res = ImageCandidate("https://example.com/3.jpg", "google", "cat", 0, 0)

    score_rel = service._score_candidate_relevance(relevant, "cat")
    score_irr = service._score_candidate_relevance(irrelevant, "cat")
    score_nores = service._score_candidate_relevance(no_res, "cat")

    assert score_rel > score_irr
    assert score_nores > 0  # title is "cat" which matches exactly
    assert score_rel >= score_nores  # "cute cat photo" also matches, with bonus for resolution


def test_diversity_selection_distributes_across_sources() -> None:
    service = ImageSearchService()
    pool = []
    for i in range(10):
        pool.append(ImageCandidate(f"https://g.example.com/{i}.jpg", "google", "cat", 800, 600))
    for i in range(10):
        pool.append(ImageCandidate(f"https://b.example.com/{i}.jpg", "bing", "cat", 800, 600))

    selected = service._select_diverse(pool, "cat", 6)
    sources = {c.source_name for c in selected}
    # Should include candidates from at least 2 different sources
    assert len(sources) >= 2


def test_final_selection_respects_requested_count() -> None:
    service = ImageSearchService()
    pool = _make_candidate_pool(30, "cat", "google")
    pool += _make_candidate_pool(10, "cat", "bing")

    deduped, exact_removed, near_removed = service._apply_selection_policy(pool, "cat", 15)
    selected = service._select_diverse(deduped, "cat", 15)

    assert len(selected) <= 15
    assert len(selected) >= 1
    assert exact_removed >= 0
    assert near_removed >= 0


# ---------------------------------------------------------------------------
# Phase 5 / US3: Shortfall diagnostics and retry suggestions
# ---------------------------------------------------------------------------


def test_retry_suggestions_generated_below_80_percent_completion() -> None:
    service = ImageSearchService()
    service._probe_google = _make_provider_stub(_make_candidate_pool(3, "rarexyz", "google"))
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("rarexyz", 50, providers=["google"])

    # 3 found / 50 requested = 6% completion → well below 80%
    completion_pct = summary.selected / summary.requested
    assert completion_pct < 0.80
    assert summary.numeric_shortfall > 0
    assert len(summary.retry_suggestions) >= 2
    assert any("search term" in s.lower() or "fewer slides" in s.lower() or "reduce" in s.lower()
               for s in summary.retry_suggestions)


def test_shortfall_above_80_percent_may_skip_retry_suggestions() -> None:
    service = ImageSearchService()
    service._probe_google = _make_provider_stub(_make_candidate_pool(45, "commonterm", "google"))
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("commonterm", 50, providers=["google"])

    completion_pct = summary.selected / summary.requested
    assert completion_pct >= 0.80 or summary.is_complete


def test_shortfall_reason_low_availability_always_present_on_shortfall() -> None:
    service = ImageSearchService()
    service._probe_google = _make_provider_stub(_make_candidate_pool(2, "scarce", "google"))
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("scarce", 20, providers=["google"])

    assert summary.numeric_shortfall > 0
    reason_values = [r.value for r in summary.shortfall_reasons]
    assert "low_availability" in reason_values


def test_source_errors_trigger_actionable_suggestion() -> None:
    service = ImageSearchService(retry_backoff_seconds=0)
    service._probe_google = _make_provider_stub(_make_candidate_pool(5, "test", "google"))
    # bing always fails
    service._probe_bing = lambda term, limit: []
    service._probe_duckduckgo = lambda term, limit: []
    service._probe_openverse = lambda term, limit: []

    results, summary = service.probe("test", 30, providers=["google", "bing"])

    assert "bing" in summary.source_errors
    assert len(summary.retry_suggestions) >= 1