"""Rows built from the IPC API answer, and the year-by-year pull."""

from datetime import date

import pytest

from src import ipcapi


def figures(suffix="", **numbers):
    """Fields of one location for one period: p1..p5 counts and their shares."""
    counts = [numbers.get(f"p{i}", 0) for i in range(1, 6)]
    total = sum(counts)
    out = {
        f"estimated_population{suffix}": total,
        f"p3plus{suffix}": sum(counts[2:]),
        f"p3plus_percentage{suffix}": round(sum(counts[2:]) / total, 2),
    }
    for i, n in enumerate(counts, start=1):
        out[f"phase{i}_population{suffix}"] = n
        out[f"phase{i}_percentage{suffix}"] = round(n / total, 2)
    return out


def analysis(**extra):
    return {
        "id": "1",
        "condition": "A",
        "country": "SO",
        "title": "Somalia January 2024",
        "analysis_date": "Jan 2024",
        "current_period_dates": "Jan 2024 - Feb 2024",
        "projected_period_dates": "Mar 2024 - Jun 2024",
        "second_projected_period_dates": "",
        "population": 1000,
        **figures(p1=50, p2=30, p3=15, p4=5),
        **figures("_projected", p1=40, p2=30, p3=20, p4=9, p5=1),
        **extra,
    }


def test_national_rows_of_one_analysis():
    rows = ipcapi.analysis_rows(analysis(), "SOM")
    assert {r["level"] for r in rows} == {"national"}
    # two periods with dates, seven phase rows each; no second projection
    assert len(rows) == 14
    assert {r["period_type"] for r in rows} == {"current", "first projection"}
    current = {r["phase"]: r for r in rows if r["period_type"] == "current"}
    assert current["all"]["population"] == 100 and current["all"]["fraction"] == 1.0
    assert current["3+"]["population"] == 20 and current["3+"]["fraction"] == 0.2
    assert current["1"]["analysis_date"] == date(2024, 1, 1)
    assert current["1"]["country_population"] == 1000
    # a period ends on the last day of its last month
    assert current["1"]["reference_period_start"] == date(2024, 1, 1)
    assert current["1"]["reference_period_end"] == date(2024, 2, 29)


def test_groups_and_areas():
    group = {
        "name": "Bay",
        **figures(p1=5, p2=5),
        "areas": [{"name": "Baidoa", **figures(p1=3, p2=2)}],
    }
    rows = ipcapi.analysis_rows(analysis(groups=[group]), "SOM")
    level1 = [r for r in rows if r["level"] == "level1"]
    areas = [r for r in rows if r["level"] == "area"]
    assert {(r["level1_name"], r["area_name"]) for r in level1} == {("Bay", None)}
    assert {(r["level1_name"], r["area_name"]) for r in areas} == {("Bay", "Baidoa")}
    # the area has no projected figures, so it gets rows for the current period only
    assert {r["period_type"] for r in areas} == {"current"}
    # dates come from the analysis, not from the area
    assert areas[0]["reference_period_end"] == date(2024, 2, 29)


def test_areas_without_groups_have_no_level1():
    rows = ipcapi.analysis_rows(
        analysis(areas=[{"name": "Baidoa", **figures(p1=3, p2=2)}]), "SOM"
    )
    areas = [r for r in rows if r["level"] == "area"]
    assert areas and {r["level1_name"] for r in areas} == {None}


@pytest.fixture
def api(monkeypatch):
    """A stand-in for the API: answers per year, and records the calls."""
    answers, calls = {}, []

    def get(path, **params):
        calls.append((path, params))
        answer = answers[params["start"]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(ipcapi, "_get", get)
    return answers, calls


def test_pull_asks_for_each_year(api):
    answers, calls = api
    answers[2023] = [analysis(id="0", analysis_date="Nov 2023")]
    answers[2024] = [
        analysis(),
        analysis(id="2", condition="C"),  # not acute
        analysis(id="3", country="LAC"),  # regional, no country code
        analysis(id="4", analysis_date="sometime"),  # unreadable
    ]
    out, failed = ipcapi.fetch_population(2023, 2024)
    assert failed == []
    assert (
        [c[1]["start"] for c in calls] == [c[1]["end"] for c in calls] == [2023, 2024]
    )
    assert sorted(out["analysis_date"].unique()) == [
        date(2023, 11, 1),
        date(2024, 1, 1),
    ]
    assert set(out["iso3"]) == {"SOM"} and set(out["source_dataset"]) == {"ipc-api"}


def test_a_malformed_record_does_not_sink_the_pull(api):
    answers, _ = api
    no_id = {k: v for k, v in analysis().items() if k != "id"}
    no_country = {k: v for k, v in analysis(id="5").items() if k != "country"}
    answers[2024] = [no_id, no_country, "not a record", analysis(id="6", groups=7)]
    answers[2025] = [analysis(id="7", analysis_date="Jan 2025")]
    out, failed = ipcapi.fetch_population(2024, 2025)
    assert failed == []
    assert out["analysis_date"].unique().tolist() == [date(2025, 1, 1)]


def test_a_year_without_answer_is_reported_not_fatal(api):
    answers, _ = api
    answers[2023] = RuntimeError("IPC API /population failed")
    answers[2024] = [analysis()]
    out, failed = ipcapi.fetch_population(2023, 2024)
    assert failed == [2023]
    assert len(out) == 14


def test_two_analyses_in_one_month_first_one_wins(api):
    answers, _ = api
    later = analysis(id="9", **figures(p1=1, p2=1))
    answers[2024] = [analysis(), later, analysis()]  # the third repeats an id
    out, _ = ipcapi.fetch_population(2024, 2024)
    current = out[(out["period_type"] == "current") & (out["phase"] == "all")]
    assert current["population"].tolist() == [100]


def test_every_country_code_of_the_standard():
    from src.iso import ISO3

    assert len(ISO3) == 249
    assert (ISO3["SO"], ISO3["CD"], ISO3["PS"]) == ("SOM", "COD", "PSE")
    assert "LAC" not in ISO3


class Answer:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        if self.body is None:
            raise ValueError("no JSON")
        return self.body


@pytest.fixture
def http(monkeypatch):
    """Stand-in for requests.get: plays back a list of answers or exceptions."""
    script, urls = [], []

    def get(url, params=None, timeout=None):
        urls.append((url, params))
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setenv("IPC_AUTH", "SECRET-KEY")
    monkeypatch.setattr(ipcapi.requests, "get", get)
    monkeypatch.setattr(ipcapi.time, "sleep", lambda seconds: None)
    return script, urls


def test_a_failed_call_is_tried_again(http):
    script, urls = http
    script += [Answer(502), ipcapi.requests.ConnectionError("down"), Answer(200, [1])]
    assert ipcapi._get("population", start=2020) == [1]
    assert len(urls) == 3 and urls[0][1]["key"] == "SECRET-KEY"


def test_a_refusal_is_not_tried_again(http):
    script, urls = http
    script += [Answer(403), Answer(200, [1])]
    with pytest.raises(RuntimeError, match="HTTP 403"):
        ipcapi._get("population", start=2020)
    assert len(urls) == 1


def test_errors_never_show_the_key(http, caplog):
    script, _ = http
    leak = ipcapi.requests.ConnectionError("GET /population?key=SECRET-KEY failed")
    script += [leak, leak, leak, leak, leak, leak]
    with pytest.raises(RuntimeError) as raised:
        ipcapi._get("population", start=2020)
    assert "SECRET-KEY" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    out, failed = ipcapi.fetch_population(2020, 2020)
    assert failed == [2020] and out.empty
    assert "SECRET-KEY" not in caplog.text
