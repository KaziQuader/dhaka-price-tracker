"""Backup rotation rules (pure) and a real dump -> change -> restore round trip (db)."""

import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from tracker.core.backup import (
    apply_rotation,
    dump,
    dump_name,
    parse_dump_name,
    plan_rotation,
    restore,
)
from tracker.core.settings import Settings
from tracker.core.timeutil import DHAKA

MONDAY = datetime(2026, 11, 23, 18, 0, tzinfo=DHAKA)  # ISO week 2026-W48


def names(start: datetime, days: int) -> list[str]:
    """One dump per day for `days` days from `start`."""
    return [dump_name(start + timedelta(days=i)) for i in range(days)]


def test_dump_name_round_trip_uses_dhaka_time() -> None:
    utc = datetime(2026, 11, 23, 19, 30, 5, tzinfo=UTC)  # 01:30 on the 24th in Dhaka
    assert dump_name(utc) == "tracker_20261124_013005.dump"
    assert parse_dump_name("tracker_20261124_013005.dump") == utc
    assert parse_dump_name("tracker_20261124_013005.dump.partial") is None
    assert parse_dump_name("notes.txt") is None


def test_first_dump_of_a_week_is_promoted_once() -> None:
    daily = names(MONDAY, 3)  # Mon, Tue, Wed of the same week

    rotation = plan_rotation(daily, [])
    assert rotation.promote == [daily[0]]

    # Next run: the week already has its weekly copy, so nothing new is promoted.
    assert plan_rotation(daily, [daily[0]]).promote == []


def test_missed_weeks_are_caught_up() -> None:
    daily = [dump_name(MONDAY), dump_name(MONDAY + timedelta(days=7))]
    assert plan_rotation(daily, []).promote == daily


def test_keeps_newest_14_daily() -> None:
    daily = names(MONDAY, 20)
    rotation = plan_rotation(daily, [], keep_weekly=100)
    assert rotation.delete_daily == daily[:6]


def test_keeps_newest_8_weekly_including_new_promotion() -> None:
    weekly = names(MONDAY - timedelta(weeks=8), 8 * 7)[::7]  # 8 weekly dumps, oldest first
    daily = [dump_name(MONDAY)]  # a new week

    rotation = plan_rotation(daily, weekly)

    assert rotation.promote == daily
    assert rotation.delete_weekly == [weekly[0]]


def test_does_not_promote_a_week_that_would_be_deleted_straight_away() -> None:
    weekly = names(MONDAY, 8 * 7)[::7]
    old_daily = [dump_name(MONDAY - timedelta(weeks=5))]  # older than every kept weekly

    rotation = plan_rotation(old_daily, weekly)

    assert rotation.promote == [] and rotation.delete_weekly == []


def test_unknown_files_are_never_deleted() -> None:
    daily = names(MONDAY, 20) + ["keep-me.dump", "tracker_x.dump.partial"]
    rotation = plan_rotation(daily, ["README.txt"], keep_daily=1)
    assert "keep-me.dump" not in rotation.delete_daily
    assert "tracker_x.dump.partial" not in rotation.delete_daily
    assert "README.txt" not in rotation.delete_weekly


def test_apply_rotation_copies_then_deletes(tmp_path: Path) -> None:
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    daily = names(MONDAY, 3)
    for name in daily:
        (daily_dir / name).write_bytes(name.encode())

    apply_rotation(tmp_path, plan_rotation(daily, [], keep_daily=1))

    assert sorted(p.name for p in daily_dir.iterdir()) == [daily[2]]
    weekly_copy = tmp_path / "weekly" / daily[0]
    assert weekly_copy.read_bytes() == daily[0].encode()  # promoted before it was deleted


# ---------------------------------------------------------------- real pg_dump / pg_restore


def _pg_major(tool: str) -> int:
    if shutil.which(tool) is None:
        return 0
    out = subprocess.run([tool, "--version"], capture_output=True, text=True).stdout
    match = re.search(r"(\d+)\.", out)
    return int(match.group(1)) if match else 0


needs_pg16_tools = pytest.mark.skipif(
    min(_pg_major("pg_dump"), _pg_major("pg_restore")) < 16,
    reason="pg_dump/pg_restore 16+ not on PATH (the collector container has them)",
)


@pytest.mark.db
@needs_pg16_tools
def test_dump_and_restore_round_trip(db: Engine, test_db_url, tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        postgres_host=test_db_url.host,
        postgres_port=test_db_url.port,
        postgres_user=test_db_url.username,
        postgres_password=test_db_url.password,
        postgres_db=test_db_url.database,
    )
    with db.begin() as conn:
        conn.execute(
            text("INSERT INTO raw.run_log (run_id, started_at) VALUES (gen_random_uuid(), now())")
        )

    path = dump(settings, tmp_path / "daily")
    assert path.stat().st_size > 0 and not list(tmp_path.rglob("*.partial"))

    with db.begin() as conn:  # a mistake made after the backup
        conn.execute(text("DELETE FROM raw.run_log"))

    safety = restore(settings, path, tmp_path)

    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM raw.run_log")) == 1
    assert safety.parent == tmp_path / "pre-restore" and safety.exists()


@pytest.mark.db
@needs_pg16_tools
def test_failed_dump_leaves_no_file(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, postgres_host="localhost", postgres_port=1)
    with pytest.raises(RuntimeError, match="pg_dump failed"):
        dump(settings, tmp_path)
    assert list(tmp_path.iterdir()) == []
