"""Compute Cohen's κ + 95% bootstrap CI for the inter-rater validation study.

Reads every committed rater response from `validation_study/responses/`,
computes pairwise Cohen's κ per axis between every pair of raters,
plus single-rater κ vs the pipeline (secondary outcome). Outputs a
markdown report ready to drop into the manuscript Results section.

Per-axis statistics reported:
    - Pairwise Cohen's κ between raters (with 95% bootstrap CI)
    - Pairwise % agreement
    - Confusion matrix (top categories)
    - Each rater's κ vs pipeline
    - Three-way agreement rate (rater A == rater B == pipeline)

Skipped trials and "Unsure" labels are excluded from the κ computation
(they're recorded as data, but they're not classifications). The skip /
Unsure rate is reported separately as a secondary outcome.

Usage (from repo root):
    python scripts/compute_validation_kappa.py
    python scripts/compute_validation_kappa.py --bootstrap 10000
    python scripts/compute_validation_kappa.py --output report.md

Requires no external deps beyond pandas + numpy (which the repo already
pins) — Cohen's κ and bootstrap are implemented in this file to keep
the dependency footprint stable.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RESPONSES_DIR = REPO_ROOT / "validation_study" / "responses"
SAMPLE_PATH = REPO_ROOT / "validation_study" / "sample_v1.json"

AXES = ["Branch", "DiseaseCategory", "DiseaseEntity",
        "TargetCategory", "ProductType", "SponsorType"]

# Labels we treat as "no classification" — excluded from κ
NON_RATING_LABELS = {"Unsure", "Skipped", "", None}


def cohens_kappa(rater_a: list[str], rater_b: list[str]) -> float | None:
    """Closed-form Cohen's κ for two equal-length label sequences.

    Returns None when N<2 or only one category is present (κ undefined).
    Same implementation as `_cohens_kappa` in app.py (unit-tested
    against the Sim & Wright 2005 BMC textbook example).
    """
    if len(rater_a) != len(rater_b) or len(rater_a) < 2:
        return None
    n = len(rater_a)
    categories = sorted(set(rater_a) | set(rater_b))
    if len(categories) < 2:
        return None
    observed = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    ca, cb = Counter(rater_a), Counter(rater_b)
    expected = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def bootstrap_kappa_ci(
    rater_a: list[str],
    rater_b: list[str],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 20260426,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for Cohen's κ.

    Resamples the (rater_a, rater_b) pair vector with replacement
    `n_resamples` times, computes κ on each resample, returns
    (lower, upper) percentile bounds. Returns (None, None) if the
    point estimate is undefined (< 2 categories or N < 2).
    """
    point = cohens_kappa(rater_a, rater_b)
    if point is None:
        return None, None
    n = len(rater_a)
    rng = np.random.default_rng(seed)
    kappas: list[float] = []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        a = [rater_a[i] for i in idx]
        b = [rater_b[i] for i in idx]
        k = cohens_kappa(a, b)
        if k is not None:
            kappas.append(k)
    if not kappas:
        return None, None
    alpha = (1.0 - confidence) / 2
    lo, hi = np.quantile(kappas, [alpha, 1 - alpha])
    return float(lo), float(hi)


def landis_koch(kappa: float | None) -> str:
    """Landis & Koch (1977) interpretive categories."""
    if kappa is None:
        return "—"
    if kappa < 0.0: return "poor"
    if kappa < 0.20: return "slight"
    if kappa < 0.40: return "fair"
    if kappa < 0.60: return "moderate"
    if kappa < 0.80: return "substantial"
    return "almost perfect"


def _load_raters() -> dict[str, dict]:
    """Returns {rater_id: rater_state_dict}."""
    raters = {}
    if not RESPONSES_DIR.exists():
        return raters
    for path in sorted(RESPONSES_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"  WARN: skipping unparseable {path.name}", file=sys.stderr)
            continue
        rater_id = doc.get("rater_id", path.stem)
        raters[rater_id] = doc
    return raters


def _load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text())


