"""The load keeps every stored round a pull does not hold.

Runs against a scratch schema on the dev database, so it needs the write
credentials and a route to the database. Opt in with IPC_TEST_DB=1:

    IPC_TEST_DB=1 uv run pytest tests/test_storage_db.py
"""

import os
import uuid

import pandas as pd
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("IPC_TEST_DB"), reason="set IPC_TEST_DB=1 to run against dev"
)


@pytest.fixture
def storage(monkeypatch):
    from src import storage

    schema = f"ipc_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(storage, "SCHEMA", schema)
    storage.ensure_tables()
    yield storage
    with storage.get_engine(write=True).begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))


def rounds(iso3, analysis, areas, level="area", number=10):
    return [
        {
            "iso3": iso3,
            "level": level,
            "level1_name": None,
            "area_name": area,
            "analysis_date": analysis,
            "period_type": "current",
            "reference_period_start": analysis,
            "reference_period_end": analysis,
            "phase": "all",
            "population": number,
            "fraction": 1.0,
            "country_population": 1000,
            "source_dataset": "test",
        }
        for area in areas
    ]


def stored(storage):
    df = storage.read_population()
    df["analysis_date"] = df["analysis_date"].astype(str)
    return df


def test_a_round_the_pull_lacks_is_kept(storage):
    first = rounds("SOM", "2019-01-01", ["a", "b"]) + rounds(
        "SOM", "2024-01-01", ["a", "b"]
    )
    storage.merge_population(pd.DataFrame(first))
    before = stored(storage)

    # the source stops serving 2019, revises 2024 (one area gone) and adds 2025
    second = rounds("SOM", "2024-01-01", ["a"], number=11) + rounds(
        "SOM", "2025-01-01", ["a"]
    )
    result = storage.merge_population(pd.DataFrame(second))
    after = stored(storage)

    assert result == {"pulled": 2, "kept": 1, "dropped": 1}
    by_round = after.groupby("analysis_date")
    assert by_round.size().to_dict() == {
        "2019-01-01": 2,
        "2024-01-01": 1,
        "2025-01-01": 1,
    }

    # the kept round is untouched, down to the time it was last read
    def old(df):
        rows = df[df["analysis_date"] == "2019-01-01"].sort_values("area_name")
        return rows.reset_index(drop=True)

    pd.testing.assert_frame_equal(old(before), old(after))
    assert after.loc[after["analysis_date"] == "2024-01-01", "population"].tolist() == [
        11
    ]
    assert old(after)["refreshed_at"].max() < after["refreshed_at"].max()

    # a round that comes back replaces what was kept
    third = second + rounds("SOM", "2019-01-01", ["a"], number=12)
    assert storage.merge_population(pd.DataFrame(third))["kept"] == 0
    assert old(stored(storage))["population"].tolist() == [12]


def test_levels_are_kept_separately(storage):
    both = rounds("SOM", "2024-01-01", ["a"]) + rounds(
        "SOM", "2024-01-01", [None], level="national"
    )
    storage.merge_population(pd.DataFrame(both))
    # the area file fails to download: the pull holds the national level only
    storage.merge_population(
        pd.DataFrame(rounds("SOM", "2024-01-01", [None], level="national"))
    )
    assert sorted(stored(storage)["level"]) == ["area", "national"]


def test_a_broken_pull_writes_nothing(storage):
    full = [
        r for year in (2021, 2022, 2023) for r in rounds("SOM", f"{year}-01-01", ["a"])
    ]
    storage.merge_population(pd.DataFrame(full))
    before = stored(storage)

    with pytest.raises(RuntimeError, match="broken pull"):
        storage.merge_population(pd.DataFrame(rounds("SOM", "2023-01-01", ["a"])))
    with pytest.raises(RuntimeError, match="empty"):
        storage.merge_population(pd.DataFrame(columns=storage.POPULATION_COLS))
    # rows that all lack their round leave nothing to load
    with pytest.raises(RuntimeError, match="empty"):
        storage.merge_population(pd.DataFrame(full).assign(analysis_date=None))
    pd.testing.assert_frame_equal(before, stored(storage))


def test_rows_without_a_round_are_left_out_not_fatal(storage):
    pull = rounds("SOM", "2024-01-01", ["a", "b"])
    pull[1]["analysis_date"] = None
    storage.merge_population(pd.DataFrame(pull))
    assert stored(storage)["area_name"].tolist() == ["a"]


def test_a_stored_row_without_a_round_is_left_alone(storage):
    storage.merge_population(pd.DataFrame(rounds("SOM", "2024-01-01", ["a"])))
    with storage.get_engine(write=True).begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {storage.SCHEMA}.population (iso3, level, area_name) "
                "VALUES ('SOM', NULL, 'by hand')"
            )
        )
    # it neither blocks later loads nor is removed by them
    storage.merge_population(pd.DataFrame(rounds("SOM", "2024-01-01", ["a", "b"])))
    assert sorted(stored(storage)["area_name"]) == ["a", "b", "by hand"]


def test_admin_periods_are_kept_too(storage):
    def period(start, end, n):
        return {
            **{c: None for c in storage.ADMIN_COLS},
            "location_code": "SOM",
            "admin_level": 1,
            "ipc_phase": "all",
            "ipc_type": "current",
            "population_in_phase": n,
            "reference_period_start": start,
            "reference_period_end": end,
        }

    storage.merge_population_admin(
        pd.DataFrame(
            [
                period("2020-10-01", "2020-12-31", 1),
                period("2024-01-01", "2024-03-31", 2),
            ]
        )
    )
    storage.merge_population_admin(
        pd.DataFrame([period("2024-01-01", "2024-03-31", 3)])
    )
    admin = storage.read_population_admin().sort_values("reference_period_start")
    assert admin["population_in_phase"].tolist() == [1, 3]
