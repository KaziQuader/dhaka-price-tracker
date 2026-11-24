"""A do-nothing collector that proves the pipeline end to end (ticket T0.3).

It fetches one page, parses its <title>, and loads nothing (there is no table for it).
Disabled in sources.yaml; run it with `make collect SOURCES=dummy`.
"""

import re

from tracker.collectors.base import LoadContext, RawMeta, RunContext
from tracker.core.db import Row
from tracker.core.fetch import FetchResult

NAME = "dummy"

_TITLE = re.compile(rb"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def fetch(ctx: RunContext) -> list[FetchResult]:
    return [ctx.fetcher.get(NAME, ctx.config.urls["page"], slug="page")]


def parse(raw: bytes, meta: RawMeta) -> list[Row]:
    match = _TITLE.search(raw)
    title = match.group(1).decode("utf-8", "replace").strip() if match else None
    return [{"url": meta.url, "title": title}]


def load(rows: list[Row], ctx: LoadContext) -> int:
    return 0
