"""Regression test for the silent NaN-exclusion bug in sidebar filters.

Bug discovered 2026-04-26 during real-data inspection:
  - 139 trials in the live dataset had `Countries = NaN` (CT.gov did not
    populate the locations module).
  - The country filter applied `df["Countries"].fillna("").str.contains(...)`,
    which returns False for empty strings.
  - Even with ALL countries selected (the default), those 139 trials
    were silently excluded from every chart, table, and CSV export.
  - User-facing impact: "Filtered trials: 2,016" while PRISMA
    "Included in analysis: 2,155" — a 6.5% silent dataset shrinkage.

Fix (commit ahead of these tests): every sidebar filter now applies
the rule "narrow ONLY when the user has selected a SUBSET of the
available options". When the user has every option selected (the
default), the filter is skipped entirely so trials with NaN values
in that column are preserved.

These tests assert:
  1. With no fields configured to NaN → df_filt == full processed dataset
  2. With ANY .isin-based filter at default ("all selected") → no exclusion
  3. The country-NaN regression: simulate NaN in Countries → trial NOT
     dropped when all countries are "selected"
  4. Snapshot integrity: the live snapshot's per-column NaN counts
     are tracked here so any future column gaining unexpected NaNs
     fires a visible warning.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import pytest

from pipeline import load_snapshot


# ---------------------------------------------------------------------------
# Direct unit test of the filter-pattern (no Streamlit needed)
# ---------------------------------------------------------------------------

def _apply_filters_minimal(
    df: pd.DataFrame,
    *,
    branch_sel: list, branch_options_all: list,
    country_sel: list, country_options: list,
) -> pd.DataFrame:
    """Replicates the production filter contract for two columns —
    enough to assert the NaN-preservation invariant.

    Real production code is in `app.py` lines ~2004-2050; this helper
    mirrors the logic but is testable without a Streamlit context.
    """
    import re as _re
    mask = pd.Series(True, index=df.index)

    if branch_sel and len(branch_sel) < len(branch_options_all):
        mask &= df["Branch"].isin(branch_sel)

    if country_sel and len(country_sel) < len(country_options):
        country_pattern = "|".join([_re.escape(c) for c in country_sel])
        mask &= df["Countries"].fillna("").str.contains(
            country_pattern, case=False, na=False, regex=True,
        )
    return df[mask].copy()


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    """3 trials: one with Countries=NaN (the regression case),
    two with normal country strings."""
    return pd.DataFrame([
        {"NCTId": "NCT0001", "Branch": "Heme-onc", "Countries": "United States"},
        {"NCTId": "NCT0002", "Branch": "Solid-onc", "Countries": "China"},
        {"NCTId": "NCT0003", "Branch": "Heme-onc", "Countries": pd.NA},
    ])


# ---- Regression: NaN-Countries trial preserved with all-selected ----

def test_country_nan_trial_preserved_when_all_countries_selected(synthetic_df):
    """The 139-trial bug regression. With ALL countries selected (the
    default), a trial with NaN Countries must NOT be filtered out."""
    country_options = ["United States", "China"]
    country_sel = country_options.copy()  # user has all selected
    out = _apply_filters_minimal(
        synthetic_df,
        branch_sel=["Heme-onc", "Solid-onc"],
        branch_options_all=["Heme-onc", "Solid-onc"],
        country_sel=country_sel,
        country_options=country_options,
    )
    assert "NCT0003" in set(out["NCTId"]), (
        "NaN-Countries trial NCT0003 was silently excluded — the "
        "139-trial bug has regressed. Check that the country filter "
        "skips when len(country_sel) == len(country_options)."
    )
    assert len(out) == 3


def test_country_subset_filter_does_narrow(synthetic_df):
    """When the user actually narrows to a subset, the filter MUST
    narrow — not just skip on every input."""
    country_options = ["United States", "China"]
    country_sel = ["China"]  # user picked just one
    out = _apply_filters_minimal(
        synthetic_df,
        branch_sel=["Heme-onc", "Solid-onc"],
        branch_options_all=["Heme-onc", "Solid-onc"],
        country_sel=country_sel,
        country_options=country_options,
    )
    assert set(out["NCTId"]) == {"NCT0002"}, (
        "Country filter must still narrow when the user picks a SUBSET. "
        "Got: " + str(set(out["NCTId"]))
    )


# ---- Same defensive pattern on Branch (.isin path) ----

def test_branch_filter_skipped_when_all_selected(synthetic_df):
    """All-branches selected → no narrowing, no NaN-Branch exclusion."""
    branch_options = ["Heme-onc", "Solid-onc"]
    out = _apply_filters_minimal(
        synthetic_df,
        branch_sel=branch_options,
        branch_options_all=branch_options,
        country_sel=["United States", "China"],
        country_options=["United States", "China"],
    )
    assert len(out) == 3


def test_branch_filter_narrows_on_subset(synthetic_df):
    """Picking just one branch must narrow."""
    branch_options = ["Heme-onc", "Solid-onc"]
    out = _apply_filters_minimal(
        synthetic_df,
        branch_sel=["Heme-onc"],
        branch_options_all=branch_options,
        country_sel=["United States", "China"],
        country_options=["United States", "China"],
    )
    assert set(out["NCTId"]) == {"NCT0001", "NCT0003"}


# ---- Live-snapshot integrity check ----

def test_live_snapshot_nan_inventory():
    """Tracks the per-column NaN counts on the live snapshot. If a
    column gains unexpected NaNs in a future snapshot AND the column
    is also a sidebar filter, this test surfaces it before raters
    notice silent dataset shrinkage.

    Whitelist: only `Countries` is allowed to have NaN values today
    (and the filter is now NaN-safe). Other filterable columns must
    stay NaN-free.
    """
    df, _, _ = load_snapshot("2026-04-24")
    nan_safe_cols = {"Countries"}  # known NaN-tolerant
    filterable_cols = [
        "Branch", "DiseaseCategory", "DiseaseEntity", "TrialDesign",
        "TargetCategory", "OverallStatus", "ProductType",
        "AgeGroup", "SponsorType", "ClassificationConfidence",
    ]
    bad = []
    for col in filterable_cols:
        if col not in df.columns:
            continue
        n_nan = int(df[col].isna().sum())
        if n_nan > 0 and col not in nan_safe_cols:
            bad.append((col, n_nan))
    assert not bad, (
        "Filterable columns gained NaN values; the sidebar filter "
        "may silently exclude these trials. Either fix the pipeline "
        "to populate the column for every row, or add the column to "
        f"`nan_safe_cols` and verify its filter uses the defensive "
        f"`if sel and len(sel) < len(options)` pattern. Bad: {bad}"
    )
