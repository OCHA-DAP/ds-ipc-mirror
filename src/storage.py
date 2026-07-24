"""DB layer: ipc schema on the team Postgres via ocha-stratus.

Stage is selected with the STAGE env var (default "dev"). Writers need the
*_UID_WRITE / *_PW_WRITE credentials; PGSSLMODE=require is enforced here.
"""

import logging
import os
from datetime import datetime, timezone

os.environ.setdefault("PGSSLMODE", "require")

import ocha_stratus as stratus
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

SCHEMA = "ipc"
STAGE = os.environ.get("STAGE", "dev")

POPULATION_COLS = [
    "iso3", "level", "level1_name", "area_name", "analysis_date",
    "period_type", "reference_period_start", "reference_period_end",
    "phase", "population", "fraction", "country_population", "source_dataset",
]
ADMIN_COLS = [
    "location_code", "location_name", "admin1_code", "admin1_name",
    "admin2_code", "admin2_name", "admin_level", "ipc_phase", "ipc_type",
    "population_in_phase", "population_fraction_in_phase",
    "reference_period_start", "reference_period_end", "resource_hdx_id",
]
ANALYSIS_COLS = [
    "analysis_id", "title", "link", "country_iso2", "year", "condition",
    "created", "modified",
]


def get_engine(write=False):
    return stratus.get_engine(stage=STAGE, write=write)


def ensure_tables():
    ddl = f"""
    CREATE SCHEMA IF NOT EXISTS {SCHEMA};
    CREATE TABLE IF NOT EXISTS {SCHEMA}.population (
        iso3 text,
        level text,
        level1_name text,
        area_name text,
        analysis_date date,
        period_type text,
        reference_period_start date,
        reference_period_end date,
        phase text,
        population bigint,
        fraction double precision,
        country_population bigint,
        source_dataset text,
        refreshed_at timestamptz
    );
    CREATE INDEX IF NOT EXISTS population_key_idx
        ON {SCHEMA}.population (iso3, level, analysis_date, period_type);
    CREATE TABLE IF NOT EXISTS {SCHEMA}.population_admin (
        location_code text,
        location_name text,
        admin1_code text,
        admin1_name text,
        admin2_code text,
        admin2_name text,
        admin_level integer,
        ipc_phase text,
        ipc_type text,
        population_in_phase bigint,
        population_fraction_in_phase double precision,
        reference_period_start date,
        reference_period_end date,
        resource_hdx_id text,
        refreshed_at timestamptz
    );
    CREATE INDEX IF NOT EXISTS population_admin_key_idx
        ON {SCHEMA}.population_admin (location_code, admin_level, ipc_type);
    CREATE TABLE IF NOT EXISTS {SCHEMA}.analyses (
        analysis_id text PRIMARY KEY,
        title text,
        link text,
        country_iso2 text,
        year integer,
        condition text,
        created date,
        modified date,
        refreshed_at timestamptz
    );
    """
    with get_engine(write=True).begin() as conn:
        conn.execute(text(ddl))


def _replace(table, df, cols, guard=0.5):
    """Full transactional replace, refusing to shrink the table by > guard."""
    df = df[cols].copy()
    df["refreshed_at"] = datetime.now(timezone.utc)
    engine = get_engine(write=True)
    with engine.begin() as conn:
        existing = conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.{table}")
        ).scalar()
        if existing and len(df) < existing * guard:
            raise RuntimeError(
                f"{table}: refusing to replace {existing} rows with {len(df)} "
                "(partial pull?)"
            )
        conn.execute(text(f"DELETE FROM {SCHEMA}.{table}"))
        df.to_sql(
            table,
            conn,
            schema=SCHEMA,
            if_exists="append",
            index=False,
            chunksize=10_000,
            method="multi",
        )
    logger.info("Replaced %s.%s with %s rows", SCHEMA, table, len(df))


def replace_population(df):
    _replace("population", df, POPULATION_COLS)


def replace_population_admin(df):
    _replace("population_admin", df, ADMIN_COLS)


def upsert_analyses(rows):
    if not rows:
        return
    now = datetime.now(timezone.utc)
    cols = ANALYSIS_COLS + ["refreshed_at"]
    collist = ", ".join(cols)
    params = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "analysis_id")
    sql = text(
        f"INSERT INTO {SCHEMA}.analyses ({collist}) VALUES ({params}) "
        f"ON CONFLICT (analysis_id) DO UPDATE SET {updates}"
    )
    with get_engine(write=True).begin() as conn:
        for row in rows:
            conn.execute(
                sql, {**{c: row.get(c) for c in ANALYSIS_COLS}, "refreshed_at": now}
            )
    logger.info("Upserted %s analyses", len(rows))


def read_population():
    return pd.read_sql(f"SELECT * FROM {SCHEMA}.population", get_engine())


def read_population_admin():
    return pd.read_sql(f"SELECT * FROM {SCHEMA}.population_admin", get_engine())


def read_analyses():
    return pd.read_sql(
        f"SELECT * FROM {SCHEMA}.analyses ORDER BY year DESC, country_iso2",
        get_engine(),
    )
