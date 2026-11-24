"""Initial schemas and Python-owned tables (IMPLEMENTATION_PLAN.md §7).

The `ref` and `feat` schemas are created by dbt, not here.

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("raw", "stg", "pred")

UPGRADE_SQL = """
-- ---------------------------------------------------------------- raw
CREATE TABLE raw.run_log (
    run_id         uuid PRIMARY KEY,
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz,
    status         text CHECK (status IN ('ok', 'partial', 'failed')),  -- NULL while running
    sources_ok     text[],
    sources_failed text[],
    notes          text
);

CREATE TABLE raw.fetch_log (
    id          bigserial PRIMARY KEY,
    run_id      uuid REFERENCES raw.run_log,
    source      text NOT NULL,
    url         text,
    fetched_at  timestamptz NOT NULL,
    http_status int,
    raw_path    text,
    bytes       int,
    error       text
);

-- Not in §7: records every alert sent so G7, F6 and A3 never send the same one twice.
CREATE TABLE raw.alert_log (
    alert_key text PRIMARY KEY,
    kind      text NOT NULL,
    sent_at   timestamptz NOT NULL DEFAULT now(),
    payload   jsonb
);

-- ---------------------------------------------------------------- stg
CREATE TABLE stg.gold_observation (
    run_id            uuid,
    observed_at       timestamptz,
    source            text,
    karat             text CHECK (karat IN ('22K', '21K', '18K', 'traditional')),
    buy_bdt_per_gram  numeric,
    sell_bdt_per_gram numeric,
    usd_bdt_used      numeric,
    effective_date    date,
    PRIMARY KEY (source, karat, effective_date, observed_at)
);

CREATE TABLE stg.fare_observation (
    run_id        uuid,
    observed_at   timestamptz,
    source        text,
    origin        text,
    destination   text,
    depart_date   date,
    return_date   date,
    airline       text,
    stops         int,
    via           text,
    duration_min  int,
    price         numeric,
    currency      text,
    price_bdt     numeric,
    fx_rate_used  numeric,
    offer_key     text,
    raw_offer     jsonb,
    -- Not in §7: the same offer is stored once per source per run (§9 rule 5).
    UNIQUE (run_id, source, offer_key)
);

CREATE TABLE stg.xau_spot (
    date       date PRIMARY KEY,
    usd_per_oz numeric,
    source     text
);

CREATE TABLE stg.fx_daily (
    date   date,
    pair   text,
    rate   numeric,
    source text,
    PRIMARY KEY (date, pair)
);

CREATE TABLE stg.news_daily (
    date          date,
    topic         text,
    article_count int,
    avg_tone      numeric,
    PRIMARY KEY (date, topic)
);

-- ---------------------------------------------------------------- pred
CREATE TABLE pred.gold_next_change (
    as_of                   timestamptz,
    karat                   text,
    p_up                    numeric,
    p_down                  numeric,
    expected_days_to_change numeric,
    rule_or_model           text,
    model_version           text
);

CREATE TABLE pred.fare_signal (
    as_of                   timestamptz,
    origin                  text,
    destination             text,
    depart_date             date,
    signal                  text CHECK (signal IN ('buy', 'wait')),
    p_drop_before_deadline  numeric,
    expected_low_bdt        numeric,
    rule_or_model           text,
    model_version           text
);

CREATE TABLE pred.outcome (
    prediction_table text,
    prediction_key   text,
    resolved_at      timestamptz,
    was_correct      boolean,
    detail           jsonb
);
"""


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    # CASCADE also drops dbt views that were built on top of these tables.
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
