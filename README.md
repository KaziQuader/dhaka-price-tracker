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
```

## Make targets

| Target | Does | Status |
|---|---|---|
| `make test` | Run pytest | ready |
| `make lint` | ruff lint and format check | ready |
| `make format` | ruff auto-fix and format | ready |
| `make up` / `make down` | Start / stop Postgres and Metabase | T0.2 |
| `make migrate` | Run Alembic migrations | T0.2 |
| `make collect` | Full daily run (`SOURCES=a,b` for a subset) | T0.3 |
| `make reparse SOURCE=x SINCE=YYYY-MM-DD` | Re-parse stored raw snapshots | T0.3 |
| `make backup` / `make restore FILE=...` | `pg_dump` / restore | T0.4 |
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

`EMAIL_DRY_RUN=1` writes emails to `data/outbox/` instead of sending them.
