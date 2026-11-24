# Dhaka Price Tracker

A local, personal tool that tracks and predicts, from a Dhaka point of view:

- **BAJUS gold prices**: 22K, 21K, 18K and traditional, buy and sell.
- **Airfares from Dhaka (DAC)** to Hanoi, Bangkok, Manila and Vientiane.

It joins these prices with context (USD/BDT, world gold, Bangladesh holidays, news shocks) and
shows KPIs, patterns and short-horizon predictions on a local Metabase dashboard, with email alerts.

Everything runs locally with Docker Compose, at zero cost, and is triggered by hand once a day.
See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the architecture, data sources and tickets.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), GNU make, Docker Desktop, git.

**Windows:** run every command below, and all `make` targets, from **Git Bash**. From PowerShell
or cmd, make falls back to `cmd.exe` and the Makefile stops with an error on purpose.

```bash
# Windows only, once: install GNU make and put it on Git Bash's PATH
winget install ezwinports.make
echo 'export PATH="$PATH:$LOCALAPPDATA/Microsoft/WinGet/Packages/ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe/bin"' >> ~/.bashrc
source ~/.bashrc

uv sync                  # creates .venv with Python 3.12 and the dev tools
cp .env.example .env     # then fill in the values
make up                  # start Postgres and Metabase (first time: downloads images)
make migrate             # build the collector image (first time: ~5 min) and create tables
make test
```

### Services

| Service | Address | Notes |
|---|---|---|
| Postgres 16 | `localhost:5433` (from the host), `postgres:5432` (inside compose) | Host port 5433 avoids clashing with a local Postgres on 5432 |
| Metabase | http://localhost:3000 | First visit: create the admin user, then add the database with host `postgres`, port `5432` and the credentials from `.env` |
| collector | `docker compose run --rm collector <command>` | Python, Playwright Chromium and `pg_dump` 16; only runs on demand |

Data lives in the Docker volumes `pgdata` and `mbdata`; `make down` keeps them.
Tests use a separate `tracker_test` database and never touch the real data.

## Make targets

| Target | Does | Status |
|---|---|---|
| `make test` | Run pytest | ready |
| `make lint` | ruff lint and format check | ready |
| `make format` | ruff auto-fix and format | ready |
| `make up` / `make down` | Start / stop Postgres and Metabase | ready |
| `make migrate` | Run Alembic migrations | ready |
| `make collect` | Full daily run (`SOURCES=a,b` for a subset) | ready |
| `make reparse SOURCE=x SINCE=YYYY-MM-DD` | Re-parse stored raw snapshots | ready |
| `make backup` | `pg_dump` to `backups/daily/` and rotate (also runs at the end of `make collect`) | ready |
| `make restore FILE=backups/...` | Replace the database with a dump (asks you to confirm) | ready |
| `make verify-backup` | Dump, restore into a throwaway Postgres, compare row counts | ready |
| `make backfill-gold` | One-off gold history backfill | G3 |
| `make dbt` | `dbt run && dbt test` | G6 |
| `make backtest` | Backtests for rules and models | P1 |

Run `make` with no target to list them.

## Configuration

| File | Holds |
|---|---|
| `.env` (from `.env.example`) | Database credentials, Gmail SMTP app password, `EMAIL_DRY_RUN` |
| `config/routes.yaml` | Fare search grid: routes, weekdays, horizon |
| `config/sources.yaml` | Per-source enable flag, rate limit and URLs |
| `config/watched_trips.yaml` | Trips with target prices for alerts |
| `config/news_topics.yaml` | GDELT news queries |

`EMAIL_DRY_RUN=1` (the default) writes emails to `data/outbox/` instead of sending them. To send
real mail, put a Gmail [app password](https://myaccount.google.com/apppasswords) in
`SMTP_APP_PASSWORD`, set `ALERT_TO`, and set `EMAIL_DRY_RUN=0`.

## How a daily run works

`make collect` runs `python -m tracker.orchestrator` in the collector container:

1. Starts a row in `raw.run_log`.
2. Runs each enabled source in `config/sources.yaml`, in file order. Each collector fetches pages
   through the shared client, which adds a polite per-domain delay and retries, saves every response
   gzipped under `data/raw/<source>/<Dhaka date>/`, and logs it in `raw.fetch_log`. The collector
   then parses and loads the rows. One failing source never stops the others.
3. Runs the later steps (dbt, scoring, alerts, backup). Each is skipped until its ticket exists.
4. Marks the run `ok`, `partial` or `failed` and emails a summary.

`SOURCES=dummy` runs a named source even if it's disabled. `dummy` fetches `example.com` and
exists only to check the pipeline end to end:

```bash
make collect SOURCES=dummy
```

Because raw responses are kept, a parser fix can be applied to past data without fetching again:
`make reparse SOURCE=goldr SINCE=2026-11-01`.

## Backups

Every run ends with a `pg_dump -Fc` into `backups/` (git-ignored):

| Folder | Holds | Kept |
|---|---|---|
| `backups/daily/` | One dump per run, `tracker_<YYYYMMDD>_<HHMMSS>.dump` (Dhaka time) | Newest 14 |
| `backups/weekly/` | A copy of the first dump of each week | Newest 8 |
| `backups/pre-restore/` | The database as it was just before each `make restore` | All (delete by hand) |

Fare history can't be collected again, so **copy `backups/weekly/` off this machine now and
then** (cloud drive or USB). Backups on the same disk don't survive a disk failure.

To restore, pick a file and run `make restore FILE=backups/daily/<name>.dump`. Run
`make verify-backup` once in a while: it proves the newest dump really restores.
