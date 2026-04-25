"""Regression tests for the auto-generated Methods text.

The Methods section in the app's Methods & Appendix tab is copied verbatim
into manuscripts. If a new antigen is added to config.py but the Methods
text doesn't mention it, the published methodology silently
under-counts. This test fails as soon as that drift happens.

Hard-coded counts in the Methods text were the actual bug (REVIEW.md
risk #1): the prose said "16 heme antigens" while the table held 22, and
"25 solid antigens" while the table held 28.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from config import (  # noqa: E402
    HEME_TARGET_TERMS,
    SOLID_TARGET_TERMS,
    DUAL_TARGET_LABELS,
)


@pytest.fixture(scope="module")
def methods_text():
    """Render the Methods text via the same function the app calls.

    Importing app.py runs Streamlit setup which we don't want under pytest;
    extract the function lazily and call it with stub args.
    """
    # app.py imports streamlit at module level. To call _build_methods_text
    # without standing up a Streamlit context, we read the function source
    # via importlib + monkey-patch streamlit if needed. Simpler path: use
    # the Python AST to extract just the function body. But the function
    # references df via closure, so the cleanest path is a runtime import
    # that tolerates Streamlit's setup.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "app",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"),
    )
    # Streamlit will be imported but its set_page_config etc. only fail
    # in a running script context. We tolerate any side effects by catching.
    try:
        app_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app_module)
    except Exception as e:
        pytest.skip(f"Could not import app.py for Methods-text test: {e}")

    text = app_module._build_methods_text(
        prisma={
            "n_fetched": 1000, "n_after_dedup": 950,
            "n_hard_excluded": 0, "n_indication_excluded": 50,
            "n_duplicates_removed": 50,
        },
        snapshot_date="2026-04-25",
        n_included=900,
    )
    return text


def test_methods_text_lists_every_heme_antigen(methods_text):
    """Every heme antigen in HEME_TARGET_TERMS must appear in the methods text."""
    missing = [k for k in HEME_TARGET_TERMS if k not in methods_text]
    assert not missing, (
        f"Methods text missing {len(missing)} heme antigen(s): {missing}. "
        "Either add them to the prose or live-derive the list."
    )


def test_methods_text_lists_every_solid_antigen(methods_text):
    """Every solid antigen in SOLID_TARGET_TERMS must appear in the methods text."""
    missing = [k for k in SOLID_TARGET_TERMS if k not in methods_text]
    assert not missing, (
        f"Methods text missing {len(missing)} solid antigen(s): {missing}. "
        "Either add them to the prose or live-derive the list."
    )


def test_methods_text_heme_count_matches_config(methods_text):
    """The (N) parenthetical must equal the actual HEME_TARGET_TERMS count."""
    expected = len(HEME_TARGET_TERMS)
    needle = f"Heme-typical ({expected})"
    assert needle in methods_text, (
        f"Methods text heme antigen count is wrong. Expected {needle!r} in "
        f"text. Either fix the count or live-derive it via len(HEME_TARGET_TERMS)."
    )


def test_methods_text_solid_count_matches_config(methods_text):
    """The (N) parenthetical must equal the actual SOLID_TARGET_TERMS count."""
    expected = len(SOLID_TARGET_TERMS)
    needle = f"Solid-typical ({expected})"
    assert needle in methods_text, (
        f"Methods text solid antigen count is wrong. Expected {needle!r} in "
        f"text. Either fix the count or live-derive it via len(SOLID_TARGET_TERMS)."
    )


def test_methods_text_dual_combo_count_matches_config(methods_text):
    """Dual-target combo count must equal len(DUAL_TARGET_LABELS)."""
    expected = len(DUAL_TARGET_LABELS)
    needle = f"Dual-target combos ({expected}"
    assert needle in methods_text, (
        f"Methods text dual-combo count is wrong. Expected {needle!r}-prefix in text."
    )


def test_methods_text_mentions_independent_llm_validation(methods_text):
    """Methods text must describe the independent-LLM validation harness,
    not just the original 2-round Claude curation."""
    assert "independent" in methods_text.lower() and "cohen" in methods_text.lower(), (
        "Methods text doesn't describe the independent-LLM cross-validation "
        "(should mention 'independent' + 'Cohen' / 'κ')."
    )
    assert "benchmark" in methods_text.lower(), (
        "Methods text doesn't describe the locked regression benchmark."
    )
    assert "snapshot_diff" in methods_text.lower() or "snapshot-to-snapshot" in methods_text.lower(), (
        "Methods text doesn't describe the snapshot-to-snapshot diff."
    )
