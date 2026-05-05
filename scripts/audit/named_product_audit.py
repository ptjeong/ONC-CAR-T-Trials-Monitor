"""Systematic named-product classification audit.

For every product in known_products.KNOWN_PRODUCTS:
  1. Find every trial in the CSV whose Title (or any text field we
     have) mentions one of the product's aliases.
  2. Verify the classifier's labels match the product's expected
     attributes (target, branch, product_type).
  3. Emit a report:
        - PASS rows: product found, all matching trials classified correctly
        - PARTIAL rows: product found, some trials misclassified
        - MISS rows: product expected but no trials found
        - UNKNOWN rows: trial mentions a product not in the knowledge base
                       (we DON'T flag those — we just count them as
                       potential additions)

Usage:
    python3 audit.py /path/to/car_t_onc_view.csv
"""

import sys
import re
import pandas as pd
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from known_products import KNOWN_PRODUCTS


def _normalize(s):
    """Lowercase + strip + collapse whitespace, matching the convention
    used by NAMED_PRODUCT_TARGETS substring lookup."""
    if pd.isna(s):
        return ""
    return re.sub(r"\s+", " ", str(s).lower().strip())


def _find_alias_in_text(aliases, text):
    """Return the first alias that appears as a substring of text, or
    None. Whole-word boundary not required — matches the live
    classifier's _lookup_named_product behavior."""
    for a in aliases:
        if a in text:
            return a
    return None


def _expected_target_in_actual(expected, actual):
    """Match expected target against the classifier's actual label.

    Permissive comparison: 'BCMA' matches 'BCMA', 'CAR-NK: BCMA',
    'BCMA/GPRC5D dual' (when expected says BCMA), etc. Strict equality
    where expected is itself a dual-target label.
    """
    if not actual or pd.isna(actual):
        return False
    actual_s = str(actual)
    if "dual" in expected.lower():
        return expected == actual_s  # dual labels need exact match
    # Single-target expected — accept if actual contains it as a token
    return (expected in actual_s)


def audit(csv_path):
    df = pd.read_csv(csv_path, comment="#")
    df["_text"] = (
        df["BriefTitle"].fillna("").astype(str) + " | "
        + df.get("DiseaseEntities", pd.Series(["" ] * len(df))).fillna("").astype(str)
    ).map(_normalize)

    rows_pass, rows_partial, rows_miss = [], [], []
    by_product = []

    for product in KNOWN_PRODUCTS:
        primary = product["aliases"][0]
        # Scan every trial for any alias hit
        hits = []
        for _, row in df.iterrows():
            alias = _find_alias_in_text(product["aliases"], row["_text"])
            if alias:
                hits.append((row, alias))

        if not hits:
            rows_miss.append((product, "no trials matched"))
            continue

        # Verify each matched trial
        per_trial = []
        for row, alias in hits:
            tgt_ok = _expected_target_in_actual(
                product["target"], row.get("TargetCategory"))
            branch_ok = (row.get("Branch") == product["branch"]
                         or product["branch"] == "Mixed")
            ptype_ok = (row.get("ProductType") == product["product_type"])
            per_trial.append({
                "nct": row["NCTId"],
                "alias_matched": alias,
                "title": row.get("BriefTitle", "")[:80],
                "target_actual": row.get("TargetCategory"),
                "target_expected": product["target"],
                "target_ok": tgt_ok,
                "branch_actual": row.get("Branch"),
                "branch_expected": product["branch"],
                "branch_ok": branch_ok,
                "product_type_actual": row.get("ProductType"),
                "product_type_expected": product["product_type"],
                "product_type_ok": ptype_ok,
                "all_ok": tgt_ok and branch_ok and ptype_ok,
            })

        n_total = len(per_trial)
        n_ok = sum(1 for t in per_trial if t["all_ok"])
        if n_ok == n_total:
            rows_pass.append((primary, n_total))
        else:
            rows_partial.append((primary, n_ok, n_total, per_trial))

        by_product.append({
            "primary": primary,
            "expected": f"{product['target']} / {product['branch']} / {product['product_type']}",
            "n_total": n_total,
            "n_ok": n_ok,
            "trials": per_trial,
        })

    # ---- Print report ----
    print("=" * 78)
    print("NAMED-PRODUCT CLASSIFICATION AUDIT")
    print(f"  CSV: {csv_path}")
    print(f"  Knowledge base: {len(KNOWN_PRODUCTS)} products")
    print(f"  Trials in CSV: {len(df)}")
    print("=" * 78)

    print(f"\n[PASS] {len(rows_pass)} products — all trials classified correctly")
    for primary, n in rows_pass:
        print(f"  {primary:35s}  {n:3d} trials  ✓")

    print(f"\n[PARTIAL] {len(rows_partial)} products — at least one misclassification")
    for primary, n_ok, n_total, trials in rows_partial:
        print(f"\n  {primary}  ({n_ok}/{n_total} correct)")
        for t in trials:
            if not t["all_ok"]:
                bits = []
                if not t["target_ok"]:
                    bits.append(
                        f"target={t['target_actual']!r} (expected {t['target_expected']!r})")
                if not t["branch_ok"]:
                    bits.append(
                        f"branch={t['branch_actual']!r} (expected {t['branch_expected']!r})")
                if not t["product_type_ok"]:
                    bits.append(
                        f"product_type={t['product_type_actual']!r} (expected {t['product_type_expected']!r})")
                print(f"    {t['nct']}: {'; '.join(bits)}")
                print(f"      {t['title']}")

    print(f"\n[MISS] {len(rows_miss)} products — no trials matched in CSV")
    for product, reason in rows_miss:
        print(f"  {product['aliases'][0]:35s}  ({reason})")

    # ---- Summary ----
    total_audited = sum(1 for p in by_product)
    total_ok = sum(1 for p in by_product if p["n_ok"] == p["n_total"])
    total_trials_audited = sum(p["n_total"] for p in by_product)
    total_trials_ok = sum(p["n_ok"] for p in by_product)
    print("\n" + "=" * 78)
    print("SUMMARY")
    print(f"  Products with ≥1 matched trial: {total_audited} of {len(KNOWN_PRODUCTS)}")
    print(f"  Products fully correct: {total_ok} of {total_audited}")
    print(f"  Trials audited: {total_trials_audited}")
    print(f"  Trials fully correct: {total_trials_ok} ({100 * total_trials_ok / max(1, total_trials_audited):.1f}%)")
    print("=" * 78)

    return by_product


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/peterjeong/Downloads/car_t_onc_view.csv"
    audit(csv_path)
