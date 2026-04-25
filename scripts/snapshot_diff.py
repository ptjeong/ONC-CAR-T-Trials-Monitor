"""Snapshot-to-snapshot reclassification diff.

Compares two saved snapshots and reports every trial whose classification
fields changed between them. Categorises each change as:

  - Expected:    NCT id is in the current llm_overrides.json  ⇒ change is
                 likely the result of an LLM curation update.
  - Hard-listed: NCT id is in HARD_EXCLUDED_NCT_IDS — change can only be a
                 pipeline / config edit (the trial shouldn't be in the new
                 snapshot, so this surfaces drift in exclusion logic).
  - Unexplained: classification differs and there's no LLM override or hard
                 exclusion — this is the bucket worth investigating because
                 it almost always means a regex / config / pipeline edit had
                 a wider blast radius than expected.

Also surfaces:
  - Trials present in only one snapshot (added / dropped at the PRISMA stage)
  - Per-axis count of changes
  - Top reclassification patterns (e.g., "B-NHL → Basket/Multidisease ×17")

Usage:
    python scripts/snapshot_diff.py snapshots/2026-04-24 snapshots/2026-04-25
    python scripts/snapshot_diff.py 2026-04-24 2026-04-25            # short form
    python scripts/snapshot_diff.py --out reports/diff_2026-04-25.md ...
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import load_snapshot  # noqa: E402

try:
    from config import HARD_EXCLUDED_NCT_IDS  # noqa: E402
except ImportError:
    HARD_EXCLUDED_NCT_IDS = set()

CHECKED_FIELDS = [
    "Branch",
    "DiseaseCategory",
    "DiseaseEntity",
    "TargetCategory",
    "ProductType",
    "SponsorType",
]


def _resolve(arg: str) -> str:
    """Accept either a snapshot directory path or a bare date."""
    p = Path(arg)
    if p.exists():
        return p.name
    return arg  # assume YYYY-MM-DD


def _load_overrides() -> set:
    """Return the set of NCT IDs that have any LLM override entry."""
    try:
        with open("llm_overrides.json") as f:
            data = json.load(f)
        return set(data.keys()) if isinstance(data, dict) else set()
    except FileNotFoundError:
        return set()


def _norm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("snapshot_a", help="Earlier snapshot (date or path)")
    ap.add_argument("snapshot_b", help="Later snapshot (date or path)")
    ap.add_argument("--out", default="reports/snapshot_diff.md")
    ap.add_argument("--show-cap", type=int, default=30,
                    help="Cap on per-axis disagreements printed (default 30)")
    args = ap.parse_args()

    a_date = _resolve(args.snapshot_a)
    b_date = _resolve(args.snapshot_b)
    df_a, _, _ = load_snapshot(a_date)
    df_b, _, _ = load_snapshot(b_date)
    print(f"A = {a_date}: {len(df_a):,} trials")
    print(f"B = {b_date}: {len(df_b):,} trials")

    a_ids = set(df_a["NCTId"])
    b_ids = set(df_b["NCTId"])
    only_a = a_ids - b_ids
    only_b = b_ids - a_ids
    common = a_ids & b_ids
    overrides = _load_overrides()

    a_idx = df_a.set_index("NCTId")
    b_idx = df_b.set_index("NCTId")

    # Walk common NCTs; record per-field changes.
    changes: list[dict] = []
    for nct in sorted(common):
        ra = a_idx.loc[nct]
        rb = b_idx.loc[nct]
        if isinstance(ra, pd.DataFrame): ra = ra.iloc[0]
        if isinstance(rb, pd.DataFrame): rb = rb.iloc[0]
        diffs = {}
        for fld in CHECKED_FIELDS:
            va, vb = _norm(ra.get(fld)), _norm(rb.get(fld))
            if va != vb:
                diffs[fld] = (va, vb)
        if not diffs:
            continue
        if nct in HARD_EXCLUDED_NCT_IDS:
            cause = "hard-listed"
        elif nct in overrides:
            cause = "expected (LLM override)"
        else:
            cause = "unexplained"
        changes.append({"nct": nct, "diffs": diffs, "cause": cause,
                         "title": _norm(rb.get("BriefTitle"))[:120]})

    # Per-axis change counts + top patterns
    per_axis_count = Counter()
    per_axis_patterns: dict[str, Counter] = defaultdict(Counter)
    cause_counts = Counter(c["cause"] for c in changes)
    for c in changes:
        for fld, (va, vb) in c["diffs"].items():
            per_axis_count[fld] += 1
            per_axis_patterns[fld][f"{va or '∅'} → {vb or '∅'}"] += 1

    # Report
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    L = []
    L.append(f"# Snapshot diff: {a_date} → {b_date}")
    L.append("")
    L.append(f"- **Trials A**: {len(df_a):,}")
    L.append(f"- **Trials B**: {len(df_b):,}  ({len(b_ids) - len(a_ids):+d})")
    L.append(f"- **Common NCT IDs**: {len(common):,}")
    L.append(f"- **Added in B**: {len(only_b):,}")
    L.append(f"- **Dropped from A**: {len(only_a):,}")
    L.append(f"- **Reclassified (in common pool)**: {len(changes):,}")
    L.append("")
    L.append("## Reclassifications by cause")
    L.append("")
    L.append("| Cause | n |")
    L.append("|---|---:|")
    for cause in ("expected (LLM override)", "hard-listed", "unexplained"):
        L.append(f"| {cause} | {cause_counts.get(cause, 0)} |")
    L.append("")
    L.append("## Reclassifications by field")
    L.append("")
    L.append("| Field | n changed |")
    L.append("|---|---:|")
    for fld in CHECKED_FIELDS:
        L.append(f"| {fld} | {per_axis_count.get(fld, 0)} |")
    L.append("")
    for fld in CHECKED_FIELDS:
        if not per_axis_patterns[fld]:
            continue
        L.append(f"### Top reclassification patterns — {fld}")
        L.append("")
        L.append("| Change | n |")
        L.append("|---|---:|")
        for pat, n in per_axis_patterns[fld].most_common(10):
            L.append(f"| `{pat}` | {n} |")
        L.append("")

    # The unexplained list is the actionable section.
    unexplained = [c for c in changes if c["cause"] == "unexplained"]
    if unexplained:
        L.append(f"## Unexplained reclassifications ({len(unexplained)})")
        L.append("")
        L.append("These trials are not in `llm_overrides.json` and not on the "
                 "hard-exclude list — the change must come from a pipeline / "
                 "config edit. Triage each before merging.")
        L.append("")
        for c in unexplained[:args.show_cap]:
            L.append(f"### `{c['nct']}` — {c['title']}")
            for fld, (va, vb) in c["diffs"].items():
                L.append(f"- **{fld}**: `{va or '∅'}` → `{vb or '∅'}`")
            L.append("")
        if len(unexplained) > args.show_cap:
            L.append(f"... and {len(unexplained) - args.show_cap} more "
                     f"(raise `--show-cap` to see all).")
            L.append("")

    if only_b:
        L.append(f"## Newly added in {b_date} (top 20)")
        L.append("")
        for nct in list(only_b)[:20]:
            row = b_idx.loc[nct]
            if isinstance(row, pd.DataFrame): row = row.iloc[0]
            L.append(f"- `{nct}` · {_norm(row.get('Branch'))} / "
                     f"{_norm(row.get('DiseaseCategory'))} · "
                     f"{_norm(row.get('BriefTitle'))[:120]}")
        L.append("")

    if only_a:
        L.append(f"## Dropped since {a_date} (top 20)")
        L.append("")
        for nct in list(only_a)[:20]:
            row = a_idx.loc[nct]
            if isinstance(row, pd.DataFrame): row = row.iloc[0]
            L.append(f"- `{nct}` · {_norm(row.get('Branch'))} / "
                     f"{_norm(row.get('DiseaseCategory'))} · "
                     f"{_norm(row.get('BriefTitle'))[:120]}")
        L.append("")

    out.write_text("\n".join(L))
    print(f"\nReport written to {out}")
    print(f"\nReclassifications: {len(changes)} ({cause_counts.get('unexplained', 0)} unexplained)")
    print(f"Added: {len(only_b)} · Dropped: {len(only_a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
