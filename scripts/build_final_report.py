"""Build the publication-grade final report for the validation study.

Single command that runs after both raters submit + you've adjudicated
the disagreements in the validation app's admin tab. Produces:

    validation_study/final_report.md

A self-contained markdown document with everything the manuscript
needs from the validation study:

  1. Sample provenance + pre-registration claims
  2. Methodology paragraph (paste-ready into Methods section)
  3. Inter-rater κ table with 95% bootstrap CI per axis (PRIMARY)
  4. Pipeline-vs-gold-standard F1 per axis (PRIMARY for pipeline perf)
  5. Per-class precision/recall/F1 breakdowns
  6. Confusion matrices per axis × rater pair
  7. Per-rater operational stats (time, skip rate)
  8. Adjudication summary (% disagreed, time spent)
  9. Limitations + caveats (auto-flagged from data)

Usage:
    python scripts/build_final_report.py
    python scripts/build_final_report.py --bootstrap 10000

Idempotent — re-runs produce identical output (modulo the bootstrap
seed). The output file is committed to the repo as the canonical
record of the κ study results.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESPONSES_DIR = REPO_ROOT / "validation_study" / "responses"
SAMPLE_PATH = REPO_ROOT / "validation_study" / "sample_v1.json"
ADJUDICATED_PATH = REPO_ROOT / "validation_study" / "adjudicated_v1.json"
FINAL_REPORT_PATH = REPO_ROOT / "validation_study" / "final_report.md"

KAPPA_SCRIPT = REPO_ROOT / "scripts" / "compute_validation_kappa.py"
F1_SCRIPT = REPO_ROOT / "scripts" / "compute_pipeline_f1.py"


def _run_subreport(script: Path, *, bootstrap: int | None = None) -> str:
    """Run a subreport script and capture its stdout."""
    cmd = [sys.executable, str(script)]
    if bootstrap is not None:
        cmd += ["--bootstrap", str(bootstrap)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return f"```\nERROR: {script.name} returned {out.returncode}\n{out.stderr}\n```"
    return out.stdout


def _load_or_empty(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _check_readiness() -> tuple[bool, list[str]]:
    """Sanity checks before producing the final report. Returns
    (is_ready, list_of_warnings)."""
    warnings: list[str] = []

    if not SAMPLE_PATH.exists():
        return False, ["sample_v1.json missing — generate it first."]

    rater_files = list(RESPONSES_DIR.glob("*.json"))
    if len(rater_files) < 2:
        warnings.append(f"Only {len(rater_files)} committed rater file(s) "
                        "— inter-rater κ requires ≥2.")

    sample = _load_or_empty(SAMPLE_PATH)
    n_target = sample.get("n", 0)
    for rp in rater_files:
        doc = _load_or_empty(rp)
        n_done = len(doc.get("ratings", {}))
        if n_done < n_target:
            warnings.append(f"Rater `{doc.get('rater_id', rp.stem)}` only "
                            f"completed {n_done}/{n_target} trials.")

    if not ADJUDICATED_PATH.exists():
        warnings.append(
            "No adjudicated_v1.json — pipeline F1 will use only trials "
            "where raters already agreed (reduced N for that analysis)."
        )

    return True, warnings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bootstrap", type=int, default=10_000,
                   help="Bootstrap resamples for κ CI. Default 10,000.")
    p.add_argument("--output", type=str, default=str(FINAL_REPORT_PATH),
                   help=f"Output path. Default {FINAL_REPORT_PATH.relative_to(REPO_ROOT)}")
    args = p.parse_args()

    print("Checking readiness …")
    ready, warnings = _check_readiness()
    if not ready:
        print(f"NOT READY: {warnings[0]}", file=sys.stderr)
        return 1
    if warnings:
        print()
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)
        print()

    sample = _load_or_empty(SAMPLE_PATH)
    adjudicated = _load_or_empty(ADJUDICATED_PATH)
    n_adj_entries = sum(1 for k in adjudicated if k != "_meta")

    print("Running κ analysis …")
    kappa_md = _run_subreport(KAPPA_SCRIPT, bootstrap=args.bootstrap)

    print("Running pipeline-F1 analysis …")
    f1_md = _run_subreport(F1_SCRIPT)

    # -------------- Compose final report --------------
    now = datetime.now(timezone.utc).isoformat()
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    ).stdout.strip() or "unknown"

    report = f"""# Inter-rater κ validation study — final report

_Generated {now}_ · _build_final_report.py @ `{git_sha[:12]}`_

---

## 1. Sample provenance

- **Sample version:** {sample.get("version", "?")}
- **N:** {sample.get("n", "?")} trials
- **sha256:** `{sample.get("sha256", "?")}`
- **Snapshot date:** {sample.get("snapshot_date", "?")}
- **Pipeline at sample time:** `{sample.get("pipeline_sha", "?")[:12]}…`
  {"(DIRTY worktree at sample time — flag in methods)" if sample.get("pipeline_dirty_worktree") else ""}
- **Stratification:** {sample.get("stratification", "—")}
- **Random seed:** {sample.get("seed", "—")}

## 2. Methodology paragraph (paste into manuscript)

