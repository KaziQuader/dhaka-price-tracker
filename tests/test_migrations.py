import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.db

EXPECTED_TABLES = {
    "raw.run_log",
    "raw.fetch_log",
    "raw.alert_log",
    "stg.gold_observation",
    "stg.fare_observation",
    "stg.xau_spot",
    "stg.fx_daily",
    "stg.news_daily",
    "pred.gold_next_change",
    "pred.fare_signal",
    "pred.outcome",
}


def tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                "WHERE table_schema IN ('raw', 'stg', 'pred')"
            )
        )
        return {r[0] for r in rows}


def test_upgrade_creates_every_table(migrated_engine: Engine) -> None:
    assert tables(migrated_engine) == EXPECTED_TABLES


def test_downgrade_then_upgrade_round_trips(migrated_engine: Engine, alembic_cfg: Config) -> None:
    command.downgrade(alembic_cfg, "base")
    assert tables(migrated_engine) == set()
    command.upgrade(alembic_cfg, "head")
    assert tables(migrated_engine) == EXPECTED_TABLES


def test_gold_observation_primary_key_makes_inserts_idempotent(migrated_engine: Engine) -> None:
    insert = text(
        "INSERT INTO stg.gold_observation "
        "(source, karat, effective_date, observed_at, buy_bdt_per_gram) "
        "VALUES ('goldr', '22K', '2026-11-23', '2026-11-23T04:00:00Z', 16985) "
        "ON CONFLICT DO NOTHING"
    )
    with migrated_engine.begin() as conn:
        first = conn.execute(insert).rowcount
        second = conn.execute(insert).rowcount
        conn.rollback()
    assert (first, second) == (1, 0)


def test_gold_observation_rejects_unknown_karat(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stg.gold_observation (source, karat, effective_date, observed_at) "
                "VALUES ('goldr', '24K', '2026-11-23', now())"
            )
        )


def test_fare_offer_is_stored_once_per_source_per_run(migrated_engine: Engine) -> None:
    insert = text(
        "INSERT INTO stg.fare_observation (run_id, source, offer_key, price) "
        "VALUES ('00000000-0000-0000-0000-000000000001', 'google', 'abc', 42000) "
        "ON CONFLICT DO NOTHING"
    )
    with migrated_engine.begin() as conn:
        first = conn.execute(insert).rowcount
        second = conn.execute(insert).rowcount
        conn.rollback()
    assert (first, second) == (1, 0)
