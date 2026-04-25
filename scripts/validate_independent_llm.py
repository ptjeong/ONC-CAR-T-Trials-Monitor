"""Independent-LLM cross-validation of pipeline classifications.

Samples N trials from the latest snapshot, asks an LLM from a *different*
provider family to re-classify them from scratch (Branch / DiseaseCategory /
TargetCategory / ProductType), and compares to the pipeline's labels. Outputs
per-axis Cohen's κ + a list of disagreement clusters.

Why a *different* provider: validate.py / the curation loop already use
Claude Opus, so Claude-vs-Claude agreement bias is built in. Hitting a second
family (OpenAI / Gemini, or a Claude model that wasn't used for curation)
gives a meaningfully independent second opinion.

Provider auto-detection (in priority order):
    GEMINI_API_KEY   → gemini-2.5-flash-lite  ← RECOMMENDED (current free tier)
    OPENAI_API_KEY   → gpt-4o
    GROQ_API_KEY     → llama-3.3-70b-versatile (free tier, ~30 req/min)
    ANTHROPIC_API_KEY → claude-haiku-4-5      (same vendor — lower independence)

Note on Gemini free tier: Google has progressively restricted which models
are available without billing. As of 2026, gemini-2.5-flash-lite is the
permissive free-tier default (15 RPM / 1000 RPD); gemini-2.5-flash and
gemini-2.0-flash often require billing for new keys. Pass --model to
override if your account has access to a different one.

Free API keys for genuinely-cross-vendor validation:
  - Gemini: https://aistudio.google.com/apikey  (1,500 req/day free)
  - Groq:   https://console.groq.com             (free tier, fast)

Usage:
    export GEMINI_API_KEY=...
    pip install google-genai            # NOTE: new package, not "google-generativeai"
    python scripts/validate_independent_llm.py                  # n=100 default
    python scripts/validate_independent_llm.py --n 200 --seed 7
    python scripts/validate_independent_llm.py --provider groq
    python scripts/validate_independent_llm.py --out reports/independent_$(date +%F).md
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import (  # noqa: E402
    list_snapshots, load_snapshot,
    _classify_disease, _assign_target, _assign_product_type,
)
from config import (  # noqa: E402
    HEME_CATEGORIES, SOLID_CATEGORIES,
    BASKET_MULTI_LABEL, HEME_BASKET_LABEL, SOLID_BASKET_LABEL,
    UNCLASSIFIED_LABEL,
)


def _live_pipeline_labels(row: dict) -> dict:
    """Re-classify a snapshot row through the LIVE pipeline.

    Snapshot CSVs freeze the classifier output as of the day they were saved.
    Without re-running the classifier here, validation would compare the LLM
    against stale labels — a classifier fix wouldn't move agreement metrics
    until a fresh snapshot is taken. Re-classifying inline means the script
    always validates current code.
    """
    disease = _classify_disease(row)
    target = _assign_target(row)
    ptype, _ = _assign_product_type(row)
    return {
        "Branch":          disease["branch"],
        "DiseaseCategory": disease["category"],
        "TargetCategory":  target,
        "ProductType":     ptype,
    }

AXES = ["Branch", "DiseaseCategory", "TargetCategory", "ProductType"]

ALLOWED_VALUES = {
    "Branch": ["Heme-onc", "Solid-onc", "Mixed", "Unknown"],
    "ProductType": [
        "Autologous", "Allogeneic/Off-the-shelf", "In vivo", "Unclear",
    ],
    # Closed list of pipeline categories — keeps the LLM from inventing its
    # own vocabulary ("Lymphoma" vs "B-NHL", "Leukemia" vs "B-ALL"), which
    # would tank the agreement metric without reflecting any real classifier
    # disagreement.
    "DiseaseCategory": (
        sorted(HEME_CATEGORIES | SOLID_CATEGORIES)
        + [HEME_BASKET_LABEL, SOLID_BASKET_LABEL, BASKET_MULTI_LABEL,
           UNCLASSIFIED_LABEL]
    ),
}

PROMPT = """You are an independent reviewer of a CAR-T clinical-trial classifier.

