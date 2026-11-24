"""Entry point for `make collect`: one full daily run (spec §2, ticket T0.3).

    run_log row -> collectors (in sources.yaml order) -> dbt -> scoring -> alerts -> backup
    -> finish run_log row -> summary email

One failing collector or step never stops the others (spec §9 rule 3): it is logged, the run
is marked `partial`, and the run continues. Steps whose ticket isn't built yet are skipped.
"""

import argparse
import importlib
import importlib.util
import logging
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from sqlalchemy import Engine

from tracker.collectors.base import (
    Collector,
    CollectorResult,
    RunContext,
    import_collector,
    run_collector,
)
from tracker.core import email
from tracker.core.config import SourcesConfig, load_sources
from tracker.core.db import make_engine
from tracker.core.fetch import Fetcher
from tracker.core.rawstore import RawStore
from tracker.core.runlog import DbFetchLog, RunStatus, finish_run, run_status, start_run
from tracker.core.settings import Settings, get_settings
from tracker.core.timeutil import dhaka_date, now_utc, to_dhaka

log = logging.getLogger("tracker.orchestrator")


@dataclass
class SourceOutcome:
    name: str
    result: CollectorResult | None = None
    error: str | None = None
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class StepOutcome:
    name: str
    status: Literal["ok", "skipped", "failed"]
    detail: str = ""


@dataclass
class RunReport:
    run_id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = "ok"
    sources: list[SourceOutcome] = field(default_factory=list)
    steps: list[StepOutcome] = field(default_factory=list)


@dataclass(frozen=True)
class StepContext:
    run_id: uuid.UUID
    engine: Engine
    settings: Settings


# A post-collection step returns a one-line summary, or raises to report failure.
Step = Callable[[StepContext], str]


class StepSkipped(Exception):
    """Raised by a step that has nothing to do yet (its ticket isn't built)."""


def select_sources(config: SourcesConfig, requested: Sequence[str] | None) -> list[str]:
    """Enabled sources in YAML order, or exactly the requested ones (enabled or not)."""
    if not requested:
        return [name for name, cfg in config.sources.items() if cfg.enabled]
    unknown = [name for name in requested if name not in config.sources]
    if unknown:
        raise SystemExit(f"Unknown source(s) {unknown}; known: {sorted(config.sources)}")
    return list(requested)


# ---------------------------------------------------------------- post-collection steps


def _module_step(module: str, ticket: str) -> Step:
    """A step implemented as `module.run(ctx) -> str`, skipped until the module exists."""

    def step(ctx: StepContext) -> str:
        if importlib.util.find_spec(module) is None:
            raise StepSkipped(f"not built yet ({ticket})")
        return importlib.import_module(module).run(ctx)

    return step


def dbt_step(_ctx: StepContext) -> str:
    project = Path("dbt")
    if not (project / "dbt_project.yml").exists():
        raise StepSkipped("not built yet (G6)")
    for command in ("run", "test"):
        subprocess.run(
            ["dbt", command, "--project-dir", str(project), "--profiles-dir", str(project)],
            check=True,
        )
    return "dbt run + dbt test passed"


DEFAULT_STEPS: dict[str, Step] = {
    "dbt": dbt_step,
    "score": _module_step("tracker.models.score", "P1"),
    "alerts": _module_step("tracker.alerts.send", "G7"),
    "backup": _module_step("tracker.core.backup", "T0.4"),
}


# ---------------------------------------------------------------- the run


