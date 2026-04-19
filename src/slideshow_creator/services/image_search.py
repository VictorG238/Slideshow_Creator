"""Image search service scaffold."""

from __future__ import annotations

from dataclasses import dataclass
import html
import hashlib
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import random
import re
from typing import Callable, Dict, List, Optional

import requests
from PIL import Image

from slideshow_creator.models.domain import AppError, ErrorCategory, ProgressEvent


@dataclass(slots=True)
class ImageCandidate:
    """Normalized image candidate returned by providers."""

    source_url: str
    source_name: str
    title: str
    width: int
    height: int


class ImageSearchService:
    """Collect and normalize image candidates for a search term."""

    PROVIDER_OPENVERSE = "openverse"
    PROVIDER_GOOGLE = "google"
    PROVIDER_BING = "bing"
    PROVIDER_DUCKDUCKGO = "duckduckgo"

    OPENVERSE_IMAGES_ENDPOINT = "https://api.openverse.org/v1/images/"
    GOOGLE_IMAGES_ENDPOINT = "https://www.google.com/search"
    BING_IMAGES_ENDPOINT = "https://www.bing.com/images/search"
    DDG_SEARCH_ENDPOINT = "https://duckduckgo.com/"
    DDG_IMAGES_JSON_ENDPOINT = "https://duckduckgo.com/i.js"

    OPENVERSE_RESULT_KEY = "results"

    _DROP_QUERY_KEYS = {
        "w",
        "width",
        "h",
        "height",
        "q",
        "quality",
        "fit",
        "crop",
        "auto",
        "dpr",
        "size",
        "fm",
        "format",
        "ixlib",
        "ixid",
        "cb",
        "pid",
    }

    _SIGNATURE_SAMPLE_BYTES = 262_144
    _SIGNATURE_GRID_SIZE = 16
    
    # Updated regexes to match current responses
    GOOGLE_IMAGE_RE = re.compile(r'\[\"(https?://[^\"]+?)\",\d+,\d+\]') 
    BING_IMAGE_RE = re.compile(r'murl(?:&quot;|\"):&quot;|(https?://[^\"]+?)(?:&quot;|\")')
    DDG_VQD_RE = re.compile(r'vqd=([\'\"]?)([A-Za-z0-9_-]+)')

    @staticmethod
    def _browser_headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_candidates(
        source_name: str,
        search_term: str,
        items: list[dict[str, object]],
    ) -> list[ImageCandidate]:
        candidates: list[ImageCandidate] = []
        for idx, item in enumerate(items, start=1):
            source_url = str(item.get("image", "") or "").strip()
            if not source_url:
                continue

            title = str(item.get("title", "") or "").strip() or f"{search_term} {idx}"
            width = ImageSearchService._safe_int(item.get("width", 0), 0)
            height = ImageSearchService._safe_int(item.get("height", 0), 0)
            candidates.append(
                ImageCandidate(
                    source_url=source_url,
                    source_name=source_name,
                    title=title,
                    width=width,
                    height=height,
                )
            )
        return candidates

    @staticmethod
    def _filter_image_urls(raw_urls: list[str]) -> list[str]:
        bad_tokens = (
            "gstatic.com",
            "google.com/images",
            "googleusercontent.com",
            "encrypted-tbn",
        )
        urls: list[str] = []
        seen: set[str] = set()
        for raw in raw_urls:
            cleaned = html.unescape(str(raw or "").strip())
            if not cleaned or not cleaned.startswith(("http://", "https://")):
                continue
            lowered = cleaned.lower()
            if any(token in lowered for token in bad_tokens):
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            urls.append(cleaned)
        return urls

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        session: Optional[requests.Session] = None,
        validate_candidates: bool = False,
        validation_pool_factor: int = 1,
        max_validation_checks: int = 80,
        validation_timeout_seconds: float = 1.8,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "slideshow-creator/0.1 (+desktop)")
        self.validate_candidates = validate_candidates
        self.validation_pool_factor = max(1, validation_pool_factor)
        self.max_validation_checks = max(10, max_validation_checks)
        self.validation_timeout_seconds = max(0.5, min(validation_timeout_seconds, self.timeout_seconds))

    def probe(
        self,
        search_term: str,
        limit: int,
        providers: Optional[list[str]] = None,
        progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    ) -> List[ImageCandidate]:
        """Probe providers and return normalized, deduplicated image candidates."""
        normalized_term = search_term.strip()
        if not normalized_term:
            raise AppError(ErrorCategory.USER_INPUT, "Search term must not be empty.", "Enter a word or phrase to search for.")
        if limit <= 0:
            return []

        active_providers = self._resolve_providers(providers)
        if not active_providers:
            raise AppError(
                ErrorCategory.USER_INPUT,
                "Select at least one search engine.",
                "Enable Google, Bing, or DuckDuckGo and try again.",
            )

        def _report(msg: str, percent: float) -> None:
            if progress_cb:
                progress_cb(ProgressEvent("image_search", msg, percent))

        candidates: List[ImageCandidate] = []
        provider_fetchers = {
            self.PROVIDER_OPENVERSE: ("Openverse", self._probe_openverse),
            self.PROVIDER_GOOGLE: ("Google Images", self._probe_google),
            self.PROVIDER_BING: ("Bing Images", self._probe_bing),
            self.PROVIDER_DUCKDUCKGO: ("DuckDuckGo", self._probe_duckduckgo),
        }

        total_providers = len(active_providers)
        for index, provider_name in enumerate(active_providers, start=1):
            provider_label, provider_fetch = provider_fetchers[provider_name]
            progress_value = 0.1 + ((index - 1) / max(total_providers, 1)) * 0.7
            _report(f"Probing {provider_label} for {normalized_term}...", progress_value)
            candidates.extend(provider_fetch(normalized_term, limit))

        # Always add Openverse as a bonus source for diversity, if not already included.
        if self.PROVIDER_OPENVERSE not in active_providers:
            _report("Probing Openverse (bonus)...", 0.85)
            candidates.extend(self._probe_openverse(normalized_term, limit))

        if not candidates:
            _report("Selected engines returned no results. Trying fallback engines...", 0.75)
            for provider_name in (
                self.PROVIDER_GOOGLE,
                self.PROVIDER_BING,
                self.PROVIDER_DUCKDUCKGO,
                self.PROVIDER_OPENVERSE,
            ):
                if provider_name in active_providers:
                    continue
                provider_label, provider_fetch = provider_fetchers[provider_name]
                _report(f"Fallback probe: {provider_label}...", 0.78)
                candidates.extend(provider_fetch(normalized_term, limit))
                if candidates:
                    break

        if not candidates:
            raise AppError(
                ErrorCategory.NETWORK,
                f"No images found for '{normalized_term}'.",
                "Check your internet connection, or try a more common search term.",
            )

        _report("Deduplicating and shuffling results...", 0.82)
        final_list = self._randomized_unique_candidates(normalized_term, limit, candidates)

        if self.validate_candidates and final_list:
            _report("Validating downloadable image sources...", 0.9)
            final_list = self._select_downloadable_unique_candidates(final_list, limit)

        if not final_list:
            raise AppError(
                ErrorCategory.NETWORK,
                f"No downloadable images found for '{normalized_term}'.",
                "Try another search term or enable more search engines.",
            )

        _report(f"Found {len(final_list)} unique matching images.", 1.0)
        return final_list

    def _select_downloadable_unique_candidates(
        self,
        candidates: List[ImageCandidate],
        limit: int,
    ) -> List[ImageCandidate]:
        if not candidates:
            return []

        requested_pool = max(limit, limit * self.validation_pool_factor)
        pool_buffer = max(5, limit // 4)
        desired_pool = min(len(candidates), min(requested_pool, limit + pool_buffer))
        max_checks = min(
            len(candidates),
            max(limit, min(self.max_validation_checks, desired_pool * 2)),
        )

        selected: List[ImageCandidate] = []
        selected_urls: set[str] = set()
        seen_signatures: set[str] = set()

        checked = 0
        for candidate in candidates:
            if checked >= max_checks:
                break
            checked += 1

            signature = self._probe_image_signature(candidate.source_url)
            if not signature or signature in seen_signatures:
                continue

            seen_signatures.add(signature)
            selected.append(candidate)
            selected_urls.add(candidate.source_url)

            if len(selected) >= desired_pool:
                break

        # If validation returned too few images, backfill by URL to avoid empty generations.
        if len(selected) < limit:
            for candidate in candidates:
                if candidate.source_url in selected_urls:
                    continue
                selected.append(candidate)
                selected_urls.add(candidate.source_url)
                if len(selected) >= limit:
                    break

        return selected

    @staticmethod
    def _visual_signature(payload: bytes) -> str:
        """Derive a resilient low-resolution grayscale signature for visual deduplication."""
        if not payload:
            return ""

        try:
            with Image.open(BytesIO(payload)) as image:
                thumb = image.convert("L").resize(
                    (ImageSearchService._SIGNATURE_GRID_SIZE, ImageSearchService._SIGNATURE_GRID_SIZE),
                    Image.Resampling.BILINEAR,
                )
                # Quantize to reduce JPEG quality/compression noise.
                quantized = bytes((pixel // 16) * 16 for pixel in thumb.get_flattened_data())
                return hashlib.sha256(quantized).hexdigest()
        except Exception:
            return ""

    def _probe_image_signature(self, source_url: str) -> str:
        response: Optional[requests.Response] = None
        try:
            request_headers = {
                **self._browser_headers(),
                "Range": f"bytes=0-{self._SIGNATURE_SAMPLE_BYTES - 1}",
            }
            response = self.session.get(
                source_url,
                headers=request_headers,
                timeout=self.validation_timeout_seconds,
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()

            content_type = str(response.headers.get("Content-Type", "")).lower()
            if content_type and not content_type.startswith("image/"):
                return ""

            payload = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) >= self._SIGNATURE_SAMPLE_BYTES:
                    break

            if not payload:
                return ""

            visual_signature = self._visual_signature(bytes(payload))
            if visual_signature:
                return visual_signature

            content_length = str(response.headers.get("Content-Length", "")).encode("utf-8")
            return hashlib.sha256(content_length + b":" + bytes(payload)).hexdigest()
        except requests.RequestException:
            return ""
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _normalize_provider_name(raw_name: str) -> str:
        normalized = raw_name.strip().lower()
        aliases = {
            "ddg": "duckduckgo",
            "duckduckgo-images": "duckduckgo",
            "google-images": "google",
            "bing-images": "bing",
        }
        return aliases.get(normalized, normalized)

    def _resolve_providers(self, providers: Optional[list[str]]) -> list[str]:
        default = [
            self.PROVIDER_OPENVERSE,
            self.PROVIDER_GOOGLE,
            self.PROVIDER_BING,
            self.PROVIDER_DUCKDUCKGO,
        ]
        if providers is None:
            return default

        supported = set(default)
        result: list[str] = []
        for item in providers:
            normalized = self._normalize_provider_name(str(item))
            if normalized in supported and normalized not in result:
                result.append(normalized)
        return result

    def _randomized_unique_candidates(
        self,
        seed_term: str,
        limit: int,
        candidates: List[ImageCandidate],
    ) -> List[ImageCandidate]:
        """Normalize, deduplicate, and shuffle candidates deterministically."""
        normalized_candidates: List[ImageCandidate] = []
        for candidate in candidates:
            canonical_url = self._canonical_url(candidate.source_url)
            if not canonical_url:
                continue

            width = max(0, int(candidate.width))
            height = max(0, int(candidate.height))
            normalized_candidates.append(
                ImageCandidate(
                    source_url=canonical_url,
                    source_name=candidate.source_name.strip() or "unknown",
                    title=candidate.title.strip() or seed_term,
                    width=width,
                    height=height,
                )
            )

        unique: Dict[str, ImageCandidate] = {}
        for candidate in normalized_candidates:
            unique.setdefault(candidate.source_url, candidate)

        # Randomize deterministically by term, so repeated runs stay stable for the same input.
        seed = int(hashlib.sha256(seed_term.encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed)
        result = list(unique.values())
        rng.shuffle(result)
        return result

    @staticmethod
    def _canonical_url(raw_url: str) -> str:
        """Normalize URL for deduplication while preserving identity query params."""
        cleaned = raw_url.strip()
        if not cleaned:
            return ""

        split = urlsplit(cleaned)
        if not split.scheme or not split.netloc:
            return ""

        filtered_pairs: list[tuple[str, str]] = []
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            lower_key = key.strip().lower()
            if lower_key.startswith("utm_") or lower_key in ImageSearchService._DROP_QUERY_KEYS:
                continue
            filtered_pairs.append((lower_key, value.strip()))

        canonical_query = urlencode(sorted(filtered_pairs), doseq=True)
        return urlunsplit((split.scheme, split.netloc, split.path, canonical_query, ""))

    def _probe_openverse(self, search_term: str, limit: int) -> List[ImageCandidate]:
        page_size = max(limit * 4, 20)
        all_candidates: List[ImageCandidate] = []

        for page_num in (1, 2):
            try:
                response = self.session.get(
                    self.OPENVERSE_IMAGES_ENDPOINT,
                    params={
                        "q": search_term,
                        "page_size": page_size,
                        "page": page_num,
                    },
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                break

            items = payload.get(self.OPENVERSE_RESULT_KEY, [])
            if not items:
                break

            for idx, item in enumerate(items[:page_size], start=1):
                source_url = str(item.get("url", "")).strip()
                if not source_url:
                    continue

                title = str(item.get("title", "")).strip() or search_term
                width = int(item.get("width", 0) or 0)
                height = int(item.get("height", 0) or 0)
                creator = str(item.get("creator", "openverse")).strip() or "openverse"

                all_candidates.append(
                    ImageCandidate(
                        source_url=source_url,
                        source_name=f"openverse:{creator}",
                        title=f"{title} {idx}" if title == search_term else title,
                        width=width,
                        height=height,
                    )
                )

        return all_candidates

    def _probe_google(self, search_term: str, limit: int) -> List[ImageCandidate]:
        # Use DDGS with "Large" size filter and international region to get
        # different results than the DDG probe (which uses default params).
        try:
            from ddgs import DDGS
            items = DDGS(timeout=max(6, int(self.timeout_seconds))).images(
                f"{search_term} HD",
                max_results=max(limit * 4, 20),
                region="wt-wt",
                size="Large",
            )
            candidates = self._to_candidates("google-images", search_term, items)
            if candidates:
                return candidates
        except Exception:
            pass

        # Fallback to Openverse
        fallback = self._probe_openverse(search_term, limit)
        return [
            ImageCandidate(
                source_url=item.source_url,
                source_name="google-fallback:openverse",
                title=item.title,
                width=item.width,
                height=item.height,
            )
            for item in fallback
        ]

    def _probe_bing(self, search_term: str, limit: int) -> List[ImageCandidate]:
        try:
            response = self.session.get(
                self.BING_IMAGES_ENDPOINT,
                params={
                    "q": search_term,
                    "form": "HDRSC3",
                    "first": 1,
                    "tsc": "ImageBasicHover",
                },
                headers=self._browser_headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []

        urls = re.findall(r'murl(?:&quot;|\"):(?:&quot;|\")?(https?://[^\"]+?)(?:&quot;|\")', response.text)
        if not urls:
            urls = re.findall(r'murl(?:&quot;|\")(?:&quot;|\")?(https?://[^\&]+?)(?:&quot;|\")', response.text)
        urls = [html.unescape(u) for u in urls]

        candidates: List[ImageCandidate] = []
        for idx, url in enumerate(urls[: max(limit * 4, 20)], start=1):
            candidates.append(
                ImageCandidate(
                    source_url=url,
                    source_name="bing-images",
                    title=f"{search_term} {idx}",
                    width=0,
                    height=0,
                )
            )
        return candidates

    def _probe_duckduckgo(self, search_term: str, limit: int) -> List[ImageCandidate]:
        max_results = max(limit * 4, 20)
        try:
            from ddgs import DDGS

            for backend in ("duckduckgo", "auto"):
                try:
                    items = DDGS(timeout=max(6, int(self.timeout_seconds))).images(
                        search_term,
                        max_results=max_results,
                        backend=backend,
                        region="us-en",
                    )
                except Exception:
                    continue

                candidates = self._to_candidates("duckduckgo-images", search_term, items)
                if candidates:
                    return candidates
        except Exception:
            pass

        try:
            landing = self.session.get(
                self.DDG_SEARCH_ENDPOINT,
                params={"q": search_term, "iax": "images", "ia": "images"},
                headers=self._browser_headers(),
                timeout=self.timeout_seconds,
            )
            landing.raise_for_status()
        except requests.RequestException:
            return []

        vqd = self._extract_ddg_vqd(landing.text)
        if not vqd:
            return []

        try:
            response = self.session.get(
                self.DDG_IMAGES_JSON_ENDPOINT,
                params={
                    "l": "us-en",
                    "o": "json",
                    "q": search_term,
                    "vqd": vqd,
                    "f": ",,,",
                    "p": 1,
                },
                headers={
                    "Referer": self.DDG_SEARCH_ENDPOINT,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    **self._browser_headers(),
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return []

        items = payload.get("results", [])
        return self._to_candidates("duckduckgo-images", search_term, items[:max_results])

    def _extract_ddg_vqd(self, html: str) -> str:
        matches = self.DDG_VQD_RE.findall(html)
        if not matches:
            return ""

        for group in matches:
            if len(group) >= 2 and group[1]:
                return group[1]
            elif group[0]:
                return group[0]
        return ""

