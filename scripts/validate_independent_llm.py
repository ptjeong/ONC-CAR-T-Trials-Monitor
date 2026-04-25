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
    GEMINI_API_KEY   → gemini-2.0-flash       ← RECOMMENDED (free tier)
    OPENAI_API_KEY   → gpt-4o
    GROQ_API_KEY     → llama-3.3-70b-versatile (free tier, ~30 req/min)
    ANTHROPIC_API_KEY → claude-haiku-4-5      (same vendor — lower independence)

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

from pipeline import list_snapshots, load_snapshot  # noqa: E402

AXES = ["Branch", "DiseaseCategory", "TargetCategory", "ProductType"]

ALLOWED_VALUES = {
    "Branch": ["Heme-onc", "Solid-onc", "Mixed", "Unknown"],
    "ProductType": [
        "Autologous", "Allogeneic/Off-the-shelf", "In vivo", "Unclear",
    ],
}

PROMPT = """You are an independent reviewer of a CAR-T clinical-trial classifier.

For the trial below, return a JSON object with these keys (no prose, no
markdown fences):
  branch:           one of {branches}
  disease_category: short label (e.g., "B-NHL", "Multiple myeloma", "GI",
                    "CNS", "Pediatric solid", "Basket/Multidisease",
                    "Heme basket", "Unclassified" — use your best judgment)
  target_category:  the antigen/construct (e.g., "CD19", "BCMA", "GPC3",
                    "CD19/CD22 dual", "CAR-NK: CD19", "B7-H3",
                    "Other_or_unknown")
  product_type:     one of {product_types}

Be conservative — if the trial text doesn't clearly support a label, use
"Unclassified" or "Other_or_unknown" rather than guess.

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

def _detect_provider(forced: str | None) -> tuple[str, str]:
    """Return (provider_name, model_id) — auto or explicit.

    Priority order favours genuine cross-vendor independence (different
    company than the one used in validate.py, which is Claude). Anthropic
    Haiku is the lowest-priority fallback because same-vendor agreement
    bias can leak in.
    """
    if forced == "gemini" or (forced is None and os.getenv("GEMINI_API_KEY")):
        return "gemini", "gemini-2.0-flash"
    if forced == "openai" or (forced is None and os.getenv("OPENAI_API_KEY")):
        return "openai", "gpt-4o-2024-11-20"
    if forced == "groq" or (forced is None and os.getenv("GROQ_API_KEY")):
        return "groq", "llama-3.3-70b-versatile"
    if forced == "anthropic" or (forced is None and os.getenv("ANTHROPIC_API_KEY")):
        return "anthropic", "claude-haiku-4-5-20251001"
    raise SystemExit(
        "No LLM API key found. Set one of:\n"
        "  GEMINI_API_KEY (recommended, free at https://aistudio.google.com/apikey)\n"
        "  OPENAI_API_KEY\n"
        "  GROQ_API_KEY (free at https://console.groq.com)\n"
        "  ANTHROPIC_API_KEY (same vendor — lowest independence)\n"
        "Or pass --provider explicitly."
    )


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
    represents the dataset's heterogeneity rather than the modal class."""
    rng = random.Random(seed)
    strata = df.groupby(["Branch", "DiseaseCategory"], observed=True)
    per_stratum = max(1, n // max(len(strata), 1))
    rows = []
    for _, grp in strata:
        k = min(per_stratum, len(grp))
        rows.extend(rng.sample(grp.index.tolist(), k))
    rows = rng.sample(rows, min(len(rows), n))
    return df.loc[rows].copy()


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
    ap.add_argument("--provider", choices=["openai", "gemini", "anthropic"])
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

    provider, model = _detect_provider(args.provider)
    print(f"Independent reviewer: {provider} / {model}")

    pipeline_labels: dict[str, dict[str, str]] = {}
    independent_labels: dict[str, dict[str, str]] = {}
    failures = []

    for i, (_, row) in enumerate(sample.iterrows(), 1):
        nct = row["NCTId"]
        prompt = PROMPT.format(
            branches=", ".join(ALLOWED_VALUES["Branch"]),
            product_types=", ".join(ALLOWED_VALUES["ProductType"]),
            nct=nct,
            title=str(row.get("BriefTitle", ""))[:300],
            conditions=str(row.get("Conditions", ""))[:300],
            interventions=str(row.get("Interventions", ""))[:300],
            summary=str(row.get("BriefSummary", ""))[:600],
        )
        try:
            result = _call_llm(provider, model, prompt)
        except Exception as e:
            failures.append((nct, str(e)[:120]))
            print(f"  [{i}/{len(sample)}] {nct} — ERROR: {type(e).__name__}")
            continue

        pipeline_labels[nct] = {
            "Branch":          str(row.get("Branch", "")),
            "DiseaseCategory": str(row.get("DiseaseCategory", "")),
            "TargetCategory":  str(row.get("TargetCategory", "")),
            "ProductType":     str(row.get("ProductType", "")),
        }
        independent_labels[nct] = {
            "Branch":          result.get("branch", ""),
            "DiseaseCategory": result.get("disease_category", ""),
            "TargetCategory":  result.get("target_category", ""),
            "ProductType":     result.get("product_type", ""),
        }
        if i % 10 == 0:
            print(f"  [{i}/{len(sample)}] processed")
        time.sleep(0.1)  # be polite

    # Compute κ + agreement per axis.
    metrics = {}
    disagreements = defaultdict(list)
    for axis in AXES:
        a, b = [], []
        for nct in pipeline_labels:
            pa = _norm(pipeline_labels[nct][axis])
            pb = _norm(independent_labels[nct][axis])
            a.append(pa); b.append(pb)
            if pa != pb:
                disagreements[axis].append((nct, pipeline_labels[nct][axis],
                                            independent_labels[nct][axis]))
        n = len(a)
        agreed = sum(1 for x, y in zip(a, b) if x == y)
        metrics[axis] = {
            "n":         n,
            "agreed":    agreed,
            "agreement": agreed / n if n else float("nan"),
            "kappa":     _cohen_kappa(a, b),
        }

    # Report
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Independent-LLM cross-validation report",
        "",
        f"- **Snapshot**: `{snap}`",
        f"- **Sample**: {len(sample)} trials (stratified by Branch × DiseaseCategory, seed={args.seed})",
        f"- **Independent reviewer**: `{provider}` · `{model}`",
        f"- **Successful comparisons**: {len(pipeline_labels)}",
        f"- **API failures**: {len(failures)}",
        "",
        "## Per-axis agreement",
        "",
        "| Axis | n | Agreed | Agreement % | Cohen's κ |",
        "|---|---:|---:|---:|---:|",
    ]
    for axis, m in metrics.items():
        lines.append(
            f"| {axis} | {m['n']} | {m['agreed']} | "
            f"{100 * m['agreement']:.1f}% | {m['kappa']:.3f} |"
        )
    lines += ["", "Cohen's κ interpretation: <0.20 slight · 0.20–0.40 fair · "
              "0.40–0.60 moderate · 0.60–0.80 substantial · ≥0.80 almost perfect.",
              ""]
    for axis in AXES:
        if not disagreements[axis]:
            continue
        lines += [f"## Disagreements — {axis} ({len(disagreements[axis])} trials)", ""]
        for nct, pip, ind in disagreements[axis][:50]:  # cap per axis
            lines.append(f"- `{nct}` · pipeline=`{pip}` · independent=`{ind}`")
        if len(disagreements[axis]) > 50:
            lines.append(f"  ... and {len(disagreements[axis]) - 50} more")
        lines.append("")
    if failures:
        lines += ["## API failures", ""]
        for nct, err in failures:
            lines.append(f"- `{nct}` — {err}")

    out_path.write_text("\n".join(lines))
    print(f"\nReport written to {out_path}")
    print("\nSummary:")
    for axis, m in metrics.items():
        print(f"  {axis:<18} n={m['n']:<4} agreement={100 * m['agreement']:5.1f}%  κ={m['kappa']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
