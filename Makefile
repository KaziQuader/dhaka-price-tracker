# Dhaka Price Tracker. See IMPLEMENTATION_PLAN.md §10 for what each target does.
# Recipes use bash so they behave the same in Git Bash (Windows) and on Linux CI.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

# On Windows, make outside Git Bash falls back to cmd.exe (or WSL's bash.exe), where recipes
# fail or, worse, report success. Git Bash sets MSYSTEM, so require it.
ifeq ($(OS),Windows_NT)
ifeq ($(MSYSTEM),)
$(error Run make from Git Bash, not PowerShell or cmd (see README "Setup"))
endif
endif
.DEFAULT_GOAL := help

# Subset of collectors for `make collect SOURCES=a,b`; empty means all enabled ones.
SOURCES ?=

.PHONY: help env-check test lint format up down migrate collect backfill-gold reparse dbt backtest backup restore verify-backup

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

# ---- Implemented ------------------------------------------------------------

# Host-side tests reach the compose Postgres on localhost:5433 (see docker-compose.yml).
test: ## Run pytest (database tests need `make up`)
	POSTGRES_HOST=localhost POSTGRES_PORT=5433 uv run pytest

lint: ## Check lint and formatting with ruff
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

env-check:
	@test -f .env || { echo "No .env file: run 'cp .env.example .env' and fill it in."; exit 1; }

up: env-check ## Start Postgres and Metabase (Metabase: http://localhost:3000)
	docker compose up -d --wait postgres metabase

down: ## Stop Postgres and Metabase (data volumes are kept)
	docker compose down

migrate: env-check ## Run Alembic migrations in the collector container
	docker compose run --rm --build collector alembic upgrade head

# The collector container sees ./config, ./data and ./backups as volumes, so config edits
# need no rebuild; code edits are picked up by --build (cached, a few seconds).
COLLECTOR := docker compose run --rm --build collector

collect: env-check ## Full daily run (SOURCES=a,b for a subset)
	$(COLLECTOR) python -m tracker.orchestrator $(if $(SOURCES),--sources $(SOURCES))

reparse: env-check ## Re-parse raw snapshots (SOURCE=x SINCE=YYYY-MM-DD)
	@test -n "$(SOURCE)" -a -n "$(SINCE)" || { echo "usage: make reparse SOURCE=x SINCE=YYYY-MM-DD"; exit 1; }
	$(COLLECTOR) python -m tracker.reparse --source $(SOURCE) --since $(SINCE)

backup: env-check ## pg_dump to backups/daily/ and rotate (make collect does this too)
	$(COLLECTOR) python -m tracker.core.backup dump

# FILE is a path under backups/, e.g. backups/daily/tracker_20261124_183022.dump. The current
# database is dumped to backups/pre-restore/ first, so a wrong restore can be undone.
restore: env-check ## Replace the database with a dump (FILE=backups/...)
	@test -f "$(FILE)" || { echo "usage: make restore FILE=backups/daily/<name>.dump"; exit 1; }
	@case "$(FILE)" in backups/*) ;; *) echo "FILE must be under backups/ (the container sees only that folder)"; exit 1;; esac
	@read -r -p "This replaces ALL data in the database with $(FILE). Type 'restore' to continue: " answer; \
	  test "$$answer" = restore || { echo "Cancelled."; exit 1; }
	$(COLLECTOR) python -m tracker.core.backup restore "$(FILE)"

verify-backup: env-check ## Dump now, restore into a throwaway Postgres, compare row counts
	bash scripts/verify_backup.sh

# ---- Not implemented yet (each stub names the ticket that builds it) --------

define todo
	@echo "make $@: not implemented yet (ticket $(1))"; exit 1
endef

backfill-gold: ## One-off gold history backfill
	$(call todo,G3)

dbt: ## dbt run && dbt test
	$(call todo,G6)

backtest: ## Run backtests for all rules and models
	$(call todo,P1)
