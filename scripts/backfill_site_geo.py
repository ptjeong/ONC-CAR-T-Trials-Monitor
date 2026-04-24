"""Backfill Latitude / Longitude into an existing snapshot's sites.csv.

The original `_extract_sites` didn't pull `geoPoint.lat` / `.lon` from the
CT.gov v2 response, so snapshots taken before that change lack coordinates.
This script re-fetches just the `contactsLocationsModule.locations` field
for each NCT in the snapshot and patches the CSV in-place.

Run:
    python scripts/backfill_site_geo.py snapshots/2026-04-24
"""
from __future__ import annotations

import sys
import os
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
BATCH_SIZE = 100
SLEEP_SECONDS = 0.25  # polite pause between batches


def fetch_geopoints(nct_ids: list[str]) -> dict[tuple[str, str, str], tuple[float, float]]:
    """Return {(NCTId, Facility, City): (lat, lon)} for sites with geoPoint."""
    out: dict[tuple[str, str, str], tuple[float, float]] = {}
    for i in range(0, len(nct_ids), BATCH_SIZE):
        chunk = nct_ids[i : i + BATCH_SIZE]
        params = {
            "filter.ids": ",".join(chunk),
            "pageSize": BATCH_SIZE,
            "format": "json",
        }
        resp = requests.get(BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        studies = resp.json().get("studies", [])
        for s in studies:
            ps = s.get("protocolSection", {})
            nct = ps.get("identificationModule", {}).get("nctId")
            locs = ps.get("contactsLocationsModule", {}).get("locations") or []
            for loc in locs:
                gp = loc.get("geoPoint") or {}
                lat, lon = gp.get("lat"), gp.get("lon")
                if lat is None or lon is None:
                    continue
                facility = loc.get("facility") or ""
                city = loc.get("city") or ""
                out[(nct, facility, city)] = (float(lat), float(lon))
        print(
            f"  batch {i // BATCH_SIZE + 1}/"
            f"{(len(nct_ids) + BATCH_SIZE - 1) // BATCH_SIZE} "
            f"({len(studies)} studies returned)"
        )
        time.sleep(SLEEP_SECONDS)
    return out


def backfill(snapshot_dir: str) -> None:
    sites_path = Path(snapshot_dir) / "sites.csv"
    if not sites_path.exists():
        print(f"sites.csv not found at {sites_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(sites_path)
    print(f"Loaded {len(df):,} site rows from {sites_path}")

    if "Latitude" in df.columns and "Longitude" in df.columns:
        existing_filled = df["Latitude"].notna().sum()
        print(f"  existing Latitude values: {existing_filled:,}")
    else:
        df["Latitude"] = pd.NA
        df["Longitude"] = pd.NA

    nct_ids = sorted(df["NCTId"].dropna().unique().tolist())
    print(f"Fetching geoPoints for {len(nct_ids):,} unique NCT IDs...")
    geo = fetch_geopoints(nct_ids)
    print(f"Got coordinates for {len(geo):,} (NCT, Facility, City) triples")

    def _lookup(row, idx: int):
        key = (row["NCTId"], row.get("Facility") or "", row.get("City") or "")
        return geo.get(key, (None, None))[idx]

    before = df["Latitude"].notna().sum()
    df["Latitude"] = df.apply(lambda r: _lookup(r, 0), axis=1)
    df["Longitude"] = df.apply(lambda r: _lookup(r, 1), axis=1)
    after = df["Latitude"].notna().sum()
    print(f"Populated Latitude on {after:,} rows (was {before:,})")

    df.to_csv(sites_path, index=False)
    print(f"Wrote {sites_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    backfill(sys.argv[1])
