"""Tests for scripts/detect_flag_consensus.py — the parsing layer.

The HTTP layer is exercised end-to-end by the GitHub Action workflow on
real issues; here we only test the pure Python that turns YAML blocks
inside markdown bodies into (axis, proposal) → {authors} agreement maps.

Why these matter: the consensus threshold (3 reviewers) is the gate
between a community flag and a moderator getting a notification, and
the gate between a moderator approval and an llm_overrides.json patch.
A parser regression here would silently break the whole pipeline.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load scripts/detect_flag_consensus.py without putting scripts/ on sys.path
# permanently — keeps the test isolated and doesn't pollute imports for
# other tests that might define their own modules with similar names.
_SPEC = importlib.util.spec_from_file_location(
    "detect_flag_consensus",
    Path(__file__).resolve().parent.parent / "scripts" / "detect_flag_consensus.py",
)
detect_flag_consensus = importlib.util.module_from_spec(_SPEC)
sys.modules["detect_flag_consensus"] = detect_flag_consensus
_SPEC.loader.exec_module(detect_flag_consensus)


_FLAG_BLOCK_TEMPLATE = """\
some prose
<!-- BEGIN_FLAG_DATA
nct_id: NCT01234567
flagged_axes:
  - axis: Branch
    pipeline_label: "Solid-onc"
    proposed_correction: "Heme-onc"
  - axis: TargetCategory
    pipeline_label: "Other_or_unknown"
    proposed_correction: "CD19"
END_FLAG_DATA -->
more prose
"""


def test_parses_basic_flag_block():
    blocks = detect_flag_consensus._parse_flag_blocks(_FLAG_BLOCK_TEMPLATE)
    assert len(blocks) == 1
    proposals = list(detect_flag_consensus._proposals_from_block(blocks[0]))
    assert ("Branch", "Heme-onc") in proposals
    assert ("TargetCategory", "CD19") in proposals


def test_handles_no_flag_block_gracefully():
    assert detect_flag_consensus._parse_flag_blocks("just regular markdown") == []
    assert detect_flag_consensus._parse_flag_blocks("") == []
    assert detect_flag_consensus._parse_flag_blocks(None) == []


def test_skips_malformed_yaml_silently():
    bad = """<!-- BEGIN_FLAG_DATA
this: is: not: valid: yaml: at: all
flagged_axes:
  - axis: Branch
END_FLAG_DATA -->"""
    # Either parses partially or returns []; never raises.
    blocks = detect_flag_consensus._parse_flag_blocks(bad)
    assert isinstance(blocks, list)


def test_three_distinct_authors_reach_consensus():
    """The core gate: 3 distinct authors agreeing on the same axis+proposal."""
    issue_body = _FLAG_BLOCK_TEMPLATE
    comments = [
        {"user": {"login": "reviewer_b"}, "body": _FLAG_BLOCK_TEMPLATE},
        {"user": {"login": "reviewer_c"}, "body": _FLAG_BLOCK_TEMPLATE},
    ]
    agreement = detect_flag_consensus._count_consensus(
        issue_author="reviewer_a",
        issue_body=issue_body,
        comments=comments,
    )
    branch_agreement = agreement[("Branch", "Heme-onc")]
    assert branch_agreement == {"reviewer_a", "reviewer_b", "reviewer_c"}
    target_agreement = agreement[("TargetCategory", "CD19")]
    assert target_agreement == {"reviewer_a", "reviewer_b", "reviewer_c"}


def test_same_author_voting_twice_counts_once():
    """A reviewer editing their comment must not double-count."""
    issue_body = _FLAG_BLOCK_TEMPLATE
    comments = [
        # Same author posts twice
        {"user": {"login": "reviewer_b"}, "body": _FLAG_BLOCK_TEMPLATE},
        {"user": {"login": "reviewer_b"}, "body": _FLAG_BLOCK_TEMPLATE},
    ]
    agreement = detect_flag_consensus._count_consensus(
        issue_author="reviewer_a",
        issue_body=issue_body,
        comments=comments,
    )
    # Only 2 distinct authors despite 3 comment bodies
    assert agreement[("Branch", "Heme-onc")] == {"reviewer_a", "reviewer_b"}


def test_disagreement_does_not_count_toward_consensus():
    """If reviewers propose different corrections, neither hits threshold."""
    body_cd19 = _FLAG_BLOCK_TEMPLATE  # proposes CD19
    body_bcma = _FLAG_BLOCK_TEMPLATE.replace("CD19", "BCMA")
    comments = [
        {"user": {"login": "reviewer_b"}, "body": body_bcma},
    ]
    agreement = detect_flag_consensus._count_consensus(
        issue_author="reviewer_a",
        issue_body=body_cd19,
        comments=comments,
    )
    # Each proposal has only 1 reviewer — neither side gets consensus
    assert len(agreement[("TargetCategory", "CD19")]) == 1
    assert len(agreement[("TargetCategory", "BCMA")]) == 1


def test_bot_authors_excluded():
    """github-actions[bot] commenting on the issue must not count as a vote."""
    comments = [
        {"user": {"login": "github-actions[bot]"}, "body": _FLAG_BLOCK_TEMPLATE},
        {"user": {"login": "reviewer_b"}, "body": _FLAG_BLOCK_TEMPLATE},
    ]
    agreement = detect_flag_consensus._count_consensus(
        issue_author="reviewer_a",
        issue_body=_FLAG_BLOCK_TEMPLATE,
        comments=comments,
    )
    # Only reviewer_a + reviewer_b — bot excluded
    assert agreement[("Branch", "Heme-onc")] == {"reviewer_a", "reviewer_b"}


def test_proposal_whitespace_normalized():
    """ 'CD19 ' and 'CD19' must count as the same proposal."""
    spaced = _FLAG_BLOCK_TEMPLATE.replace('"CD19"', '"  CD19  "')
    blocks = detect_flag_consensus._parse_flag_blocks(spaced)
    proposals = list(detect_flag_consensus._proposals_from_block(blocks[0]))
    assert ("TargetCategory", "CD19") in proposals
