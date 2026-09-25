# ds-ipc-mirror

Daily mirror of **IPC / Cadre Harmonisé acute food insecurity** classifications
into the CHD DS team Postgres (dev, schema `ipc`), with a
[GitHub Pages explorer](https://ocha-dap.github.io/ds-ipc-mirror/).

Three tables, deliberately split by source:

| table | source | depth | granularity |
|---|---|---|---|
| `ipc.population` | per-country HDX `ipc` org datasets | 2017+ (full analysis history) | national / level-1 / area — **names only** |
| `ipc.population_admin` | HDX HAPI `food-security` | Oct 2020+ | admin 0–2 with **COD p-codes** |
| `ipc.analyses` | IPC API `/analyses` (optional, `IPC_AUTH`) | 2017+ | analysis registry (id, title, link) |

Every row is keyed on **both** the analysis round (`analysis_date`) and the
reference (validity) period (`period_type` × `reference_period_start/end`) —
current vs first/second projection — because rounds overlap in time.

## Pipelines (Databricks + GitHub Pages)

The dev DB is reachable only through its private endpoint, so the refresh and
the site-data export run on Databricks; GitHub Actions only deploys the site.

- **IPC Mirror** (Databricks job, `databricks.yml`) — daily 03:37 UTC: `refresh_ipc.py`, then `export_site_data.py`, then parks `site/data/` on the dev blob (`projects/ds-ipc-mirror/site-data/`, `scripts/site_data_blob.py upload`).
- **Deploy explorer site** (`deploy-site.yml`) — daily 07:00 UTC (and on dispatch): copies `site/data/` down from the blob and deploys `site/` to GitHub Pages. Output identical to when the export ran in the workflow.

The Job Compute policy injects the `DSCI_AZ_*` secrets; `HAPI_APP_IDENTIFIER` and `IPC_AUTH` must exist in the `dsci` secret scope.

```sh
databricks bundle validate -t prod -p DEFAULT
databricks bundle deploy   -t prod -p DEFAULT   # config changes only; code ships by pushing main
```

## Run locally

```sh
uv sync
cp .env.example .env  # fill in creds
uv run python scripts/refresh_ipc.py
uv run python scripts/export_site_data.py
```

## License / attribution

IPC data: [IPC](https://www.ipcinfo.org/) CC BY-NC-SA 3.0 IGO. Cadre Harmonisé
data additionally: [cadreharmonise.org](https://www.cadreharmonise.org/).
