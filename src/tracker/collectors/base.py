"""The contract every collector module follows.

A collector is a module `tracker.collectors.<name>` (the name used in sources.yaml) with:

    NAME: str
    def fetch(ctx: RunContext) -> list[FetchResult]       # network, via ctx.fetcher only
    def parse(raw: bytes, meta: RawMeta) -> list[Row]      # pure: no network, no DB
    def load(rows: list[Row], ctx: LoadContext) -> int     # idempotent DB writes

Keeping parse pure and separate from fetch is what lets `make reparse` re-run parse + load
on old raw snapshots after a parser fix, and lets tests run parsers on saved fixtures.
"""

import importlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from types import ModuleType
from typing import Protocol

from sqlalchemy import Engine

from tracker.core.config import SourceConfig
from tracker.core.db import Row
from tracker.core.fetch import Fetcher, FetchResult
from tracker.core.settings import Settings


@dataclass(frozen=True)
class RawMeta:
    source: str
    url: str
    fetched_at: datetime
    raw_path: str


@dataclass(frozen=True)
class LoadContext:
    run_id: uuid.UUID
    engine: Engine
    settings: Settings


@dataclass(frozen=True)
class RunContext(LoadContext):
    fetcher: Fetcher
    config: SourceConfig
    today: date  # the run's calendar day in Dhaka


class Collector(Protocol):
    NAME: str

    def fetch(self, ctx: RunContext) -> list[FetchResult]: ...

    def parse(self, raw: bytes, meta: RawMeta) -> list[Row]: ...

    def load(self, rows: list[Row], ctx: LoadContext) -> int: ...


@dataclass(frozen=True)
class CollectorResult:
    fetches: int
    rows_parsed: int
    rows_loaded: int


def import_collector(name: str) -> ModuleType:
    return importlib.import_module(f"tracker.collectors.{name}")


def run_collector(collector: Collector, ctx: RunContext) -> CollectorResult:
    fetched = collector.fetch(ctx)
    parsed = loaded = 0
    for result in fetched:
        meta = RawMeta(result.source, result.url, result.fetched_at, result.raw_path)
        rows = collector.parse(result.content, meta)
        parsed += len(rows)
        loaded += collector.load(rows, ctx)
    return CollectorResult(fetches=len(fetched), rows_parsed=parsed, rows_loaded=loaded)
