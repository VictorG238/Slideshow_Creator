"""Image search service scaffold."""

from __future__ import annotations

from dataclasses import dataclass
import html
import hashlib
from io import BytesIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import random
import re
import time
from typing import Callable, Dict, List, Optional

import requests
from PIL import Image

from slideshow_creator.models.domain import AppError, ErrorCategory, ProgressEvent, SearchRunSummary, ShortfallReason


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

    MAX_REQUESTED_COUNT = 2000
    COMPLETION_THRESHOLD_RATIO = 0.95
    EXPANSION_BUDGET_FACTOR = 4
    MAX_VALIDATION_POOL_FACTOR = 4
    HARD_VALIDATION_CAP = 1500

    # Pagination / rate-limit settings for scrape-based providers
    BING_PAGE_SIZE = 35
    BING_MAX_PAGES = 15
    BING_INTER_PAGE_DELAY_SECONDS = 0.9
    OPENVERSE_PAGE_SIZE = 100
    OPENVERSE_MAX_PAGES = 10
    OPENVERSE_INTER_PAGE_DELAY_SECONDS = 0.4


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
        max_validation_checks: int = 500,
        validation_timeout_seconds: float = 1.8,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "slideshow-creator/0.1 (+desktop)")
        self.validate_candidates = validate_candidates
        self.validation_pool_factor = max(1, validation_pool_factor)
        self.max_validation_checks = max(10, max_validation_checks)
        self.validation_timeout_seconds = max(0.5, min(validation_timeout_seconds, self.timeout_seconds))
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def probe(
        self,
        search_term: str,
        limit: int,
        providers: Optional[list[str]] = None,
        progress_cb: Optional[Callable[[ProgressEvent], None]] = None,
    ) -> tuple[List[ImageCandidate], SearchRunSummary]:
        """Probe providers and return selected candidates plus summary metrics."""
        normalized_term = search_term.strip()
        if not normalized_term:
            raise AppError(ErrorCategory.USER_INPUT, "Search term must not be empty.", "Enter a word or phrase to search for.")
        if limit < 1 or limit > self.MAX_REQUESTED_COUNT:
            raise AppError(
                ErrorCategory.USER_INPUT,
                f"Requested count must be between 1 and {self.MAX_REQUESTED_COUNT}.",
                f"Enter a number between 1 and {self.MAX_REQUESTED_COUNT}.",
            )

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
        source_errors: Dict[str, str] = {}
        provider_fetchers = {
            self.PROVIDER_OPENVERSE: ("Openverse", self._probe_openverse),
            self.PROVIDER_GOOGLE: ("Google Images", self._probe_google),
            self.PROVIDER_BING: ("Bing Images", self._probe_bing),
            self.PROVIDER_DUCKDUCKGO: ("DuckDuckGo", self._probe_duckduckgo),
        }

        query_variants = self._generate_query_variants(normalized_term)
        
        for variant_idx, variant in enumerate(query_variants):
            if len(candidates) >= limit * self.COMPLETION_THRESHOLD_RATIO:
                break
                
            for index, provider_name in enumerate(active_providers, start=1):
                provider_label, provider_fetch = provider_fetchers[provider_name]
                progress_value = 0.1 + ((variant_idx * len(active_providers) + index) / (len(query_variants) * len(active_providers))) * 0.7
                _report(f"Probing {provider_label} for '{variant}'...", progress_value)
                
                remaining = max(0, limit - len(candidates))
                fetch_limit = max(50, int(remaining * 1.5 + 20))
                fetched, error = self._fetch_with_retry(
                    provider_name, provider_fetch, variant, fetch_limit
                )
                if error:
                    source_errors[provider_name] = error
                candidates.extend(fetched)

                if len(candidates) >= limit * self.COMPLETION_THRESHOLD_RATIO:
                    break

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
                fetched, error = self._fetch_with_retry(
                    provider_name, provider_fetch, normalized_term, limit
                )
                if error:
                    source_errors[provider_name] = error
                candidates.extend(fetched)
                if candidates:
                    break

        if not candidates:
            raise AppError(
                ErrorCategory.NETWORK,
                f"No images found for '{normalized_term}'.",
                "Check your internet connection, or try a more common search term.",
            )

        _report("Deduplicating results...", 0.82)
        deduped, exact_removed, near_removed = self._apply_selection_policy(
            candidates, normalized_term, limit
        )

        invalid_removed = 0
        if self.validate_candidates and deduped:
            _report("Validating downloadable image sources...", 0.88)
            before_count = len(deduped)
            deduped = self._select_downloadable_unique_candidates(deduped, limit)
            invalid_removed = max(0, before_count - len(deduped))

        _report("Selecting best results...", 0.92)
        final_list = self._select_diverse(deduped, normalized_term, limit)

        if not final_list:
            raise AppError(
                ErrorCategory.NETWORK,
                f"No downloadable images found for '{normalized_term}'.",
                "Try another search term or enable more search engines.",
            )

        provider_logs = {}
        for c in candidates:
            provider_logs[c.source_name] = provider_logs.get(c.source_name, 0) + 1

        shortfall_reasons = []
        if len(final_list) < limit:
            shortfall_reasons.append(ShortfallReason.LOW_AVAILABILITY)
        if near_removed > 0:
            shortfall_reasons.append(ShortfallReason.FILTERED_DUPLICATES)
        if invalid_removed > 0:
            shortfall_reasons.append(ShortfallReason.FILTERED_VALIDATION)

        retry_suggestions = self._generate_retry_suggestions(
            search_term=normalized_term,
            limit=limit,
            discovered=len(candidates),
            selected=len(final_list),
            provider_logs=provider_logs,
            source_errors=source_errors,
            shortfall_reasons=shortfall_reasons,
        )

        summary = SearchRunSummary(
            requested=limit,
            discovered=len(candidates),
            invalid_removed=invalid_removed,
            duplicate_removed=exact_removed,
            near_duplicate_removed=near_removed,
            selected=len(final_list),
            provider_logs=provider_logs,
            shortfall_reasons=shortfall_reasons,
            retry_suggestions=retry_suggestions,
            source_errors=source_errors,
        )

        _report(f"Found {len(final_list)} unique matching images.", 1.0)
        return final_list, summary

    _TERM_SYNONYMS: dict[str, str] = {
        "cars": "auto",
        "car": "auto",
        "autos": "car",
        "auto": "car",
        "dogs": "puppy",
        "dog": "puppy",
        "cats": "kitten",
        "cat": "kitten",
        "music": "song",
        "house": "home",
        "food": "meal",
        "city": "town",
        "ocean": "sea",
        "mountain": "hill",
        "flower": "bloom",
        "bird": "avian",
    }

    def _generate_query_variants(self, search_term: str) -> list[str]:
        normalized = search_term.strip().lower()
        variants = [normalized]
        if normalized.endswith("s"):
            variants.append(normalized[:-1])
        else:
            variants.append(normalized + "s")

        synonym = self._TERM_SYNONYMS.get(normalized)
        if synonym:
            variants.append(synonym)

        variants.append(f"{normalized} HD")
        variants.append(f"{normalized} photography")

        unique_variants = []
        seen = set()
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)

        return unique_variants[:self.EXPANSION_BUDGET_FACTOR]

    def _select_downloadable_unique_candidates(
        self,
        candidates: List[ImageCandidate],
        limit: int,
    ) -> List[ImageCandidate]:
        if not candidates:
            return []

        # Scale the check budget with limit so large requests aren't under-validated.
        # Allow checking up to max_validation_checks or all candidates, whichever is less.
        max_checks = min(len(candidates), max(limit * 2, self.max_validation_checks))
        desired_pool = min(len(candidates), max(limit, limit + max(5, limit // 4)))

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

        # Backfill with remaining unvalidated candidates if still short.
        # Also check against seen_signatures to avoid adding known visual dupes.
        if len(selected) < limit:
            for candidate in candidates:
                if candidate.source_url in selected_urls:
                    continue
                # Try to get signature for backfill candidates too, but don't block on failure.
                sig = self._probe_image_signature(candidate.source_url)
                if sig and sig in seen_signatures:
                    continue
                if sig:
                    seen_signatures.add(sig)
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

    def _fetch_with_retry(
        self,
        provider_name: str,
        provider_fetch: Callable[[str, int], List[ImageCandidate]],
        search_term: str,
        limit: int,
    ) -> tuple[List[ImageCandidate], Optional[str]]:
        """Fetch from provider with one retry on empty result with backoff."""
        result = provider_fetch(search_term, limit)
        if result:
            return result, None

        time.sleep(self.retry_backoff_seconds)
        result = provider_fetch(search_term, limit)
        if result:
            return result, None

        return [], f"No results from {provider_name} for '{search_term}' after retry"

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

    _NEAR_DUPE_SIZE_RE = re.compile(r"[_-]\d{2,5}x\d{2,5}")

    @staticmethod
    def _url_path_stem(url: str) -> str:
        """Extract domain + filename stem for near-duplicate grouping."""
        split = urlsplit(url)
        path = split.path or "/"
        filename = path.rsplit("/", 1)[-1] if "/" in path else path
        stem = ImageSearchService._NEAR_DUPE_SIZE_RE.sub("", filename)
        stem = re.sub(r"\.(jpg|jpeg|png|gif|webp|bmp|tiff?)(\?.*)?$", "", stem, flags=re.IGNORECASE)
        return f"{split.netloc}/{stem}"

    def _detect_near_duplicate_urls(
        self, candidates: List[ImageCandidate]
    ) -> set[str]:
        """Identify near-duplicate URLs by shared domain + filename stem."""
        groups: Dict[str, list[str]] = {}
        for c in candidates:
            stem = self._url_path_stem(c.source_url)
            groups.setdefault(stem, []).append(c.source_url)

        near_dupes: set[str] = set()
        for urls in groups.values():
            if len(urls) > 1:
                near_dupes.update(urls[1:])
        return near_dupes

    def _filter_near_duplicates_by_signature(
        self, candidates: List[ImageCandidate]
    ) -> tuple[List[ImageCandidate], int]:
        """Remove near-duplicates using pHash-like visual signatures."""
        kept: List[ImageCandidate] = []
        seen_signatures: set[str] = set()
        removed = 0
        for c in candidates:
            sig = self._probe_image_signature(c.source_url)
            if sig and sig in seen_signatures:
                removed += 1
                continue
            if sig:
                seen_signatures.add(sig)
            kept.append(c)
        return kept, removed

    @staticmethod
    def _score_candidate_relevance(candidate: ImageCandidate, search_term: str) -> float:
        """Score candidate relevance to search term on 0.0–1.0 scale."""
        score = 0.0
        term_lower = search_term.lower()
        title_lower = candidate.title.lower()

        term_words = set(term_lower.split())
        title_words = set(title_lower.split())
        word_overlap = term_words & title_words
        if word_overlap:
            score += 0.4 * (len(word_overlap) / len(term_words))

        if term_lower in title_lower:
            score += 0.25

        if candidate.width > 0 and candidate.height > 0:
            score += 0.1
            megapixels = (candidate.width * candidate.height) / 1_000_000
            if megapixels >= 0.5:
                score += min(0.15, megapixels * 0.05)

        return min(1.0, score)

    def _select_diverse(
        self,
        candidates: List[ImageCandidate],
        search_term: str,
        limit: int,
    ) -> List[ImageCandidate]:
        """Select candidates balancing relevance scores with source diversity."""
        if not candidates:
            return []

        scored = [(self._score_candidate_relevance(c, search_term), c) for c in candidates]
        scored.sort(key=lambda pair: pair[0], reverse=True)

        selected: List[ImageCandidate] = []
        source_counts: Dict[str, int] = {}
        unique_sources = len({c.source_name for c in candidates})
        max_per_source = max(2, int(limit * 0.6)) if unique_sources > 1 else limit

        for _score, candidate in scored:
            if len(selected) >= limit:
                break
            src = candidate.source_name
            if source_counts.get(src, 0) >= max_per_source:
                continue
            selected.append(candidate)
            source_counts[src] = source_counts.get(src, 0) + 1

        return selected

    def _apply_selection_policy(
        self,
        candidates: List[ImageCandidate],
        search_term: str,
        limit: int,
    ) -> tuple[List[ImageCandidate], int, int]:
        """Apply dedup and near-duplicate filtering. Returns (deduped, exact_removed, near_removed)."""
        unique: Dict[str, ImageCandidate] = {}
        for c in candidates:
            canonical = self._canonical_url(c.source_url)
            if not canonical:
                continue
            c.source_url = canonical
            unique.setdefault(canonical, c)
        deduped = list(unique.values())
        exact_removed = len(candidates) - len(deduped)

        near_dupe_urls = self._detect_near_duplicate_urls(deduped)
        after_near: List[ImageCandidate] = []
        near_removed = 0
        for c in deduped:
            if c.source_url in near_dupe_urls:
                near_removed += 1
            else:
                after_near.append(c)

        return after_near, exact_removed, near_removed

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

    def _generate_retry_suggestions(
        self,
        search_term: str,
        limit: int,
        discovered: int,
        selected: int,
        provider_logs: Dict[str, int],
        source_errors: Dict[str, str],
        shortfall_reasons: list[ShortfallReason],
    ) -> list[str]:
        """Generate plain-language retry suggestions when completion is below 80%."""
        completion_pct = selected / max(1, limit)
        if completion_pct >= 0.80:
            return []

        suggestions: list[str] = []

        if source_errors:
            failed = ", ".join(source_errors.keys())
            suggestions.append(
                f"Some search engines ({failed}) did not return results. "
                "Try enabling more engines or retrying later."
            )

        if discovered < limit:
            variants_suggestion = (
                f"Try a broader search term instead of '{search_term}' "
                f"(for example, use a more common word or phrase)."
            )
            suggestions.append(variants_suggestion)

        if selected < limit:
            suggestions.append(
                f"Reduce slide count to {selected} or fewer to match the available images."
            )

        if not suggestions:
            suggestions.append(
                "Try a different or more common search term to find more images."
            )
            suggestions.append(
                f"Enable more search engines to increase the variety of results."
            )

        return suggestions

    def _probe_openverse(self, search_term: str, limit: int) -> List[ImageCandidate]:
        """Paginate Openverse API with a delay between pages to respect rate limits."""
        target = max(limit * 2, 20)
        max_pages = min(
            self.OPENVERSE_MAX_PAGES,
            (target // self.OPENVERSE_PAGE_SIZE) + 1,
        )
        all_candidates: List[ImageCandidate] = []

        for page_num in range(1, max_pages + 1):
            try:
                response = self.session.get(
                    self.OPENVERSE_IMAGES_ENDPOINT,
                    params={
                        "q": search_term,
                        "page_size": self.OPENVERSE_PAGE_SIZE,
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

            page_start_idx = len(all_candidates) + 1
            for idx, item in enumerate(items, start=page_start_idx):
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

            if len(all_candidates) >= target:
                break

            # Provider returned a partial page — no more results available
            if len(items) < self.OPENVERSE_PAGE_SIZE:
                break

            if page_num < max_pages:
                time.sleep(self.OPENVERSE_INTER_PAGE_DELAY_SECONDS)

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
        """Paginate Bing image search using the `first` offset param with delays between pages."""
        target = max(limit * 2, 20)
        max_pages = min(
            self.BING_MAX_PAGES,
            (target // self.BING_PAGE_SIZE) + 1,
        )
        candidates: List[ImageCandidate] = []
        seen_urls: set[str] = set()

        for page in range(max_pages):
            first = page * self.BING_PAGE_SIZE + 1
            try:
                response = self.session.get(
                    self.BING_IMAGES_ENDPOINT,
                    params={
                        "q": search_term,
                        "form": "HDRSC3",
                        "first": first,
                        "count": self.BING_PAGE_SIZE,
                        "tsc": "ImageBasicHover",
                    },
                    headers=self._browser_headers(),
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
            except requests.RequestException:
                break

            urls = re.findall(r'murl(?:&quot;|\"):(?:&quot;|\")?(https?://[^\"]+?)(?:&quot;|\")', response.text)
            if not urls:
                urls = re.findall(r'murl(?:&quot;|\")(?:&quot;|\")?(https?://[^\&]+?)(?:&quot;|\")', response.text)
            urls = [html.unescape(u) for u in urls]

            new_this_page = 0
            for url in urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                new_this_page += 1
                candidates.append(
                    ImageCandidate(
                        source_url=url,
                        source_name="bing-images",
                        title=f"{search_term} {len(candidates) + 1}",
                        width=0,
                        height=0,
                    )
                )

            if len(candidates) >= target:
                break

            # Bing returned no new URLs — end of results
            if new_this_page == 0:
                break

            if page < max_pages - 1:
                time.sleep(self.BING_INTER_PAGE_DELAY_SECONDS)

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

