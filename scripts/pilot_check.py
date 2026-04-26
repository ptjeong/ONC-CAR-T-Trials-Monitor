"""Pilot-check script — assess pipeline quality from a small rater sample
BEFORE rolling out the full N=200 inter-rater κ study.

Use case: PJ rates ~20-30 trials on the validation app first, runs this
script, and gets a GREEN / YELLOW / RED decision on whether to invite
Rater B for the full study. Saves Rater B's time if the classifier
turns out to need fixing first.

Decision thresholds (Landis & Koch 1977):
    GREEN    macro F1 ≥ 0.75 on every axis    →  invite Rater B
    YELLOW   macro F1 ≥ 0.60 on every axis,
             but at least one axis below 0.75 →  investigate, decide
    RED      any axis macro F1 < 0.60         →  fix classifier first

The 25 ratings are NOT thrown away — they become part of the full
study's first rater file. Pilot = checkpoint, not a separate study.

Usage (from repo root):
    python3 scripts/pilot_check.py
    python3 scripts/pilot_check.py --rater peter   # if multiple files committed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the κ + F1 helpers from the main analysis scripts so the same
# math runs in pilot mode that runs in the final report.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute_validation_kappa import cohens_kappa, NON_RATING_LABELS, AXES  # noqa: E402
from compute_pipeline_f1 import _per_axis_metrics  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RESPONSES_DIR = REPO_ROOT / "validation_study" / "responses"
SAMPLE_PATH = REPO_ROOT / "validation_study" / "sample_v1.json"


def _decision(metrics_per_axis: dict) -> tuple[str, list[str]]:
    """Returns (color, reasons)."""
    f1s = {a: m["macro_f1"] for a, m in metrics_per_axis.items()
           if m["macro_f1"] is not None}
    if not f1s:
        return "RED", ["No axis had enough data to compute F1."]

    min_f1 = min(f1s.values())
    weak = [a for a, f in f1s.items() if f < 0.60]
    yellow = [a for a, f in f1s.items() if 0.60 <= f < 0.75]

    if weak:
        return "RED", [
            f"Axis `{a}` macro F1 = {f1s[a]:.3f} (< 0.60 = below "
            "Landis-Koch substantial agreement)" for a in weak
        ]
    if yellow:
        return "YELLOW", [
            f"Axis `{a}` macro F1 = {f1s[a]:.3f} (between 0.60 and 0.75 — "
            "substantial but not strong)" for a in yellow
        ]
    return "GREEN", [f"All axes ≥ 0.75 (min: {min_f1:.3f})"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rater", default=None,
                   help="Rater ID to use (default: pick the most-rated file)")
    p.add_argument("--min-n", type=int, default=15,
                   help="Minimum N before reporting (default 15)")
    args = p.parse_args()

    if not SAMPLE_PATH.exists():
        print(f"sample_v1.json missing: {SAMPLE_PATH}", file=sys.stderr)
        return 1

    sample = json.loads(SAMPLE_PATH.read_text())
    pipeline_lookup = {
        t["NCTId"]: (t.get("_pipeline") or {})
        for t in sample["trials"]
    }

    rater_files = sorted(RESPONSES_DIR.glob("*.json"))
    if not rater_files:
        # Also check the local /tmp backup since the rater may not have
        # committed their pilot ratings yet.
        tmp_files = sorted(Path("/tmp/validation_responses").glob("*.json"))
        if tmp_files:
            print(f"NOTE: no committed responses, using /tmp backup: "
                  f"{tmp_files[0]}", file=sys.stderr)
            rater_files = tmp_files
    if not rater_files:
        print("No rater responses found. Rate at least "
              f"{args.min_n} trials in the validation app first, then "
              "re-run this script.", file=sys.stderr)
        return 1

    # Pick the rater
    if args.rater:
        match = [f for f in rater_files if args.rater in f.stem]
        if not match:
            print(f"No file matching `{args.rater}` in {rater_files}",
                  file=sys.stderr)
            return 1
        rater_file = match[0]
    else:
        # Pick the file with the most ratings
        rater_file = max(rater_files,
                          key=lambda p: len(
                              json.loads(p.read_text()).get("ratings", {})
                          ))

    doc = json.loads(rater_file.read_text())
    rater_id = doc.get("rater_id", rater_file.stem)
    n_done = len(doc.get("ratings", {}))
    n_skipped = sum(1 for r in doc["ratings"].values() if r.get("skipped"))
    n_scoreable = n_done - n_skipped

    print(f"Pilot check — rater: {rater_id}")
    print(f"  ratings: {n_done} ({n_skipped} skipped, {n_scoreable} scoreable)")
    print()

    if n_scoreable < args.min_n:
        print(f"Need at least {args.min_n} non-skipped ratings to pilot. "
              f"Have {n_scoreable}. Rate more trials and re-run.",
              file=sys.stderr)
        return 1

    # Per-axis pipeline-vs-rater
    print(f"{'Axis':<20} {'N':>5} {'Acc':>8} {'Macro F1':>10} {'κ':>8}  Decision")
    print("-" * 70)
    metrics_per_axis: dict[str, dict] = {}
    for axis in AXES:
        gold, pred = [], []
        for nct, rec in doc["ratings"].items():
            if rec.get("skipped"):
                continue
            r_label = rec.get("labels", {}).get(axis)
            if r_label in NON_RATING_LABELS:
                continue
            p_label = pipeline_lookup.get(nct, {}).get(axis)
            if not p_label:
                continue
            gold.append(str(r_label))
            pred.append(str(p_label))

        if len(gold) < 5:
            metrics_per_axis[axis] = {"n": len(gold), "macro_f1": None,
                                       "accuracy": None}
            print(f"{axis:<20} {len(gold):>5}  {'—':>7}  {'—':>9}  {'—':>7}  "
                  f"too few")
            continue

        m = _per_axis_metrics(gold, pred)
        kappa = cohens_kappa(gold, pred)
        metrics_per_axis[axis] = m
        print(f"{axis:<20} {m['n']:>5} "
              f"{m['accuracy']*100:>6.1f}%  {m['macro_f1']:>9.3f} "
              f"{kappa:>8.3f}" if kappa is not None
              else f"{axis:<20} {m['n']:>5} {m['accuracy']*100:>6.1f}%  "
                   f"{m['macro_f1']:>9.3f}    —")

    print()
    print("=" * 70)
    color, reasons = _decision(metrics_per_axis)
    color_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[color]
    action = {
        "GREEN": "PROCEED — invite Rater B for the full N=200 study.",
        "YELLOW": "INVESTIGATE — review confusion matrices for weak axes; "
                  "decide whether to fix or proceed.",
        "RED": "STOP — fix the classifier on the weak axes before "
               "burning Rater B's time. Re-pilot after fixes.",
    }[color]
    print(f"{color_emoji}  Decision: {color}")
    print(f"   {action}")
    for r in reasons:
        print(f"   - {r}")
    print()

    # On YELLOW or RED, dump the disagreements to help debugging
    if color in {"YELLOW", "RED"}:
        print("Disagreements (rater vs pipeline) on weak axes:")
        for axis in AXES:
            m = metrics_per_axis.get(axis, {})
            if m.get("macro_f1") is None or m["macro_f1"] >= 0.75:
                continue
            print(f"\n  {axis}:")
            for nct, rec in doc["ratings"].items():
                if rec.get("skipped"):
                    continue
                r_label = rec.get("labels", {}).get(axis)
                if r_label in NON_RATING_LABELS:
                    continue
                p_label = pipeline_lookup.get(nct, {}).get(axis)
                if str(r_label) != str(p_label):
                    print(f"    {nct}: rater={r_label!r} vs pipeline={p_label!r}")

    print()
    print(f"Pilot ratings are preserved in {rater_file}; they count toward "
          "the full study (no rework).")
    return {"GREEN": 0, "YELLOW": 2, "RED": 1}[color]


if __name__ == "__main__":
    sys.exit(main())
