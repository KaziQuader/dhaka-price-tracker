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

.PHONY: help test lint format up down migrate collect backfill-gold reparse dbt backtest backup restore

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

# ---- Implemented ------------------------------------------------------------

test: ## Run pytest
	uv run pytest

lint: ## Check lint and formatting with ruff
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

# ---- Not implemented yet (each stub names the ticket that builds it) --------

define todo
	@echo "make $@: not implemented yet (ticket $(1))"; exit 1
endef

up: ## Start Postgres and Metabase
	$(call todo,T0.2)

down: ## Stop Postgres and Metabase
	$(call todo,T0.2)

migrate: ## Run Alembic migrations
	$(call todo,T0.2)

collect: ## Full daily run (SOURCES=a,b for a subset)
	$(call todo,T0.3)

backfill-gold: ## One-off gold history backfill
	$(call todo,G3)

reparse: ## Re-parse raw snapshots (SOURCE=x SINCE=YYYY-MM-DD)
	$(call todo,T0.3)

dbt: ## dbt run && dbt test
	$(call todo,G6)

backtest: ## Run backtests for all rules and models
	$(call todo,P1)

backup: ## pg_dump the database
	$(call todo,T0.4)

restore: ## Restore a dump (FILE=...)
	$(call todo,T0.4)
