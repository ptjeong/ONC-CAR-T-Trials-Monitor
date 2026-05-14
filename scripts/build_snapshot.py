"""Build + save a dated snapshot from the live CT.gov API.

Standalone CLI used by the daily-snapshot CI (`.github/workflows/
daily-snapshot.yml`). Equivalent to the Streamlit UI's "Save current
as snapshot" button but headless: fetches → classifies → writes to
`snapshots/<YYYY-MM-DD>/`.

The geo backfill is SKIPPED by default (network-heavy, slow in CI;
the UI button opts in via `backfill_geo=True`). For citation purposes
the site lat/lon enrichment can be backfilled offline via
`scripts/backfill_site_geo.py` when needed.

Exit codes:
  0 — success, snapshot written
  1 — CT.gov API failure (network / 5xx / rate limit)
  2 — classifier produced empty output (pipeline / config bug)

Usage:
    python scripts/build_snapshot.py
    python scripts/build_snapshot.py --max-records 12000
    python scripts/build_snapshot.py --snapshot-dir custom/path
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# Allow running as `python scripts/build_snapshot.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import build_all_from_api, save_snapshot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-records", type=int, default=10000,
        help="Max trials to fetch from CT.gov. Default 10000 — onc's "
             "CAR-T-in-oncology pipeline is ~2500-3000 trials with "
             "headroom for growth. (Rheum uses 2000.)"
    )
    ap.add_argument(
        "--snapshot-dir", default="snapshots",
        help="Output directory (default: snapshots/)."
    )
    ap.add_argument(
        "--backfill-geo", action="store_true",
        help="Backfill site lat/lon from CT.gov via reverse-geocoding. "
             "OFF by default in CI (slow, network-heavy). The UI's "
             "Save-snapshot button uses backfill_geo=True; CI runs "
             "should leave it off and run scripts/backfill_site_geo.py "
             "as a separate offline pass when needed."
    )
    args = ap.parse_args()

    # --- 1. Fetch + classify --------------------------------------------------
    try:
        df, df_sites, prisma_counts = build_all_from_api(
            max_records=args.max_records, statuses=None,
        )
    except Exception:  # noqa: BLE001 — top-level CLI handler
        print("ERROR: CT.gov API fetch / classification failed.",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    # --- 2. Sanity-check classifier output ------------------------------------
    if df is None or df.empty:
        print(f"ERROR: classifier produced empty DataFrame "
              f"(prisma_counts={prisma_counts}). Likely a config / "
              f"pipeline bug — check pipeline.py / config.py / "
              f"llm_overrides.json for recent edits.", file=sys.stderr)
        return 2

    # --- 3. Persist -----------------------------------------------------------
    snapshot_date = save_snapshot(
        df, df_sites, prisma_counts,
        snapshot_dir=args.snapshot_dir,
        statuses=None,
        backfill_geo=args.backfill_geo,
    )

    print(f"Wrote snapshot {snapshot_date} "
          f"({len(df):,} trials, {len(df_sites):,} site rows) "
          f"to {args.snapshot_dir}/{snapshot_date}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
