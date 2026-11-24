"""Engine creation and idempotent write helpers (spec §9 rule 5).

No ORM models: tables are addressed by name ("stg.fx_daily"), and rows are plain dicts.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Connection, Engine
from sqlalchemy.dialects.postgresql import insert

from tracker.core.settings import Settings, get_settings

Row = dict[str, Any]


def make_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    return sa.create_engine(settings.database_url(), pool_pre_ping=True)


def _table(qualified_name: str, columns: Sequence[str]) -> sa.TableClause:
    schema, _, name = qualified_name.rpartition(".")
    return sa.table(name, *(sa.column(c) for c in columns), schema=schema or None)


def _columns(rows: Sequence[Row]) -> list[str]:
    columns = list(rows[0])
    for row in rows:
        if list(row) != columns:
            raise ValueError("all rows must have the same keys in the same order")
    return columns


def insert_ignore(conn: Connection, table: str, rows: Sequence[Row]) -> int:
    """INSERT ... ON CONFLICT DO NOTHING. Returns how many rows were actually inserted."""
    if not rows:
        return 0
    stmt = (
        insert(_table(table, _columns(rows)))
        .on_conflict_do_nothing()
        .returning(sa.literal_column("1"))
    )
    # RETURNING only yields inserted rows, so counting them skips the conflicting ones.
    return len(conn.execute(stmt, list(rows)).all())


def upsert(conn: Connection, table: str, rows: Sequence[Row], key: Sequence[str]) -> int:
    """INSERT ... ON CONFLICT (key) DO UPDATE the other columns. Returns rows written."""
    if not rows:
        return 0
    columns = _columns(rows)
    stmt = insert(_table(table, columns))
    stmt = stmt.on_conflict_do_update(
        index_elements=list(key),
        set_={c: stmt.excluded[c] for c in columns if c not in key},
    ).returning(sa.literal_column("1"))
    return len(conn.execute(stmt, list(rows)).all())
