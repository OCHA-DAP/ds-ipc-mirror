# ds-ipc-mirror

Mirror of IPC/Cadre Harmonisé acute food insecurity classifications into the
team **dev** Postgres, schema **`ipc`**. GH Pages explorer deployed from Actions.

## Key facts

- Tables: `ipc.population` (IPC API `/population` — every acute analysis since
  2017 at national / level-1 / area level; area/level-1 **names only, no
  p-codes**), `ipc.population_admin` (HDX HAPI food-security — the p-coded
  layer, admin 0–2, Oct 2020+ only), `ipc.analyses` (IPC API analysis
  registry: id/title/link). The API calls need `IPC_AUTH`.
- **Loads never delete a round the pull does not hold** (`storage._merge`). A
  pull replaces the rows of the rounds it brings — `(iso3, level,
  analysis_date)` for `population`, `(location_code, ipc_type, reference
  period)` for `population_admin` — and leaves every other stored round
  untouched. Do not bring back a full replace: that is how the mirror lost
  2017–2020 in 2026. `refreshed_at` is the last time a row was read from its
  source; rows older than the latest refresh are no longer served there.
- **Ask the API for each year.** `/population` without `start`/`end` returns
  2021 onward only (seen October 2026; whether that floor moves is unknown).
  `ipcapi.fetch_population` calls it once per year from `HISTORY_START` (2017).
  The API also serves 62 analyses of 2012–2014, never mirrored;
  `IPC_HISTORY_START=2012` would add them, and the load would then keep them.
- **Keying**: every population row carries BOTH the `analysis_date` (the
  assessment round, parsed from "Apr 2026"-style strings) AND the reference
  (validity) period `reference_period_start/end` with `period_type`
  (current / first projection / second projection). A later round's "current"
  overlaps an earlier round's projection — never build a time series without
  keying on both.
- Phase rows overlap: `all` = analyzed population, `3+` duplicates 3/4/5 —
  filter, never sum across phase rows. `fraction` is of *analyzed* population,
  which can be well below the country total.
- The HDX per-country datasets (`ipc` org, `ipc_<iso3>_{national,level1,area}_long.csv`)
  are built from the same API by `hdx-scraper-ipc`, with no year range, so
  they now hold 2021 onward only. `src/hdx.py` reads them when there is no
  `IPC_AUTH` or the API gives nothing; rows are built the same way in both
  (`ipcapi.analysis_rows` follows the scraper), and `source_dataset` says
  which source a row came from (`ipc-api` or the HDX dataset name).
- Two analyses of one country can share a month (the CSV-era key has no
  analysis id); the first one listed wins where they give the same row.
  Dead series: ETH (2021), AGO/SLV/ZWE/ZAF — stale upstream, not a bug. BFA
  stalled at 2024-06.
- A load refuses to write when the pull is empty or holds fewer than half the
  stored rounds, and rolls back if any stored round would be missing after.
  When the API fails for some years the rest is loaded and the run then fails,
  so the gap is seen. `tests/test_storage_db.py` checks all this against a
  scratch schema on dev (`IPC_TEST_DB=1`, needs the tunnel and write creds).
- DB access via `ocha_stratus.get_engine(stage=STAGE, write=...)`; `PGSSLMODE=require`.
- Secrets: the Databricks job reads `HAPI_APP_IDENTIFIER` (base64 of
  `app-name:email`) and `IPC_AUTH` (IPC API key, per-user, from the IPC GSU)
  from the `dsci` scope. `IPC_AUTH` is passed as optional: without it the run
  falls back to HDX and refreshes 2021 onward only.
- License: IPC data is CC BY-NC-SA 3.0 IGO — attribute "IPC CC BY-NC-SA 3.0
  IGO"; link cadreharmonise.org when using CH data.
- IPC ≠ FEWS NET: FEWS NET's IPC-compatible classifications are a different
  product (deliberately NOT mirrored here).
- CI pins Python 3.12 (psycopg2-binary); installs with `uv pip install --no-sources -e .`.
- Pipeline: the Databricks job (`databricks.yml`, daily) refreshes the tables,
  exports `site/data/*.json` (git-ignored) and parks it on the dev blob;
  `deploy-site.yml` copies it down and deploys the explorer.
- `projects/ds-ipc-mirror/archive/` on the dev blob holds the site export of
  2026-07-24, the last copy made before most of the older analyses went
  missing. The API now serves a corrected version of a few of those rounds;
  the export is kept as a record, not as a source.
- KB pages: `pipelines/ipc-mirror.md`, `infrastructure/datasets/ipc.md`.
