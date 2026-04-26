"""Tests for the inline-flag-prefix UX (replaces the dedicated _Flag column).

We test that:
  - flagged trials get a 🚩 prepended to their BriefTitle
  - unflagged trials are untouched
  - the operation is idempotent (re-running on already-prefixed titles is a no-op)
  - show_cols is returned unchanged (no `_Flag` column added anymore)

These tests stub out _load_active_flags so we don't hit the GitHub API.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _make_stub_streamlit() -> types.ModuleType:
    """Minimal Streamlit stub so app.py module-level code can run under test."""
    st = types.ModuleType("streamlit")

    class _Col:
        def __getattr__(self, _):
            def _f(*_a, **_k): return None
            return _f
    st.column_config = _Col()

    def _passthrough(*a, **k):
        if len(a) == 1 and callable(a[0]) and not k:
            return a[0]
        def _w(fn): return fn
        return _w

    st.cache_data = _passthrough
    st.cache_resource = _passthrough

    class _Secrets:
        def get(self, *a, **k): return None
    st.secrets = _Secrets()
    st.session_state = {}
    st.query_params = {}
    return st


def _load_attach():
    """Slice out _attach_flag_column from app.py via AST and exec it standalone.

    We only need the function body and its module-level dependencies
    (_FLAG_EMOJI, _load_active_flags). The latter is stubbed per-test
    via a globals dict so we don't hit GitHub during the test.
    """
    import ast as _ast
    src = (Path(__file__).resolve().parent.parent / "app.py").read_text()
    src_lines = src.splitlines()
    tree = _ast.parse(src)
    func_node = next(
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.FunctionDef) and n.name == "_attach_flag_column"
    )
    func_src = "\n".join(
        src_lines[func_node.lineno - 1: func_node.end_lineno]
    )
    stub_loader = """
_FLAG_EMOJI = "\U0001F6A9"
import pandas as pd

def _load_active_flags():
    return globals().get("_TEST_FLAGS", {})
"""
    ns: dict = {}
    exec(stub_loader + "\n" + func_src, ns)
    return ns


def test_unflagged_trials_keep_original_title():
    ns = _load_attach()
    pd = ns["pd"]
    df = pd.DataFrame({
        "NCTId": ["NCT01", "NCT02"],
        "BriefTitle": ["Trial One", "Trial Two"],
    })
    out, cols = ns["_attach_flag_column"](df, ["NCTId", "BriefTitle"])
    assert list(out["BriefTitle"]) == ["Trial One", "Trial Two"]
    assert cols == ["NCTId", "BriefTitle"]


def test_flagged_trial_gets_emoji_prefix():
    ns = _load_attach()
    pd = ns["pd"]
    ns["_TEST_FLAGS"] = {
        "NCT01": {"count": 2, "consensus": False, "issue_urls": []},
    }
    df = pd.DataFrame({
        "NCTId": ["NCT01", "NCT02"],
        "BriefTitle": ["Flagged Trial", "Unflagged Trial"],
    })
    out, cols = ns["_attach_flag_column"](df, ["NCTId", "BriefTitle"])
    assert out.loc[0, "BriefTitle"] == "🚩 Flagged Trial"
    assert out.loc[1, "BriefTitle"] == "Unflagged Trial"
    # No new column added
    assert "_Flag" not in out.columns
    assert cols == ["NCTId", "BriefTitle"]


def test_idempotent_double_call_does_not_double_prefix():
    """Re-running on an already-prefixed df must NOT produce 🚩 🚩 Title."""
    ns = _load_attach()
    pd = ns["pd"]
    ns["_TEST_FLAGS"] = {
        "NCT01": {"count": 1, "consensus": False, "issue_urls": []},
    }
    df = pd.DataFrame({"NCTId": ["NCT01"], "BriefTitle": ["My Trial"]})
    out1, _ = ns["_attach_flag_column"](df, ["NCTId", "BriefTitle"])
    assert out1.loc[0, "BriefTitle"] == "🚩 My Trial"
    out2, _ = ns["_attach_flag_column"](out1, ["NCTId", "BriefTitle"])
    assert out2.loc[0, "BriefTitle"] == "🚩 My Trial"  # not 🚩 🚩 My Trial


def test_consensus_trial_also_gets_prefix():
    """Both open-flag and consensus-reached trials get the same prefix —
    differentiation happens in the drilldown banner, not the title."""
    ns = _load_attach()
    pd = ns["pd"]
    ns["_TEST_FLAGS"] = {
        "NCT01": {"count": 3, "consensus": True, "issue_urls": []},
    }
    df = pd.DataFrame({"NCTId": ["NCT01"], "BriefTitle": ["Consensus Trial"]})
    out, _ = ns["_attach_flag_column"](df, ["NCTId", "BriefTitle"])
    assert out.loc[0, "BriefTitle"] == "🚩 Consensus Trial"


def test_zero_count_entry_does_not_get_prefix():
    """Defensive: an entry with count==0 must not produce a flag prefix."""
    ns = _load_attach()
    pd = ns["pd"]
    ns["_TEST_FLAGS"] = {
        "NCT01": {"count": 0, "consensus": False, "issue_urls": []},
    }
    df = pd.DataFrame({"NCTId": ["NCT01"], "BriefTitle": ["Edge Case"]})
    out, _ = ns["_attach_flag_column"](df, ["NCTId", "BriefTitle"])
    assert out.loc[0, "BriefTitle"] == "Edge Case"


def test_empty_flags_dict_returns_input_unchanged():
    """Most common case (no flags exist anywhere) — early-return path."""
    ns = _load_attach()
    pd = ns["pd"]
    ns["_TEST_FLAGS"] = {}
    df = pd.DataFrame({"NCTId": ["NCT01"], "BriefTitle": ["Anything"]})
    out, cols = ns["_attach_flag_column"](df, ["NCTId", "BriefTitle"])
    assert out.loc[0, "BriefTitle"] == "Anything"
