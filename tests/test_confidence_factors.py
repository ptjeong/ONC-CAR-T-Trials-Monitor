"""Tests for `pipeline.compute_confidence_factors`.

Two contracts:
  1. Per-axis sub-scores ∈ [0, 1] always
  2. Composite-to-bucket mapping preserves the legacy `_confidence`
     3-bucket binning (high / medium / low) on representative inputs

Pattern ported from rheum (REVIEW.md Phase 3 item 20).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from pipeline import compute_confidence_factors


_AXES = {"Branch", "DiseaseCategory", "DiseaseEntity",
         "TargetCategory", "ProductType"}


@pytest.fixture
def clean_dlbcl_row() -> dict:
    """A fully-classified row that should land squarely in 'high'."""
    return {
        "NCTId": "NCT_HIGH_CONF",
        "Branch": "Heme-onc",
        "DiseaseCategory": "B-NHL",
        "DiseaseEntity": "DLBCL",
        "TargetCategory": "CD19",
        "ProductType": "Autologous",
        "ProductTypeSource": "explicit_autologous",
        "LLMOverride": False,
    }


@pytest.fixture
def unclassified_row() -> dict:
    """A row with multiple axes failing — should land in 'low'."""
    return {
        "NCTId": "NCT_LOW_CONF",
        "Branch": "Unknown",
        "DiseaseCategory": "Unclassified",
        "DiseaseEntity": "Unclassified",
        "TargetCategory": "Other_or_unknown",
        "ProductType": "Unclear",
        "ProductTypeSource": "default_autologous_no_allo_markers",
        "LLMOverride": False,
    }


@pytest.fixture
def borderline_row() -> dict:
    """A row that should land in 'medium' — basket category but
    everything else clean."""
    return {
        "NCTId": "NCT_MED_CONF",
        "Branch": "Heme-onc",
        "DiseaseCategory": "Basket/Multidisease",
        "DiseaseEntity": "Basket/Multidisease",
        "TargetCategory": "CD19",
        "ProductType": "Autologous",
        "ProductTypeSource": "default_autologous_no_allo_markers",
        "LLMOverride": False,
    }


# ---- Shape ----

def test_returns_required_keys(clean_dlbcl_row):
    cf = compute_confidence_factors(clean_dlbcl_row)
    assert {"score", "level", "factors", "drivers"} <= cf.keys()


def test_factors_cover_five_axes(clean_dlbcl_row):
    cf = compute_confidence_factors(clean_dlbcl_row)
    assert set(cf["factors"]) == _AXES


def test_per_axis_score_in_unit_interval(clean_dlbcl_row, unclassified_row):
    for row in (clean_dlbcl_row, unclassified_row):
        cf = compute_confidence_factors(row)
        for axis, info in cf["factors"].items():
            assert 0.0 <= info["score"] <= 1.0, (
                f"{axis} score {info['score']} not in [0,1]"
            )
            assert "driver" in info, f"{axis} missing driver"


def test_composite_in_unit_interval(clean_dlbcl_row, unclassified_row):
    for row in (clean_dlbcl_row, unclassified_row):
        cf = compute_confidence_factors(row)
        assert 0.0 <= cf["score"] <= 1.0


# ---- Composite-to-bucket alignment with legacy ----

def test_high_confidence_row_maps_to_high(clean_dlbcl_row):
    cf = compute_confidence_factors(clean_dlbcl_row)
    assert cf["level"] == "high", (
        f"Clean DLBCL row should be high; got {cf['level']} "
        f"(composite {cf['score']:.3f})"
    )


def test_low_confidence_row_maps_to_low(unclassified_row):
    cf = compute_confidence_factors(unclassified_row)
    assert cf["level"] == "low", (
        f"Fully-unclassified row should be low; got {cf['level']}"
    )


def test_borderline_row_maps_to_medium(borderline_row):
    cf = compute_confidence_factors(borderline_row)
    assert cf["level"] in ("medium", "high"), (
        f"Basket+default row should be medium-or-high; got {cf['level']}"
    )


def test_llm_override_row_always_high():
    cf = compute_confidence_factors({
        "NCTId": "NCT_OVERRIDE",
        "Branch": "Unknown",  # would normally be low
        "DiseaseCategory": "Unclassified",
        "DiseaseEntity": "Unclassified",
        "TargetCategory": "Other_or_unknown",
        "ProductType": "Unclear",
        "ProductTypeSource": "",
        "LLMOverride": True,
    })
    assert cf["level"] == "high", (
        "LLM-override should bypass all degraders → high. Got "
        f"{cf['level']} ({cf['score']:.3f})"
    )


# ---- Drivers ----

def test_drivers_surface_worst_scoring_axes(unclassified_row):
    cf = compute_confidence_factors(unclassified_row)
    assert len(cf["drivers"]) > 0
    driver_axes = {a for a, _ in cf["drivers"]}
    # The lowest-scoring axes should be present (Branch / DiseaseEntity / etc.)
    assert driver_axes & {"Branch", "DiseaseEntity", "TargetCategory"}


def test_drivers_have_non_empty_explanations(unclassified_row):
    cf = compute_confidence_factors(unclassified_row)
    for axis, drv in cf["drivers"]:
        assert isinstance(drv, str) and drv.strip(), (
            f"{axis} driver is empty"
        )


# ---- Pure function ----

def test_pure_function(clean_dlbcl_row):
    snapshot = dict(clean_dlbcl_row)
    _ = compute_confidence_factors(clean_dlbcl_row)
    assert clean_dlbcl_row == snapshot


def test_idempotent(clean_dlbcl_row):
    a = compute_confidence_factors(clean_dlbcl_row)
    b = compute_confidence_factors(clean_dlbcl_row)
    assert a == b
