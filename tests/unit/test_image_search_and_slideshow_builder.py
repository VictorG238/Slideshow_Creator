from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest
from PIL import Image

from slideshow_creator.models.domain import AppError
from slideshow_creator.services.image_search import ImageCandidate, ImageSearchService
from slideshow_creator.services.slideshow_builder import SlideshowBuilder


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

    results = service.probe("cats", 5)

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

    results = service.probe("cats", 10, providers=["bing"])

    # Bing returns 1 + bonus Openverse adds 1 = 2 unique URLs
    assert len(results) == 2
    result_urls = {r.source_url for r in results}
    assert "https://images.example.com/bing.jpg" in result_urls
    assert "https://images.example.com/openverse.jpg" in result_urls


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

    results = service.probe("cats", 5, providers=["openverse"])

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

    results = service.probe("cats", 2, providers=["google"])

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
