"""Compute pipeline classification performance vs adjudicated gold standard.

After the κ analysis (`scripts/compute_validation_kappa.py`) identifies
disagreements, the moderator adjudicates them in the validation app's
admin tab → writes `validation_study/adjudicated_v1.json`. This script
takes that gold-standard file, plus the original sample (which carries
the pipeline labels under `_pipeline`), and reports per-axis pipeline
performance: precision, recall, F1, accuracy, weighted-by-support.

For trials where BOTH raters agreed (no adjudication needed), the
agreed-upon label IS the gold standard. For trials where they
disagreed, the adjudicated_v1.json entry IS the gold standard. For
trials where one rater marked Unsure, the other rater's label is the
gold standard if the moderator hasn't adjudicated.

This is the script that produces the "pipeline F1 = 0.XX" numbers for
the manuscript's Results section.

Usage (from repo root):
    python scripts/compute_pipeline_f1.py
    python scripts/compute_pipeline_f1.py --output pipeline_f1.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RESPONSES_DIR = REPO_ROOT / "validation_study" / "responses"
SAMPLE_PATH = REPO_ROOT / "validation_study" / "sample_v1.json"
ADJUDICATED_PATH = REPO_ROOT / "validation_study" / "adjudicated_v1.json"

AXES = ["Branch", "DiseaseCategory", "DiseaseEntity",
        "TargetCategory", "ProductType", "SponsorType"]

NON_RATING_LABELS = {"Unsure", "Skipped", "", None}


def _load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text())


def _load_adjudicated() -> dict:
    if not ADJUDICATED_PATH.exists():
        return {}
    return json.loads(ADJUDICATED_PATH.read_text())


def _load_raters() -> dict[str, dict]:
    raters = {}
    for path in sorted(RESPONSES_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        raters[doc.get("rater_id", path.stem)] = doc
    return raters


def _gold_label(
    nct: str,
    axis: str,
    rater_docs: dict[str, dict],
    adjudicated: dict,
) -> str | None:
    """Resolve the gold-standard label for one (NCT, axis):

    Resolution order (in priority):
      1. Explicit adjudication entry (overrides everything)
      2. Both raters agree on a non-Unsure label → that label
      3. Exactly one rater rated it (other Unsure or absent) → that label
      4. None scoreable → None
    """
    adj_key = f"{nct}::{axis}"
    if adj_key in adjudicated:
        return adjudicated[adj_key].get("gold_label")

    labels = []
    for rater_doc in rater_docs.values():
        l = rater_doc.get("ratings", {}).get(nct, {}).get("labels", {}).get(axis)
        if l not in NON_RATING_LABELS:
            labels.append(l)
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    # Two or more — must agree (else adjudication should exist; if not, skip)
    if all(l == labels[0] for l in labels):
        return labels[0]
    return None  # disagreement without adjudication — exclude from F1


def _per_axis_metrics(
    gold: list[str],
    pred: list[str],
) -> dict:
    """Per-axis precision, recall, F1, accuracy — macro and weighted.

    Implemented inline (no sklearn dep) using the standard confusion-
    matrix-based formulas.
    """
    if not gold or len(gold) != len(pred):
        return {"n": 0, "accuracy": None,
                "macro_f1": None, "weighted_f1": None}
    classes = sorted(set(gold) | set(pred))
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    for g, p in zip(gold, pred):
        if g == p:
            tp[g] += 1
        else:
            fp[p] += 1
            fn[g] += 1

    n = len(gold)
    correct = sum(1 for g, p in zip(gold, pred) if g == p)
    accuracy = correct / n

    per_class = {}
    for c in classes:
        prec = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) > 0 else 0.0
        rec  = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) > 0 else 0.0
        f1   = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class[c] = {"precision": prec, "recall": rec, "f1": f1,
                        "support": tp[c] + fn[c]}

    macro_f1 = float(np.mean([m["f1"] for m in per_class.values()]))
    total_support = sum(m["support"] for m in per_class.values())
    weighted_f1 = (
        sum(m["f1"] * m["support"] for m in per_class.values()) / total_support
        if total_support > 0 else 0.0
    )

    return {
        "n": n,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": per_class,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--output", default=None,
                   help="Optional markdown output file.")
    args = p.parse_args()

    sample = _load_sample()
    rater_docs = _load_raters()
    adjudicated = {k: v for k, v in _load_adjudicated().items() if k != "_meta"}

    if not rater_docs:
        print(f"No rater responses in {RESPONSES_DIR}.", file=sys.stderr)
        return 1

    # Build per-trial pipeline lookup
    pipeline_labels = {
        t["NCTId"]: (t.get("_pipeline") or {})
        for t in sample["trials"]
    }

    out_lines: list[str] = []
    def emit(s: str = "") -> None:
        out_lines.append(s)
        print(s)

    emit(f"# Pipeline classification performance vs gold standard")
    emit()
    emit(f"- **Sample:** v1 (sha256: `{sample['sha256']}`)")
    emit(f"- **Pipeline at sample-time:** `{sample.get('pipeline_sha', '?')[:12]}…`"
         f"{' (DIRTY worktree)' if sample.get('pipeline_dirty_worktree') else ''}")
    emit(f"- **Raters:** {', '.join(sorted(rater_docs))}")
    emit(f"- **Adjudicated entries:** {len(adjudicated)}")
    emit()
    emit("Gold-standard resolution: explicit adjudication > both-raters-agree > "
         "single-rater-scoreable > excluded.")
    emit()

    # ---- Per-axis F1 ----
    emit("## Per-axis pipeline performance")
    emit()
    rows = []
    per_axis_full = {}
    for axis in AXES:
        gold_list = []
        pred_list = []
        n_excluded = 0
        for nct in pipeline_labels:
            gold = _gold_label(nct, axis, rater_docs, adjudicated)
            if gold is None:
                n_excluded += 1
                continue
            pred = pipeline_labels[nct].get(axis)
            if pred is None or pred == "":
                n_excluded += 1
                continue
            gold_list.append(str(gold))
            pred_list.append(str(pred))
        m = _per_axis_metrics(gold_list, pred_list)
        per_axis_full[axis] = m
        rows.append({
            "Axis": axis,
            "N evaluable": m["n"],
            "Accuracy": (f"{m['accuracy']*100:.1f}%"
                         if m["accuracy"] is not None else "—"),
            "Macro F1": (f"{m['macro_f1']:.3f}"
                         if m["macro_f1"] is not None else "—"),
            "Weighted F1": (f"{m['weighted_f1']:.3f}"
                            if m["weighted_f1"] is not None else "—"),
            "Excluded": n_excluded,
        })
    emit(pd.DataFrame(rows).to_markdown(index=False))
    emit()

    # ---- Per-class breakdown for each axis ----
    for axis in AXES:
        m = per_axis_full[axis]
        if not m.get("per_class"):
            continue
        emit(f"### {axis} — per-class breakdown")
        emit()
        rows = [
            {
                "Class": c,
                "Support (gold)": v["support"],
                "Precision": f"{v['precision']:.3f}",
                "Recall": f"{v['recall']:.3f}",
                "F1": f"{v['f1']:.3f}",
            }
            for c, v in sorted(m["per_class"].items(),
                               key=lambda kv: -kv[1]["support"])
        ]
        emit(pd.DataFrame(rows).to_markdown(index=False))
        emit()

    if args.output:
        Path(args.output).write_text("\n".join(out_lines) + "\n")
        print(f"\n→ Report written to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
