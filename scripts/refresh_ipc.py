"""Refresh the IPC mirror: population history + HAPI p-coded layer + analyses.

Population comes from the IPC API, asked for every year since 2017, because
the HDX files now hold 2021 onward only. Without IPC_AUTH, or when the API
gives nothing, the HDX files are read instead; the load keeps every stored
round a pull does not hold, so the older analyses stay either way.

Each table is loaded even if another fails. The run ends with an error when
anything kept it from being a full refresh, so that a source cutting its
history again is seen the day it happens.
"""

import logging
import sys

sys.path.insert(0, ".")

import pandas as pd
from dotenv import load_dotenv

from src import hapi, hdx, ipcapi, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("refresh_ipc")


def fetch_population(stored_years):
    """Rows for ipc.population, and what kept the pull from being the full one."""
    if not ipcapi.api_key():
        return hdx.fetch_all(), [
            "IPC_AUTH is not set: read the HDX files, which hold 2021 onward only"
        ]
    problems = []
    population, failed = ipcapi.fetch_population()
    if failed:
        problems.append(f"the IPC API did not answer for {failed}")
    if population.empty:
        problems.append("the IPC API gave no rows: read the HDX files instead")
        return hdx.fetch_all(), problems
    # An empty answer is not an error to the API. For a year that has stored
    # analyses it means the history is being cut again.
    answered = set(pd.to_datetime(population["analysis_date"]).dt.year)
    silent = sorted(
        year
        for year in stored_years - answered - set(failed)
        if year >= ipcapi.HISTORY_START
    )
    if silent:
        problems.append(
            f"the IPC API returned no analysis for {silent}, which have stored ones"
        )
    return population, problems


def main():
    load_dotenv()
    storage.ensure_tables()
    problems = []

    def population():
        rows, notes = fetch_population(storage.population_years())
        problems.extend(notes)
        storage.merge_population(rows)

    loads = {
        "ipc.population": population,
        "ipc.population_admin": lambda: storage.merge_population_admin(
            pd.DataFrame(hapi.fetch_food_security())
        ),
        "ipc.analyses": lambda: storage.upsert_analyses(ipcapi.fetch_analyses()),
    }
    for table, load in loads.items():
        try:
            load()
        except Exception as exc:  # noqa: BLE001 — load the other tables regardless
            logger.exception("%s was not refreshed", table)
            reason = str(exc).splitlines()[0][:200] if str(exc) else ""
            problems.append(
                f"{table} was not refreshed ({type(exc).__name__}: {reason})"
            )

    if problems:
        sys.exit(
            "Refresh finished with problems (everything stored before is kept):\n- "
            + "\n- ".join(problems)
        )
    logger.info("Refresh complete")


if __name__ == "__main__":
    main()
