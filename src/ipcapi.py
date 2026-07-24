"""Analysis metadata from the official IPC-CH API (api.ipcinfo.org).

Optional: runs only when IPC_AUTH is set (free per-user key from the IPC GSU).
Gives the analysis registry — id, title, link to the ipcinfo analysis page,
created/modified dates — which the HDX CSVs lack. Joined loosely to
ipc.population on (iso3, analysis month); IPC uses ISO2 country codes.

IPC data is CC BY-NC-SA 3.0 IGO — attribute "IPC CC BY-NC-SA 3.0 IGO" and link
cadreharmonise.org when using CH data.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.ipcinfo.org"


def api_key():
    return os.environ.get("IPC_AUTH")


def fetch_analyses():
    """All acute food insecurity analyses; [] when no key is configured."""
    key = api_key()
    if not key:
        logger.info("IPC_AUTH not set — skipping IPC API analyses metadata")
        return []
    for attempt in range(3):
        try:
            r = requests.get(
                f"{BASE}/analyses",
                params={"type": "A", "format": "json", "key": key},
                timeout=120,
            )
            r.raise_for_status()
            rows = r.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
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
