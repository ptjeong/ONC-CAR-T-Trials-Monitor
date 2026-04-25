"""Locked-benchmark accuracy test.

Loads `tests/benchmark_set.csv`, looks each NCT up in the most recent local
snapshot, and compares the pipeline's classification against the hand-curated
ground truth across every axis. Prints a per-axis precision / recall / F1
table and fails CI if F1 drops below the per-axis floor.

Run:
    python -m pytest tests/test_benchmark.py -v -s
    python -m pytest tests/ -k benchmark -s        # via pytest selection

Skip semantics (NOT failures):
  - The benchmark trial is missing from the loaded snapshot (filtered out
    upstream, no longer in CT.gov, etc.).
  - Ground-truth cell is empty (means "don't check this axis").
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pytest

# Allow running from repo root without install.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import list_snapshots, load_snapshot  # noqa: E402
# We need the same post-processing the app applies on load (Modality and the
# vectorised phase columns); pulling it from app.py would create a circular
# dep, so we duplicate the small step here.
from pipeline import _flatten_study  # noqa: E402,F401  (sanity check pipeline imports)

BENCHMARK_PATH = Path(__file__).parent / "benchmark_set.csv"

# Per-axis F1 floor — regression below this fails the test. Tunable; start
# conservative (most axes should be near-perfect for a well-curated benchmark)
# and tighten as the benchmark grows.
F1_FLOOR = {
    "Branch":          0.90,
    "DiseaseCategory": 0.80,
    "DiseaseEntity":   0.70,
    "TargetCategory":  0.85,
    "ProductType":     0.85,
    "Modality":        0.85,
    "SponsorType":     0.85,
}

CHECKED_AXES = list(F1_FLOOR.keys())


def _load_benchmark() -> pd.DataFrame:
    df = pd.read_csv(BENCHMARK_PATH, comment="#")
    df.columns = [c.strip() for c in df.columns]
    return df


def _load_latest_snapshot():
    snaps = list_snapshots()
    if not snaps:
        return None
    return load_snapshot(snaps[0])  # list_snapshots returns newest-first


def _norm(value) -> str | None:
    """Normalise a label for comparison: strip, lowercase, treat empty/NaN as None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s.lower() if s else None


def _per_axis_metrics(rows: list[dict]) -> dict:
    """Compute precision / recall / F1 per axis from row-level matches.

    For multi-class classification on a benchmark, each row is one prediction
    so 'precision' and 'recall' collapse to plain accuracy — but we keep the
    full metric vocabulary for forward-compat once the benchmark grows enough
    to support per-class breakdowns.
    """
    by_axis = defaultdict(list)  # axis -> list of (truth, predicted)
    for r in rows:
        for axis in CHECKED_AXES:
            t = _norm(r.get(f"truth_{axis}"))
            p = _norm(r.get(f"pred_{axis}"))
            if t is None:           # axis intentionally blank in benchmark
                continue
            by_axis[axis].append((t, p))

    out = {}
    for axis, pairs in by_axis.items():
        n = len(pairs)
        agreed = sum(1 for t, p in pairs if t == p)
        # Plain accuracy framed as F1 since class-weighted F1 needs per-class
        # confusion matrices — we'll evolve this once the benchmark passes 100
        # trials per branch.
        f1 = agreed / n if n else float("nan")
        out[axis] = {
            "n":        n,
            "agreed":   agreed,
            "accuracy": f1,
            "f1":       f1,
        }
    return out


def _print_metrics(metrics: dict, n_total: int, n_skipped: int) -> None:
    print("\n")
    print("=" * 72)
    print(
        f"BENCHMARK ACCURACY  ·  {n_total - n_skipped}/{n_total} trials evaluated "
        f"({n_skipped} skipped — not in snapshot)"
    )
    print("=" * 72)
    print(f"{'Axis':<18} {'n':>5} {'agreed':>8} {'F1':>8} {'floor':>8} {'status':>10}")
    print("-" * 72)
    for axis in CHECKED_AXES:
        m = metrics.get(axis)
        floor = F1_FLOOR[axis]
        if m is None:
            print(f"{axis:<18} {'—':>5} {'—':>8} {'—':>8} {floor:>8.2f} {'no data':>10}")
            continue
        status = "PASS" if m["f1"] >= floor else "FAIL"
        print(
            f"{axis:<18} {m['n']:>5d} {m['agreed']:>8d} "
            f"{m['f1']:>8.3f} {floor:>8.2f} {status:>10}"
        )
    print("=" * 72)


