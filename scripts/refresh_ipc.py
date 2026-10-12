"""Refresh the IPC mirror: population history + HAPI p-coded layer + analyses.

Population comes from the IPC API, asked for every year since 2017, because
the HDX files now hold 2021 onward only. Without IPC_AUTH, or when the API
gives nothing, the HDX files are read instead; the load keeps every stored
round a pull does not hold, so the older analyses stay either way.
"""

import logging
import sys

sys.path.insert(0, ".")

import pandas as pd
from dotenv import load_dotenv

from src import hapi, hdx, ipcapi, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("refresh_ipc")


def fetch_population():
    """Rows from the IPC API, or from HDX; and the years the API failed on."""
    if not ipcapi.api_key():
        logger.warning("IPC_AUTH not set — reading the HDX files (2021 onward only)")
        return hdx.fetch_all(), []
    population, failed = ipcapi.fetch_population()
    if population.empty:
        logger.error("IPC API gave no rows — reading the HDX files instead")
        return hdx.fetch_all(), failed
    return population, failed


def main():
    load_dotenv()
    storage.ensure_tables()

    population, failed = fetch_population()
    storage.merge_population(population)

    admin = pd.DataFrame(hapi.fetch_food_security())
    storage.merge_population_admin(admin)

    storage.upsert_analyses(ipcapi.fetch_analyses())

    if failed:
        # everything else is loaded; fail the run so the gap is seen
        sys.exit(
            f"IPC API did not answer for {failed}: analyses of those years were "
            "not refreshed (what was stored is kept)"
        )
    logger.info("Refresh complete")


if __name__ == "__main__":
    main()
