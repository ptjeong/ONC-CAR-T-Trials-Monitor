"""Inter-rater κ validation study — standalone Streamlit app.

Companion app to the main ONC-CAR-T-Trials-Monitor dashboard. Two
clinical raters (PJ + collaborator) independently classify a locked
random sample of 200 trials on six axes; Cohen's κ between raters
is the primary outcome (with bootstrap 95% CI), agreement with
the pipeline is a secondary outcome.

Methodology (locked 2026-04-26, see methods.md § Inter-rater κ):
  - Sample: validation_study/sample_v1.json (sha256 in manifest;
    pre-registered in commit before raters enrolled)
  - 200 trials stratified 50% Heme-onc / 50% Solid-onc, ≥5 trials
    per major DiseaseCategory
  - Six axes: Branch, DiseaseCategory, DiseaseEntity, TargetCategory,
    ProductType, SponsorType
  - "Unsure" is a first-class option on every axis (don't force a
    guess — better to mark unscorable than fabricate)
  - Pipeline labels are HIDDEN during rating (no anchoring)
  - Raters cannot see each other's classifications

DATA SAFETY (this is a multi-hour clinical rater session — every
single rating must be durable from the moment it leaves the rater's
fingers):
  1. Server-side autosave on every submit  (/tmp/...{token}.json)
  2. Git-committed canonical store          (responses/{rater}.json)
  3. Crash recovery: /tmp newer than git → offer to resume
  4. Visible "Last saved" indicator with stale-threshold warning
  5. Always-visible manual download button
  6. Auto-prompt for backup every 10 trials
  7. "Email progress" mailto: template for non-git-savvy raters
  8. Schema-versioned JSON with sample sha256 + app version
  9. Atomic writes (write to .tmp, rename)
 10. Resume uploads MERGE not replace

Deploy as a separate Streamlit Cloud app pointed at this file:
  https://share.streamlit.io → New app → main file = validation_study/app.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the parent repo importable so we can read sample_v1.json with
# the same path conventions whether running locally or on Streamlit Cloud.
APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"
APP_VERSION = "0.5.1"  # bump when rater UX changes
SAMPLE_PATH = APP_DIR / "sample_v1.json"
RESPONSES_DIR = APP_DIR / "responses"
LOCAL_BACKUP_DIR = Path("/tmp/validation_responses")
LOCAL_BACKUP_DIR.mkdir(exist_ok=True, parents=True)

# Axis options — kept in sync with config.py / app.py's _FLAG_AXIS_OPTIONS.
# "Unsure" is appended to every axis as a first-class option.
AXIS_OPTIONS = {
    "Branch": ["Heme-onc", "Solid-onc", "Mixed", "Unknown", "Unsure"],
    "DiseaseCategory": "_dynamic",   # populated from sample at load time
    "DiseaseEntity": None,            # free text + autocomplete
    "TargetCategory": None,           # free text + autocomplete
    "ProductType": ["Autologous", "Allogeneic/Off-the-shelf", "In vivo",
                    "Unclear", "Unsure"],
    "SponsorType": ["Industry", "Academic", "Government", "Other", "Unsure"],
}

AXIS_HELP = {
    "Branch": "The trial's primary indication: hematologic, solid, mixed, "
              "or unknown.",
    "DiseaseCategory": "Mid-level disease grouping (e.g. B-NHL, GI, CNS). "
                       "Pick the dominant category if multiple apply.",
    "DiseaseEntity": "Most specific disease leaf (e.g. DLBCL, GBM, HCC). "
                     "Use the trial's terminology where possible.",
    "TargetCategory": "The CAR antigen or, for non-antigen platforms, the "
                      "construct family (e.g. CD19, BCMA, CAR-NK, CAAR-T).",
    "ProductType": "Autologous = patient-derived, Allogeneic = "
                   "off-the-shelf donor, In vivo = mRNA-LNP delivery to "
                   "endogenous T cells.",
    "SponsorType": "Industry = for-profit, Academic = university/hospital, "
                   "Government = NIH/NCI/etc., Other = NGO/foundation.",
}

# Progress visualisation — clean unicode block characters, no emoji.
# Filled cell = rated; empty cell = pending.
PROGRESS_FILLED = "■"
PROGRESS_EMPTY = "□"


# ---------------------------------------------------------------------------
# Page config + styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Trial Classification Validation Study",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* Tight typography for a long rater session — clean but with polish.
       Inspired by Linear, Stripe, and the GitHub contributions heatmap:
       sophisticated gamification through CSS, never through emoji. */
    .block-container { max-width: 1100px; padding-top: 2rem; }
    .stRadio > div { gap: 0.4rem; }

    /* Heatmap card — premium, COMPACT. Visible by default at the top of
       every session. Side-by-side: thin grid strip on the left, summary
       stats on the right. Total card height ~120px — gives visual reward
       without eating real estate. */
    .heatmap-card {
        display: flex;
        align-items: center;
        gap: 22px;
        background: linear-gradient(180deg, #ffffff 0%, #fafbfc 100%);
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 16px;
        margin: 4px 0 14px 0;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03),
                    0 2px 8px rgba(15, 23, 42, 0.025);
    }
    .heatmap-grid-wrap {
        flex: 1 1 auto; min-width: 0;
    }
    .heatmap-stats {
        flex: 0 0 auto;
        display: flex; flex-direction: column; align-items: flex-end;
        gap: 2px; min-width: 130px;
    }
    .heatmap-pct {
        font-size: 22px; font-weight: 700; color: #1e40af;
        line-height: 1.0; font-variant-numeric: tabular-nums;
        letter-spacing: -0.02em;
    }
    .heatmap-lbl {
        font-size: 10px; color: #64748b;
        text-transform: uppercase; letter-spacing: 0.6px;
        font-weight: 600;
    }
    .heatmap-count {
        font-size: 11px; color: #475569;
        font-variant-numeric: tabular-nums;
        margin-top: 2px;
    }

    /* Compact heatmap grid — 50 columns × 4 rows for 200 cells.
       Each cell is a tiny pixel-precise square. Three intensity bands
       so the grid has visual texture as it fills. */
    .pgrid {
        display: grid;
        grid-template-columns: repeat(50, 1fr);
        gap: 2px;
        max-width: 100%;
    }
    .pcell {
        width: 100%; aspect-ratio: 1 / 1;
        border-radius: 2px;
        transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1),
                    box-shadow 180ms cubic-bezier(0.16, 1, 0.3, 1),
                    background-color 240ms ease;
    }
    .pcell.empty {
        background: #eef2f7;
        box-shadow: inset 0 0 0 0.5px rgba(203, 213, 225, 0.6);
    }
    .pcell.older {
        background: #6688c8;
    }
    .pcell.recent {
        background: #1e40af;
        box-shadow: 0 0 0 0.5px rgba(30, 64, 175, 0.4);
    }
    .pcell.fresh {
        background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
        box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.4),
                    0 1px 3px rgba(30, 64, 175, 0.4);
    }
    .pcell.empty:hover, .pcell.older:hover,
    .pcell.recent:hover, .pcell.fresh:hover {
        transform: scale(2.2);
        z-index: 2;
        position: relative;
        box-shadow: 0 4px 12px rgba(30, 64, 175, 0.45);
        cursor: default;
    }

    /* Stat tiles — clean numeric callouts in the session-stats panel.
       Big number, small label — the same hierarchy Linear / Stripe use. */
    .stat-tile { display: inline-block; padding: 12px 18px;
                 margin-right: 8px; border-radius: 6px;
                 background: #f8fafc; border: 1px solid #e2e8f0; }
    .stat-tile .num { font-size: 22px; font-weight: 700;
                       color: #0f172a; line-height: 1.0; }
    .stat-tile .lbl { font-size: 11px; color: #64748b;
                       text-transform: uppercase; letter-spacing: 0.5px;
                       margin-top: 4px; }

    /* Save-state indicator: text only, no animation, color-coded by age */
    .save-stale { color: #b91c1c; font-weight: 600; }
    .save-fresh { color: #166534; }

    /* Subtle separator between trials so the page feels rhythmic */
    hr.trial-sep { border: none; border-top: 1px solid #e2e8f0;
                    margin: 24px 0 16px 0; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Token auth
# ---------------------------------------------------------------------------

def _get_rater_identity() -> tuple[str, str] | tuple[None, None]:
    """Return (rater_id, role) where role in {'rater', 'admin'} or (None, None).

    Server-side: VALIDATION_TOKENS env var (or st.secrets) is a JSON dict
    mapping {token_str: {rater_id, role}}. Example:
        {"abc123": {"rater_id": "peter", "role": "rater"},
         "def456": {"rater_id": "drsmith", "role": "rater"},
         "admin789": {"rater_id": "ptjeong", "role": "admin"}}
    """
    token = ""
    try:
        token = st.query_params.get("token", "")
    except Exception:
        pass
    if not token:
        return None, None

    raw = os.environ.get("VALIDATION_TOKENS")
    if not raw:
        try:
            raw = st.secrets.get("validation_tokens", None)
        except Exception:
            raw = None
    if not raw:
        return None, None
    try:
        # secrets can be either a JSON string or a TOML-parsed dict
        tokens = raw if isinstance(raw, dict) else json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, None

    info = tokens.get(token)
    if not info or not isinstance(info, dict):
        return None, None
    return info.get("rater_id", "anon"), info.get("role", "rater")


# ---------------------------------------------------------------------------
# Sample loading
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_sample() -> dict:
    """Load the locked sample manifest. Cached for the session."""
    if not SAMPLE_PATH.exists():
        st.error(f"Sample file not found: {SAMPLE_PATH}. "
                 "Run scripts/generate_validation_sample.py first.")
        st.stop()
    return json.loads(SAMPLE_PATH.read_text())


# ---------------------------------------------------------------------------
# Atomic file ops + storage
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: dict | list) -> None:
    """Write JSON atomically: write to .tmp, then rename. No half-written files."""
    path.parent.mkdir(exist_ok=True, parents=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n")
    tmp_path.replace(path)


def _local_backup_path(rater_id: str) -> Path:
    return LOCAL_BACKUP_DIR / f"{rater_id}.json"


def _committed_responses_path(rater_id: str) -> Path:
    return RESPONSES_DIR / f"{rater_id}.json"


def _load_persisted_responses(rater_id: str) -> dict:
    """Return the most recent persisted state for this rater.

    Resolution: the file with the latest `last_updated` timestamp wins,
    falling back to the committed file if the local backup is missing
    or older. Schema-validated; bad files return empty state with a
    warning so the rater isn't blocked.
    """
    sources: list[tuple[Path, dict]] = []
    for p in (_local_backup_path(rater_id), _committed_responses_path(rater_id)):
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            st.warning(f"Could not parse {p.name}: {e}. Ignored.")
            continue
        if doc.get("schema_version") != SCHEMA_VERSION:
            st.warning(f"{p.name} has incompatible schema version "
                       f"{doc.get('schema_version')!r} (expected {SCHEMA_VERSION!r}). "
                       "Ignored.")
            continue
        sources.append((p, doc))

    if not sources:
        return _empty_state(rater_id)

    sources.sort(key=lambda t: t[1].get("last_updated", ""), reverse=True)
    return sources[0][1]


def _empty_state(rater_id: str) -> dict:
    sample = _load_sample()
    return {
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "rater_id": rater_id,
        "sample_version": sample.get("version", "?"),
        "sample_sha256": sample.get("sha256", "?"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "ratings": {},        # nct_id → {labels, durations, notes, timestamp}
        "session_log": [],    # list of {start, end, n_rated} per session
    }


def _persist(state: dict) -> None:
    """Write state to local /tmp backup. Called on every submit."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["app_version"] = APP_VERSION
    rater_id = state.get("rater_id", "anon")
    _atomic_write_json(_local_backup_path(rater_id), state)


