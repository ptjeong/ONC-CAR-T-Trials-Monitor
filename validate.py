#!/usr/bin/env python3
"""
LLM validation loop for oncology CAR-T trial classifications.

Fetches live trial data, identifies borderline classifications, and sends each
to Claude for a structured second opinion. Outputs a human-readable change
summary and copy-pasteable config patches.

Usage:
    python validate.py                        # review borderline cases (default ≤30)
    python validate.py --nct NCT06123456      # review a single trial
    python validate.py --all --limit 100      # review up to 100 trials
    python validate.py --output results.json  # custom output path

Requires:
    ANTHROPIC_API_KEY environment variable
    pip install anthropic  (already in requirements.txt)
"""

import json
import os
import sys
import textwrap
import argparse

import anthropic
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import build_clean_dataframe  # noqa: E402
from config import (  # noqa: E402
    VALID_DISEASE_ENTITIES,
    VALID_BRANCHES,
    VALID_CATEGORIES,
    VALID_TARGETS,
    VALID_PRODUCT_TYPES,
)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = textwrap.dedent("""
    You are an expert in CAR-T, CAR-NK, CAAR-T, and CAR-Treg clinical trials
    in oncology (heme-onc and solid-onc).

    Your task: validate automated classifications for a clinical trial and
    return a corrected classification as a JSON object — no prose, no markdown
    fences, no extra keys.

    Schema (return exactly this):
    {{
        "nct_id":           "NCTXXXXXXXX",
        "branch":           "<Heme-onc | Solid-onc | Mixed | Unknown>",
        "disease_category": "<see list>",
        "disease_entity":   "<see list>",
        "target_category":  "<see list>",
        "product_type":     "<see list>",
        "exclude":          false,
        "exclude_reason":   null,
        "confidence":       "high|medium|low",
        "notes":            "<one sentence rationale>"
    }}

    Valid branch values:
      {branches}

    Valid disease_category values:
      {categories}

    Valid disease_entity values (Tier-3 leaf):
      {diseases}

    Valid target_category values:
      {targets}

    Valid product_type values:
      {product_types}

    Key rules:
    - "Exclude" → remove entirely (autoimmune-only indications, non-CAR-T
      interventions, purely observational, cell-therapy registry / LTFU).
    - "Basket/Multidisease" → ≥2 Tier-3 entities or ≥2 Tier-2 categories.
    - "Advanced solid tumors" → pan-solid basket with no specific tumour type.
    - "Heme basket" → pan-heme basket with no specific disease.
    - "Unclassified" → genuinely cannot determine from available text.
    - "CAR-T_unspecified" → confirmed CAR-T but target antigen not disclosed.
    - confidence "high" = certain from trial text; "low" = best guess only.
""")

_USER = textwrap.dedent("""
    Classify this clinical trial.

    NCT ID:       {nct_id}
    Title:        {title}
    Conditions:   {conditions}
    Interventions:{interventions}

    Brief summary:
    {summary}

    Current automated classifications (may be incorrect):
      Branch:          {branch}
      DiseaseCategory: {category}
      DiseaseEntity:   {disease}
      TargetCategory:  {target}
      ProductType:     {product_type}

    Return corrected JSON only.
""")


def _make_system() -> str:
    return _SYSTEM.format(
        branches=", ".join(VALID_BRANCHES),
        categories=", ".join(VALID_CATEGORIES),
        diseases=", ".join(VALID_DISEASE_ENTITIES),
        targets=", ".join(VALID_TARGETS),
        product_types=", ".join(VALID_PRODUCT_TYPES),
    )


def validate_trial(client: anthropic.Anthropic, row: dict) -> dict | None:
    prompt = _USER.format(
        nct_id=row.get("NCTId", ""),
        title=row.get("BriefTitle", ""),
        conditions=(row.get("Conditions") or "")[:400],
        interventions=(row.get("Interventions") or "")[:400],
        summary=(row.get("BriefSummary") or "")[:900],
        branch=row.get("Branch", ""),
        category=row.get("DiseaseCategory", ""),
        disease=row.get("DiseaseEntity", ""),
        target=row.get("TargetCategory", ""),
        product_type=row.get("ProductType", ""),
    )
    try:
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=512,
            system=_make_system(),
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON parse error for {row.get('NCTId')}: {e}")
        return None
    except Exception as e:
        print(f"  ✗ API error for {row.get('NCTId')}: {e}")
        return None


