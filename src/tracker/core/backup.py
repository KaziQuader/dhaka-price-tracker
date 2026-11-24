"""Database backups (ticket T0.4, spec §2 "Backups").

After every run the orchestrator calls `run(ctx)`, which:
1. writes `pg_dump -Fc` to `backups/daily/tracker_<YYYYMMDD>_<HHMMSS>.dump` (Dhaka time),
2. copies the first dump of each ISO week to `backups/weekly/`,
3. deletes all but the newest 14 daily and 8 weekly dumps.

Step 2 and 3 are decided by `plan_rotation`, a pure function over file names, so the rules
are unit-tested without touching a database or the disk.

`make restore FILE=...` calls `restore()`, which first dumps the current database to
`backups/pre-restore/` (never rotated) so a wrong restore can itself be undone.

Command line: `python -m tracker.core.backup dump` / `restore FILE`.
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from tracker.core.settings import Settings, get_settings
from tracker.core.timeutil import DHAKA, now_utc, to_dhaka

log = logging.getLogger("tracker.backup")

KEEP_DAILY = 14
KEEP_WEEKLY = 8
DUMP_NAME = re.compile(r"^tracker_(\d{8})_(\d{6})\.dump$")


def dump_name(at: datetime) -> str:
    return f"tracker_{to_dhaka(at):%Y%m%d_%H%M%S}.dump"


def parse_dump_name(name: str) -> datetime | None:
    """The Dhaka time in a dump's file name, or None for files that aren't our dumps."""
    match = DUMP_NAME.match(name)
    if match is None:
        return None
    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=DHAKA)


@dataclass(frozen=True)
class Rotation:
    promote: list[str] = field(default_factory=list)  # daily names to copy into weekly/
    delete_daily: list[str] = field(default_factory=list)
    delete_weekly: list[str] = field(default_factory=list)


def plan_rotation(
    daily: Iterable[str],
    weekly: Iterable[str],
    *,
    keep_daily: int = KEEP_DAILY,
    keep_weekly: int = KEEP_WEEKLY,
) -> Rotation:
    """Decide which dumps to promote and delete. Unknown file names are never touched.

    A week (ISO year + week, Dhaka time) gets a weekly copy of its first daily dump if it has
    none yet. Then only the newest `keep_daily` / `keep_weekly` dumps are kept.
    """
    daily_times = {n: t for n in daily if (t := parse_dump_name(n))}
    weekly_times = {n: t for n in weekly if (t := parse_dump_name(n))}

    weeks_covered = {t.isocalendar()[:2] for t in weekly_times.values()}
    promote: list[str] = []
    for name, ts in sorted(daily_times.items(), key=lambda item: item[1]):  # oldest first
        week = ts.isocalendar()[:2]
        if week not in weeks_covered:
            promote.append(name)
            weeks_covered.add(week)

    after_promotion = weekly_times | {n: daily_times[n] for n in promote}
    delete_weekly = _all_but_newest(after_promotion, keep_weekly)
    return Rotation(
        # A week too old to be kept isn't copied just to be deleted again.
        promote=[n for n in promote if n not in delete_weekly],
        delete_daily=_all_but_newest(daily_times, keep_daily),
        delete_weekly=[n for n in delete_weekly if n in weekly_times],
    )


def _all_but_newest(times: dict[str, datetime], keep: int) -> list[str]:
    newest_first = sorted(times, key=times.__getitem__, reverse=True)
    return sorted(newest_first[keep:])


# ---------------------------------------------------------------- pg_dump / pg_restore


def _pg_env(settings: Settings) -> dict[str, str]:
    """Connection settings as libpq environment variables, so the password is not an argv
    entry (visible in `ps`)."""
    return os.environ | {
        "PGHOST": settings.postgres_host,
        "PGPORT": str(settings.postgres_port),
        "PGUSER": settings.postgres_user,
        "PGPASSWORD": settings.postgres_password,
        "PGDATABASE": settings.postgres_db,
    }


def dump(settings: Settings, target_dir: Path, at: datetime | None = None) -> Path:
    """`pg_dump -Fc` into `target_dir`. Written to a `.partial` file and renamed only when
    pg_dump succeeds, so a failed dump never looks like a backup (and never rotates a good
    one out)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / dump_name(at or now_utc())
    partial = final.with_name(final.name + ".partial")
    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(partial)],
            env=_pg_env(settings),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed: {exc.stderr.strip()}") from exc
    partial.replace(final)
    return final


def apply_rotation(backup_dir: Path, rotation: Rotation) -> None:
    daily, weekly = backup_dir / "daily", backup_dir / "weekly"
    weekly.mkdir(parents=True, exist_ok=True)
    for name in rotation.promote:
        # A copy, not a hard link: the two files must survive each other's deletion, and hard
        # links don't work reliably on Docker Desktop's Windows bind mounts.
        shutil.copy2(daily / name, weekly / name)
    for name in rotation.delete_daily:
        (daily / name).unlink(missing_ok=True)
    for name in rotation.delete_weekly:
        (weekly / name).unlink(missing_ok=True)


def backup(settings: Settings, backup_dir: Path) -> tuple[Path, Rotation]:
    path = dump(settings, backup_dir / "daily")
    rotation = plan_rotation(
        _names(backup_dir / "daily"),
        _names(backup_dir / "weekly"),
    )
    apply_rotation(backup_dir, rotation)
    return path, rotation


def restore(settings: Settings, file: Path, backup_dir: Path) -> Path:
    """Replace the database's contents with `file`. Returns the safety dump taken first."""
    if not file.is_file():
        raise FileNotFoundError(file)
    safety = dump(settings, backup_dir / "pre-restore")
    log.info("current database saved to %s before restoring", safety)
    # --clean --if-exists drops each object before recreating it; --single-transaction means
    # a failure leaves the database exactly as it was.
    args = ["pg_restore", "--clean", "--if-exists", "--no-owner", "--single-transaction"]
    args += ["--dbname", settings.postgres_db, str(file)]
    try:
        subprocess.run(args, env=_pg_env(settings), check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"pg_restore failed: {exc.stderr.strip()}") from exc
    return safety


def _names(directory: Path) -> list[str]:
    return [p.name for p in directory.iterdir()] if directory.is_dir() else []


def _backup_dir(settings: Settings) -> Path:
    # Sibling of data/: the repo root on the host, /app in the container (mounted ./backups).
    return settings.data_dir.parent / "backups"


# ---------------------------------------------------------------- entry points


def run(ctx) -> str:
    """Orchestrator step: back up after every run. Returns a one-line summary."""
    path, rotation = backup(ctx.settings, _backup_dir(ctx.settings))
    size = path.stat().st_size
    size_text = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} KB"
    deleted = len(rotation.delete_daily) + len(rotation.delete_weekly)
    promoted = ", promoted to weekly" if rotation.promote else ""
    return f"{path.name} ({size_text}){promoted}, {deleted} old dumps removed"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up or restore the tracker database.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dump", help="pg_dump to backups/daily/ and rotate")
    restore_cmd = sub.add_parser("restore", help="replace the database with a dump")
    restore_cmd.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    settings = get_settings()
    backup_dir = _backup_dir(settings)
    if args.command == "dump":
        path, rotation = backup(settings, backup_dir)
        print(f"wrote {path}")
        for name in rotation.promote:
            print(f"promoted {name} to weekly/")
        for name in rotation.delete_daily + rotation.delete_weekly:
            print(f"deleted {name}")
    else:
        safety = restore(settings, args.file, backup_dir)
        print(f"restored {args.file} (previous contents saved to {safety})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
