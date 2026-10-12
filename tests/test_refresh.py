"""The refresh script: where the population rows come from, and when a run
counts as incomplete."""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import refresh_ipc


def rows(*years):
    return pd.DataFrame({"analysis_date": [date(year, 3, 1) for year in years]})


@pytest.fixture
def sources(monkeypatch):
    """The API answers with ``sources['api']``; HDX holds 2021 onward."""
    state = {"api": (rows(2019, 2021), []), "key": "k"}
    monkeypatch.setattr(refresh_ipc.ipcapi, "api_key", lambda: state["key"])
    monkeypatch.setattr(refresh_ipc.ipcapi, "fetch_population", lambda: state["api"])
    monkeypatch.setattr(refresh_ipc.hdx, "fetch_all", lambda: rows(2021))
    return state


def years(frame):
    return sorted(pd.to_datetime(frame["analysis_date"]).dt.year)


def test_a_full_pull_has_no_problems(sources):
    population, problems = refresh_ipc.fetch_population({2019, 2021})
    assert years(population) == [2019, 2021] and problems == []


def test_without_a_key_hdx_is_read_and_the_run_says_so(sources):
    sources["key"] = None
    population, problems = refresh_ipc.fetch_population({2019, 2021})
    assert years(population) == [2021]
    assert len(problems) == 1 and "IPC_AUTH" in problems[0]


def test_years_the_api_failed_on_are_reported(sources):
    sources["api"] = (rows(2021), [2019])
    population, problems = refresh_ipc.fetch_population({2019, 2021})
    assert years(population) == [2021]
    assert problems == ["the IPC API did not answer for [2019]"]


def test_a_stored_year_coming_back_empty_is_reported(sources):
    # no error from the API: it just has nothing for 2019 any more
    sources["api"] = (rows(2021), [])
    _, problems = refresh_ipc.fetch_population({2019, 2021})
    assert len(problems) == 1 and "[2019]" in problems[0]
    # a year with nothing stored yet, or before the history starts, is fine
    assert refresh_ipc.fetch_population({2012, 2021})[1] == []


def test_an_empty_api_answer_falls_back_to_hdx(sources):
    sources["api"] = (pd.DataFrame(), [2019, 2021])
    population, problems = refresh_ipc.fetch_population({2019, 2021})
    assert years(population) == [2021] and len(problems) == 2


@pytest.fixture
def run(monkeypatch, sources):
    """main() with the database and the other sources replaced; records loads."""
    done = []
    storage = refresh_ipc.storage
    monkeypatch.setattr(refresh_ipc, "load_dotenv", lambda: None)
    monkeypatch.setattr(storage, "ensure_tables", lambda: None)
    monkeypatch.setattr(storage, "population_years", lambda: {2019, 2021})
    monkeypatch.setattr(storage, "merge_population", lambda df: done.append("pop"))
    monkeypatch.setattr(
        storage, "merge_population_admin", lambda df: done.append("admin")
    )
    monkeypatch.setattr(storage, "upsert_analyses", lambda r: done.append("analyses"))
    monkeypatch.setattr(refresh_ipc.hapi, "fetch_food_security", lambda: [])
    monkeypatch.setattr(refresh_ipc.ipcapi, "fetch_analyses", lambda: [])
    return done


def test_a_clean_run_ends_normally(run):
    refresh_ipc.main()
    assert run == ["pop", "admin", "analyses"]


def test_an_incomplete_pull_loads_everything_then_fails(run, sources):
    sources["api"] = (rows(2021), [2019])
    with pytest.raises(SystemExit) as stop:
        refresh_ipc.main()
    assert run == ["pop", "admin", "analyses"]
    assert "did not answer for [2019]" in str(stop.value.code)


def test_one_table_failing_does_not_skip_the_others(run, monkeypatch):
    def refuse(df):
        raise RuntimeError("population: the pull is empty, nothing written")

    monkeypatch.setattr(refresh_ipc.storage, "merge_population", refuse)
    with pytest.raises(SystemExit) as stop:
        refresh_ipc.main()
    assert run == ["admin", "analyses"]
    assert "ipc.population was not refreshed" in str(stop.value.code)
