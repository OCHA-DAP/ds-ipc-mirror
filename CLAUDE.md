# ds-ipc-mirror

Mirror of IPC/Cadre Harmonisé acute food insecurity classifications into the
team **dev** Postgres, schema **`ipc`**. GH Pages explorer deployed from Actions.

## Key facts

- Tables: `ipc.population` (per-country HDX long CSVs — the deepest public
  record of the consensus product, 2017+ where published; area/level-1 **names
  only, no p-codes**), `ipc.population_admin` (HDX HAPI food-security — the
  p-coded layer, admin 0–2, Oct 2020+ only), `ipc.analyses` (IPC API analysis
  registry: id/title/link; optional, needs `IPC_AUTH`).
- **Keying**: every population row carries BOTH the `analysis_date` (the
  assessment round, parsed from "Apr 2026"-style strings) AND the reference
  (validity) period `reference_period_start/end` with `period_type`
  (current / first projection / second projection). A later round's "current"
  overlaps an earlier round's projection — never build a time series without
  keying on both.
- Phase rows overlap: `all` = analyzed population, `3+` duplicates 3/4/5 —
  filter, never sum across phase rows. `fraction` is of *analyzed* population,
  which can be well below the country total.
- HDX sources: all `*-acute-food-insecurity-country-data` datasets in the `ipc`
  org (`ipc_<iso3>_{national,level1,area}_long.csv`, not `_latest`). The global
  dataset and HAPI only reach Oct 2020 — that's why we ingest per-country.
  Duplicate datasets exist (eswatini twice); ingest dedupes newest-first on the
  full row key. Dead series: ETH (2021), AGO/SLV/ZWE/ZAF — stale upstream, not
  a bug. BFA stalled at 2024-06.
- Full-replace loads guard against partial pulls (refuse to shrink >50%).
- DB access via `ocha_stratus.get_engine(stage=STAGE, write=...)`; `PGSSLMODE=require`.
- GHA: `DSCI_AZ_DB_*` are OCHA-DAP **org-level** secrets (no per-repo setup);
  repo secrets: `HAPI_APP_IDENTIFIER` (base64 of `app-name:email`), `IPC_AUTH`
  (optional — IPC API key, per-user, from the IPC GSU; skipped gracefully).
- License: IPC data is CC BY-NC-SA 3.0 IGO — attribute "IPC CC BY-NC-SA 3.0
  IGO"; link cadreharmonise.org when using CH data.
- IPC ≠ FEWS NET: FEWS NET's IPC-compatible classifications are a different
  product (deliberately NOT mirrored here).
- CI pins Python 3.12 (psycopg2-binary); installs with `uv pip install --no-sources -e .`.
- Workflows: `refresh-ipc.yml` (daily) → `deploy-site.yml` chains via
  `workflow_run`, regenerates `site/data/*.json` from the DB (git-ignored).
- KB pages: `pipelines/ipc-mirror.md`, `infrastructure/datasets/ipc.md`.
