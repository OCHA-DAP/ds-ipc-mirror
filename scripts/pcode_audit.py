"""Audit HAPI IPC p-codes against the team boundary reference (public.polygon, prod).

Reports, per country and admin level: how many distinct pcodes in
ipc.population_admin match public.polygon exactly, and lists the misses.
Also reports how much of the deep name-only history (ipc.population areas)
is joinable to a p-coded HAPI row by name.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import ocha_stratus as stratus  # noqa: E402
import pandas as pd  # noqa: E402

from src import storage  # noqa: E402


def main():
    admin = storage.read_population_admin()
    poly = pd.read_sql(
        "SELECT pcode, name, adm_level, iso3 FROM public.polygon "
        "WHERE adm_level IN (1,2)",
        stratus.get_engine(stage="prod"),
    )
    ref = set(poly["pcode"])

    print("== HAPI pcodes vs public.polygon (prod) ==")
    rows = []
    for lvl in (1, 2):
        code_col = f"admin{lvl}_code"
        sub = admin[admin["admin_level"] == lvl][["location_code", code_col]]
        sub = sub.dropna(subset=[code_col]).drop_duplicates()
        for iso3, g in sub.groupby("location_code"):
            codes = set(g[code_col])
            missing = sorted(codes - ref)
            rows.append(
                {
                    "iso3": iso3,
                    "adm_level": lvl,
                    "pcodes": len(codes),
                    "matched": len(codes) - len(missing),
                    "missing": len(missing),
                    "examples": ", ".join(missing[:4]),
                }
            )
    report = pd.DataFrame(rows).sort_values(["missing", "iso3"], ascending=[False, True])
    print(report.to_string(index=False))
    total = report[["pcodes", "matched"]].sum()
    print(
        f"\nTOTAL: {total.matched}/{total.pcodes} distinct pcodes matched "
        f"({100 * total.matched / total.pcodes:.1f}%)"
    )

    print("\n== name-history joinability: ipc.population areas vs HAPI names ==")
    pop = storage.read_population()
    areas = pop[pop["level"] == "area"][["iso3", "area_name"]].drop_duplicates()
    hapi_names = set(
        admin[admin["admin_level"] == 2]["admin2_name"].str.lower().dropna()
    ) | set(admin[admin["admin_level"] == 1]["admin1_name"].str.lower().dropna())
    areas["joins"] = areas["area_name"].str.lower().isin(hapi_names)
    by_iso = areas.groupby("iso3")["joins"].agg(["sum", "count"])
    by_iso["pct"] = (100 * by_iso["sum"] / by_iso["count"]).round(0).astype(int)
    print(by_iso.sort_values("pct").to_string())
    print(
        f"\nTOTAL: {int(areas['joins'].sum())}/{len(areas)} distinct area names "
        f"join a HAPI admin name ({100 * areas['joins'].mean():.1f}%)"
    )


if __name__ == "__main__":
    main()
