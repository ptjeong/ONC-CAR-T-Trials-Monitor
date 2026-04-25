"""Tests for scripts/promote_consensus_flags.py — patch construction.

Covers the part of the promotion script that we can test without making
real GitHub API calls: the YAML-block parser shared with the consensus
detector, and the llm_overrides.json patch builder. The HTTP layer is
covered by manually running --close-issues against a real test issue
when the script is first deployed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "promote_consensus_flags",
    Path(__file__).resolve().parent.parent / "scripts" / "promote_consensus_flags.py",
)
promote_consensus_flags = importlib.util.module_from_spec(_SPEC)
sys.modules["promote_consensus_flags"] = promote_consensus_flags
_SPEC.loader.exec_module(promote_consensus_flags)


def test_axis_field_map_covers_all_supported_axes():
    """The Moderation tab and the override file must agree on field names."""
    assert promote_consensus_flags.AXIS_TO_OVERRIDE_FIELD["Branch"] == "branch"
    assert promote_consensus_flags.AXIS_TO_OVERRIDE_FIELD["TargetCategory"] == "target_category"
    assert promote_consensus_flags.AXIS_TO_OVERRIDE_FIELD["DiseaseEntity"] == "disease_entity"
    assert promote_consensus_flags.AXIS_TO_OVERRIDE_FIELD["DiseaseCategory"] == "disease_category"
    assert promote_consensus_flags.AXIS_TO_OVERRIDE_FIELD["ProductType"] == "product_type"


def test_build_patch_creates_new_entry_when_no_existing():
    proposals = {
        ("Branch", "Heme-onc"): {"a", "b", "c"},
        ("TargetCategory", "CD19"): {"a", "b", "c"},
    }
    entry = promote_consensus_flags._build_patch(
        nct="NCT12345678",
        proposals=proposals,
        issue_url="https://github.com/foo/bar/issues/1",
        existing=None,
    )
    assert entry["nct_id"] == "NCT12345678"
    assert entry["branch"] == "Heme-onc"
    assert entry["target_category"] == "CD19"
    assert entry["confidence"] == "high"
    assert entry["exclude"] is False
    assert "community-flag" in entry["notes"]
    assert "https://github.com/foo/bar/issues/1" in entry["notes"]


def test_build_patch_updates_existing_entry_in_place():
    """Existing entries must keep unrelated fields and update only flagged axes."""
    existing = {
        "nct_id": "NCT99999999",
        "branch": "Solid-onc",  # WRONG, will be corrected
        "disease_category": "GI",  # unchanged
        "disease_entity": "HCC",   # unchanged
        "target_category": "GPC3",
        "product_type": "Autologous",
        "exclude": False,
        "exclude_reason": None,
        "confidence": "medium",  # will be bumped to high
        "notes": "Original Claude curation 2025",
    }
    proposals = {
        ("Branch", "Heme-onc"): {"a", "b", "c"},  # the only correction
    }
    entry = promote_consensus_flags._build_patch(
        nct="NCT99999999",
        proposals=proposals,
        issue_url="https://github.com/foo/bar/issues/2",
        existing=existing,
    )
    assert entry["branch"] == "Heme-onc"
    # Untouched fields preserved
    assert entry["disease_category"] == "GI"
    assert entry["disease_entity"] == "HCC"
    assert entry["target_category"] == "GPC3"
    # Confidence bumped to high
    assert entry["confidence"] == "high"
    # Notes append (don't overwrite)
    assert "Original Claude curation 2025" in entry["notes"]
    assert "community-flag" in entry["notes"]
    assert "Heme-onc" in entry["notes"]


def test_build_patch_returns_none_for_unsupported_axes_only():
    """SponsorType corrections aren't applied through llm_overrides.json
    (they live in pipeline.py's name-pattern classifier). The patch
    builder must return None so the script reports `skipped` rather
    than silently inserting an empty entry."""
    proposals = {
        ("SponsorType", "Industry"): {"a", "b", "c"},
    }
    entry = promote_consensus_flags._build_patch(
        nct="NCT12345678",
        proposals=proposals,
        issue_url="https://github.com/foo/bar/issues/3",
        existing=None,
    )
    assert entry is None


def test_nct_extraction_from_issue_title():
    issue = {
        "title": "[Flag] NCT01234567 — TargetCategory should be CD19",
        "body": "details here",
    }
    assert promote_consensus_flags._nct_from_issue(issue) == "NCT01234567"


def test_nct_extraction_falls_back_to_body():
    issue = {
        "title": "[Flag] classification correction",
        "body": "Trial NCT09876543 needs a new branch label.",
    }
    assert promote_consensus_flags._nct_from_issue(issue) == "NCT09876543"


def test_nct_extraction_returns_none_when_absent():
    issue = {"title": "no NCT here", "body": "neither here"}
    assert promote_consensus_flags._nct_from_issue(issue) is None


def test_parse_flag_block_handles_real_template():
    """The exact YAML payload the dashboard's link-out builder generates
    must round-trip through the parser cleanly."""
    text = """
some markdown

<!-- BEGIN_FLAG_DATA
nct_id: NCT07386002
flagged_axes:
  - axis: Branch
    pipeline_label: "Solid-onc"
    proposed_correction: "Solid-onc"
  - axis: TargetCategory
    pipeline_label: "B7-H3"
    proposed_correction: "B7-H3 (allogeneic platform)"
END_FLAG_DATA -->

more markdown
"""
    blocks = promote_consensus_flags._parse_flag_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["nct_id"] == "NCT07386002"
    axes = blocks[0]["flagged_axes"]
    assert {a["axis"] for a in axes} == {"Branch", "TargetCategory"}
