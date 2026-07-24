"""Export DB contents to static JSON for the GitHub Pages explorer.

Writes site/data/index.json, site/data/national.json, and per-country
site/data/areas/{ISO3}.json + site/data/admin/{ISO3}.json (compact arrays).
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import pandas as pd  # noqa: E402

from src import storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SITE_DATA = Path(__file__).parent.parent / "site" / "data"

AREA_ROW_COLS = [
    "level", "level1_name", "area_name", "analysis_date", "period_type",
    "reference_period_start", "reference_period_end", "phase",
    "population", "fraction",
]
ADMIN_ROW_COLS = [
    "admin_level", "admin1_code", "admin1_name", "admin2_code", "admin2_name",
    "ipc_phase", "ipc_type", "population_in_phase",
    "population_fraction_in_phase", "reference_period_start",
    "reference_period_end",
]


def _clean(v):
    if pd.isna(v):
        return None
    if isinstance(v, float) and v == int(v):
        return int(v)
    return str(v) if hasattr(v, "isoformat") else v


def _rows(df, cols):
    return [
        [_clean(v) for v in row]
        for row in df[cols].itertuples(index=False, name=None)
    ]


def main():
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    pop = storage.read_population()
    admin = storage.read_population_admin()

    national = pop[pop["level"] == "national"]
    (SITE_DATA / "national.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "columns": ["iso3"] + AREA_ROW_COLS,
                "rows": _rows(national, ["iso3"] + AREA_ROW_COLS),
            }
        )
    )
    logger.info("national.json: %s rows", len(national))

    subnat = pop[pop["level"] != "national"]
    (SITE_DATA / "areas").mkdir(exist_ok=True)
    for iso3, g in sorted(subnat.groupby("iso3")):
        (SITE_DATA / "areas" / f"{iso3}.json").write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "iso3": iso3,
                    "columns": AREA_ROW_COLS,
                    "rows": _rows(g, AREA_ROW_COLS),
                }
            )
        )

    (SITE_DATA / "admin").mkdir(exist_ok=True)
    for iso3, g in sorted(admin.groupby("location_code")):
        (SITE_DATA / "admin" / f"{iso3}.json").write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "iso3": iso3,
                    "columns": ADMIN_ROW_COLS,
                    "rows": _rows(g, ADMIN_ROW_COLS),
                }
            )
        )

    countries = []
    admin_isos = set(admin["location_code"].unique())
    for iso3, g in sorted(pop.groupby("iso3")):
        countries.append(
            {
                "iso3": iso3,
                "analyses": sorted(
                    {str(d) for d in g["analysis_date"].unique()}, reverse=True
                ),
                "has_admin": iso3 in admin_isos,
            }
        )
    (SITE_DATA / "index.json").write_text(
        json.dumps({"generated_at": generated_at, "countries": countries})
    )
    logger.info(
        "index.json: %s countries (%s with p-coded admin rows)",
        len(countries), len(admin_isos),
    )


if __name__ == "__main__":
    main()
