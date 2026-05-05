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

from pipeline import (  # noqa: E402
    load_snapshot,
    _assign_target_with_source,
    _assign_product_type,
    _sponsor_type,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "validation_study"


_CT_GOV_BASE = "https://clinicaltrials.gov/api/v2/studies"


def _fetch_ctgov_detail(nct_ids: list[str]) -> dict[str, dict]:
    """Fetch long-form fields from CT.gov v2 API for each NCT in the sample.

    Returns {nct_id: {DetailedDescription, EligibilityCriteria,
                       InterventionDescription, ArmGroupDescriptions,
                       CollaboratorNames, StudyType, Allocation,
                       InterventionModel, Masking, PrimaryCompletionDate,
                       CompletionDate, ResponsiblePartyType, ConditionsDetail}}

    Batches 100 NCTs per request via filter.ids. On any per-batch failure
    we continue (return what we have); on per-trial parse failure that
    trial silently gets an empty enrichment dict.

    Polite 0.25s pause between batches — same as backfill_site_geo.
    """
    import time as _time
    import requests as _req

    out: dict[str, dict] = {}
    BATCH = 100
    for i in range(0, len(nct_ids), BATCH):
        chunk = nct_ids[i: i + BATCH]
        params = {
            "filter.ids": ",".join(chunk),
            "pageSize": BATCH,
            "format": "json",
        }
        try:
            resp = _req.get(_CT_GOV_BASE, params=params, timeout=60)
            if resp.status_code != 200:
                print(f"  WARN batch {i // BATCH + 1}: HTTP "
                      f"{resp.status_code}; skipping {len(chunk)} trials")
                continue
            for s in resp.json().get("studies", []):
                ps = s.get("protocolSection", {})
                ident = ps.get("identificationModule", {})
                nct = ident.get("nctId")
                if not nct:
                    continue
                desc = ps.get("descriptionModule", {})
                elig = ps.get("eligibilityModule", {})
                arms = ps.get("armsInterventionsModule", {})
                spons = ps.get("sponsorCollaboratorsModule", {})
                design = ps.get("designModule", {})
                status = ps.get("statusModule", {})
                conds = ps.get("conditionsModule", {})

                # Pull intervention descriptions per arm
                interventions = arms.get("interventions") or []
                int_descs = []
                for iv in interventions:
                    name = iv.get("name") or ""
                    desc_text = iv.get("description") or ""
                    if desc_text:
                        int_descs.append(f"{name}: {desc_text}".strip())
                    elif name:
                        int_descs.append(name)

                arm_groups = arms.get("armGroups") or []
                arm_descs = []
                for ag in arm_groups:
                    label = ag.get("label") or ""
                    arm_type = ag.get("type") or ""
                    desc_text = ag.get("description") or ""
                    bits = " · ".join(b for b in [
                        label, arm_type, desc_text
                    ] if b)
                    if bits:
                        arm_descs.append(bits)

                collaborators = [
                    c.get("name", "") for c in (spons.get("collaborators") or [])
                ]
                resp_party = spons.get("responsibleParty") or {}

                out[nct] = {
                    "DetailedDescription": desc.get("detailedDescription") or "",
                    "EligibilityCriteria": elig.get("eligibilityCriteria") or "",
                    "InterventionDescription": "\n\n".join(int_descs),
                    "ArmGroupDescriptions": "\n\n".join(arm_descs),
                    "CollaboratorNames": "; ".join(collaborators),
                    "ResponsiblePartyType": resp_party.get("type") or "",
                    "ResponsiblePartyName": resp_party.get(
                        "investigatorFullName"
                    ) or resp_party.get("oldNameTitle") or "",
                    "StudyType": design.get("studyType") or "",
                    "Allocation": (
                        design.get("designInfo", {}).get("allocation") or ""
                    ),
                    "InterventionModel": (
                        design.get("designInfo", {}).get("interventionModel")
                        or ""
                    ),
                    "Masking": (
                        design.get("designInfo", {})
                        .get("maskingInfo", {})
                        .get("masking") or ""
                    ),
                    "PrimaryCompletionDate": (
                        status.get("primaryCompletionDateStruct", {})
                        .get("date") or ""
                    ),
                    "CompletionDate": (
                        status.get("completionDateStruct", {}).get("date") or ""
                    ),
                    "ConditionKeywords": "; ".join(conds.get("keywords") or []),
                }
        except Exception as _e:
            print(f"  WARN batch {i // BATCH + 1} failed: {_e}")
            continue
        _time.sleep(0.25)
    return out


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

    # ---- Refresh classifier-derived labels in-memory ----
    # `load_snapshot` reads the pre-computed labels from the snapshot CSV,
    # which was built when the snapshot was originally captured. If
    # `config.py` (target term-lists, ligand aliases) or
    # `llm_overrides.json` has changed since, those updates are stale on
    # disk. Re-run the per-row classifier here so the manifest reflects
    # the current pipeline rules without touching the on-disk snapshot.
    # Cheap (~200 trials × O(1) regex per axis); avoids a full re-fetch.
    print("  re-applying classifier (TargetCategory, ProductType, SponsorType) "
          "with current config + overrides …")
    target_results = df.apply(
        lambda r: _assign_target_with_source(r.to_dict()), axis=1
    )
    df["TargetCategory"] = target_results.apply(lambda t: t[0])
    product_results = df.apply(
        lambda r: _assign_product_type(r.to_dict()), axis=1
    )
    df["ProductType"] = product_results.apply(lambda t: t[0])
    df["SponsorType"] = df.apply(lambda r: _sponsor_type(r.to_dict()), axis=1)

    print(f"Sampling N={args.n} stratified (seed={args.seed}) …")
    sample_df = _stratified_sample(df, args.n, args.seed)
    print(f"  drew {len(sample_df)} trials.")

    # ---- Live CT.gov enrichment ----
    # The snapshot's trials.csv has the high-frequency fields (Title,
    # BriefSummary, Conditions, Interventions, Phase, etc.) but is
    # deliberately compact. Raters benefit from the longer-form CT.gov
    # fields (DetailedDescription, EligibilityCriteria, InterventionDescription,
    # CollaboratorNames) that aren't worth carrying in every snapshot
    # but ARE worth baking into the locked validation sample for
    # one-time per-trial enrichment.
    #
    # We fetch from CT.gov ONCE during sample generation, then store
    # the enriched fields in the manifest. This preserves reproducibility
    # (sample sha256 captures what raters see) without bloating the
    # daily snapshot.
    print(f"Enriching {len(sample_df)} sample trials with live CT.gov data …")
    enriched = _fetch_ctgov_detail(sample_df["NCTId"].tolist())
    print(f"  enriched {len(enriched)}/{len(sample_df)} trials.")

    # Build the manifest with everything raters need to make a confident call
    # — no pipeline labels (those are deliberately hidden during rating)
    fields_for_raters = [
        "NCTId", "BriefTitle", "BriefSummary",
        "Conditions", "Interventions",
        "Phase", "OverallStatus", "LeadSponsor", "LeadSponsorClass",
        "EnrollmentCount", "StartDate", "TrialDesign",
        "PrimaryEndpoints", "Countries",
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
        # Live CT.gov enrichment — long-form fields
        rec.update(enriched.get(row["NCTId"], {}))
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

    # Provenance: pin the exact pipeline state at sample-generation time
    # so the analysis can claim "we compared against pipeline @ <sha>"
    # in the manuscript's methods section. Without this, a pipeline
    # change mid-study could silently shift the secondary-outcome
    # (rater-vs-pipeline) numbers and require re-running everything.
    import subprocess as _sp
    try:
        pipeline_sha = _sp.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT), text=True, stderr=_sp.DEVNULL,
        ).strip()
    except Exception:
        pipeline_sha = "unknown"
    try:
        pipeline_dirty = bool(_sp.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT), text=True, stderr=_sp.DEVNULL,
        ).strip())
    except Exception:
        pipeline_dirty = False

    # Autocomplete vocabularies — surface the canonical entity + antigen
    # lists in the manifest so the rater UI can offer them as quick-pick
    # suggestions while still allowing free text. Cuts typing time and
    # standardizes spelling so κ doesn't get artificially deflated by
    # "DLBCL" vs "Diffuse large B-cell lymphoma".
    try:
        from config import (
            HEME_TARGET_TERMS, SOLID_TARGET_TERMS, ENTITY_TERMS,
            DUAL_TARGET_LABELS,
        )
        # Target vocab = single antigens (heme + solid) ∪ dual-target
        # labels (CD19/CD22 dual, CD19/BCMA dual, BCMA/GPRC5D dual, etc.)
        # Dual labels were missing pre-2026-04-27 — raters had to type
        # them as free text, which broke κ comparison vs pipeline
        # because the pipeline emits exact strings ("BCMA/GPRC5D dual")
        # that raters couldn't easily reproduce.
        dual_labels = [label for (_pair, label) in DUAL_TARGET_LABELS]
        autocomplete_vocab = {
            "DiseaseEntity": sorted(ENTITY_TERMS.keys()),
            "TargetCategory": sorted(
                set(HEME_TARGET_TERMS) | set(SOLID_TARGET_TERMS)
                | set(dual_labels)
            ),
        }
    except Exception:
        autocomplete_vocab = {"DiseaseEntity": [], "TargetCategory": []}

    manifest = {
        "version": args.version,
        "n": len(manifest_trials),
        "n_requested": args.n,
        "snapshot_date": args.snapshot,
        "seed": args.seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_sha": pipeline_sha,
        "pipeline_dirty_worktree": pipeline_dirty,
        "stratification": "50% Heme-onc / 50% Solid-onc; ≥5 trials per "
                          "major DiseaseCategory (≥10 in source). Trials "
                          "with insufficient text (no Title/Summary/"
                          "Conditions/Interventions ≥50 chars) excluded.",
        "stratification_breakdown": strat_summary,
        "axes_to_rate": [
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "SponsorType",
        ],
        "autocomplete_vocab": autocomplete_vocab,
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