def _config_patch_lines(results: list[dict]) -> list[str]:
    lines = []
    for r in results:
        if r.get("exclude") and r.get("confidence") == "high":
            reason = (r.get("exclude_reason") or r.get("notes") or "").replace("\n", " ")
            lines.append(f'    "{r["nct_id"]}",  # {reason}')
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM validation loop for oncology CAR-T trial classifications"
    )
    parser.add_argument("--nct", help="Validate a specific NCT ID only")
    parser.add_argument("--all", action="store_true", help="Validate all trials (ignores borderline filter)")
    parser.add_argument("--limit", type=int, default=30, help="Max borderline trials to validate (default 30)")
    parser.add_argument("--output", default="llm_overrides.json", help="JSON output path (merged with existing)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("Fetching trial data from ClinicalTrials.gov …")
    df = build_clean_dataframe(max_records=2000)
    print(f"  {len(df)} trials loaded\n")

    if args.nct:
        subset = df[df["NCTId"] == args.nct]
        if subset.empty:
            print(f"Trial {args.nct} not found in current dataset.")
            sys.exit(1)
    elif args.all:
        subset = df.head(args.limit)
    else:
        borderline = (
            df["Branch"].eq("Unknown")
            | df["DiseaseEntity"].isin(["Unclassified", "Heme-onc_other", "Solid-onc_other"])
            | df["TargetCategory"].isin(["CAR-T_unspecified", "Other_or_unknown"])
            | df["ProductType"].eq("Unclear")
        )
        subset = df[borderline].head(args.limit)
        print(f"  {len(subset)} borderline trials selected for validation\n")

    results: list[dict] = []
    changes: list[dict] = []

    for i, (_, row) in enumerate(subset.iterrows(), 1):
        nct = row["NCTId"]
        title = (row.get("BriefTitle") or "")[:70]
        print(f"[{i:>3}/{len(subset)}] {nct}  {title}")

        result = validate_trial(client, row.to_dict())
        if result is None:
            continue

        result["_orig_branch"]   = row.get("Branch")
        result["_orig_category"] = row.get("DiseaseCategory")
        result["_orig_disease"]  = row.get("DiseaseEntity")
        result["_orig_target"]   = row.get("TargetCategory")
        result["_orig_product"]  = row.get("ProductType")
        results.append(result)

        diffs = []
        if result.get("branch") and result["branch"] != row.get("Branch"):
            diffs.append(f"branch:  {row['Branch']} → {result['branch']}")
        if result.get("disease_category") != row.get("DiseaseCategory"):
            diffs.append(f"category: {row['DiseaseCategory']} → {result.get('disease_category')}")
        if result.get("disease_entity") != row.get("DiseaseEntity"):
            diffs.append(f"disease:  {row['DiseaseEntity']} → {result.get('disease_entity')}")
        if result.get("target_category") != row.get("TargetCategory"):
            diffs.append(f"target:   {row['TargetCategory']} → {result.get('target_category')}")
        if result.get("product_type") != row.get("ProductType"):
            diffs.append(f"product:  {row['ProductType']} → {result.get('product_type')}")
        if result.get("exclude"):
            diffs.append(f"EXCLUDE   {result.get('exclude_reason') or ''}")

        conf = result.get("confidence", "?")
        if diffs:
            changes.append({
                "nct_id": nct, "title": title,
                "diffs": diffs, "confidence": conf,
                "notes": result.get("notes", ""),
            })
            for d in diffs:
                print(f"       ✎  {d}  [{conf}]")
        else:
            print(f"       ✓  confirmed  [{conf}]")

    existing: dict[str, dict] = {}
    if os.path.exists(args.output):
        try:
            with open(args.output) as f:
                for e in json.load(f):
                    existing[e["nct_id"]] = e
        except (json.JSONDecodeError, KeyError):
            existing = {}
    n_before = len(existing)
    for r in results:
        existing[r["nct_id"]] = r
    with open(args.output, "w") as f:
        json.dump(list(existing.values()), f, indent=2)
    n_new = len(existing) - n_before
    print(f"\nOverrides → {args.output}  ({len(existing)} total, {n_new} new)")

    if not changes:
        print("\nAll classifications look correct — no changes suggested.")
        return

    W = 70
    print(f"\n{'═' * W}")
    print(f"  SUGGESTED CHANGES  ({len(changes)} of {len(results)} trials reviewed)")
    print(f"{'═' * W}")
    for c in changes:
        print(f"\n  {c['nct_id']}  {c['title']}")
        for d in c["diffs"]:
            print(f"    • {d}")
        print(f"    Confidence: {c['confidence']}")
        if c["notes"]:
            print(f"    {c['notes']}")

    excl_lines = _config_patch_lines(results)
    if excl_lines:
        print(f"\n{'─' * W}")
        print("  ADD TO HARD_EXCLUDED_NCT_IDS in config.py:")
        print(f"{'─' * W}")
        for ln in excl_lines:
            print(ln)

    print(f"\n{'═' * W}\n")


if __name__ == "__main__":
    main()