For the trial below, return a JSON object with these keys (no prose, no
markdown fences):
  branch:           EXACTLY one of: {branches}
  disease_category: EXACTLY one of: {categories}
                    (use the exact label spelling — do not invent variants)
  target_category:  the antigen/construct, using the protein name (NOT the
                    gene symbol) — e.g. "Mesothelin" not "MSLN"; "GPC3" not
                    "Glypican-3"; "Claudin 18.2" not "CLDN18.2". Other
                    examples: "CD19", "BCMA", "B7-H3", "CD19/CD22 dual",
                    "CAR-NK: CD19", "Other_or_unknown".
  product_type:     EXACTLY one of: {product_types}

Be conservative — if the trial text doesn't clearly support a label, use
"Unclassified" / "Unclear" / "Other_or_unknown" rather than guess.

Trial:
  NCT ID:        {nct}
  Brief title:   {title}
  Conditions:    {conditions}
  Interventions: {interventions}
  Brief summary: {summary}
"""


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

_DEFAULT_MODELS = {
    "gemini":    "gemini-2.5-flash-lite",
    "openai":    "gpt-4o-2024-11-20",
    "groq":      "llama-3.3-70b-versatile",
    "anthropic": "claude-haiku-4-5-20251001",
}
_PROVIDER_ENV = {
    "gemini":    "GEMINI_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "groq":      "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
# Per-provider safe-default RPM. Each call to a given provider waits
# 60/_PROVIDER_RPM[provider] seconds since that provider's last call.
# Conservative — set ~80% of the documented free-tier RPM ceiling so a
# minor clock skew doesn't trigger a 429. User can override globally with
# --rpm (which becomes the cap for every provider).
#
# Free-tier ceilings (verify against the live dashboards — these change):
#   Gemini 2.5 Flash Lite: 15 RPM / 1000 RPD  (https://ai.google.dev/pricing)
#   Groq llama-3.3-70b:    30 RPM / 1000 RPD  (https://console.groq.com/settings/limits)
#   OpenAI gpt-4o:         500 RPM (paid)     (https://platform.openai.com/docs/guides/rate-limits)
#   Anthropic Haiku:       50 RPM (paid)
_PROVIDER_RPM = {
    "gemini":    12,    # 80% of 15 RPM free-tier ceiling
    "groq":      25,    # 80% of 30 RPM free-tier ceiling
    "openai":    60,    # comfortable for paid tier
    "anthropic": 30,    # comfortable for paid tier
}


def _detect_reviewers(forced: list[str] | None) -> list[tuple[str, str]]:
    """Return list of (provider, model) reviewer pairs.

    With multiple reviewers, the report adds a 'consensus disagreement'
    section: trials where ALL reviewers agree on a label but the pipeline
    disagrees — the highest-signal bucket because it can't be a single LLM
    quirk. Two-LLM agreement is much harder to dismiss than one.

    Anthropic stays last (same vendor as validate.py — lowest independence).
    """
    available = []
    for provider in ("gemini", "openai", "groq", "anthropic"):
        if forced and provider not in forced:
            continue
        if os.getenv(_PROVIDER_ENV[provider]):
            available.append((provider, _DEFAULT_MODELS[provider]))
    if not available:
        raise SystemExit(
            "No LLM API key found. Set one or more of:\n"
            "  GEMINI_API_KEY (free at https://aistudio.google.com/apikey)\n"
            "  OPENAI_API_KEY\n"
            "  GROQ_API_KEY (free at https://console.groq.com)\n"
            "  ANTHROPIC_API_KEY (same vendor — lowest independence)\n"
            "Or pass --providers explicitly."
        )
    return available


def _call_llm(provider: str, model: str, prompt: str) -> dict:
    """Provider-agnostic LLM call returning the parsed JSON dict.
    Raises on transport / parsing errors so the caller can decide retry policy."""
    if provider == "openai":
        from openai import OpenAI  # type: ignore
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)
    if provider == "gemini":
        # New SDK (`google-genai`) — the old `google-generativeai` is deprecated
        # and its model registry no longer resolves modern Gemini IDs.
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(resp.text)
    if provider == "anthropic":
        from anthropic import Anthropic  # type: ignore
        client = Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=512,
            temperature=0,
            messages=[{"role": "user", "content": prompt + "\n\nReturn only the JSON object."}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        return json.loads(text)
    if provider == "groq":
        from groq import Groq  # type: ignore
        client = Groq()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return json.loads(resp.choices[0].message.content)
    raise ValueError(f"Unknown provider: {provider}")


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _stratified_sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Sample n trials, stratified by Branch × DiseaseCategory so the cohort
    represents the dataset's heterogeneity rather than the modal class.

    Two-pass: (1) take ⌈n/strata⌉ per stratum so every stratum is represented,
    then (2) top up randomly from the remaining pool until we hit n. The
    earlier single-pass version capped output at one-per-stratum when n was
    smaller than the stratum count (e.g., asking for n=50 returned 27 rows
    when there were 27 strata).
    """
    rng = random.Random(seed)
    strata = list(df.groupby(["Branch", "DiseaseCategory"], observed=True))
    per_stratum = max(1, -(-n // max(len(strata), 1)))  # ceiling division
    picked = set()
    for _, grp in strata:
        idxs = grp.index.tolist()
        k = min(per_stratum, len(idxs))
        picked.update(rng.sample(idxs, k))
    if len(picked) > n:
        picked = set(rng.sample(list(picked), n))
    elif len(picked) < n:
        # Top up from the unpicked remainder so we actually hit n.
        remainder = [i for i in df.index if i not in picked]
        rng.shuffle(remainder)
        picked.update(remainder[: (n - len(picked))])
    return df.loc[list(picked)].copy()


# ---------------------------------------------------------------------------
# Comparison metrics
# ---------------------------------------------------------------------------

def _norm(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip().lower()


def _cohen_kappa(a: list, b: list) -> float:
    if not a:
        return float("nan")
    n = len(a)
    p_o = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    labels = set(ca) | set(cb)
    p_e = sum((ca[k] / n) * (cb[k] / n) for k in labels)
    if p_e >= 1.0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=100, help="Sample size (default 100)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--providers", help="Comma-separated provider list "
                    "(default = use every provider whose API key is set). "
                    "Choices: gemini, openai, groq, anthropic")
    ap.add_argument("--model", help="Override the model for a SINGLE-provider run")
    ap.add_argument("--rpm", type=int, default=0,
                    help="Cap requests per minute (per provider). Default 0 = "
                         "use per-provider safe defaults (Gemini 12, Groq 25, "
                         "OpenAI 60, Anthropic 30). Pass an explicit value to "
                         "force a uniform cap across providers.")
    ap.add_argument("--snapshot", help="Snapshot date (default = latest)")
    ap.add_argument("--out", default="reports/independent_llm_validation.md")
    ap.add_argument("--limit", type=int, help="Hard limit on trials processed (debug)")
    args = ap.parse_args()

    snaps = list_snapshots()
    if not snaps:
        raise SystemExit("No snapshots available. Save one from the app first.")
    snap = args.snapshot or snaps[0]
    df, _, _ = load_snapshot(snap)
    print(f"Loaded snapshot {snap}: {len(df):,} trials")

    sample = _stratified_sample(df, args.n, args.seed)
    if args.limit:
        sample = sample.head(args.limit)
    print(f"Sampled {len(sample)} trials (seed={args.seed})")

    forced = [p.strip() for p in args.providers.split(",")] if args.providers else None
    reviewers = _detect_reviewers(forced)
    if args.model and len(reviewers) == 1:
        reviewers = [(reviewers[0][0], args.model)]
    elif args.model and len(reviewers) > 1:
        print("[warning] --model ignored — applies to single-provider runs only")

    # Per-provider RPM ceiling — use safe per-provider default unless --rpm
    # was passed explicitly. Each provider sleeps only as long as IT needs.
    provider_rpm = {p: (args.rpm if args.rpm > 0 else _PROVIDER_RPM.get(p, 12))
                    for p, _ in reviewers}
    last_call_at: dict[str, float] = {p: 0.0 for p, _ in reviewers}

    print(f"Reviewers: {', '.join(p+'/'+m for p, m in reviewers)}")
    print("Pacing per provider: " +
          ", ".join(f"{p}={provider_rpm[p]} RPM" for p in provider_rpm))

    # results[reviewer_name][nct] = {axis: label, ...}
    pipeline_labels: dict[str, dict[str, str]] = {}
    reviewer_results: dict[str, dict[str, dict[str, str]]] = {
        f"{p}/{m}": {} for p, m in reviewers
    }
    failures: dict[str, list[tuple[str, str]]] = {
        f"{p}/{m}": [] for p, m in reviewers
    }

    for i, (_, row) in enumerate(sample.iterrows(), 1):
        nct = row["NCTId"]
        prompt = PROMPT.format(
            branches=", ".join(ALLOWED_VALUES["Branch"]),
            categories=", ".join(ALLOWED_VALUES["DiseaseCategory"]),
            product_types=", ".join(ALLOWED_VALUES["ProductType"]),
            nct=nct,
            title=str(row.get("BriefTitle", ""))[:300],
            conditions=str(row.get("Conditions", ""))[:300],
            interventions=str(row.get("Interventions", ""))[:300],
            summary=str(row.get("BriefSummary", ""))[:600],
        )
        # Re-classify through LIVE pipeline so the comparison reflects the
        # current code, not the snapshot's frozen labels (which would mask
        # any classifier fix shipped after the snapshot was saved).
        pipeline_labels[nct] = _live_pipeline_labels(row.to_dict())
        any_success = False
        for provider, model in reviewers:
            tag = f"{provider}/{model}"
            # Per-provider pacing: only wait if THIS provider has been called
            # too recently. Lets a fast provider (Groq) hit its 25 RPM ceiling
            # without being slowed to a slow provider's (Gemini) cadence.
            min_interval = 60.0 / max(provider_rpm[provider], 1)
            elapsed = time.monotonic() - last_call_at[provider]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            try:
                result = _call_llm(provider, model, prompt)
            except Exception as e:
                last_call_at[provider] = time.monotonic()
                err_text = f"{type(e).__name__}: {str(e)}"[:300]
                failures[tag].append((nct, err_text))
                if len(failures[tag]) <= 3:
                    print(f"  [{i}/{len(sample)}] {nct} {tag} — {err_text}")
                continue
            last_call_at[provider] = time.monotonic()
            reviewer_results[tag][nct] = {
                "Branch":          str(result.get("branch", "")),
                "DiseaseCategory": str(result.get("disease_category", "")),
                "TargetCategory":  str(result.get("target_category", "")),
                "ProductType":     str(result.get("product_type", "")),
            }
            any_success = True
        if not any_success:
            # If no reviewer succeeded, drop pipeline label for clean accounting
            pipeline_labels.pop(nct, None)
        if i % 10 == 0:
            print(f"  [{i}/{len(sample)}] processed")

    # ------ Per-reviewer metrics ------
    per_reviewer_metrics: dict[str, dict[str, dict]] = {}
    per_reviewer_disagreements: dict[str, dict[str, list]] = {}
    for tag, labels in reviewer_results.items():
        per_reviewer_metrics[tag] = {}
        per_reviewer_disagreements[tag] = defaultdict(list)
        for axis in AXES:
            a, b = [], []
            for nct in labels:
                pa = _norm(pipeline_labels.get(nct, {}).get(axis, ""))
                pb = _norm(labels[nct][axis])
                a.append(pa); b.append(pb)
                if pa != pb:
                    per_reviewer_disagreements[tag][axis].append(
                        (nct, pipeline_labels[nct][axis], labels[nct][axis])
                    )
            n = len(a)
            agreed = sum(1 for x, y in zip(a, b) if x == y)
            per_reviewer_metrics[tag][axis] = {
                "n":         n,
                "agreed":    agreed,
                "agreement": agreed / n if n else float("nan"),
                "kappa":     _cohen_kappa(a, b),
            }

    # ------ Consensus disagreement (only when ≥2 reviewers) ------
    # A trial is "consensus disagreement" on an axis when EVERY reviewer
    # classified it AND they all agree with each other AND they all disagree
    # with the pipeline. This is the highest-signal bucket — it can't be
    # explained as one LLM's quirk.
    consensus_disagreements: dict[str, list] = defaultdict(list)
    if len(reviewers) >= 2:
        for nct in pipeline_labels:
            for axis in AXES:
                pip = _norm(pipeline_labels[nct][axis])
                rev_labels = []
                rev_raw = []
                for tag in reviewer_results:
                    if nct not in reviewer_results[tag]:
                        rev_labels = []  # missing → can't be consensus
                        break
                    rev_labels.append(_norm(reviewer_results[tag][nct][axis]))
                    rev_raw.append(reviewer_results[tag][nct][axis])
                if not rev_labels:
                    continue
                if len(set(rev_labels)) == 1 and rev_labels[0] != pip:
                    consensus_disagreements[axis].append(
                        (nct, pipeline_labels[nct][axis], rev_raw[0])
                    )

    # ------ Report ------
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    L = []
    L += [
        "# Independent-LLM cross-validation report",
        "",
        f"- **Snapshot**: `{snap}`",
        f"- **Sample**: {len(sample)} trials (stratified by Branch × DiseaseCategory, seed={args.seed})",
        f"- **Reviewers**: {', '.join(reviewer_results.keys())}",
        f"- **Successful comparisons**: {len(pipeline_labels)} (pipeline rows with ≥1 reviewer success)",
        "",
        "Cohen's κ interpretation: <0.20 slight · 0.20–0.40 fair · "
        "0.40–0.60 moderate · 0.60–0.80 substantial · ≥0.80 almost perfect.",
        "",
    ]

    # Per-reviewer agreement tables
    for tag, metrics in per_reviewer_metrics.items():
        L += [f"## Per-reviewer agreement — `{tag}`", ""]
        n_fail = len(failures[tag])
        L.append(f"- API failures on this reviewer: **{n_fail}**")
        L.append("")
        L += ["| Axis | n | Agreed | Agreement % | Cohen's κ |",
              "|---|---:|---:|---:|---:|"]
        for axis, m in metrics.items():
            L.append(f"| {axis} | {m['n']} | {m['agreed']} | "
                     f"{100 * m['agreement']:.1f}% | {m['kappa']:.3f} |")
        L.append("")

    # Consensus disagreements (highest-signal triage list)
    if len(reviewers) >= 2:
        n_consensus = sum(len(v) for v in consensus_disagreements.values())
        L += [
            f"## Consensus disagreements ({n_consensus} across all axes) — HIGHEST PRIORITY",
            "",
            "Trials where every reviewer agrees on a label different from the "
            "pipeline. These cannot be explained by a single LLM's quirk and "
            "are the most actionable signal — investigate each before any "
            "classifier change.",
            "",
        ]
        for axis in AXES:
            if not consensus_disagreements[axis]:
                continue
            L += [f"### {axis} — {len(consensus_disagreements[axis])} trials", ""]
            for nct, pip, ind in consensus_disagreements[axis][:80]:
                L.append(f"- `{nct}` · pipeline=`{pip}` · all reviewers=`{ind}`")
            L.append("")

    # Per-reviewer disagreement detail (lower-priority triage)
    for tag, ax_dis in per_reviewer_disagreements.items():
        any_dis = sum(len(v) for v in ax_dis.values())
        if not any_dis:
            continue
        L += [f"## Solo disagreements — `{tag}` ({any_dis} across all axes)", ""]
        for axis in AXES:
            if not ax_dis[axis]:
                continue
            L += [f"### {axis} — {len(ax_dis[axis])} trials", ""]
            for nct, pip, ind in ax_dis[axis][:50]:
                L.append(f"- `{nct}` · pipeline=`{pip}` · {tag}=`{ind}`")
            if len(ax_dis[axis]) > 50:
                L.append(f"  ... and {len(ax_dis[axis]) - 50} more")
            L.append("")

    # Failures
    for tag, fails in failures.items():
        if not fails:
            continue
        L += [f"## API failures — `{tag}`", ""]
        for nct, err in fails:
            L.append(f"- `{nct}` — {err}")
        L.append("")

    out_path.write_text("\n".join(L))
    print(f"\nReport written to {out_path}")

    print("\nPer-reviewer summary:")
    for tag, metrics in per_reviewer_metrics.items():
        print(f"  {tag}")
        for axis, m in metrics.items():
            print(f"    {axis:<18} n={m['n']:<4} agreement={100 * m['agreement']:5.1f}%  κ={m['kappa']:.3f}")
    if len(reviewers) >= 2:
        n_consensus = sum(len(v) for v in consensus_disagreements.values())
        print(f"\nConsensus disagreements: {n_consensus} trial-axis pairs (highest-priority triage)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