def run(
    *,
    settings: Settings,
    engine: Engine,
    sources_config: SourcesConfig,
    requested: Sequence[str] | None = None,
    collectors: Mapping[str, Collector] | None = None,
    steps: Mapping[str, Step] | None = None,
    client: httpx.Client | None = None,
) -> RunReport:
    """One full run. `collectors`, `steps` and `client` are injectable for tests."""
    names = select_sources(sources_config, requested)
    steps = DEFAULT_STEPS if steps is None else steps
    run_id = start_run(engine)
    report = RunReport(run_id=run_id, started_at=now_utc())
    log.info("run %s started; sources: %s", run_id, ", ".join(names) or "(none)")

    with Fetcher(
        run_id=run_id,
        sources=sources_config.sources,
        raw_store=RawStore(settings.data_dir),
        fetch_log=DbFetchLog(engine),
        client=client,
    ) as fetcher:
        for name in names:
            outcome = SourceOutcome(name)
            t0 = time.monotonic()
            try:
                collector = (collectors or {}).get(name) or import_collector(name)
                ctx = RunContext(
                    run_id=run_id,
                    engine=engine,
                    settings=settings,
                    fetcher=fetcher,
                    config=sources_config.sources[name],
                    today=dhaka_date(report.started_at),
                )
                outcome.result = run_collector(collector, ctx)
            except Exception as exc:
                log.exception("source %s failed", name)
                outcome.error = f"{type(exc).__name__}: {exc}"
            outcome.seconds = time.monotonic() - t0
            report.sources.append(outcome)

    step_ctx = StepContext(run_id=run_id, engine=engine, settings=settings)
    for name, step in steps.items():
        try:
            report.steps.append(StepOutcome(name, "ok", step(step_ctx)))
        except StepSkipped as skip:
            report.steps.append(StepOutcome(name, "skipped", str(skip)))
        except Exception as exc:
            log.exception("step %s failed", name)
            report.steps.append(StepOutcome(name, "failed", f"{type(exc).__name__}: {exc}"))

    ok = [s.name for s in report.sources if s.ok]
    failed = [s.name for s in report.sources if not s.ok]
    report.status = run_status(ok, failed)
    if report.status == "ok" and any(s.status == "failed" for s in report.steps):
        report.status = "partial"
    report.finished_at = now_utc()
    finish_run(engine, run_id, report.status, ok, failed, notes=_notes(report))
    log.info("run %s finished: %s", run_id, report.status)
    return report


def _notes(report: RunReport) -> str | None:
    problems = [f"{s.name}: {s.error}" for s in report.sources if not s.ok]
    problems += [f"step {s.name}: {s.detail}" for s in report.steps if s.status == "failed"]
    return "; ".join(problems) or None


# ---------------------------------------------------------------- summary email


def summary_email(report: RunReport) -> email.Email:
    started = to_dhaka(report.started_at)
    lines = [
        f"Run {report.run_id}",
        f"Started  {started:%Y-%m-%d %H:%M:%S} (Asia/Dhaka)",
        f"Status   {report.status.upper()}",
    ]
    if report.finished_at:
        lines.append(f"Duration {(report.finished_at - report.started_at).total_seconds():.0f} s")
    lines += ["", "Sources"]
    if not report.sources:
        lines.append("  (none enabled)")
    for s in report.sources:
        if s.ok and s.result:
            r = s.result
            lines.append(
                f"  OK      {s.name}: {r.fetches} fetches, {r.rows_parsed} rows parsed, "
                f"{r.rows_loaded} loaded ({s.seconds:.1f} s)"
            )
        else:
            lines.append(f"  FAILED  {s.name}: {s.error}")
    lines += ["", "Steps"]
    for st in report.steps:
        lines.append(f"  {st.status.upper():<8}{st.name}: {st.detail}")
    subject = f"[tracker] {report.status.upper()} run {started:%Y-%m-%d %H:%M}"
    return email.Email(subject=subject, text="\n".join(lines) + "\n")


# ---------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the daily collection.")
    parser.add_argument(
        "--sources", default="", help="comma-separated subset of sources (default: all enabled)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    settings = get_settings()
    engine = make_engine(settings)
    requested = [s.strip() for s in args.sources.split(",") if s.strip()]
    report = run(
        settings=settings,
        engine=engine,
        sources_config=load_sources(settings.config_dir),
        requested=requested,
    )

    exit_code = 1 if report.status == "failed" else 0
    try:
        path = email.send(summary_email(report), settings)
        log.info("summary email %s", f"written to {path}" if path else "sent")
    except Exception:
        log.exception("could not send the summary email")
        exit_code = 1
    print(summary_email(report).text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