# ---------------------------------------------------------------------------
# Garden gamification
# ---------------------------------------------------------------------------

def _progress_grid_html(state: dict, sample: dict) -> str:
    """Render the compact progress heatmap card — visible by default.

    Three intensity bands give the grid visual texture as it fills:
      - fresh   = the 5 most-recently-rated trials (gradient + glow)
      - recent  = next 25 rated (saturated navy)
      - older   = everything else rated (slightly desaturated navy)
      - empty   = pending (subtle slate)

    Side-by-side card layout: thin grid strip on the left, summary
    stats (percentage + count) on the right. Total height ~120px.
    """
    n_total = len(sample["trials"])
    ratings = state.get("ratings", {})
    n_done = len(ratings)

    # Order rated NCTs by timestamp (most recent first) to assign tiers
    rated_with_ts = sorted(
        [(nct, r.get("timestamp", "")) for nct, r in ratings.items()],
        key=lambda t: t[1] or "",
        reverse=True,
    )
    fresh_set = {nct for nct, _ in rated_with_ts[:5]}
    recent_set = {nct for nct, _ in rated_with_ts[5:30]}

    cells = []
    for trial in sample["trials"]:
        nct = trial["NCTId"]
        if nct in fresh_set:
            cells.append(
                f'<div class="pcell fresh" title="{nct} — just rated"></div>'
            )
        elif nct in recent_set:
            cells.append(
                f'<div class="pcell recent" title="{nct} — recent"></div>'
            )
        elif nct in ratings:
            cells.append(
                f'<div class="pcell older" title="{nct} — rated"></div>'
            )
        else:
            cells.append(
                f'<div class="pcell empty" title="{nct} — pending"></div>'
            )
    pct = (n_done / n_total * 100) if n_total else 0
    return (
        f'<div class="heatmap-card">'
        f'  <div class="heatmap-grid-wrap">'
        f'    <div class="pgrid">{"".join(cells)}</div>'
        f'  </div>'
        f'  <div class="heatmap-stats">'
        f'    <div class="heatmap-pct">{pct:.0f}%</div>'
        f'    <div class="heatmap-lbl">complete</div>'
        f'    <div class="heatmap-count">{n_done} / {n_total} trials</div>'
        f'  </div>'
        f'</div>'
    )


def _stat_tiles_html(stats: list[tuple[str, str]]) -> str:
    """Render a row of stat tiles for the session-stats panel.

    Each tile = (number, label). Stripe/Linear-style typography:
    large number, small all-caps label below. Sophisticated, never
    cartoonish.
    """
    tiles = "".join(
        f'<div class="stat-tile">'
        f'  <div class="num">{num}</div>'
        f'  <div class="lbl">{lbl}</div>'
        f'</div>'
        for num, lbl in stats
    )
    return f'<div>{tiles}</div>'


def _milestone_message(n_done: int, median_secs: int = 0) -> str | None:
    """Sophisticated milestone messages — informative, never childish.

    Each milestone surfaces a real stat or piece of methodology context
    that the rater would actually find interesting. The reward is
    knowledge, not confetti.
    """
    n_left = max(0, 200 - n_done)
    eta_min = (median_secs * n_left) / 60 if median_secs else None

    def _eta_clause() -> str:
        if eta_min is None:
            return ""
        if eta_min < 60:
            return f" Median pace says ~{eta_min:.0f} min remaining."
        return (f" Median pace says ~{eta_min/60:.1f} h remaining "
                f"(~{eta_min:.0f} min).")

    if n_done == 25:
        return ("Quartile 1 complete (25 trials, 12.5%)."
                + _eta_clause()
                + " Baseline rhythm established; subsequent sessions "
                "typically run faster.")
    if n_done == 50:
        return ("First half of half complete (50 trials, 25%)."
                + _eta_clause()
                + " Inter-rater κ studies typically need ≥100 to power "
                "detection of κ ≥ 0.40; you're already past half of that.")
    if n_done == 75:
        return ("Three eighths complete (75 trials, 37.5%)."
                + _eta_clause())
    if n_done == 100:
        return ("Halfway: 100 trials rated."
                + _eta_clause()
                + " Now is the right time for a short break — fatigue "
                "effects on κ become detectable past ~60 min of "
                "uninterrupted rating (Gwet 2014).")
    if n_done == 125:
        return ("Five eighths complete (125 trials, 62.5%)."
                + _eta_clause())
    if n_done == 150:
        return ("Three quarters complete (150 trials, 75%)."
                + _eta_clause()
                + " The bootstrap CI on κ stabilises around N=150 — your "
                "remaining ratings tighten the interval rather than "
                "shifting the point estimate.")
    if n_done == 175:
        return ("Final stretch: 25 trials remaining."
                + _eta_clause())
    if n_done == 200:
        return ("Complete: all 200 trials rated. Your submission is "
                "preserved on the server. Please use **Download FINAL "
                "submission** below and email the JSON to "
                "peter.jeong@uk-koeln.de. The κ analysis runs once both "
                "rater files are committed.")
    return None