def _aligned_rating_vectors(
    rater_a_doc: dict,
    rater_b_doc: dict,
    axis: str,
) -> tuple[list[str], list[str], int]:
    """For a given axis, return (a_labels, b_labels, n_excluded).

    Aligns on the intersection of NCT IDs both raters scored, then
    drops any pair where either label is in NON_RATING_LABELS.
    """
    a_ratings = rater_a_doc.get("ratings", {})
    b_ratings = rater_b_doc.get("ratings", {})
    common_ncts = sorted(set(a_ratings) & set(b_ratings))

    a_labels: list[str] = []
    b_labels: list[str] = []
    excluded = 0
    for nct in common_ncts:
        la = a_ratings[nct].get("labels", {}).get(axis)
        lb = b_ratings[nct].get("labels", {}).get(axis)
        if la in NON_RATING_LABELS or lb in NON_RATING_LABELS:
            excluded += 1
            continue
        a_labels.append(str(la))
        b_labels.append(str(lb))
    return a_labels, b_labels, excluded


def _pipeline_labels(sample: dict, ncts: list[str], axis: str) -> dict[str, str]:
    """{nct_id: pipeline_label_for_axis} for the requested NCTs."""
    out = {}
    for trial in sample["trials"]:
        if trial["NCTId"] in ncts:
            out[trial["NCTId"]] = (
                trial.get("_pipeline", {}).get(axis) or ""
            )
    return out


