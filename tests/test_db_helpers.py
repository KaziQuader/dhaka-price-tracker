from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from tracker.core.db import insert_ignore, upsert

pytestmark = pytest.mark.db


@pytest.fixture
def fx(db: Engine) -> Engine:
    with db.begin() as conn:
        conn.execute(text("TRUNCATE stg.fx_daily"))
    return db


def rate(day: str, value: str) -> dict:
    return {"date": day, "pair": "USDBDT", "rate": Decimal(value), "source": "test"}


def test_insert_ignore_counts_only_new_rows(fx: Engine) -> None:
    with fx.begin() as conn:
        assert insert_ignore(conn, "stg.fx_daily", [rate("2026-11-23", "122.0")]) == 1
        assert (
            insert_ignore(
                conn, "stg.fx_daily", [rate("2026-11-23", "999"), rate("2026-11-24", "122.1")]
            )
            == 1
        )
        rows = conn.execute(text("SELECT date::text, rate FROM stg.fx_daily ORDER BY date")).all()
    # The duplicate was ignored, not overwritten.
    assert rows == [("2026-11-23", Decimal("122.0")), ("2026-11-24", Decimal("122.1"))]


def test_upsert_overwrites_non_key_columns(fx: Engine) -> None:
    with fx.begin() as conn:
        upsert(conn, "stg.fx_daily", [rate("2026-11-23", "122.0")], key=["date", "pair"])
        upsert(conn, "stg.fx_daily", [rate("2026-11-23", "122.5")], key=["date", "pair"])
        rows = conn.execute(text("SELECT rate FROM stg.fx_daily")).scalars().all()
    assert rows == [Decimal("122.5")]


def test_empty_rows_and_mismatched_keys(fx: Engine) -> None:
    with fx.begin() as conn:
        assert insert_ignore(conn, "stg.fx_daily", []) == 0
        with pytest.raises(ValueError, match="same keys"):
            insert_ignore(conn, "stg.fx_daily", [rate("2026-11-23", "1"), {"date": "2026-11-24"}])