> Inter-rater reliability of the automated trial classification was assessed
> on a pre-registered random sample of {sample.get("n", "?")} trials
> (sample manifest sha256: `{sample.get("sha256", "?")[:16]}…`) drawn from
> the {sample.get("snapshot_date", "?")} ClinicalTrials.gov snapshot using
> seed {sample.get("seed", "?")}. The sample was stratified by primary
> indication branch (50% hematologic, 50% solid) and disease category
> (≥5 trials per major category, defined as ≥10 trials in the source
> snapshot). Trials with insufficient text (no title, summary, conditions,
> or interventions ≥50 characters) were excluded prior to sampling.
>
> Two independent raters classified each trial on six axes (Branch,
> DiseaseCategory, DiseaseEntity, TargetCategory, ProductType,
> SponsorType) using a custom Streamlit interface that displayed only
> the trial's title, brief summary, conditions, interventions, phase,
> lead sponsor, and trial design. Pipeline-generated labels were not
> visible to raters during classification, and raters were blinded to
> each other's classifications. Each axis offered "Unsure" as a
> first-class option to avoid forced guessing. Raters used dropdown
> autocompletion populated from the canonical antigen and disease-entity
> vocabularies (with free-text fallback) to standardize spelling.
>
> Cohen's κ was computed per axis between raters with 95% confidence
> intervals from {args.bootstrap:,} bootstrap resamples. Pairwise
> agreement with the pipeline was reported as a secondary statistic.
> Disagreements ({n_adj_entries} of N pairs) were resolved in an
> adjudication round using a custom in-app moderator interface; the
> resulting consensus labels served as the gold standard against which
> per-axis pipeline F1 was reported.

## 3. Inter-rater κ analysis

{kappa_md}

## 4. Pipeline performance vs gold standard

{f1_md}

## 5. Limitations / caveats

"""

    # Auto-flagged limitations from the data
    limitations: list[str] = []
    rater_docs = {}
    for rp in RESPONSES_DIR.glob("*.json"):
        try:
            doc = json.loads(rp.read_text())
            rater_docs[doc.get("rater_id", rp.stem)] = doc
        except Exception:
            continue

    if len(rater_docs) < 2:
        limitations.append(
            "**Single-rater study** — inter-rater κ not reportable. "
            "Recruit a second rater to enable the headline statistic."
        )

    n_target = sample.get("n", 0)
    for rid, doc in rater_docs.items():
        n_done = len(doc.get("ratings", {}))
        n_skip = sum(1 for r in doc["ratings"].values() if r.get("skipped"))
        if n_done < n_target:
            limitations.append(
                f"Rater `{rid}` completed {n_done}/{n_target} trials "
                f"({100 * n_done / n_target:.0f}%); incomplete sample limits "
                "statistical power for that rater's pairwise κ."
            )
        if n_skip / max(n_done, 1) > 0.05:
            limitations.append(
                f"Rater `{rid}` skipped {n_skip} of {n_done} trials "
                f"({100 * n_skip / n_done:.1f}%); high skip rate may indicate "
                "ambiguous trials and warrants discussion."
            )

    if not adjudicated:
        limitations.append(
            "**No adjudication round completed** — pipeline F1 was computed "
            "only on trials where both raters spontaneously agreed. The "
            "Methods section should state this; ideally complete "
            "adjudication via the validation app's admin tab before "
            "manuscript submission."
        )

    if sample.get("pipeline_dirty_worktree"):
        limitations.append(
            "Sample was generated with an uncommitted-changes worktree "
            "(pipeline_dirty_worktree = true). Pipeline labels in this "
            "report may not match any committed pipeline state. Re-generate "
            "the sample on a clean tree before submission."
        )

    if not limitations:
        limitations.append("None auto-detected. Review the per-axis "
                            "tables for low-N or low-κ axes.")

    for lim in limitations:
        report += f"- {lim}\n"

    report += f"""
## 6. Reproducibility

This report is reproducible by:
1. Checking out commit `{git_sha[:12]}` of the repo
2. Restoring `{SAMPLE_PATH.relative_to(REPO_ROOT)}` (sha256 `{sample.get('sha256', '?')[:16]}…`)
3. Restoring `{RESPONSES_DIR.relative_to(REPO_ROOT)}/*.json` (rater submissions)
4. Restoring `{ADJUDICATED_PATH.relative_to(REPO_ROOT)}` (gold standard)
5. Running `python3 scripts/build_final_report.py --bootstrap {args.bootstrap}`

Bootstrap CIs are seeded (seed=20260426) so re-runs produce identical numbers.

---

_End of report._
"""

    out_path = Path(args.output)
    out_path.write_text(report)
    print(f"\n✓ Final report written to {out_path}")
    print(f"  ({len(report.splitlines())} lines, {len(report):,} chars)")
    print()
    print("Next steps:")
    print("  1. git add validation_study/final_report.md")
    print("  2. git commit -m 'Validation study final report (κ + pipeline F1)'")
    print("  3. git push")
    print("  4. Drop the relevant sections into the manuscript")
    return 0


if __name__ == "__main__":
    sys.exit(main())
