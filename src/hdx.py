"""Ingest the per-country HDX `ipc` org datasets (full 2017+ history).

The per-country long CSVs (`ipc_<iso3>_{national,level1,area}_long.csv`) are the
deepest public record of the IPC/CH consensus product — the global dataset and
HAPI only reach back to Oct 2020. They carry area/level-1 *names* only; p-codes
exist solely in the HAPI layer (src/hapi.py).

Row key: (iso3, level, level1_name, area_name, analysis_date, period_type,
reference_period_start, phase). `analysis_date` is the analysis/exercise round
("Date of analysis", e.g. "Apr 2026"); the reference (validity) period is what
the classification is valid FOR — a later round's "current" can overlap an
earlier round's projection, so never build a time series without keying on both.
"""

import io
import logging
import re
import time
from datetime import datetime

import pandas as pd
import requests

logger = logging.getLogger(__name__)

CKAN = "https://data.humdata.org/api/3/action"
RESOURCE_RE = re.compile(r"^ipc_([a-z]{3})_(national|level1|area)_long\.csv$")
# derived/legacy datasets that duplicate or truncate the per-country record
SKIP_DATASETS = {"global-acute-food-insecurity-country-data", "ipc-country-data"}

PERIOD_TYPES = {"current", "first projection", "second projection"}


def _get(url, **kwargs):
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=120, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))


def list_country_datasets():
    """All ipc-org datasets with their long-CSV resources, newest-modified first."""
    r = _get(f"{CKAN}/package_search", params={"fq": "organization:ipc", "rows": 200})
    datasets = []
    for pkg in r.json()["result"]["results"]:
        if pkg["name"] in SKIP_DATASETS:
            continue
        resources = [
            res
            for res in pkg.get("resources", [])
            if RESOURCE_RE.match(res.get("name", ""))
        ]
        if resources:
            datasets.append(
                {
                    "name": pkg["name"],
                    "last_modified": pkg.get("last_modified", ""),
                    "resources": resources,
                }
            )
        else:
            logger.warning(
                "Dataset %s has no matching long CSVs — skipped", pkg["name"]
            )
    datasets.sort(key=lambda d: d["last_modified"], reverse=True)
    return datasets


def _parse_analysis_date(s):
    return datetime.strptime(s.strip(), "%b %Y").date()


def parse_long_csv(content, level):
    """Normalize one long CSV into mirror rows."""
    df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    df = df.rename(
        columns={
            "Date of analysis": "analysis_date",
            "Country": "iso3",
            "Total country population": "country_population",
            "Level 1": "level1_name",
            "Area": "area_name",
            "Validity period": "period_type",
            "From": "reference_period_start",
            "To": "reference_period_end",
            "Phase": "phase",
            "Number": "population",
            "Percentage": "fraction",
        }
    )
    for col in ("level1_name", "area_name"):
        if col not in df.columns:
            df[col] = None
    df["analysis_date"] = df["analysis_date"].map(_parse_analysis_date)
    df["level"] = level
    bad = ~df["period_type"].isin(PERIOD_TYPES)
    if bad.any():
        logger.warning(
            "Unexpected period types dropped: %s",
            df.loc[bad, "period_type"].unique().tolist(),
        )
        df = df[~bad]
    cols = [
        "iso3", "level", "level1_name", "area_name", "analysis_date",
        "period_type", "reference_period_start", "reference_period_end",
        "phase", "population", "fraction", "country_population",
    ]
    return df[cols]


def fetch_all():
    """Download + normalize every country dataset; dedupe across datasets.

    Duplicate datasets exist (e.g. eswatini vs kingdom-of-eswatini); iterating
    newest-modified first and dropping exact key duplicates keeps the freshest.
    """
    frames = []
    for ds in list_country_datasets():
        for res in ds["resources"]:
            iso3, level = RESOURCE_RE.match(res["name"]).groups()
            try:
                content = _get(res["download_url"]).content
                df = parse_long_csv(content, level)
            except Exception:
                logger.exception(
                    "Failed to ingest %s from %s — skipped", res["name"], ds["name"]
                )
                continue
            df["source_dataset"] = ds["name"]
            frames.append(df)
        logger.info("Ingested %s", ds["name"])
    out = pd.concat(frames, ignore_index=True)
    key = [
        "iso3", "level", "level1_name", "area_name", "analysis_date",
        "period_type", "reference_period_start", "phase",
    ]
    before = len(out)
    out = out.drop_duplicates(subset=key, keep="first")
    logger.info(
        "HDX ingest: %s rows (%s cross-dataset duplicates dropped)",
        len(out), before - len(out),
    )
    return out
