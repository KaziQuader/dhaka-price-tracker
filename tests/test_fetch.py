"""Fetch client tests. No network: httpx.MockTransport answers every request."""

import gzip
import random
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tracker.core.config import SourceConfig
from tracker.core.fetch import USER_AGENT, Fetcher, FetchError
from tracker.core.rawstore import RawStore
from tracker.core.runlog import FetchLogEntry

URL = "https://prices.example/today"


class FakeClock:
    """Time only moves when the fetcher sleeps, so tests are instant and exact."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def make_fetcher(
    tmp_path: Path,
    responses: list[httpx.Response | Exception],
    *,
    min_interval_s: float = 0.0,
) -> tuple[Fetcher, list[FetchLogEntry], FakeClock, list[httpx.Request]]:
    """A fetcher whose server answers with `responses` in order."""
    queue = list(responses)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    log: list[FetchLogEntry] = []
    clock = FakeClock()
    fetcher = Fetcher(
        run_id=None,
        sources={"src": SourceConfig(enabled=True, min_interval_s=min_interval_s)},
        raw_store=RawStore(tmp_path),
        fetch_log=log.append,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT}
        ),
        sleep=clock.sleep,
        clock=clock,
        rng=random.Random(0),
    )
    return fetcher, log, clock, requests


ok: Callable[[], httpx.Response] = lambda: httpx.Response(200, content=b"<p>16985</p>")  # noqa: E731


def test_success_saves_gzipped_snapshot_and_logs_it(tmp_path: Path) -> None:
    fetcher, log, clock, requests = make_fetcher(tmp_path, [ok()])

    result = fetcher.get("src", URL, slug="today")

    assert result.content == b"<p>16985</p>"
    assert gzip.decompress(Path(result.raw_path).read_bytes()) == b"<p>16985</p>"
    assert "/raw/src/" in result.raw_path and result.raw_path.endswith("_today.gz")
    assert [(e.http_status, e.bytes, e.error, e.raw_path) for e in log] == [
        (200, 12, None, result.raw_path)
    ]
    assert requests[0].headers["User-Agent"] == USER_AGENT
    assert clock.sleeps == []


def test_retries_server_errors_with_exponential_backoff(tmp_path: Path) -> None:
    fetcher, log, clock, requests = make_fetcher(
        tmp_path, [httpx.Response(503), httpx.Response(502), ok()]
    )

    fetcher.get("src", URL, slug="today")

    assert len(requests) == 3
    # 1 s then 2 s, each plus up to 1 s of jitter
    assert 1 <= clock.sleeps[0] < 2 and 2 <= clock.sleeps[1] < 3
    assert len(log) == 1 and log[0].http_status == 200


def test_gives_up_after_three_retries_and_logs_the_failure(tmp_path: Path) -> None:
    fetcher, log, clock, requests = make_fetcher(tmp_path, [httpx.Response(500)] * 4)

    with pytest.raises(FetchError, match="HTTP 500"):
        fetcher.get("src", URL, slug="today")

    assert len(requests) == 4  # first try + 3 retries
    assert len(clock.sleeps) == 3
    assert [(e.http_status, e.error, e.raw_path) for e in log] == [(500, "HTTP 500", None)]
    assert not (tmp_path / "raw").exists()  # nothing saved for a failed fetch


def test_does_not_retry_client_errors(tmp_path: Path) -> None:
    fetcher, log, clock, requests = make_fetcher(tmp_path, [httpx.Response(404)])

    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher.get("src", URL, slug="today")

    assert len(requests) == 1 and clock.sleeps == []
    assert log[0].http_status == 404


def test_retries_transport_errors(tmp_path: Path) -> None:
    fetcher, log, _, requests = make_fetcher(tmp_path, [httpx.ConnectTimeout("timed out"), ok()])

    fetcher.get("src", URL, slug="today")

    assert len(requests) == 2 and log[0].http_status == 200


def test_transport_error_after_all_retries_is_logged_without_status(tmp_path: Path) -> None:
    fetcher, log, _, _ = make_fetcher(tmp_path, [httpx.ConnectError("refused")] * 4)

    with pytest.raises(FetchError, match="ConnectError"):
        fetcher.get("src", URL, slug="today")

    assert log[0].http_status is None and "refused" in (log[0].error or "")


def test_honours_retry_after_on_429(tmp_path: Path) -> None:
    fetcher, _, clock, _ = make_fetcher(
        tmp_path, [httpx.Response(429, headers={"Retry-After": "7"}), ok()]
    )

    fetcher.get("src", URL, slug="today")

    assert clock.sleeps == [7.0]


def test_waits_between_requests_to_the_same_domain(tmp_path: Path) -> None:
    fetcher, _, clock, _ = make_fetcher(tmp_path, [ok(), ok(), ok()], min_interval_s=5)

    fetcher.get("src", URL, slug="a")
    clock.now += 2  # 2 s of other work happen between the first two requests
    fetcher.get("src", URL, slug="b")
    fetcher.get("src", "https://other.example/x", slug="c")  # different domain: no wait

    assert clock.sleeps == [3.0]


def test_same_slug_in_the_same_second_does_not_overwrite(tmp_path: Path) -> None:
    fetcher, _, _, _ = make_fetcher(tmp_path, [ok(), ok()])

    first = fetcher.get("src", URL, slug="today")
    second = fetcher.get("src", URL, slug="today")

    assert first.raw_path != second.raw_path
