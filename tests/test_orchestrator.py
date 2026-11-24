"""End-to-end orchestrator tests against the test database (ticket T0.3 "Done when")."""

from datetime import date
from email import message_from_bytes
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import Engine, text

from tracker.collectors import dummy
from tracker.core import email
from tracker.core.config import SourceConfig, SourcesConfig
from tracker.core.settings import Settings
from tracker.orchestrator import DEFAULT_STEPS, StepSkipped, run, summary_email
from tracker.reparse import reparse

pytestmark = pytest.mark.db

PAGE = b"<html><head><title>Example Domain</title></head></html>"
SOURCES = SourcesConfig(
    sources={
        "dummy": SourceConfig(enabled=True, min_interval_s=0, urls={"page": "https://x.test/"}),
        "broken": SourceConfig(enabled=True, min_interval_s=0),
    }
)


def boom(*_args):
    raise RuntimeError("site changed its HTML")


BROKEN = SimpleNamespace(NAME="broken", fetch=boom, parse=boom, load=boom)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", email_dry_run=True)


@pytest.fixture
def client() -> httpx.Client:
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, content=PAGE))
    return httpx.Client(transport=transport)


def counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as conn:
        return (
            conn.scalar(text("SELECT count(*) FROM raw.run_log")),
            conn.scalar(text("SELECT count(*) FROM raw.fetch_log")),
        )


def test_dummy_run_end_to_end(db: Engine, settings: Settings, client: httpx.Client) -> None:
    # The real backup step would pg_dump whatever database `settings` points at; the
    # round trip itself is tested in test_backup.py.
    steps = DEFAULT_STEPS | {"backup": lambda _ctx: "tracker_x.dump (0.1 MB)"}
    report = run(
        settings=settings,
        engine=db,
        sources_config=SOURCES,
        requested=["dummy"],
        steps=steps,
        client=client,
    )
    email_path = email.send(summary_email(report), settings)

    assert report.status == "ok"
    assert counts(db) == (1, 1)
    with db.connect() as conn:
        run_row = conn.execute(
            text("SELECT status, sources_ok, finished_at FROM raw.run_log")
        ).one()
        fetch_row = conn.execute(
            text("SELECT run_id, http_status, raw_path FROM raw.fetch_log")
        ).one()
    assert run_row.status == "ok" and run_row.sources_ok == ["dummy"] and run_row.finished_at
    assert fetch_row.run_id == report.run_id and fetch_row.http_status == 200
    assert len(list((settings.data_dir / "raw" / "dummy").rglob("*.gz"))) == 1
    assert email_path is not None and email_path.exists()
    body = message_from_bytes(email_path.read_bytes()).get_payload()
    assert "OK      dummy: 1 fetches, 1 rows parsed" in body
    # Steps whose tickets aren't built yet are reported, not failed.
    assert {s.name: s.status for s in report.steps} == {
        "dbt": "skipped",
        "score": "skipped",
        "alerts": "skipped",
        "backup": "ok",
    }
    assert "OK      backup: tracker_x.dump (0.1 MB)" in body


def test_one_failing_collector_does_not_stop_the_others(
    db: Engine, settings: Settings, client: httpx.Client
) -> None:
    report = run(
        settings=settings,
        engine=db,
        sources_config=SOURCES,
        collectors={"broken": BROKEN},
        steps={},
        client=client,
    )

    assert report.status == "partial"
    assert [(s.name, s.ok) for s in report.sources] == [("dummy", True), ("broken", False)]
    with db.connect() as conn:
        row = conn.execute(text("SELECT status, sources_failed, notes FROM raw.run_log")).one()
    assert row.status == "partial" and row.sources_failed == ["broken"]
    assert "site changed its HTML" in row.notes
    assert "FAILED  broken: RuntimeError: site changed its HTML" in summary_email(report).text


def test_all_sources_failing_marks_the_run_failed(db: Engine, settings: Settings) -> None:
    report = run(
        settings=settings,
        engine=db,
        sources_config=SOURCES,
        requested=["broken"],
        collectors={"broken": BROKEN},
        steps={},
    )
    assert report.status == "failed"


def test_failing_step_makes_the_run_partial(
    db: Engine, settings: Settings, client: httpx.Client
) -> None:
    def skipped(_ctx):
        raise StepSkipped("later")

    report = run(
        settings=settings,
        engine=db,
        sources_config=SOURCES,
        requested=["dummy"],
        steps={"dbt": boom, "score": skipped, "alerts": lambda _ctx: "0 alerts"},
        client=client,
    )

    assert report.status == "partial"
    assert [(s.name, s.status) for s in report.steps] == [
        ("dbt", "failed"),
        ("score", "skipped"),
        ("alerts", "ok"),
    ]


def test_reparse_reads_stored_snapshots(
    db: Engine, settings: Settings, client: httpx.Client
) -> None:
    run(
        settings=settings,
        engine=db,
        sources_config=SOURCES,
        requested=["dummy"],
        steps={},
        client=client,
    )
    parsed: list[list[dict]] = []
    spy = SimpleNamespace(
        parse=dummy.parse, load=lambda rows, ctx: parsed.append(rows) or len(rows)
    )

    result = reparse(
        source="dummy", since=date(2000, 1, 1), engine=db, settings=settings, collector=spy
    )

    assert (result.files, result.missing_files, result.rows_loaded) == (1, 0, 1)
    assert parsed == [[{"url": "https://x.test/", "title": "Example Domain"}]]
