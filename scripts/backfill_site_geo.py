"""Backfill Latitude / Longitude into an existing snapshot's sites.csv.

Thin CLI wrapper around `pipeline.backfill_site_geo` (the canonical
implementation). The same code path is also chained into
`pipeline.save_snapshot(backfill_geo=True)` so new snapshots can be
geo-complete on day one without a separate backfill pass.

Usage:
    python scripts/backfill_site_geo.py snapshots/2026-04-24
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import backfill_site_geo  # noqa: E402


def backfill(snapshot_dir: str) -> None:
    sites_path = Path(snapshot_dir) / "sites.csv"
    if not sites_path.exists():
        print(f"sites.csv not found at {sites_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(sites_path)
    print(f"Loaded {len(df):,} site rows from {sites_path}")

    before = (
        df["Latitude"].notna().sum()
        if "Latitude" in df.columns else 0
    )
    print(f"  existing Latitude values: {before:,}")

    df = backfill_site_geo(df)

    after = df["Latitude"].notna().sum()
    print(f"Populated Latitude on {after:,} rows (was {before:,})")
    df.to_csv(sites_path, index=False)
    print(f"Wrote {sites_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    backfill(sys.argv[1])
