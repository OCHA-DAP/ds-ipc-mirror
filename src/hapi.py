"""HDX HAPI food-security: the p-coded IPC/CH layer (admin 0-2, Oct 2020+).

HAPI p-codes the IPC area names by phonetic matching against CODs — coverage is
good but lossy in ~9 countries (rows fall back to a higher admin level where
matching fails). This is the standardized join surface for our boundaries; the
deeper name-only history lives in ipc.population (src/hdx.py).

HAPI requires an app identifier (base64 of "app-name:email", no registration).
Set HAPI_APP_IDENTIFIER in the environment.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

BASE = "https://hapi.humdata.org/api/v2"
PAGE_SIZE = 10_000


def app_identifier():
    ident = os.environ.get("HAPI_APP_IDENTIFIER")
    if not ident:
        raise RuntimeError("HAPI_APP_IDENTIFIER env var is required")
    return ident


def fetch_food_security():
    """All rows from food-security-nutrition-poverty/food-security, paginated."""
    rows = []
    offset = 0
    while True:
        for attempt in range(3):
            try:
                r = requests.get(
                    f"{BASE}/food-security-nutrition-poverty/food-security",
                    params={
                        "limit": PAGE_SIZE,
                        "offset": offset,
                        "output_format": "json",
                        "app_identifier": app_identifier(),
                    },
                    timeout=180,
                )
                r.raise_for_status()
                page = r.json()["data"]
                break
            except (requests.RequestException, ValueError, KeyError):
                if attempt == 2:
                    raise
                time.sleep(10 * (attempt + 1))
        rows.extend(page)
        logger.info("HAPI food-security: %s rows so far", len(rows))
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE
