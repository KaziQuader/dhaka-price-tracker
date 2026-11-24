"""raw.run_log and raw.fetch_log writers."""

import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import Engine

from tracker.core.timeutil import now_utc

RunStatus = Literal["ok", "partial", "failed"]


def run_status(sources_ok: Sequence[str], sources_failed: Sequence[str]) -> RunStatus:
    """ok: nothing failed. failed: something failed and nothing succeeded. Otherwise partial."""
    if not sources_failed:
        return "ok"
    return "partial" if sources_ok else "failed"


def start_run(engine: Engine) -> uuid.UUID:
    run_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO raw.run_log (run_id, started_at) VALUES (:run_id, :started_at)"),
            {"run_id": run_id, "started_at": now_utc()},
        )
    return run_id


def finish_run(
    engine: Engine,
    run_id: uuid.UUID,
    status: RunStatus,
    sources_ok: Sequence[str],
    sources_failed: Sequence[str],
    notes: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE raw.run_log SET finished_at = :finished_at, status = :status, "
                "sources_ok = :ok, sources_failed = :failed, notes = :notes "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": run_id,
                "finished_at": now_utc(),
                "status": status,
                "ok": list(sources_ok),
                "failed": list(sources_failed),
                "notes": notes,
            },
        )


@dataclass(frozen=True)
class FetchLogEntry:
    run_id: uuid.UUID | None
    source: str
    url: str
    fetched_at: datetime
    http_status: int | None = None
    raw_path: str | None = None
    bytes: int | None = None
    error: str | None = None


class DbFetchLog:
    """Writes one raw.fetch_log row per fetch, in its own transaction so it survives failures."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def __call__(self, entry: FetchLogEntry) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO raw.fetch_log (run_id, source, url, fetched_at, http_status, "
                    "raw_path, bytes, error) VALUES (:run_id, :source, :url, :fetched_at, "
                    ":http_status, :raw_path, :bytes, :error)"
                ),
                asdict(entry),
            )
