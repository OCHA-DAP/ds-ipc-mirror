# ds-ipc-mirror

Daily mirror of **IPC / Cadre Harmonisé acute food insecurity** classifications
into the CHD DS team Postgres (dev, schema `ipc`), with a
[GitHub Pages explorer](https://ocha-dap.github.io/ds-ipc-mirror/).

Three tables, deliberately split by source:

| table | source | depth | granularity |
|---|---|---|---|
| `ipc.population` | IPC API `/population`, asked year by year (`IPC_AUTH`) | 2017+ (every acute analysis) | national / level-1 / area — **names only** |
| `ipc.population_admin` | HDX HAPI `food-security` | Oct 2020+ | admin 0–2 with **COD p-codes** |
| `ipc.analyses` | IPC API `/analyses` (`IPC_AUTH`) | 2012+ | analysis registry (id, title, link) |

Every row is keyed on **both** the analysis round (`analysis_date`) and the
reference (validity) period (`period_type` × `reference_period_start/end`) —
current vs first/second projection — because rounds overlap in time.

## Nothing is deleted when a source stops serving it

The population figures used to be read from the per-country IPC datasets on
HDX, and each daily load replaced the whole table. Those datasets are built
from the IPC API with a call that has no year range, and the API now answers
such a call with 2021 onward only. As the HDX files were rebuilt they lost
their older analyses, and the mirror lost them with them: by October 2026
nothing before 2021 was left except Zimbabwe.

Two changes came out of that:

- **The mirror reads the IPC API itself**, one call per year since 2017, which
  the API still serves in full. The rows are built the way `hdx-scraper-ipc`
  builds the HDX files, and match them exactly for the analyses both hold.
  Without `IPC_AUTH`, or if the API gives nothing, the HDX files are read
  instead (2021 onward).
- **A load replaces only the rounds its pull holds** and keeps every other
  stored round as it was. A round that a source stops serving stays, with the
  `refreshed_at` of the last time it was read; the run logs which rounds
  dropped out. This holds for `ipc.population_admin` too.

A refresh that was not a full one (a year the API did not answer, a stored
year that came back empty, no `IPC_AUTH`, a table that refused its pull) loads
what it can and then ends with an error. Nothing stored is lost in those
cases; the error is how a source cutting its history again gets noticed.

The other side of keeping everything: a round IPC withdraws or re-dates stays
in the table as last read, and has to be deleted by hand once checked (see
`CLAUDE.md`).

## Pipelines (Databricks + GitHub Pages)

The dev DB is reachable only through its private endpoint, so the refresh and
the site-data export run on Databricks; GitHub Actions only deploys the site.

- **IPC Mirror** (Databricks job, `databricks.yml`) — daily 03:37 UTC: `refresh_ipc.py`, then `export_site_data.py`, then parks `site/data/` on the dev blob (`projects/ds-ipc-mirror/site-data/`, `scripts/site_data_blob.py upload`).
- **Deploy explorer site** (`deploy-site.yml`) — daily 07:00 UTC (and on dispatch): copies `site/data/` down from the blob and deploys `site/` to GitHub Pages. Output identical to when the export ran in the workflow.

The Job Compute policy injects the `DSCI_AZ_*` secrets; `HAPI_APP_IDENTIFIER` and `IPC_AUTH` come from the `dsci` secret scope. Without `IPC_AUTH` the refresh reads HDX (2021 onward) and ends with an error.

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
uv run pytest                                             # no database needed
IPC_TEST_DB=1 uv run pytest tests/test_storage_db.py      # scratch schema on dev
```

The database is reachable only through its private endpoint: from a laptop,
through the tunnel described in the team knowledge base.

## License / attribution

IPC data: [IPC](https://www.ipcinfo.org/) CC BY-NC-SA 3.0 IGO. Cadre Harmonisé
data additionally: [cadreharmonise.org](https://www.cadreharmonise.org/).
