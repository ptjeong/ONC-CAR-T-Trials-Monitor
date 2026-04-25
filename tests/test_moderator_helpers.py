"""Tests for the moderator-tab pure helpers in app.py.

Avoids importing the whole Streamlit app (which would need a script
context) by AST-extracting the function source for `_cohens_kappa`.
This keeps the test fast and independent of Streamlit's import-time
side effects.

Why these matter: Cohen's κ is the headline statistic in the per-axis
agreement panel of the Moderation tab and (after C10) in the Methods
section. A wrong κ implementation would silently degrade the whole
quality narrative. We anchor it against textbook hand-worked numbers.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


# Stub Streamlit so we can import app.py module-level helpers without
# Streamlit's side-effects. We only need the helpers themselves; the
# stub gives `st.cache_data`, `st.column_config`, etc. the bare-minimum
# attributes their decorators look up.
class _StubColumn:
    def __getattr__(self, _):
        def _wrap(*_args, **_kwargs):
            return None
        return _wrap


def _make_stub_streamlit() -> types.ModuleType:
    st_stub = types.ModuleType("streamlit")
    st_stub.column_config = _StubColumn()

    def _passthrough_decorator(*_d_args, **_d_kwargs):
        # Support both @st.cache_data and @st.cache_data(ttl=…)
        if len(_d_args) == 1 and callable(_d_args[0]) and not _d_kwargs:
            return _d_args[0]
        def _wrap(fn):
            return fn
        return _wrap

    st_stub.cache_data = _passthrough_decorator
    st_stub.cache_resource = _passthrough_decorator
    st_stub.secrets = {}
    st_stub.session_state = {}
    st_stub.query_params = {}
    return st_stub


def _load_kappa():
    """Extract just _cohens_kappa from app.py without importing the rest.

    We grep the source for the def block and exec it standalone — far
    cheaper than loading the whole 5800-line app module just for one
    20-line helper.
    """
    src = (Path(__file__).resolve().parent.parent / "app.py").read_text()
    # Slice from `def _cohens_kappa(` to the next top-level statement
    # (line beginning with a non-space). The function body is indented,
    # so the first column-0 line after it terminates the slice.
    start = src.index("def _cohens_kappa(")
    after = src[start:].splitlines()
    out = [after[0]]
    for line in after[1:]:
        if line.startswith((" ", "\t")) or not line.strip():
            out.append(line)
        else:
            break
    func_src = "\n".join(out)
    ns: dict = {}
    exec(func_src, ns)
    return ns["_cohens_kappa"]


_cohens_kappa = _load_kappa()


def test_kappa_perfect_agreement():
    """Identical sequences → κ == 1."""
    a = ["X", "Y", "X", "Y", "Z"]
    b = ["X", "Y", "X", "Y", "Z"]
    assert _cohens_kappa(a, b) == 1.0


def test_kappa_chance_agreement():
    """A random-looking case where observed == expected → κ ≈ 0."""
    # 50/50 split with no actual correlation: expected = observed = 0.5
    a = ["X", "X", "Y", "Y"]
    b = ["X", "Y", "X", "Y"]
    k = _cohens_kappa(a, b)
    assert k is not None
    assert abs(k) < 1e-9  # exactly 0.0


def test_kappa_perfect_disagreement():
    """Two-class flip → κ should be negative."""
    a = ["X", "X", "X", "Y", "Y", "Y"]
    b = ["Y", "Y", "Y", "X", "X", "X"]
    k = _cohens_kappa(a, b)
    assert k is not None
    assert k < 0


def test_kappa_returns_none_for_too_short():
    assert _cohens_kappa([], []) is None
    assert _cohens_kappa(["X"], ["X"]) is None


def test_kappa_returns_none_when_only_one_category():
    """Cohen's κ is undefined when only one label is present (no variance)."""
    assert _cohens_kappa(["X", "X", "X"], ["X", "X", "X"]) is None


def test_kappa_returns_none_for_unequal_lengths():
    """Defensive: caller bug, return None rather than raise."""
    assert _cohens_kappa(["X", "Y"], ["X"]) is None


def test_kappa_textbook_example():
    """Sim Wright (2005) BMC Med Res Methodol — worked example: κ ≈ 0.40.

    Two raters on 100 subjects, 2-class problem (yes/no):
        a says yes, b says yes: 45
        a says yes, b says no:  15
        a says no,  b says yes: 25
        a says no,  b says no:  15
    p_o = (45 + 15) / 100 = 0.60
    p_yes_a = 60/100, p_no_a = 40/100
    p_yes_b = 70/100, p_no_b = 30/100
    p_e = 0.60*0.70 + 0.40*0.30 = 0.42 + 0.12 = 0.54
    κ = (0.60 - 0.54) / (1 - 0.54) = 0.06 / 0.46 ≈ 0.1304
    """
    a = ["yes"] * 60 + ["no"] * 40   # 60 yes, 40 no
    b = (
        ["yes"] * 45 + ["no"] * 15   # for the 60 a-yes
        + ["yes"] * 25 + ["no"] * 15  # for the 40 a-no
    )
    k = _cohens_kappa(a, b)
    assert k is not None
    assert abs(k - 0.1304) < 0.01