def _session_stats_html(state: dict) -> str:
    """Build the stat-tile row shown above the rating area.

    Surfaces: trials rated, median seconds per trial, total time spent,
    estimated time to completion. Makes the rater aware of their own
    pace — same psychology as a runner watching pace tick down.
    """
    n_done = len(state["ratings"])
    durations = [r.get("duration_seconds", 0) for r in state["ratings"].values()
                 if not r.get("skipped")]
    n_left = max(0, 200 - n_done)
    if durations:
        median_s = sorted(durations)[len(durations) // 2]
        total_min = sum(durations) / 60
        eta_min = (median_s * n_left) / 60
    else:
        median_s = 0
        total_min = 0
        eta_min = 0

    def _fmt_min(m: float) -> str:
        if m < 1:
            return "—"
        if m < 60:
            return f"{m:.0f} min"
        return f"{m/60:.1f} h"

    return _stat_tiles_html([
        (f"{n_done}/200", "rated"),
        (f"{median_s}s" if median_s else "—", "median per trial"),
        (_fmt_min(total_min), "session time"),
        (_fmt_min(eta_min), "est. remaining"),
    ])


# ---------------------------------------------------------------------------
# Rater workflow
# ---------------------------------------------------------------------------

def _next_unrated_trial(state: dict, sample: dict) -> dict | None:
    """First trial in sample order that hasn't been rated yet."""
    for trial in sample["trials"]:
        if trial["NCTId"] not in state["ratings"]:
            return trial
    return None


def _scrollbox(label: str, content: str, *, max_height: int = 240,
                accent: str = "#cbd5e1") -> None:
    """Reusable scrollable text panel — used for long-form CT.gov fields."""
    if not content:
        return
    st.markdown(f"**{label}**")
    st.markdown(
        f"<div style='max-height:{max_height}px; overflow-y:auto; "
        f"padding:8px 12px; background:#f8fafc; "
        f"border-left:3px solid {accent}; border-radius:4px; "
        f"font-size:0.92em; white-space:pre-wrap;'>"
        f"{_html_escape(content)}</div>",
        unsafe_allow_html=True,
    )


def _html_escape(s: str) -> str:
    """Minimal HTML escape so trial text doesn't break the markdown div."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_trial_for_rater(trial: dict) -> None:
    """Render the trial info — ONLY the raw evidence, no pipeline labels.

    Layout is optimized for one-glance scannability with progressive
    disclosure for long-form fields:

      ABOVE THE FOLD (always visible — sufficient for ~70% of trials):
        - Title
        - Metadata chip row (NCT link · Phase · Status · Sponsor + class · Design)
        - Conditions + Interventions side-by-side (highest-signal)
        - Brief summary (scrollable, max-height 240px)

      BELOW THE FOLD (in expanders — open when context insufficient):
        - Detailed description (often 5-10× the BriefSummary)
        - Eligibility criteria (disease-defining inclusion/exclusion)
        - Intervention + arm group details (antigen + product type signals)
        - Primary endpoints + study design (interventional/observational, etc.)
        - Sponsor + collaborators (SponsorType signal)
        - Direct CT.gov link (full record)
    """
    nct = trial["NCTId"]
    title = trial.get("BriefTitle") or "(no title)"
    st.markdown(f"#### {title}")

    # Build the metadata chip row — adds LeadSponsorClass to give the
    # rater an immediate hint for SponsorType (INDUSTRY/OTHER/NIH/etc.)
    sponsor_str = trial.get("LeadSponsor") or "—"
    if trial.get("LeadSponsorClass"):
        sponsor_str = f"{sponsor_str} ({trial['LeadSponsorClass']})"
    st.caption(
        f"[{nct}](https://clinicaltrials.gov/study/{nct}) · "
        f"**Phase:** {trial.get('Phase') or '—'} · "
        f"**Status:** {trial.get('OverallStatus') or '—'} · "
        f"**Sponsor:** {sponsor_str} · "
        f"**Design:** {trial.get('TrialDesign') or '—'} · "
        f"**Enrollment:** {trial.get('EnrollmentCount') or '—'} · "
        f"**Started:** {(trial.get('StartDate') or '—')[:10]}"
    )
    if trial.get("Countries"):
        st.caption(f"**Countries:** {trial['Countries']}")

    # Conditions + Interventions side-by-side (highest-signal fields)
    _ec1, _ec2 = st.columns(2)
    with _ec1:
        if trial.get("Conditions"):
            st.markdown(f"**Conditions**")
            st.markdown(f"<small>{_html_escape(trial['Conditions'])}</small>",
                        unsafe_allow_html=True)
        if trial.get("ConditionKeywords"):
            st.caption(f"_Keywords:_ {trial['ConditionKeywords']}")
    with _ec2:
        if trial.get("Interventions"):
            st.markdown(f"**Interventions**")
            st.markdown(
                f"<small>{_html_escape(trial['Interventions'])}</small>",
                unsafe_allow_html=True,
            )

    # Brief summary always visible (no expander click)
    _scrollbox("Brief summary", trial.get("BriefSummary") or "")

    # ---- Below-the-fold: expanders for deep context ----
    # These open progressively. Most trials are classifiable from above-fold
    # alone; expanders unlock fast for the hard ones.

    # The longest-form fields are gated behind expanders so the page is
    # scannable on first render. Single column (full-width) inside each
    # expander so the text isn't squeezed.

    if trial.get("DetailedDescription"):
        with st.expander(
            f"Detailed description "
            f"({len(trial['DetailedDescription'])} chars)",
            expanded=False,
        ):
            _scrollbox(
                "", trial["DetailedDescription"],
                max_height=400, accent="#3b82f6",
            )

    if trial.get("InterventionDescription"):
        with st.expander(
            "Intervention details (antigen / construct / route)",
            expanded=False,
        ):
            _scrollbox(
                "", trial["InterventionDescription"],
                max_height=300, accent="#10b981",
            )
            if trial.get("ArmGroupDescriptions"):
                _scrollbox(
                    "Arm groups", trial["ArmGroupDescriptions"],
                    max_height=200, accent="#10b981",
                )

    if trial.get("EligibilityCriteria"):
        with st.expander(
            f"Eligibility criteria "
            f"({len(trial['EligibilityCriteria'])} chars — often disease-defining)",
            expanded=False,
        ):
            _scrollbox(
                "", trial["EligibilityCriteria"],
                max_height=400, accent="#f59e0b",
            )

    if trial.get("PrimaryEndpoints"):
        with st.expander(
            "Primary endpoints + study design", expanded=False,
        ):
            _scrollbox(
                "", trial["PrimaryEndpoints"],
                max_height=240, accent="#8b5cf6",
            )
            design_bits = []
            if trial.get("StudyType"):
                design_bits.append(f"**Study type:** {trial['StudyType']}")
            if trial.get("Allocation"):
                design_bits.append(f"**Allocation:** {trial['Allocation']}")
            if trial.get("InterventionModel"):
                design_bits.append(
                    f"**Intervention model:** {trial['InterventionModel']}"
                )
            if trial.get("Masking"):
                design_bits.append(f"**Masking:** {trial['Masking']}")
            if design_bits:
                st.markdown(" · ".join(design_bits))

    if trial.get("CollaboratorNames") or trial.get("ResponsiblePartyType"):
        with st.expander(
            "Sponsor + collaborators (SponsorType signal)",
            expanded=False,
        ):
            st.markdown(
                f"**Lead sponsor:** {trial.get('LeadSponsor') or '—'}"
            )
            if trial.get("LeadSponsorClass"):
                st.markdown(
                    f"**LeadSponsorClass (CT.gov):** "
                    f"`{trial['LeadSponsorClass']}`"
                )
            if trial.get("CollaboratorNames"):
                st.markdown(
                    f"**Collaborators:** {trial['CollaboratorNames']}"
                )
            if trial.get("ResponsiblePartyType"):
                st.markdown(
                    f"**Responsible party:** "
                    f"{trial.get('ResponsiblePartyName') or '—'} "
                    f"({trial['ResponsiblePartyType']})"
                )

    # Always-visible direct CT.gov link at the bottom — for raters who want
    # to verify against the live record (or check anything we didn't cache).
    st.caption(
        f"**Anything else you need?** "
        f"[Open the full record on ClinicalTrials.gov ↗]"
        f"(https://clinicaltrials.gov/study/{nct}) "
        f"(opens in a new tab)."
    )


def _render_axis_input(axis: str, sample: dict, key: str) -> str:
    """Render a single axis input. Returns the chosen value (or "").

    Three input modes by axis type:
      - Enumerable (Branch / ProductType / SponsorType): radio buttons
      - Categorical with many levels (DiseaseCategory): dropdown +
        "Other (specify)" text fallback
      - Free-text-with-suggestions (DiseaseEntity / TargetCategory):
        selectbox of the canonical vocabulary + "Other (specify)" text
        fallback. Standardizes spelling so κ doesn't get artificially
        deflated by 'DLBCL' vs 'Diffuse large B-cell lymphoma'.
    """
    options = AXIS_OPTIONS.get(axis)

    if options == "_dynamic":
        # DiseaseCategory — populated from the sample's pipeline labels
        cats = sorted({
            t["_pipeline"].get("DiseaseCategory") or ""
            for t in sample["trials"]
        } - {""})
        options = cats + ["Other (specify)", "Unsure"]
        choice = st.selectbox(
            axis, options=[""] + options, key=key,
            help=AXIS_HELP[axis], index=0,
            format_func=lambda x: "(pick one)" if not x else x,
        )
        if choice == "Other (specify)":
            other = st.text_input(
                f"Specify {axis}", key=f"{key}_other",
                placeholder="Type the category you'd use",
            ).strip()
            return other or ""
        return choice or ""

    if options is None:
        # Free-text-with-suggestions axis (DiseaseEntity, TargetCategory)
        vocab = sample.get("autocomplete_vocab", {}).get(axis, [])
        choices = [""] + sorted(vocab) + ["Other (specify)", "Unsure"]
        choice = st.selectbox(
            axis, options=choices, key=key,
            help=AXIS_HELP[axis], index=0,
            format_func=lambda x: ("(pick from canonical list, "
                                    "or 'Other' to type)" if not x else x),
        )
        if choice == "Other (specify)":
            other = st.text_input(
                f"Specify {axis}", key=f"{key}_other",
                placeholder="Type the value you'd use",
            ).strip()
            return other or ""
        return choice or ""

    # Enumerable axis — horizontal radio for tightness
    return st.radio(
        axis, options=options, key=key, horizontal=True,
        help=AXIS_HELP[axis], index=None,
    ) or ""


def _render_rater(rater_id: str) -> None:
    """Main rater workflow: one trial at a time + garden + safety nets."""
    sample = _load_sample()
    if "state" not in st.session_state:
        st.session_state["state"] = _load_persisted_responses(rater_id)
    state = st.session_state["state"]

    n_done = len(state["ratings"])
    n_total = len(sample["trials"])

    # ---- Top header: progress + save status + always-on manual save ----
    _c1, _c2, _c3 = st.columns([0.55, 0.25, 0.20])
    with _c1:
        st.progress(n_done / n_total, text=f"**{n_done} / {n_total} trials rated**")
    with _c2:
        last_save = state.get("last_updated", "—")
        try:
            dt = datetime.fromisoformat(last_save.replace("Z", "+00:00"))
            secs_ago = (datetime.now(timezone.utc) - dt).total_seconds()
            stale = secs_ago > 120
            klass = "save-stale" if stale else "save-fresh"
            label = (f"{int(secs_ago)}s ago — save!" if stale
                     else f"saved {int(secs_ago)}s ago")
            st.markdown(
                f"<small>Last saved: <span class='{klass}'>{label}</span></small>",
                unsafe_allow_html=True,
            )
        except Exception:
            st.caption("Last saved: —")
    with _c3:
        st.download_button(
            "Download progress",
            data=json.dumps(state, indent=2),
            file_name=f"{rater_id}_progress_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            help="Save a backup to your computer. Do this whenever you "
                 "leave for a break — it's your safety net if the server "
                 "restarts.",
            use_container_width=True,
        )

    # ---- Compact heatmap card — visible by default, sleek + tight ----
    # Side-by-side card: 50-col × 4-row strip on the left, big percent +
    # count on the right. ~120px tall. Hover any cell for the NCT ID.
    # Three intensity tiers (fresh/recent/older) give the visual texture.
    st.markdown(_progress_grid_html(state, sample), unsafe_allow_html=True)

    # ---- Session stats tile row (live pace + ETA) ----
    st.markdown(_session_stats_html(state), unsafe_allow_html=True)

    # ---- Milestone banner (informative + methodologically grounded) ----
    _durations_for_msg = [
        r.get("duration_seconds", 0) for r in state["ratings"].values()
        if not r.get("skipped")
    ]
    _median_for_msg = (
        sorted(_durations_for_msg)[len(_durations_for_msg) // 2]
        if _durations_for_msg else 0
    )
    msg = _milestone_message(n_done, median_secs=_median_for_msg)
    if msg and st.session_state.get("last_milestone_shown") != n_done:
        st.success(msg)
        st.session_state["last_milestone_shown"] = n_done

    # ---- Done? ----
    if n_done >= n_total:
        _render_done(state, rater_id)
        return

    # ---- Current trial ----
    trial = _next_unrated_trial(state, sample)
    if trial is None:
        _render_done(state, rater_id)
        return

    nct = trial["NCTId"]
    st.divider()
    _format_trial_for_rater(trial)
    st.divider()

    st.markdown(f"#### Classify this trial across the six axes")
    st.caption("Pipeline labels are deliberately hidden. If you can't make a "
               "confident call, mark **Unsure** — that's data, not failure.")

    # Track time-on-trial — start the clock when this trial is first shown
    timer_key = f"timer_{nct}"
    if timer_key not in st.session_state:
        st.session_state[timer_key] = time.time()

    # Two-column layout for the six axes (3 left, 3 right)
    axes = list(AXIS_OPTIONS.keys())
    col_l, col_r = st.columns(2)
    user_labels: dict[str, str] = {}
    with col_l:
        for axis in axes[:3]:
            user_labels[axis] = _render_axis_input(axis, sample, key=f"input_{nct}_{axis}")
    with col_r:
        for axis in axes[3:]:
            user_labels[axis] = _render_axis_input(axis, sample, key=f"input_{nct}_{axis}")

    notes = st.text_input(
        "Notes (optional)",
        key=f"notes_{nct}",
        placeholder="Any rationale, ambiguity, or note for adjudication.",
    )

    # ---- Submit ----
    _submit_c1, _submit_c2 = st.columns([0.7, 0.3])
    with _submit_c1:
        skip = st.button("Skip this trial (don't record)",
                          key=f"skip_{nct}",
                          help="Use sparingly — every skip reduces κ statistical power.")
    with _submit_c2:
        submit = st.button(
            f"Submit + next ({n_done + 1}/{n_total}) →",
            key=f"submit_{nct}",
            type="primary",
            use_container_width=True,
        )

    if skip:
        # Record the skip (still durable; lets us report skip rate)
        state["ratings"][nct] = {
            "labels": {ax: "Skipped" for ax in AXIS_OPTIONS},
            "notes": "[skipped by rater]",
            "duration_seconds": int(time.time() - st.session_state[timer_key]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skipped": True,
        }
        _persist(state)
        st.session_state.pop(timer_key, None)
        st.rerun()

    if submit:
        # Validate: every axis must be filled (Unsure counts)
        unfilled = [ax for ax, v in user_labels.items() if not v]
        if unfilled:
            st.error(f"Please answer every axis (or pick 'Unsure'). "
                     f"Missing: {', '.join(unfilled)}")
            return
        state["ratings"][nct] = {
            "labels": user_labels,
            "notes": notes.strip(),
            "duration_seconds": int(time.time() - st.session_state[timer_key]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skipped": False,
        }
        _persist(state)
        st.session_state.pop(timer_key, None)

        # Auto-prompt for backup every 10 ratings
        if (n_done + 1) % 10 == 0:
            st.toast(
                f"{n_done + 1} done — please click 'Download progress' "
                f"as a backup. Takes 2 sec.",
            )
        st.rerun()

    # ---- Footer: median time + email ----
    _render_footer(state, rater_id)


def _render_footer(state: dict, rater_id: str) -> None:
    """Bottom-of-page utilities: median time, email backup, resume upload."""
    durations = [r.get("duration_seconds", 0) for r in state["ratings"].values()
                 if not r.get("skipped")]
    if durations:
        med = sorted(durations)[len(durations) // 2]
        n_left = 200 - len(state["ratings"])
        eta_min = (med * n_left) / 60
        st.divider()
        st.caption(
            f"Median time per trial so far: **{med}s**. "
            f"Estimated time remaining: **~{eta_min:.0f} min** "
            f"({n_left} trials left). Take breaks — fatigue degrades κ."
        )

    # Email backup template (mailto: with body) — works in any mail client.
    # The JSON itself is too large to fit in a mailto: body for full
    # progress, so we send a stub message + ask the rater to attach the
    # downloaded JSON manually. Lower friction for non-technical raters.
    n_done = len(state["ratings"])
    subj = f"Validation study progress — {rater_id} ({n_done}/200)"
    body = (
        f"Hi Peter,\n\nI've rated {n_done}/200 trials so far. "
        f"Attaching my progress JSON (downloaded just now).\n\n"
        f"Sample: {state.get('sample_sha256', '?')[:12]}…\n\n"
        f"Thanks!\n"
    )
    import urllib.parse as _up
    mailto = (
        f"mailto:peter.jeong@uk-koeln.de?"
        f"subject={_up.quote(subj)}&body={_up.quote(body)}"
    )
    st.markdown(
        f"[Email progress to Peter (open mail client + attach the JSON)]({mailto})",
        unsafe_allow_html=True,
    )

    # Resume from upload — MERGE not replace
    with st.expander("Resume from a previously-downloaded JSON file"):
        uploaded = st.file_uploader(
            "Upload JSON to merge with your current progress",
            type="json", key="resume_upload",
            help="Only NCTs missing from your current state will be filled "
                 "in. Existing ratings are never overwritten.",
        )
        if uploaded:
            try:
                doc = json.loads(uploaded.getvalue())
                if doc.get("schema_version") != SCHEMA_VERSION:
                    st.error(f"Schema mismatch: file has "
                             f"{doc.get('schema_version')!r}, expected "
                             f"{SCHEMA_VERSION!r}.")
                else:
                    n_added = 0
                    for nct, rec in doc.get("ratings", {}).items():
                        if nct not in state["ratings"]:
                            state["ratings"][nct] = rec
                            n_added += 1
                    if n_added:
                        _persist(state)
                        st.success(f"Merged {n_added} new ratings. Refresh to continue.")
                    else:
                        st.info("No new ratings to merge — your current state "
                                "already has all of them.")
            except json.JSONDecodeError as e:
                st.error(f"Couldn't parse the uploaded JSON: {e}")


def _render_done(state: dict, rater_id: str) -> None:
    """All 200 done — celebration + final-submission instructions."""
    st.success(
        f"### Complete: {len(state['ratings'])} trials rated.\n\n"
        "Your contribution is preserved on the server. **One last step:**"
    )
    st.markdown(
        "1. Click **Download progress** at the top-right one final time. "
        "Save the JSON somewhere safe.\n"
        "2. Email it to **peter.jeong@uk-koeln.de** with subject "
        f"**[validation-final] {rater_id}**.\n"
        "3. Peter commits it to `validation_study/responses/` and the "
        "κ analysis runs.\n\n"
        "Thank you for the time and the careful judgment — you're "
        "the difference between a tool and a published methodology."
    )

    # Always-visible final download
    st.download_button(
        "Download FINAL submission",
        data=json.dumps(state, indent=2),
        file_name=f"{rater_id}_FINAL.json",
        mime="application/json",
        type="primary",
    )


# ---------------------------------------------------------------------------
# Admin view (separate role)
# ---------------------------------------------------------------------------

_ADJUDICATED_PATH = APP_DIR / "adjudicated_v1.json"
NON_RATING_LABELS_ADMIN = {"Unsure", "Skipped", "", None}

# Flag-triage subsystem — pulls open community classification-flag GitHub
# issues into the validation app's admin role so the moderator can triage
# them in the same one-item-at-a-time flow as the adjudication queue,
# instead of clicking through the GitHub UI manually.
GITHUB_REPO_SLUG = os.environ.get(
    "FLAG_REPO_SLUG", "ptjeong/ONC-CAR-T-Trials-Monitor"
)
FLAG_TRIAGE_LOG_PATH = APP_DIR / "moderator_flag_decisions.json"


@st.cache_data(ttl=60 * 5, show_spinner=False)
def _admin_load_active_flags() -> list[dict]:
    """Fetch open classification-flag issues, ordered by recency.

    Returns a list of issue dicts (filtered to those carrying the
    consensus-reached label — those are the ones that have hit
    the threshold and are awaiting moderator review). Cached 5 min
    so triage clicks don't re-hit the rate limit.
    """
    try:
        import requests
        url = (
            f"https://api.github.com/repos/{GITHUB_REPO_SLUG}/issues"
            "?state=open&labels=classification-flag,consensus-reached"
            "&per_page=100&sort=updated&direction=desc"
        )
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        return resp.json() or []
    except Exception:
        return []


@st.cache_data(ttl=60 * 5, show_spinner=False)
def _admin_load_issue_detail(issue_number: int) -> dict:
    """Fetch the full issue body + comments for one classification-flag.

    Parses the BEGIN_FLAG_DATA YAML blocks out of the body + every
    human comment. Returns:
        {"title": str, "body_md": str, "author": str,
         "html_url": str, "proposals": [...], "comments": [...]}
    """
    out = {"proposals": [], "comments": []}
    try:
        import requests, re as _re
        api = f"https://api.github.com/repos/{GITHUB_REPO_SLUG}/issues/{issue_number}"
        r = requests.get(api, timeout=8)
        if r.status_code != 200:
            return out
        issue = r.json()
        out["title"] = issue.get("title", "")
        out["body_md"] = issue.get("body", "") or ""
        out["html_url"] = issue.get("html_url", "")
        out["author"] = (issue.get("user") or {}).get("login", "")
        out["created_at"] = issue.get("created_at", "")

        # Comments (human only — exclude bot)
        cr = requests.get(f"{api}/comments?per_page=100", timeout=8)
        if cr.status_code == 200:
            for c in cr.json() or []:
                author = (c.get("user") or {}).get("login", "")
                if author.endswith("[bot]"):
                    continue
                out["comments"].append({
                    "author": author,
                    "body": c.get("body", "") or "",
                    "created_at": c.get("created_at", ""),
                    "html_url": c.get("html_url", ""),
                })

        # Parse all BEGIN_FLAG_DATA YAML blocks across body + comments
        block_re = _re.compile(
            r"<!--\s*BEGIN_FLAG_DATA\s*\n(.*?)END_FLAG_DATA\s*-->",
            _re.DOTALL,
        )
        try:
            import yaml as _yaml_admin
            yaml_safe = _yaml_admin.safe_load
        except ImportError:
            yaml_safe = None

        all_texts = [(out["author"], out["body_md"])]
        all_texts += [(c["author"], c["body"]) for c in out["comments"]]
        for author, text in all_texts:
            for blk in block_re.finditer(text or ""):
                if yaml_safe:
                    try:
                        data = yaml_safe(blk.group(1))
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    for ax in (data.get("flagged_axes") or []):
                        if isinstance(ax, dict) and ax.get("axis"):
                            out["proposals"].append({
                                "author": author,
                                "axis": ax.get("axis", "").strip(),
                                "pipeline_label": ax.get("pipeline_label") or "",
                                "proposed_correction": ax.get("proposed_correction") or "",
                            })
        return out
    except Exception:
        return out


def _admin_load_flag_decisions() -> dict:
    """Local persistent log of moderator flag decisions, keyed by NCT."""
    if not FLAG_TRIAGE_LOG_PATH.exists():
        return {}
    try:
        return json.loads(FLAG_TRIAGE_LOG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _admin_save_flag_decision(nct: str, decision: dict) -> None:
    """Append a moderator decision atomically. The decision dict carries
    the full audit context: rater, axis, proposed, gold, rationale, etc."""
    log = _admin_load_flag_decisions()
    log[nct] = decision
    _atomic_write_json(FLAG_TRIAGE_LOG_PATH, log)


def _admin_post_github_action(
    issue_number: int,
    *,
    comment_body: str,
    label_to_add: str | None = None,
    close: bool = False,
    token: str | None = None,
) -> tuple[bool, str]:
    """Write back to GitHub: comment + optional label + optional close.

    Returns (success, message). On any error, returns (False, error_text)
    — the local moderator_flag_decisions.json record is the durable
    audit; GitHub writeback is best-effort.
    """
    if not token:
        return False, ("GH_MODERATOR_TOKEN not set — decision recorded "
                        "locally only. Set the secret to enable GitHub writeback.")
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api = f"https://api.github.com/repos/{GITHUB_REPO_SLUG}/issues/{issue_number}"

        # 1. Post the comment
        cr = requests.post(
            f"{api}/comments",
            headers=headers, timeout=10,
            json={"body": comment_body},
        )
        if cr.status_code not in (200, 201):
            return False, f"Comment failed: HTTP {cr.status_code}: {cr.text[:200]}"

        # 2. Apply the label
        if label_to_add:
            lr = requests.post(
                f"{api}/labels",
                headers=headers, timeout=10,
                json={"labels": [label_to_add]},
            )
            if lr.status_code not in (200, 201):
                return False, f"Label failed: HTTP {lr.status_code}: {lr.text[:200]}"

        # 3. Close the issue
        if close:
            xr = requests.patch(
                api, headers=headers, timeout=10,
                json={"state": "closed", "state_reason": "completed"},
            )
            if xr.status_code != 200:
                return False, f"Close failed: HTTP {xr.status_code}: {xr.text[:200]}"

        return True, "GitHub updated."
    except Exception as e:  # noqa: BLE001
        return False, f"Network error: {e}"


def _admin_get_moderator_token() -> str | None:
    """Pull the moderator's GitHub PAT from env or st.secrets."""
    token = os.environ.get("GH_MODERATOR_TOKEN")
    if token:
        return token
    try:
        return st.secrets.get("gh_moderator_token", None)
    except Exception:
        return None


def _load_adjudicated() -> dict:
    """Load committed adjudicated gold-standard labels.

    Schema: {nct_id: {axis: gold_label, ...}, "_meta": {...}}
    """
    if not _ADJUDICATED_PATH.exists():
        return {"_meta": {
            "schema_version": SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }}
    try:
        return json.loads(_ADJUDICATED_PATH.read_text())
    except json.JSONDecodeError:
        return {"_meta": {"corrupted": True}}


def _save_adjudicated(adj: dict) -> None:
    """Atomic write of the adjudicated truth file."""
    adj["_meta"] = {
        **(adj.get("_meta") or {}),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
    }
    _atomic_write_json(_ADJUDICATED_PATH, adj)


def _disagreements(rater_docs: dict[str, dict]) -> list[dict]:
    """List every (nct_id, axis) where two raters disagree (excluding
    Unsure/Skipped, which aren't classifications).

    Returns flat list, sorted by NCT then axis, suitable for sequential
    moderator triage.
    """
    if len(rater_docs) < 2:
        return []
    rater_ids = sorted(rater_docs.keys())
    out = []
    a_id, b_id = rater_ids[0], rater_ids[1]  # only first pair for now
    a_doc, b_doc = rater_docs[a_id], rater_docs[b_id]
    common = sorted(set(a_doc.get("ratings", {})) & set(b_doc.get("ratings", {})))
    for nct in common:
        a_rec = a_doc["ratings"][nct]
        b_rec = b_doc["ratings"][nct]
        for axis in AXIS_OPTIONS:
            la = a_rec.get("labels", {}).get(axis)
            lb = b_rec.get("labels", {}).get(axis)
            if la in NON_RATING_LABELS_ADMIN or lb in NON_RATING_LABELS_ADMIN:
                continue
            if la != lb:
                out.append({
                    "nct_id": nct, "axis": axis,
                    "rater_a": a_id, "rater_b": b_id,
                    "label_a": la, "label_b": lb,
                    "notes_a": a_rec.get("notes", ""),
                    "notes_b": b_rec.get("notes", ""),
                })
    return out


def _render_admin(rater_id: str) -> None:
    sample = _load_sample()
    st.title(f"Admin — {rater_id}")
    st.caption(f"Sample: {sample['sha256'][:16]}… · N={sample['n']} · "
               f"Schema v{SCHEMA_VERSION} · App v{APP_VERSION}")

    tab_status, tab_adj, tab_flags = st.tabs([
        "Rater status", "Adjudication queue", "Flag triage",
    ])

    # --- Tab 1: rater status ---
    with tab_status:
        rater_files = sorted(RESPONSES_DIR.glob("*.json"))
        if not rater_files:
            st.info(
                "No committed rater responses yet. Final submissions go in "
                f"`{RESPONSES_DIR.relative_to(REPO_ROOT)}/`. Each rater "
                "emails their final JSON, you commit it as `<rater_id>.json`."
            )
            return
        rows = []
        for rp in rater_files:
            try:
                doc = json.loads(rp.read_text())
            except Exception:
                continue
            n_done = len(doc.get("ratings", {}))
            n_skipped = sum(1 for r in doc.get("ratings", {}).values()
                            if r.get("skipped"))
            durations = [r.get("duration_seconds", 0)
                         for r in doc.get("ratings", {}).values()
                         if not r.get("skipped")]
            median_s = (sorted(durations)[len(durations) // 2]
                        if durations else 0)
            rows.append({
                "Rater": doc.get("rater_id", rp.stem),
                "N rated": n_done,
                "N skipped": n_skipped,
                "Median time/trial (s)": median_s,
                "Last updated": doc.get("last_updated", "—"),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.info(
            "When all raters have submitted: run "
            "`python3 scripts/build_final_report.py` locally — "
            "produces the publication-ready markdown with κ + bootstrap "
            "CI + pipeline F1 + confusion matrices in one shot."
        )

    # --- Tab 2: adjudication ---
    with tab_adj:
        st.markdown("### Adjudicate disagreements")
        st.caption(
            "Walk through every trial × axis where the two raters "
            "disagreed. The label you pick becomes the gold-standard "
            "ground truth for computing the pipeline's per-axis F1. "
            "All adjudications are saved to "
            f"`{_ADJUDICATED_PATH.relative_to(REPO_ROOT)}` after each pick "
            "so partial sessions are durable."
        )

        # Load the committed rater files
        rater_docs = {}
        for rp in sorted(RESPONSES_DIR.glob("*.json")):
            try:
                doc = json.loads(rp.read_text())
                rater_docs[doc.get("rater_id", rp.stem)] = doc
            except Exception:
                continue
        if len(rater_docs) < 2:
            st.warning(
                f"Need ≥2 committed rater files; have {len(rater_docs)}. "
                "Adjudication queue activates once both raters submit."
            )
            return

        disagreements = _disagreements(rater_docs)
        adj = _load_adjudicated()
        adjudicated_keys = {
            k for k in adj if k != "_meta"
            for _ in [None]  # noqa
        }
        # Outstanding queue = disagreements not yet adjudicated AND
        # not session-skipped (lets the moderator deprioritize a hard
        # one and come back later in the same session).
        def _adj_key(d):
            return f"{d['nct_id']}::{d['axis']}"
        skipped_keys = st.session_state.get("adj_skipped_keys", set())
        outstanding = [d for d in disagreements
                       if _adj_key(d) not in adj
                       and _adj_key(d) not in skipped_keys]

        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("Disagreed pairs", len(disagreements))
        _m2.metric("Adjudicated", sum(1 for k in adj if k != "_meta"))
        _m3.metric("Outstanding (not skipped)", len(outstanding))

        if not outstanding:
            st.success(
                "All disagreements adjudicated. Run "
                "`python3 scripts/compute_pipeline_f1.py` "
                "to compute pipeline F1 against the gold standard."
            )
            with st.expander("Review/edit adjudicated truth"):
                rows = [{"NCT": k.split("::")[0], "Axis": k.split("::")[1],
                         "Gold label": v}
                        for k, v in adj.items() if k != "_meta"]
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            return

        # Show the next outstanding disagreement
        d = outstanding[0]
        nct, axis = d["nct_id"], d["axis"]
        st.markdown(f"#### Trial {nct} — axis: **{axis}**")

        # Look up the trial in the sample for context
        trial = next((t for t in sample["trials"] if t["NCTId"] == nct), None)
        if trial:
            with st.expander("Trial info", expanded=True):
                _format_trial_for_rater(trial)

        st.markdown(f"##### Rater calls (disagreement)")
        _ac1, _ac2 = st.columns(2)
        with _ac1:
            st.markdown(f"**{d['rater_a']}** said: `{d['label_a']}`")
            if d["notes_a"]:
                st.caption(f"Notes: _{d['notes_a']}_")
        with _ac2:
            st.markdown(f"**{d['rater_b']}** said: `{d['label_b']}`")
            if d["notes_b"]:
                st.caption(f"Notes: _{d['notes_b']}_")

        # Picker for the consensus / gold-standard label
        st.markdown(f"##### Your decision")

        # Pre-compose a sensible option list: rater_a label, rater_b label,
        # plus the canonical option set for this axis (or the autocomplete
        # vocab for free-text axes).
        seed_options = [d["label_a"], d["label_b"]]
        axis_options = AXIS_OPTIONS.get(axis)
        if axis_options is None:
            vocab = sample.get("autocomplete_vocab", {}).get(axis, [])
            extra = vocab
        elif axis_options == "_dynamic":
            extra = sorted({
                t["_pipeline"].get("DiseaseCategory") or ""
                for t in sample["trials"]
            } - {""})
        else:
            extra = [o for o in axis_options if o not in NON_RATING_LABELS_ADMIN]
        all_options = sorted(set(seed_options + list(extra)))

        gold = st.selectbox(
            "Gold-standard label",
            options=[""] + all_options + ["Other (specify)"],
            key=f"adj_gold_{nct}_{axis}",
            format_func=lambda x: "(pick the consensus label)" if not x else x,
        )
        if gold == "Other (specify)":
            other = st.text_input(
                "Specify gold label",
                key=f"adj_other_{nct}_{axis}",
            ).strip()
            gold = other or ""

        rationale = st.text_area(
            "Rationale (recorded, public, becomes part of methodology)",
            key=f"adj_rationale_{nct}_{axis}",
            placeholder="e.g. 'CT.gov primary condition is GBM, not generic CNS'",
        )

        _bc1, _bc2 = st.columns([0.7, 0.3])
        with _bc1:
            if st.button(
                "Skip this disagreement (revisit later)",
                key=f"adj_skip_{nct}_{axis}",
            ):
                # Move to next by NOT recording — the queue auto-advances
                # because outstanding[0] is recomputed each render.
                # But we need to actually skip this one in the current
                # render — use a session-level skip set.
                skipped = st.session_state.setdefault("adj_skipped_keys", set())
                skipped.add(_adj_key(d))
                st.rerun()
        with _bc2:
            if st.button(
                "Record + next →",
                key=f"adj_record_{nct}_{axis}",
                type="primary", use_container_width=True,
            ):
                if not gold:
                    st.error("Pick a gold-standard label first.")
                    return
                adj[_adj_key(d)] = {
                    "nct_id": nct, "axis": axis,
                    "gold_label": gold,
                    "rater_a": d["rater_a"], "label_a": d["label_a"],
                    "rater_b": d["rater_b"], "label_b": d["label_b"],
                    "rationale": rationale.strip(),
                    "adjudicated_by": rater_id,
                    "adjudicated_at": datetime.now(timezone.utc).isoformat(),
                }
                _save_adjudicated(adj)
                st.toast(f"Adjudicated {nct} / {axis} → {gold}")
                st.rerun()

        if skipped_keys:
            st.caption(f"Skipped in this session: {len(skipped_keys)} "
                       "(will resurface on next session)")

    # --- Tab 3: Flag triage ---
    # Pulls open community classification-flag GitHub issues that have hit
    # the consensus threshold (so the moderator only sees issues worth their
    # time) and presents them one-at-a-time in the same flow as adjudication.
    # Each decision: writes to local moderator_flag_decisions.json (durable
    # audit) AND, if a GitHub PAT is set, posts a moderator comment +
    # applies a label (moderator-approved / moderator-rejected) + closes
    # the issue. No more clicking through GitHub manually.
    with tab_flags:
        st.markdown("### Flag triage")

        # Cache-bust button + repo info
        _fc1, _fc2 = st.columns([0.7, 0.3])
        with _fc1:
            st.caption(
                f"Pulls open `consensus-reached` flags from "
                f"[github.com/{GITHUB_REPO_SLUG}/issues]"
                f"(https://github.com/{GITHUB_REPO_SLUG}/issues?q=is%3Aopen+label%3Aclassification-flag+label%3Aconsensus-reached). "
                "Each decision is recorded locally and "
                "(if GH_MODERATOR_TOKEN is set) automatically commented "
                "+ labelled + closed on the issue itself."
            )
        with _fc2:
            if st.button("Refresh from GitHub", key="flag_refresh",
                          use_container_width=True):
                _admin_load_active_flags.clear()
                _admin_load_issue_detail.clear()
                st.rerun()

        flag_issues = _admin_load_active_flags()
        flag_log = _admin_load_flag_decisions()
        gh_token = _admin_get_moderator_token()

        # Filter to issues not yet locally-decided + not session-skipped
        _flag_skipped = st.session_state.setdefault(
            "flag_skipped_keys", set(),
        )

        def _issue_nct(issue: dict) -> str | None:
            import re as _re_n
            t = issue.get("title", "") or ""
            b = issue.get("body", "") or ""
            m = _re_n.search(r"NCT\d{8}", t) or _re_n.search(r"NCT\d{8}", b)
            return m.group(0) if m else None

        outstanding_flags = [
            iss for iss in flag_issues
            if (n := _issue_nct(iss))
            and n not in flag_log
            and iss.get("number") not in _flag_skipped
        ]

        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("Open consensus flags", len(flag_issues))
        _m2.metric("Decided locally", len(flag_log))
        _m3.metric("Outstanding (not skipped)", len(outstanding_flags))

        if not gh_token:
            st.warning(
                "**`GH_MODERATOR_TOKEN` not set.** Decisions will be "
                "recorded locally but NOT pushed back to GitHub. To enable "
                "automatic commenting + labelling + closing, add the secret "
                "to Streamlit Cloud (Settings → Secrets):\n"
                "```toml\ngh_moderator_token = \"ghp_…\"\n```\n"
                "PAT needs `repo` scope for issue write access."
            )

        if not outstanding_flags:
            if flag_issues:
                st.success(
                    "All open consensus-flagged trials have been triaged "
                    "in this session. Click **Refresh from GitHub** if you "
                    "expect new ones."
                )
            else:
                st.info(
                    "No open consensus-reached flags awaiting moderation. "
                    "Either no community flags have been filed, or they "
                    "haven't hit the consensus threshold yet."
                )
        else:
            # Show the next outstanding flag
            issue = outstanding_flags[0]
            nct = _issue_nct(issue)
            issue_num = issue.get("number")
            issue_url = issue.get("html_url", "")

            st.markdown(
                f"#### Flag {len(flag_log) + 1} of "
                f"{len(flag_log) + len(outstanding_flags)}: "
                f"[{nct}]({issue_url})"
            )
            st.caption(
                f"Issue #{issue_num} · "
                f"opened by **{(issue.get('user') or {}).get('login', '?')}** "
                f"· created {issue.get('created_at', '?')[:10]}"
            )

            # Pull issue details (cached)
            details = _admin_load_issue_detail(issue_num) if issue_num else {}

            # Show the trial (uses the same _format_trial_for_rater layout)
            sample = _load_sample()
            trial = next(
                (t for t in sample["trials"] if t["NCTId"] == nct), None,
            )
            if trial:
                with st.expander("Trial info (from validation sample)",
                                  expanded=True):
                    _format_trial_for_rater(trial)
            else:
                st.caption(
                    f"Trial {nct} is not in the locked validation sample "
                    "v1; only the GitHub issue context is available below."
                )

            # Show the proposed corrections
            if details.get("proposals"):
                st.markdown("##### Community proposed corrections")
                _ptable = pd.DataFrame(details["proposals"]).rename(columns={
                    "axis": "Axis",
                    "pipeline_label": "Current label",
                    "proposed_correction": "Proposed",
                    "author": "Reviewer",
                })
                st.dataframe(_ptable, hide_index=True, width="stretch")
            else:
                st.caption("_(No structured BEGIN_FLAG_DATA blocks parseable "
                           "from issue body / comments. See the full thread "
                           "for context.)_")

            # Show free-text rationale from the issue body
            with st.expander("Issue body + comments (full thread)",
                              expanded=False):
                if details.get("body_md"):
                    st.markdown("**Body**")
                    st.markdown(details["body_md"])
                if details.get("comments"):
                    st.markdown("---")
                    st.markdown("**Comments**")
                    for c in details["comments"]:
                        st.markdown(
                            f"**{c['author']}** · "
                            f"_{c.get('created_at', '')[:10]}_"
                        )
                        st.markdown(c["body"])
                        st.markdown("---")
                st.markdown(f"[Open on GitHub ↗]({issue_url})")

            # Decision form
            st.markdown("##### Your decision")
            decision = st.radio(
                "Action",
                options=["Approve correction",
                         "Reject correction",
                         "Defer (revisit later)"],
                key=f"flag_decision_{issue_num}",
                horizontal=True,
            )
            rationale = st.text_area(
                "Rationale (recorded locally; included in GitHub comment)",
                key=f"flag_rationale_{issue_num}",
                placeholder="e.g. 'Confirmed via CT.gov primary condition: "
                            "GBM, not generic CNS.'",
            )

            _bc1, _bc2 = st.columns([0.7, 0.3])
            with _bc1:
                if st.button(
                    "Skip for this session",
                    key=f"flag_skip_{issue_num}",
                ):
                    _flag_skipped.add(issue_num)
                    st.rerun()
            with _bc2:
                if st.button(
                    "Record + next →",
                    key=f"flag_record_{issue_num}",
                    type="primary",
                    use_container_width=True,
                ):
                    if decision == "Defer (revisit later)":
                        _flag_skipped.add(issue_num)
                        st.toast(f"Deferred {nct}")
                        st.rerun()
                    if decision != "Defer (revisit later)" and not rationale.strip():
                        st.error(
                            "Please add a rationale — it gets posted as a "
                            "moderator comment on the issue."
                        )
                    else:
                        # Save local decision (durable)
                        from datetime import datetime as _dt_flag
                        _admin_save_flag_decision(nct, {
                            "nct_id": nct,
                            "issue_number": issue_num,
                            "issue_url": issue_url,
                            "decision": decision,
                            "rationale": rationale.strip(),
                            "moderator": rater_id,
                            "decided_at": _dt_flag.now(timezone.utc).isoformat(),
                            "proposals": details.get("proposals", []),
                        })

                        # Optional GitHub writeback
                        if gh_token:
                            label = ("moderator-approved"
                                     if decision == "Approve correction"
                                     else "moderator-rejected")
                            comment = (
                                f"**Moderator decision: {decision}**\n\n"
                                f"{rationale.strip()}\n\n"
                                f"_Recorded by @{rater_id} via the validation-app "
                                f"flag-triage queue at "
                                f"{_dt_flag.now(timezone.utc).isoformat()}._\n\n"
                                f"---\n"
                                f"_Approved corrections are queued for "
                                f"promotion to `llm_overrides.json` via "
                                f"`scripts/promote_consensus_flags.py "
                                f"--require-moderator-approval --apply --close-issues`._"
                                if decision == "Approve correction"
                                else f"**Moderator decision: {decision}**\n\n"
                                     f"{rationale.strip()}\n\n"
                                     f"_Recorded by @{rater_id} via the validation-app "
                                     f"flag-triage queue at "
                                     f"{_dt_flag.now(timezone.utc).isoformat()}._"
                            )
                            ok, msg = _admin_post_github_action(
                                issue_num,
                                comment_body=comment,
                                label_to_add=label,
                                close=True,
                                token=gh_token,
                            )
                            if ok:
                                st.toast(f"GitHub: comment + label + close OK ({nct})")
                            else:
                                st.warning(
                                    f"Local decision saved, but GitHub "
                                    f"writeback failed: {msg}"
                                )
                        else:
                            st.toast(
                                f"Decision saved locally ({nct}). Set "
                                "GH_MODERATOR_TOKEN to enable writeback."
                            )
                        # Bust the cache so the closed issue drops out next render
                        _admin_load_active_flags.clear()
                        st.rerun()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    rater_id, role = _get_rater_identity()
    if rater_id is None:
        st.title("Trial Classification Validation Study")
        st.caption("Inter-rater reliability study for the CAR-T Trials "
                   "Monitor classification pipeline.")
        st.error(
            "**Access requires an invitation link with a token.**\n\n"
            "If you've been invited as a rater and don't have your link, "
            "please contact peter.jeong@uk-koeln.de.\n\n"
            "If you ARE Peter and the link looks broken, check that "
            "`VALIDATION_TOKENS` is set in Streamlit Cloud secrets."
        )
        return

    st.title("Trial Classification Validation Study")
    st.caption(
        f"Rater: **{rater_id}** ({role}) · "
        f"Sample v1 · sha256: `{_load_sample()['sha256'][:16]}…`"
    )

    if role == "admin":
        _render_admin(rater_id)
    else:
        _render_rater(rater_id)


if __name__ == "__main__":
    main()