def _confusion_top(rater_a: list[str], rater_b: list[str], top: int = 6) -> str:
    """Compact markdown confusion matrix (top N categories by frequency)."""
    if not rater_a:
        return "_(no comparable ratings)_"
    df = pd.DataFrame({"A": rater_a, "B": rater_b})
    top_cats = list(pd.concat([df["A"], df["B"]]).value_counts().head(top).index)
    pivot = (
        df[df["A"].isin(top_cats) & df["B"].isin(top_cats)]
        .pivot_table(index="A", columns="B", aggfunc="size", fill_value=0)
        .reindex(index=top_cats, columns=top_cats, fill_value=0)
    )
    return pivot.to_markdown()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bootstrap", type=int, default=10_000,
                   help="Bootstrap resamples for κ CI. Default 10000.")
    p.add_argument("--output", type=str, default=None,
                   help="Optional markdown output file.")
    args = p.parse_args()

    sample = _load_sample()
    raters = _load_raters()

    if not raters:
        print(f"No rater responses found in {RESPONSES_DIR}.", file=sys.stderr)
        return 1

    out_lines: list[str] = []

    def emit(s: str = "") -> None:
        out_lines.append(s)
        print(s)

    emit(f"# Validation study — Cohen's κ report")
    emit()
    emit(f"- **Sample:** v1 (sha256: `{sample['sha256']}`)")
    emit(f"- **N trials:** {sample['n']}")
    emit(f"- **Raters:** {', '.join(sorted(raters))}")
    emit(f"- **Bootstrap resamples:** {args.bootstrap:,}")
    emit()

    # ---- Per-rater progress summary ----
    emit("## Per-rater completion")
    emit()
    rows = []
    for rid, doc in sorted(raters.items()):
        n_total = len(doc.get("ratings", {}))
        n_skipped = sum(1 for r in doc["ratings"].values() if r.get("skipped"))
        durations = [r.get("duration_seconds", 0) for r in doc["ratings"].values()
                     if not r.get("skipped")]
        median_s = int(np.median(durations)) if durations else 0
        rows.append({
            "Rater": rid,
            "N rated": n_total,
            "Skipped": n_skipped,
            "Median time (s)": median_s,
        })
    emit(pd.DataFrame(rows).to_markdown(index=False))
    emit()

    # ---- Pairwise inter-rater κ per axis ----
    rater_ids = sorted(raters)
    if len(rater_ids) < 2:
        emit(f"Only {len(rater_ids)} rater(s) — pairwise κ requires ≥ 2.")
    else:
        for i, a in enumerate(rater_ids):
            for b in rater_ids[i + 1:]:
                emit(f"## Inter-rater κ: **{a}** vs **{b}**")
                emit()
                rows = []
                for axis in AXES:
                    av, bv, n_excluded = _aligned_rating_vectors(
                        raters[a], raters[b], axis,
                    )
                    n = len(av)
                    if n < 2:
                        rows.append({
                            "Axis": axis, "N comparable": n,
                            "% agreement": "—", "κ": "—",
                            "95% CI": "—", "Interpretation": "—",
                        })
                        continue
                    agree = sum(1 for x, y in zip(av, bv) if x == y) / n
                    kappa = cohens_kappa(av, bv)
                    lo, hi = bootstrap_kappa_ci(
                        av, bv, n_resamples=args.bootstrap,
                    )
                    rows.append({
                        "Axis": axis,
                        "N comparable": n,
                        "% agreement": f"{agree*100:.1f}%",
                        "κ": (f"{kappa:.3f}" if kappa is not None else "—"),
                        "95% CI": (f"[{lo:.3f}, {hi:.3f}]"
                                   if lo is not None else "—"),
                        "Interpretation": landis_koch(kappa),
                    })
                emit(pd.DataFrame(rows).to_markdown(index=False))
                emit()

                # Per-axis confusion matrices
                emit(f"### Confusion matrices ({a} vs {b})")
                emit()
                for axis in AXES:
                    av, bv, _ = _aligned_rating_vectors(
                        raters[a], raters[b], axis,
                    )
                    if not av:
                        continue
                    emit(f"**{axis}** (top categories):")
                    emit()
                    emit(_confusion_top(av, bv))
                    emit()

    # ---- Single-rater vs pipeline (secondary outcome) ----
    emit("## Per-rater agreement with pipeline (secondary outcome)")
    emit()
    rows = []
    for rid, doc in sorted(raters.items()):
        for axis in AXES:
            ratings = doc.get("ratings", {})
            ncts = list(ratings.keys())
            pipe = _pipeline_labels(sample, ncts, axis)
            ra = []
            pa = []
            excl = 0
            for nct in ncts:
                rl = ratings[nct].get("labels", {}).get(axis)
                pl = pipe.get(nct)
                if rl in NON_RATING_LABELS or not pl:
                    excl += 1
                    continue
                ra.append(str(rl))
                pa.append(str(pl))
            n = len(ra)
            if n < 2:
                continue
            kappa = cohens_kappa(ra, pa)
            agree = sum(1 for x, y in zip(ra, pa) if x == y) / n
            rows.append({
                "Rater": rid, "Axis": axis, "N": n,
                "% agreement": f"{agree*100:.1f}%",
                "κ vs pipeline": (f"{kappa:.3f}"
                                  if kappa is not None else "—"),
                "Interpretation": landis_koch(kappa),
            })
    emit(pd.DataFrame(rows).to_markdown(index=False))
    emit()

    # ---- Disagreement queue (for adjudication) ----
    if len(rater_ids) >= 2:
        emit("## Disagreement queue (for adjudication)")
        emit()
        a_id, b_id = rater_ids[0], rater_ids[1]  # only show first pair
        a_doc, b_doc = raters[a_id], raters[b_id]
        common = sorted(set(a_doc["ratings"]) & set(b_doc["ratings"]))
        disagreements = []
        for nct in common:
            for axis in AXES:
                la = a_doc["ratings"][nct]["labels"].get(axis)
                lb = b_doc["ratings"][nct]["labels"].get(axis)
                if la in NON_RATING_LABELS or lb in NON_RATING_LABELS:
                    continue
                if la != lb:
                    disagreements.append({
                        "NCTId": nct, "Axis": axis,
                        f"{a_id}": la, f"{b_id}": lb,
                    })
        emit(f"**{len(disagreements)} disagreed pairs** across all axes.")
        emit("Adjudicate these by joint review; the consensus label "
             "becomes the gold-standard ground truth.")
        emit()
        if disagreements:
            df_dis = pd.DataFrame(disagreements)
            emit(df_dis.head(30).to_markdown(index=False))
            if len(disagreements) > 30:
                emit(f"_… {len(disagreements) - 30} more rows omitted; "
                     f"see full disagreement CSV._")
            emit()
            # Also write a CSV next to the markdown report for adjudication
            out_dir = REPO_ROOT / "validation_study"
            (out_dir / "disagreements.csv").write_text(df_dis.to_csv(index=False))
            emit(f"Full disagreement set written to "
                 f"`{(out_dir / 'disagreements.csv').relative_to(REPO_ROOT)}`.")
            emit()

    if args.output:
        Path(args.output).write_text("\n".join(out_lines) + "\n")
        print(f"\n→ Report written to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
