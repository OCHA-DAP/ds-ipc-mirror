"""The official IPC-CH API (api.ipcinfo.org): population in phase and the
analysis registry.

Needs IPC_AUTH (free per-user key from the IPC GSU). The per-country HDX
datasets (src/hdx.py) are built from this same API by hdx-scraper-ipc, which
calls `/population` without a year range. The API now answers such a call
with the analyses of 2021 onward only (seen October 2026), so the HDX files
lost everything older as each was rebuilt. Asked for a year explicitly, the
API still serves every analysis — which is why the mirror reads the API
itself, one year at a time.

The population rows are built the way hdx-scraper-ipc builds the HDX long
CSVs, so both sources give the same rows for the same analysis.

IPC data is CC BY-NC-SA 3.0 IGO — attribute "IPC CC BY-NC-SA 3.0 IGO" and link
cadreharmonise.org when using CH data.
"""

import calendar
import logging
import os
import time
from datetime import date, datetime

import pandas as pd
import requests

from src.iso import ISO3

logger = logging.getLogger(__name__)

BASE = "https://api.ipcinfo.org"
# The mirror's history starts in 2017. The API also serves 62 analyses of
# 2012-2014 (none for 2015-2016), made under the previous IPC protocols; they
# have never been mirrored. IPC_HISTORY_START=2012 would bring them in.
HISTORY_START = int(os.environ.get("IPC_HISTORY_START", 2017))
SOURCE = "ipc-api"

# period type -> (field holding its dates on the analysis, suffix of its figures)
PERIODS = {
    "current": ("current_period_dates", ""),
    "first projection": ("projected_period_dates", "_projected"),
    "second projection": ("second_projected_period_dates", "_second_projected"),
}
# phase -> (field of the number, field of the share), before the period suffix
PHASES = {
    "all": ("estimated_population", None),
    "3+": ("p3plus", "p3plus_percentage"),
    "1": ("phase1_population", "phase1_percentage"),
    "2": ("phase2_population", "phase2_percentage"),
    "3": ("phase3_population", "phase3_percentage"),
    "4": ("phase4_population", "phase4_percentage"),
    "5": ("phase5_population", "phase5_percentage"),
}
POPULATION_KEY = [
    "iso3", "level", "level1_name", "area_name", "analysis_date",
    "period_type", "reference_period_start", "phase",
]


def api_key():
    return os.environ.get("IPC_AUTH")


def _get(path, **params):
    """One API call as JSON. Errors never carry the URL, which holds the key."""
    for attempt in range(3):
        try:
            r = requests.get(
                f"{BASE}/{path}",
                params={**params, "format": "json", "key": api_key()},
                timeout=300,
            )
            if r.status_code != 200:
                raise RuntimeError(f"IPC API /{path}: HTTP {r.status_code}")
            return r.json()
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            if attempt == 2:
                raise RuntimeError(
                    f"IPC API /{path} failed: {type(exc).__name__}"
                    + (f" ({exc})" if isinstance(exc, RuntimeError) else "")
                ) from None
            time.sleep(10 * (attempt + 1))


def fetch_analyses():
    """All acute food insecurity analyses; [] when no key is configured."""
    if not api_key():
        logger.info("IPC_AUTH not set — skipping IPC API analyses metadata")
        return []
    rows = _get("analyses", type="A")
    logger.info("IPC API: %s analyses", len(rows))
    return [
        {
            "analysis_id": row.get("id"),
            "title": row.get("title"),
            "link": row.get("link"),
            "country_iso2": row.get("country"),
            "year": row.get("year"),
            "condition": row.get("condition"),
            "created": row.get("created"),
            "modified": row.get("modified"),
        }
        for row in rows
    ]


def _month(text):
    return datetime.strptime(text.strip(), "%b %Y").date()


def _span(text):
    """'Jan 2021 - Mar 2021' -> (2021-01-01, 2021-03-31)."""
    first, last = (_month(part) for part in text.split(" - "))
    return first, last.replace(day=calendar.monthrange(last.year, last.month)[1])


def _location_rows(location, analysis, base):
    """One row per period and phase for a country, a level-1 group or an area.

    The dates of a period come from the analysis, its figures from the location.
    """
    rows = []
    for period_type, (dates_field, suffix) in PERIODS.items():
        dates = analysis.get(dates_field)
        if not dates:
            continue
        start, end = _span(dates)
        for phase, (number_field, share_field) in PHASES.items():
            number = location.get(number_field + suffix)
            if number is None:
                continue
            rows.append(
                {
                    **base,
                    "period_type": period_type,
                    "reference_period_start": start,
                    "reference_period_end": end,
                    "phase": phase,
                    "population": number,
                    # the share is of the analysed population, so "all" is 1
                    "fraction": location.get(share_field + suffix)
                    if share_field
                    else 1.0,
                }
            )
    return rows


def analysis_rows(analysis, iso3):
    """Mirror rows of one analysis: national, level 1 (groups) and areas."""
    base = {
        "iso3": iso3,
        "analysis_date": _month(analysis["analysis_date"]),
        "country_population": analysis.get("population"),
    }

    def at(level, level1_name, area_name):
        return {
            **base, "level": level, "level1_name": level1_name, "area_name": area_name
        }

    rows = _location_rows(analysis, analysis, at("national", None, None))
    groups = analysis.get("groups")
    if groups:
        for group in groups:
            name = group["name"]
            rows += _location_rows(group, analysis, at("level1", name, None))
            for area in group.get("areas") or []:
                rows += _location_rows(area, analysis, at("area", name, area["name"]))
    else:
        for area in analysis.get("areas") or []:
            rows += _location_rows(area, analysis, at("area", None, area["name"]))
    return rows


def fetch_population(start=HISTORY_START, end=None):
    """Population in phase of every acute analysis from ``start`` to ``end``.

    One call per year, because a call without a year range no longer returns
    the whole history. Returns the rows and the years the API did not answer
    for; the caller keeps what is stored for those.
    """
    end = end or date.today().year
    rows, seen, failed = [], set(), []
    for year in range(start, end + 1):
        try:
            analyses = _get("population", type="A", start=year, end=year)
            if not isinstance(analyses, list):
                raise RuntimeError(f"IPC API /population {year}: not a list")
        except RuntimeError as exc:
            logger.error("%s — year %s skipped", exc, year)
            failed.append(year)
            continue
        kept = 0
        for analysis in analyses:
            if analysis.get("condition") != "A" or analysis["id"] in seen:
                continue
            iso3 = ISO3.get(analysis["country"])
            if iso3 is None:  # regional analyses, e.g. "LAC"
                logger.warning(
                    "No ISO3 for %s (%s) — skipped",
                    analysis["country"], analysis.get("title"),
                )
                continue
            seen.add(analysis["id"])
            try:
                rows += analysis_rows(analysis, iso3)
            except (KeyError, ValueError, TypeError):
                # its stored rows stay as they are
                logger.exception(
                    "Could not read analysis %s (%s) — skipped",
                    analysis["id"], analysis.get("title"),
                )
                continue
            kept += 1
        logger.info("IPC API population %s: %s analyses", year, kept)
    out = pd.DataFrame(rows)
    if out.empty:
        return out, failed
    # Two analyses of one country can share a month; as with the HDX files,
    # the first one listed wins where they give the same row.
    before = len(out)
    out = out.drop_duplicates(subset=POPULATION_KEY, keep="first")
    out["source_dataset"] = SOURCE
    logger.info(
        "IPC API ingest: %s rows, %s analyses (%s duplicate rows dropped)",
        len(out), len(seen), before - len(out),
    )
    return out, failed
