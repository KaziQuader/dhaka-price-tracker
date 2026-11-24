"""`make reparse SOURCE=x SINCE=YYYY-MM-DD`: re-run parse + load on stored raw snapshots.

Use it after fixing a parser. It reads the snapshots listed in raw.fetch_log (successful
fetches only), so no site is contacted. Rows keep the run_id of the run that fetched them,
and loads are idempotent, so running it twice is harmless.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time

import sqlalchemy as sa
from sqlalchemy import Engine

from tracker.collectors.base import Collector, LoadContext, RawMeta, import_collector
from tracker.core.db import make_engine
from tracker.core.rawstore import RawStore
from tracker.core.settings import Settings, get_settings
from tracker.core.timeutil import DHAKA

log = logging.getLogger("tracker.reparse")


@dataclass(frozen=True)
class ReparseResult:
    files: int
    missing_files: int
    rows_parsed: int
    rows_loaded: int


def reparse(
    *, source: str, since: date, engine: Engine, settings: Settings, collector: Collector
) -> ReparseResult:
    since_ts = datetime.combine(since, time.min, tzinfo=DHAKA)
    with engine.connect() as conn:
        snapshots = conn.execute(
            sa.text(
                "SELECT run_id, url, fetched_at, raw_path FROM raw.fetch_log "
                "WHERE source = :source AND fetched_at >= :since "
                "AND raw_path IS NOT NULL AND error IS NULL ORDER BY fetched_at"
            ),
            {"source": source, "since": since_ts},
        ).all()

    files = missing = parsed = loaded = 0
    for snap in snapshots:
        try:
            raw = RawStore.load(snap.raw_path)
        except FileNotFoundError:
            log.warning("missing snapshot %s", snap.raw_path)
            missing += 1
            continue
        files += 1
        rows = collector.parse(raw, RawMeta(source, snap.url, snap.fetched_at, snap.raw_path))
        parsed += len(rows)
        loaded += collector.load(rows, LoadContext(snap.run_id, engine, settings))
    return ReparseResult(files, missing, parsed, loaded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-parse stored raw snapshots.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--since", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    settings = get_settings()
    result = reparse(
        source=args.source,
        since=args.since,
        engine=make_engine(settings),
        settings=settings,
        collector=import_collector(args.source),
    )
    print(
        f"{args.source}: {result.files} snapshots re-parsed ({result.missing_files} missing), "
        f"{result.rows_parsed} rows parsed, {result.rows_loaded} loaded"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
