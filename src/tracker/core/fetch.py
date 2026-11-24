"""The shared HTTP client (spec §9 rule 2). Every fetch goes through `Fetcher.get`.

It handles, in order:
1. a per-domain minimum interval between requests (from sources.yaml),
2. up to 3 retries with exponential backoff + jitter, only for errors worth retrying,
3. saving the response body as a gzipped raw snapshot,
4. one raw.fetch_log row per fetch, including failed ones.

Sleep, clock and randomness are injectable so tests run instantly and deterministically.
"""

import random
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import httpx

from tracker import __version__
from tracker.core.config import SourceConfig
from tracker.core.rawstore import RawStore
from tracker.core.runlog import FetchLogEntry
from tracker.core.timeutil import now_utc

USER_AGENT = f"dhaka-price-tracker/{__version__} (personal, non-commercial; one run per day)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_S = 60.0


class FetchError(Exception):
    """The fetch failed after all retries (or with a status that is not retried)."""


@dataclass(frozen=True)
class FetchResult:
    source: str
    url: str
    status: int
    content: bytes
    raw_path: str
    fetched_at: datetime


class Fetcher:
    def __init__(
        self,
        *,
        run_id: uuid.UUID | None,
        sources: Mapping[str, SourceConfig],
        raw_store: RawStore,
        fetch_log: Callable[[FetchLogEntry], None],
        client: httpx.Client | None = None,
        max_retries: int = 3,
        backoff_base_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.run_id = run_id
        self.sources = sources
        self.raw_store = raw_store
        self.fetch_log = fetch_log
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True
        )
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.sleep = sleep
        self.clock = clock
        self.rng = rng or random.Random()
        self._last_request: dict[str, float] = {}  # domain -> clock() of the last request

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, source: str, url: str, *, slug: str, **kwargs) -> FetchResult:
        """GET `url` on behalf of `source`. Raises FetchError when it finally fails."""
        config = self.sources.get(source, SourceConfig())
        fetched_at = now_utc()
        response: httpx.Response | None = None
        error: str | None = None

        for attempt in range(self.max_retries + 1):
            if attempt:
                self.sleep(self._backoff(attempt, response))
            self._wait_for_domain(url, config.min_interval_s)
            fetched_at = now_utc()
            try:
                response = self.client.get(url, **kwargs)
            except httpx.TransportError as exc:  # timeouts, DNS, refused connections
                response, error = None, f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code in RETRY_STATUSES:
                error = f"HTTP {response.status_code}"
                continue
            error = None if response.is_success else f"HTTP {response.status_code}"
            break  # success, or a status that retrying won't fix (404, 403, ...)

        status = response.status_code if response is not None else None
        if error is not None:
            self.fetch_log(self._entry(source, url, fetched_at, status=status, error=error))
            raise FetchError(f"{source}: {url}: {error}")

        assert response is not None
        raw_path = self.raw_store.save(source, slug, response.content, fetched_at)
        self.fetch_log(
            self._entry(
                source,
                url,
                fetched_at,
                status=status,
                raw_path=raw_path,
                size=len(response.content),
            )
        )
        return FetchResult(
            source, url, response.status_code, response.content, raw_path, fetched_at
        )

    def _wait_for_domain(self, url: str, min_interval_s: float) -> None:
        domain = httpx.URL(url).host
        last = self._last_request.get(domain)
        if last is not None:
            remaining = min_interval_s - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request[domain] = self.clock()

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        """1 s, 2 s, 4 s (+ up to 1 s jitter), or the server's Retry-After if it gives one."""
        if response is not None and (retry_after := response.headers.get("Retry-After")):
            try:
                return min(float(retry_after), MAX_RETRY_AFTER_S)
            except ValueError:
                pass  # an HTTP date instead of seconds: fall back to our own backoff
        return self.backoff_base_s * 2 ** (attempt - 1) + self.rng.uniform(0, self.backoff_base_s)

    def _entry(
        self,
        source: str,
        url: str,
        fetched_at: datetime,
        *,
        status: int | None,
        raw_path: str | None = None,
        size: int | None = None,
        error: str | None = None,
    ) -> FetchLogEntry:
        return FetchLogEntry(
            run_id=self.run_id,
            source=source,
            url=url,
            fetched_at=fetched_at,
            http_status=status,
            raw_path=raw_path,
            bytes=size,
            error=error,
        )
