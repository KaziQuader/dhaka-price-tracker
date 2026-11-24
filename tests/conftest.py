"""Shared fixtures.

Database tests run against a separate `tracker_test` database on the same Postgres server,
so they never touch the real `tracker` data. They are skipped when Postgres is unreachable.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from tracker.core.settings import get_settings

TEST_DB = "tracker_test"
REPO_ROOT = Path(__file__).resolve().parent.parent


def alembic_config(url: URL) -> Config:
    cfg = Config(REPO_ROOT / "alembic.ini")
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False  # keep pytest's log capture intact
    return cfg


@pytest.fixture(scope="session")
def test_db_url() -> URL:
    """Create the test database if needed and return its URL."""
    settings = get_settings()
    admin = create_engine(
        settings.database_url(),
        isolation_level="AUTOCOMMIT",  # CREATE DATABASE can't run inside a transaction
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except OperationalError:
        pytest.skip("Postgres is not reachable: run `make up` first")
    finally:
        admin.dispose()
    # Fail fast instead of hanging if Postgres disappears mid-run or a lock is never released.
    return settings.database_url(TEST_DB).update_query_dict(
        {"connect_timeout": "5", "options": "-c statement_timeout=60s -c lock_timeout=10s"}
    )


@pytest.fixture(scope="session")
def alembic_cfg(test_db_url: URL) -> Config:
    return alembic_config(test_db_url)


@pytest.fixture(scope="session")
def migrated_engine(test_db_url: URL, alembic_cfg: Config) -> Iterator[Engine]:
    """Engine on a freshly migrated test database (rebuilt once per test session)."""
    cfg = alembic_cfg
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(test_db_url)
    yield engine
    engine.dispose()
