"""Tests for scripts/compute_validation_kappa.py.

Covers the κ + bootstrap CI math (anchored against the same Sim &
Wright 2005 BMC textbook example used by the in-app helper) plus the
NON_RATING_LABELS exclusion logic. The HTTP/file-IO layers are
exercised end-to-end when the script runs against committed responses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "compute_validation_kappa",
    Path(__file__).resolve().parent.parent / "scripts" / "compute_validation_kappa.py",
)
ck = importlib.util.module_from_spec(_SPEC)
sys.modules["compute_validation_kappa"] = ck
_SPEC.loader.exec_module(ck)


# ---- κ point estimate ----

def test_kappa_perfect_agreement():
    a = ["X", "Y", "X", "Y", "Z"]
    b = ["X", "Y", "X", "Y", "Z"]
    assert ck.cohens_kappa(a, b) == 1.0


def test_kappa_chance_agreement_is_zero():
    """50/50 split, no correlation → κ ≈ 0."""
    a = ["X", "X", "Y", "Y"]
    b = ["X", "Y", "X", "Y"]
    k = ck.cohens_kappa(a, b)
    assert k is not None and abs(k) < 1e-9


def test_kappa_textbook_example():
    """Sim & Wright (2005) BMC: κ ≈ 0.1304 to ±0.01.

    Same anchor used by app.py's _cohens_kappa — keeps the two
    implementations honest against each other.
    """
    a = ["yes"] * 60 + ["no"] * 40
    b = (["yes"] * 45 + ["no"] * 15
         + ["yes"] * 25 + ["no"] * 15)
    k = ck.cohens_kappa(a, b)
    assert k is not None and abs(k - 0.1304) < 0.01


def test_kappa_returns_none_when_undefined():
    assert ck.cohens_kappa([], []) is None
    assert ck.cohens_kappa(["X"], ["X"]) is None
    # Single category — κ undefined (no variance)
    assert ck.cohens_kappa(["X", "X", "X"], ["X", "X", "X"]) is None
    # Length mismatch — defensive return
    assert ck.cohens_kappa(["X"], ["X", "Y"]) is None


# ---- Bootstrap CI ----

def test_bootstrap_ci_brackets_point_estimate_for_perfect():
    """For perfect agreement (κ=1), bootstrap CI must be [1, 1] or close."""
    a = ["X", "Y"] * 50
    b = list(a)
    lo, hi = ck.bootstrap_kappa_ci(a, b, n_resamples=500, seed=42)
    assert lo is not None and hi is not None
    assert lo > 0.99 and hi >= 0.99


def test_bootstrap_ci_returns_none_when_undefined():
    lo, hi = ck.bootstrap_kappa_ci([], [], n_resamples=100)
    assert lo is None and hi is None


def test_bootstrap_ci_brackets_point_estimate_for_textbook():
    """For the Sim-Wright textbook κ ≈ 0.13, the 95% CI should bracket
    that value (with sufficient bootstrap replicates)."""
    a = ["yes"] * 60 + ["no"] * 40
    b = (["yes"] * 45 + ["no"] * 15
         + ["yes"] * 25 + ["no"] * 15)
    point = ck.cohens_kappa(a, b)
    lo, hi = ck.bootstrap_kappa_ci(a, b, n_resamples=2000, seed=123)
    assert lo is not None and hi is not None
    assert lo <= point <= hi


# ---- Landis & Koch interpretation ----

def test_landis_koch_thresholds():
    assert ck.landis_koch(None) == "—"
    assert ck.landis_koch(-0.1) == "poor"
    assert ck.landis_koch(0.0) == "slight"
    assert ck.landis_koch(0.10) == "slight"
    assert ck.landis_koch(0.30) == "fair"
    assert ck.landis_koch(0.50) == "moderate"
    assert ck.landis_koch(0.70) == "substantial"
    assert ck.landis_koch(0.90) == "almost perfect"


# ---- NON_RATING_LABELS handling ----

def test_non_rating_labels_set_includes_unsure_and_skipped():
    """Critical: 'Unsure' and 'Skipped' must be excluded from κ
    computation per the methodology — they're recorded as data, not
    classifications. A regression here would inflate disagreement
    rates and tank κ artificially."""
    assert "Unsure" in ck.NON_RATING_LABELS
    assert "Skipped" in ck.NON_RATING_LABELS
    assert "" in ck.NON_RATING_LABELS
    assert None in ck.NON_RATING_LABELS


def test_aligned_rating_vectors_excludes_unsure():
    rater_a = {
        "ratings": {
            "NCT01": {"labels": {"Branch": "Heme-onc"}},
            "NCT02": {"labels": {"Branch": "Solid-onc"}},
            "NCT03": {"labels": {"Branch": "Unsure"}},  # excluded
        }
    }
    rater_b = {
        "ratings": {
            "NCT01": {"labels": {"Branch": "Heme-onc"}},
            "NCT02": {"labels": {"Branch": "Solid-onc"}},
            "NCT03": {"labels": {"Branch": "Heme-onc"}},
        }
    }
    av, bv, n_excluded = ck._aligned_rating_vectors(rater_a, rater_b, "Branch")
    assert av == ["Heme-onc", "Solid-onc"]
    assert bv == ["Heme-onc", "Solid-onc"]
    assert n_excluded == 1


def test_aligned_rating_vectors_intersects_ncts():
    """Only NCTs both raters scored should be compared."""
    rater_a = {
        "ratings": {
            "NCT01": {"labels": {"Branch": "Heme-onc"}},
            "NCT02": {"labels": {"Branch": "Solid-onc"}},
        }
    }
    rater_b = {
        "ratings": {
            "NCT01": {"labels": {"Branch": "Heme-onc"}},
            "NCT99": {"labels": {"Branch": "Solid-onc"}},  # not in A
        }
    }
    av, bv, _ = ck._aligned_rating_vectors(rater_a, rater_b, "Branch")
    assert av == ["Heme-onc"]
    assert bv == ["Heme-onc"]