def _print_disagreements(rows: list[dict]) -> None:
    """Per-trial disagreement table — invaluable when triaging an F1 drop."""
    bad = []
    for r in rows:
        diffs = []
        for axis in CHECKED_AXES:
            t = _norm(r.get(f"truth_{axis}"))
            p = _norm(r.get(f"pred_{axis}"))
            if t is None:
                continue
            if t != p:
                diffs.append((axis, r.get(f"truth_{axis}"), r.get(f"pred_{axis}")))
        if diffs:
            bad.append((r["NCTId"], diffs, r.get("Source", "")))
    if not bad:
        return
    print(f"\nDISAGREEMENTS  ·  {len(bad)} trial(s) with at least one axis mismatch:\n")
    for nct, diffs, source in bad:
        print(f"  {nct}  ({source})")
        for axis, truth, pred in diffs:
            print(f"     {axis}: truth={truth!r}  ·  pred={pred!r}")
        print()


def _ensure_modality(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute Modality the same way the live app does, in case the loaded
    snapshot CSV predates the column being baked into save_snapshot."""
    if "Modality" in df.columns and df["Modality"].notna().any():
        return df
    out = df.copy()
    tc = out.get("TargetCategory", pd.Series(index=out.index, dtype=object)).astype(str).fillna("")
    pt = out.get("ProductType", pd.Series(index=out.index, dtype=object)).astype(str).fillna("")
    title = out.get("BriefTitle", pd.Series(index=out.index, dtype=object)).astype(str).fillna("").str.lower()
    summ = out.get("BriefSummary", pd.Series(index=out.index, dtype=object)).astype(str).fillna("").str.lower()
    intv = out.get("Interventions", pd.Series(index=out.index, dtype=object)).astype(str).fillna("").str.lower()
    txt = title + " " + summ + " " + intv

    import numpy as np
    has_gd = (
        txt.str.contains("γδ", regex=False, na=False)
        | txt.str.contains("gamma delta", regex=False, na=False)
        | txt.str.contains("gamma-delta", regex=False, na=False)
        | txt.str.contains("-gdt", regex=False, na=False)
        | txt.str.contains(" gdt ", regex=False, na=False)
    )
    has_nk = (
        txt.str.contains("car-nk", regex=False, na=False)
        | txt.str.contains("car nk", regex=False, na=False)
        | tc.str.startswith("CAR-NK")
    )
    conditions = [
        has_nk, tc == "CAAR-T", tc == "CAR-Treg",
        has_gd | (tc == "CAR-γδ T"),
        pt == "In vivo", pt == "Autologous", pt == "Allogeneic/Off-the-shelf",
    ]
    choices = [
        "CAR-NK", "CAAR-T", "CAR-Treg", "CAR-γδ T",
        "In vivo CAR", "Auto CAR-T", "Allo CAR-T",
    ]
    out["Modality"] = np.select(conditions, choices, default="CAR-T (unclear)")
    return out


@pytest.fixture(scope="module")
def evaluation_rows():
    """Resolve each benchmark trial against the latest snapshot."""
    bench = _load_benchmark()
    snap = _load_latest_snapshot()
    if snap is None:
        pytest.skip("No snapshot available for benchmark evaluation")
    df, _, _ = snap
    df = _ensure_modality(df)

    by_nct = df.set_index("NCTId")

    rows = []
    skipped = 0
    for _, brow in bench.iterrows():
        nct = brow["NCTId"]
        if nct not in by_nct.index:
            skipped += 1
            continue
        prow = by_nct.loc[nct]
        if isinstance(prow, pd.DataFrame):
            prow = prow.iloc[0]
        record = {"NCTId": nct, "Source": brow.get("Source", "")}
        for axis in CHECKED_AXES:
            record[f"truth_{axis}"] = brow.get(axis)
            record[f"pred_{axis}"] = prow.get(axis)
        rows.append(record)

    return rows, len(bench), skipped


def test_benchmark_per_axis_accuracy(evaluation_rows):
    """Fails if F1 drops below the per-axis floor for any axis with >=5 trials."""
    rows, n_total, n_skipped = evaluation_rows
    if not rows:
        pytest.skip("No benchmark trials matched the loaded snapshot")
    metrics = _per_axis_metrics(rows)
    _print_metrics(metrics, n_total, n_skipped)
    _print_disagreements(rows)

    failures = []
    for axis, m in metrics.items():
        if m["n"] < 5:
            continue  # too few samples to be meaningful
        floor = F1_FLOOR[axis]
        if m["f1"] < floor:
            failures.append(f"{axis}: F1={m['f1']:.3f} < floor {floor:.2f}")
    assert not failures, "Benchmark accuracy regressions:\n  " + "\n  ".join(failures)


def test_benchmark_coverage(evaluation_rows):
    """Sanity check — at least 50% of benchmark trials should be in the snapshot.

    A massive drop in coverage usually means: (1) the snapshot got over-narrowed
    by an upstream filter, or (2) CT.gov dropped trials we expected to be there.
    Either way, worth surfacing as a separate signal from accuracy.
    """
    rows, n_total, _ = evaluation_rows
    coverage = len(rows) / n_total if n_total else 0
    assert coverage >= 0.5, (
        f"Only {len(rows)}/{n_total} benchmark trials matched the snapshot "
        f"({coverage:.0%}); expected ≥ 50%. Investigate upstream filter changes."
    )
