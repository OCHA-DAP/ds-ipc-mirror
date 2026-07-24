"""Refresh the IPC mirror: HDX per-country history + HAPI p-coded layer + analyses."""

import logging
import sys

sys.path.insert(0, ".")

import pandas as pd
from dotenv import load_dotenv

from src import hapi, hdx, ipcapi, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("refresh_ipc")


def main():
    load_dotenv()
    storage.ensure_tables()

    population = hdx.fetch_all()
    storage.replace_population(population)

    admin = pd.DataFrame(hapi.fetch_food_security())
    storage.replace_population_admin(admin)

    storage.upsert_analyses(ipcapi.fetch_analyses())

    logger.info("Refresh complete")


if __name__ == "__main__":
    main()
