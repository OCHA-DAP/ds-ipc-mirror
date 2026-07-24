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
