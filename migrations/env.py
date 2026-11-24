"""Alembic environment.

The database URL comes from `tracker.core.settings` (i.e. `.env` plus environment variables),
so credentials live in one place. Tests pass a URL for the test database through
`config.attributes["url"]` instead.

Migrations are hand-written SQL (no ORM models), so there is no autogenerate metadata.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from tracker.core.settings import get_settings

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def _url():
    return config.attributes.get("url") or get_settings().database_url()


def run_migrations_offline() -> None:
    """Print the SQL instead of running it (`alembic upgrade head --sql`)."""
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
