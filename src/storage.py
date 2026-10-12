"""DB layer: ipc schema on the team Postgres via ocha-stratus.

Stage is selected with the STAGE env var (default "dev"). Writers need the
*_UID_WRITE / *_PW_WRITE credentials; PGSSLMODE=require is enforced here.

Loads never delete a round the pull does not hold. A pull replaces the rows of
the rounds it brings and leaves every other stored round as it was, so a
source that stops serving old analyses (as the HDX files did in 2026) cannot
empty the mirror. `refreshed_at` is therefore the last time a row was read
from its source: rows older than the latest refresh are no longer served.
"""

import logging
import os
from datetime import datetime, timezone

os.environ.setdefault("PGSSLMODE", "require")

import ocha_stratus as stratus
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

# IPC_SCHEMA points a run at a scratch copy (tests/test_storage_db.py)
SCHEMA = os.environ.get("IPC_SCHEMA", "ipc")
STAGE = os.environ.get("STAGE", "dev")

# What a pull replaces as a unit. A round held by the pull is replaced whole;
# a round it does not hold is kept. Level is part of the population key so
# that one level failing to download cannot remove that level's rows.
ROUND = {
    "population": ["iso3", "level", "analysis_date"],
    "population_admin": [
        "location_code", "ipc_type", "reference_period_start", "reference_period_end",
    ],
}

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


def _merge(table, df, cols, guard=0.5):
    """Replace the rounds the pull holds; keep every round it does not.

    One transaction. The only rows deleted are those of rounds the pull holds,
    which are inserted again from the pull straight after. Refuses to write
    when the pull is empty or holds fewer than ``guard`` of the stored rounds
    (a broken pull). Before committing it checks that every round stored
    before is still stored; that cannot fail unless this function is changed.
    """
    key = ROUND[table]
    keys = ", ".join(key)
    target = f"{SCHEMA}.{table}"
    df = df[cols].copy()
    # A row without its round cannot be matched to anything: leave it out
    # rather than refuse the whole load over it.
    keyless = df[key].isna().any(axis=1)
    if keyless.any():
        logger.warning(
            "%s: %s pulled rows without %s were left out",
            table, int(keyless.sum()), keys,
        )
        df = df[~keyless]
    if df.empty:
        raise RuntimeError(f"{table}: the pull is empty, nothing written")
    df["refreshed_at"] = datetime.now(timezone.utc)
    collist = ", ".join([*cols, "refreshed_at"])

    def same_round(a, b):
        return " AND ".join(f"{a}.{c} = {b}.{c}" for c in key)

    with get_engine(write=True).begin() as conn:
        conn.execute(text(f"CREATE TEMP TABLE _pull (LIKE {target}) ON COMMIT DROP"))
        df.to_sql(
            "_pull", conn, if_exists="append", index=False, chunksize=10_000,
            method="multi",
        )
        # one load at a time (readers are not blocked): two overlapping loads
        # would each insert the rounds the other had just replaced
        conn.execute(text(f"LOCK TABLE {target} IN SHARE ROW EXCLUSIVE MODE"))
        # Stored rows without a full key (none today) belong to no round; no
        # pull can match them, so they are never deleted and not counted here.
        keyed = " AND ".join(f"{c} IS NOT NULL" for c in key)
        conn.execute(
            text(
                f"CREATE TEMP TABLE _before ON COMMIT DROP AS "
                f"SELECT {keys}, max(refreshed_at) AS seen FROM {target} "
                f"WHERE {keyed} GROUP BY {keys}"
            )
        )
        conn.execute(
            text(
                f"CREATE TEMP TABLE _rounds ON COMMIT DROP AS "
                f"SELECT DISTINCT {keys} FROM _pull"
            )
        )
        stored = conn.execute(text("SELECT count(*) FROM _before")).scalar()
        pulled = conn.execute(text("SELECT count(*) FROM _rounds")).scalar()
        if stored and pulled < stored * guard:
            raise RuntimeError(
                f"{table}: the pull holds {pulled} rounds against {stored} stored "
                "(broken pull?), nothing written"
            )
        absent = (
            f"FROM _before b WHERE NOT EXISTS "
            f"(SELECT 1 FROM _rounds r WHERE {same_round('r', 'b')})"
        )
        kept = conn.execute(text(f"SELECT count(*) {absent}")).scalar()
        # of those, the rounds read at the last load: new to being left out
        dropped = conn.execute(
            text(
                f"SELECT {keys} {absent} AND b.seen = (SELECT max(seen) FROM _before) "
                f"ORDER BY {keys}"
            )
        ).fetchall()
        conn.execute(
            text(f"DELETE FROM {target} t USING _rounds r WHERE {same_round('t', 'r')}")
        )
        conn.execute(
            text(f"INSERT INTO {target} ({collist}) SELECT {collist} FROM _pull")
        )
        lost = conn.execute(
            text(
                f"SELECT count(*) FROM _before b WHERE NOT EXISTS "
                f"(SELECT 1 FROM {target} t WHERE {same_round('t', 'b')})"
            )
        ).scalar()
        if lost:
            raise RuntimeError(
                f"{table}: {lost} stored rounds would be lost, rolled back"
            )
    logger.info(
        "Merged %s: %s rows in %s rounds pulled, %s stored rounds kept that "
        "the pull does not hold",
        target, len(df), pulled, kept,
    )
    if dropped:
        logger.warning(
            "%s: %s rounds read at the last load are not in this pull; kept as "
            "last read. First ones: %s",
            table, len(dropped), [tuple(str(v) for v in row) for row in dropped[:20]],
        )
    return {"pulled": pulled, "kept": kept, "dropped": len(dropped)}


def merge_population(df):
    return _merge("population", df, POPULATION_COLS)


def merge_population_admin(df):
    return _merge("population_admin", df, ADMIN_COLS)


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


def population_years():
    """The years that have stored analyses."""
    sql = (
        f"SELECT DISTINCT extract(year FROM analysis_date)::int "
        f"FROM {SCHEMA}.population WHERE analysis_date IS NOT NULL"
    )
    with get_engine().connect() as conn:
        return {row[0] for row in conn.execute(text(sql))}


def read_population():
    return pd.read_sql(f"SELECT * FROM {SCHEMA}.population", get_engine())


def read_population_admin():
    return pd.read_sql(f"SELECT * FROM {SCHEMA}.population_admin", get_engine())


def read_analyses():
    return pd.read_sql(
        f"SELECT * FROM {SCHEMA}.analyses ORDER BY year DESC, country_iso2",
        get_engine(),
    )
