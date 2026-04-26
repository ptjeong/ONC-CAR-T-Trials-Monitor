"""Generate the locked random sample for the inter-rater κ validation study.

This is a ONE-SHOT script. The output (`validation_study/sample.json`) is
committed to the repository before any rater starts work, with a sha256
hash recorded in the commit message — this is the pre-registration
analog for the validation study (the equivalent of registering a trial
on ClinicalTrials.gov before enrollment opens).

Re-running this script with the same seed + snapshot produces the
identical sample (deterministic). If a future revision of the study
needs a different sample (e.g. expanded to 500 trials, or stratified
differently), increment the `--version` arg → output goes to
`sample_v2.json` etc., never overwriting v1.

Stratification (locked design for v1):
    50% Heme-onc + 50% Solid-onc (excludes Mixed and Unknown).
    Within each branch, ensure ≥5 trials per major DiseaseCategory
    (defined as any category with ≥10 trials in the source snapshot).
    Trials with insufficient text for human classification (no
    BriefSummary, no Conditions, no Interventions) are filtered out
    before sampling.

Sample size (N=200) justification: powers detection of κ ≥ 0.4 vs null
κ=0.0 at α=0.05, β=0.2 even for 5–10-category axes, with ~10% margin
for items raters mark "Unsure" or skip. Standard for inter-rater
κ studies in clinical informatics literature (see Sim & Wright 2005
BMC Med Res Methodol).

Usage:
    python scripts/generate_validation_sample.py \\
        --snapshot 2026-04-24 --n 200 --seed 20260426 --version v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Make the repo importable regardless of where this script is invoked
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from pipeline import load_snapshot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "validation_study"


def _stratified_sample(
    df: pd.DataFrame,
    n_total: int,
    seed: int,
) -> pd.DataFrame:
    """Stratified sample: 50/50 heme/solid + ≥5 per major DiseaseCategory.

    Algorithm:
      1. Filter to Heme-onc / Solid-onc (drop Mixed, Unknown — too rare
         for clean κ at this N)
      2. Filter out trials with insufficient text (no rater can score them)
      3. Within each branch, identify "major" categories (≥10 trials)
      4. For each major category, take ceil(5) trials minimum (random)
      5. Top up each branch to its target (n_total/2) with random draws
         from the remaining branch pool
      6. Shuffle final concatenation so raters don't see all heme then all solid
    """
    rng = random.Random(seed)

    # ---- 1. Branch filter ----
    df = df[df["Branch"].isin(["Heme-onc", "Solid-onc"])].copy()

    # ---- 2. Minimum-evidence filter ----
    def _has_evidence(row) -> bool:
        bits = [str(row.get(c, "") or "") for c in
                ["BriefSummary", "Conditions", "Interventions"]]
        return any(len(b.strip()) >= 50 for b in bits)
    df = df[df.apply(_has_evidence, axis=1)].copy()

    n_per_branch = n_total // 2
    selected: list[str] = []

    for branch in ["Heme-onc", "Solid-onc"]:
        branch_df = df[df["Branch"] == branch]
        cat_counts = branch_df["DiseaseCategory"].value_counts()
        major_cats = cat_counts[cat_counts >= 10].index.tolist()

        per_branch_picked: set[str] = set()

        # ---- 3+4. Floor per major category ----
        for cat in major_cats:
            cat_pool = branch_df[branch_df["DiseaseCategory"] == cat]["NCTId"].tolist()
            k = min(5, len(cat_pool))
            picks = rng.sample(cat_pool, k)
            per_branch_picked.update(picks)

        # ---- 5. Top up to n_per_branch ----
        remaining_pool = [
            n for n in branch_df["NCTId"].tolist() if n not in per_branch_picked
        ]
        slots_left = n_per_branch - len(per_branch_picked)
        if slots_left > 0:
            top_up = rng.sample(remaining_pool, min(slots_left, len(remaining_pool)))
            per_branch_picked.update(top_up)

        selected.extend(per_branch_picked)

    # ---- 6. Shuffle ----
    rng.shuffle(selected)
    return df[df["NCTId"].isin(selected)].copy().set_index("NCTId").loc[selected].reset_index()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--snapshot", required=True,
                   help="Snapshot date (e.g. 2026-04-24).")
    p.add_argument("--n", type=int, default=200,
                   help="Total sample size. Default 200.")
    p.add_argument("--seed", type=int, default=20260426,
                   help="Random seed for reproducibility. Default 20260426.")
    p.add_argument("--version", default="v1",
                   help="Output suffix: validation_study/sample_<version>.json")
    args = p.parse_args()

    print(f"Loading snapshot {args.snapshot} …")
    df, _df_sites, _meta = load_snapshot(args.snapshot)
    print(f"  {len(df):,} trials in snapshot.")

    print(f"Sampling N={args.n} stratified (seed={args.seed}) …")
    sample_df = _stratified_sample(df, args.n, args.seed)
    print(f"  drew {len(sample_df)} trials.")

    # Build the manifest with the minimum trial info raters need
    # — no pipeline labels (those are deliberately hidden during rating)
    fields_for_raters = [
        "NCTId", "BriefTitle", "BriefSummary",
        "Conditions", "Interventions",
        "Phase", "OverallStatus", "LeadSponsor",
        "EnrollmentCount", "StartDate", "TrialDesign",
    ]
    manifest_trials = []
    for _, row in sample_df.iterrows():
        rec = {}
        for f in fields_for_raters:
            v = row.get(f)
            if pd.isna(v):
                rec[f] = None
            elif isinstance(v, (pd.Timestamp,)):
                rec[f] = v.isoformat()
            else:
                rec[f] = str(v) if not isinstance(v, (int, float, bool)) else v
        # Pipeline labels — kept in the manifest under a `_pipeline` key
        # so the analysis script can compute κ vs pipeline as a secondary
        # statistic. The rater UI MUST NOT display these.
        rec["_pipeline"] = {
            ax: (None if pd.isna(row.get(ax)) else str(row.get(ax)))
            for ax in ["Branch", "DiseaseCategory", "DiseaseEntity",
                       "TargetCategory", "ProductType", "SponsorType"]
        }
        manifest_trials.append(rec)

    # Stratification summary (audit trail)
    strat_summary = (
        sample_df.groupby(["Branch", "DiseaseCategory"])
        .size().reset_index(name="n").to_dict("records")
    )

    manifest = {
        "version": args.version,
        "n": len(manifest_trials),
        "n_requested": args.n,
        "snapshot_date": args.snapshot,
        "seed": args.seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stratification": "50% Heme-onc / 50% Solid-onc; ≥5 trials per "
                          "major DiseaseCategory (≥10 in source). Trials "
                          "with insufficient text (no Title/Summary/"
                          "Conditions/Interventions ≥50 chars) excluded.",
        "stratification_breakdown": strat_summary,
        "axes_to_rate": [
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "SponsorType",
        ],
        "trials": manifest_trials,
    }

    # Compute hash of the canonical (sorted-keys) JSON for pre-registration
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    manifest["sha256"] = sha

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"sample_{args.version}.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print()
    print(f"✓ Wrote {out_path}")
    print(f"  N = {manifest['n']}")
    print(f"  sha256 = {sha}")
    print()
    print("Stratification breakdown:")
    for row in strat_summary:
        print(f"  {row['Branch']:10s}  {row['DiseaseCategory']:30s}  N={row['n']}")
    print()
    print("→ Commit this file with the sha256 in the commit message; "
          "this is the pre-registration anchor for the κ study.")
    print(f"→ Then deploy validation_study/app.py and share the rater "
          f"URLs with PJ + the clinical collaborator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
