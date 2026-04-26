"""Tests for `pipeline.compute_classification_rationale`.

The dashboard's "How was this classified?" expander depends on this
helper returning a stable shape with sensible content. A regression
here would silently degrade the per-trial audit experience without
any failing user-facing path — hence dedicated tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from pipeline import compute_classification_rationale


_AXES = {"Branch", "DiseaseCategory", "DiseaseEntity",
         "TargetCategory", "ProductType", "SponsorType"}


@pytest.fixture
def dlbcl_row() -> dict:
    return {
        "NCTId": "NCT_TEST_DLBCL",
        "BriefTitle": "Anti-CD19 CAR-T in r/r DLBCL",
        "BriefSummary": "Phase 2 trial of autologous anti-CD19 CAR-T in DLBCL",
        "Conditions": "Diffuse Large B-Cell Lymphoma",
        "Interventions": "anti-CD19 CAR-T",
        "LeadSponsor": "ACME University",
        "LeadSponsorClass": "OTHER",
    }


@pytest.fixture
def gbm_b7h3_row() -> dict:
    return {
        "NCTId": "NCT_TEST_GBM",
        "BriefTitle": "B7-H3 CAR-T in recurrent glioblastoma",
        "BriefSummary": "Phase 1 dose escalation in r/r GBM",
        "Conditions": "Glioblastoma multiforme",
        "Interventions": "B7-H3 CAR-T",
        "LeadSponsor": "Acme Biopharma Inc",
        "LeadSponsorClass": "INDUSTRY",
    }


def test_returns_all_six_axes(dlbcl_row):
    out = compute_classification_rationale(dlbcl_row)
    assert set(out.keys()) == _AXES


def test_each_axis_has_required_keys(dlbcl_row):
    out = compute_classification_rationale(dlbcl_row)
    for axis, info in out.items():
        assert "label" in info, f"{axis} missing 'label'"
        assert "source" in info, f"{axis} missing 'source'"
        assert "matched_terms" in info, f"{axis} missing 'matched_terms'"
        assert "explanation" in info, f"{axis} missing 'explanation'"
        assert isinstance(info["matched_terms"], list), (
            f"{axis} matched_terms must be a list"
        )


def test_target_category_surfaces_matched_antigens(dlbcl_row):
    out = compute_classification_rationale(dlbcl_row)
    assert out["TargetCategory"]["label"] == "CD19"
    assert "CD19" in out["TargetCategory"]["matched_terms"]


def test_solid_b7h3_classified_correctly(gbm_b7h3_row):
    out = compute_classification_rationale(gbm_b7h3_row)
    assert out["Branch"]["label"] == "Solid-onc"
    assert out["TargetCategory"]["label"] == "B7-H3"


def test_pure_function_no_side_effects(dlbcl_row):
    """Calling rationale must not mutate the input row."""
    snapshot = dict(dlbcl_row)
    _ = compute_classification_rationale(dlbcl_row)
    assert dlbcl_row == snapshot


def test_idempotent(dlbcl_row):
    """Same input → same output, every time."""
    a = compute_classification_rationale(dlbcl_row)
    b = compute_classification_rationale(dlbcl_row)
    assert a == b


def test_handles_empty_row():
    """Defensive: a near-empty row should still return all 6 axes
    rather than raising — drilldown UI must not crash on edge data."""
    out = compute_classification_rationale({"NCTId": "NCT_TEST_EMPTY"})
    assert set(out.keys()) == _AXES


def test_source_tag_is_one_of_known_values(dlbcl_row):
    """Source tags must come from a known vocabulary (not ad-hoc)."""
    known_sources = {
        "llm_override", "rule_based", "named_product", "antigen_match",
        "platform_only", "fallback", "lead_sponsor_class + name_pattern",
        "explicit_allogeneic", "explicit_autologous", "explicit_in_vivo",
        "default_autologous_no_allo_markers",
        "weak_autologous_marker", "weak_allogeneic_marker",
    }
    out = compute_classification_rationale(dlbcl_row)
    unknown = [
        (axis, info["source"]) for axis, info in out.items()
        if info["source"] not in known_sources
        and not info["source"].startswith("explicit_")
        and not info["source"].startswith("default_")
        and not info["source"].startswith("weak_")
    ]
    assert not unknown, f"Unknown source tags surfaced: {unknown}"
