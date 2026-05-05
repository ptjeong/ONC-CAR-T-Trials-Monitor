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

# Durable submission storage (revised 2026-04-27 to address /tmp eviction).
# Two-tier: state-JSON snapshot (rewritten on every submit) + append-only
# audit log JSONL (one line per submit). The audit log is the recovery
# trail — even if the state JSON is lost or corrupted, replaying the
# JSONL rebuilds full state.
#
# Storage location: $HOME/.validation_responses preferred (survives
# server restarts; writable on Streamlit Cloud + most managed hosts).
# Fall back to /tmp if $HOME is not writable (some Docker setups).
# Old /tmp path is also probed on load so previously-saved data
# from before this migration isn't orphaned.
def _resolve_backup_dir() -> Path:
    home_dir = Path.home() / ".validation_responses"
    try:
        home_dir.mkdir(exist_ok=True, parents=True)
        # Quick write probe to confirm permissions
        probe = home_dir / ".write_probe"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return home_dir
    except (OSError, PermissionError):
        fallback = Path("/tmp/validation_responses")
        fallback.mkdir(exist_ok=True, parents=True)
        return fallback


LOCAL_BACKUP_DIR = _resolve_backup_dir()
AUDIT_LOG_DIR = LOCAL_BACKUP_DIR / "audit"
AUDIT_LOG_DIR.mkdir(exist_ok=True, parents=True)
# Legacy /tmp path probed on load only — we read from it, never write.
LEGACY_BACKUP_DIR = Path("/tmp/validation_responses")

# Axis options — kept in sync with config.py / app.py's _FLAG_AXIS_OPTIONS.
# "Unsure" is appended to every axis as a first-class option.
AXIS_OPTIONS = {
    "Branch": ["Heme-onc", "Solid-onc", "Mixed", "Unknown", "Unsure"],
    "DiseaseCategory": "_dynamic",   # populated from sample at load time
    "DiseaseEntity": None,            # free text + autocomplete
    "TrialDesign": ["Single disease", "Multi-disease", "Unsure"],
    # Platform — what KIND of cell therapy. Pre-selected to CAR-T as
    # the modal class (~85% of the dataset). Documented bias trade-off
    # in the methods section: raters can change it freely, but the
    # κ on this axis is reported with the pre-selection caveat.
    "Platform": ["CAR-T", "CAR-NK", "CAAR-T", "CAR-γδ T", "CAR-Treg", "Unsure"],
    "TargetCategory": None,           # free text + autocomplete
    "ProductType": ["Autologous", "Allogeneic/Off-the-shelf", "In vivo",
                    "Unclear", "Unsure"],
    "SponsorType": ["Industry", "Academic", "Government", "Other", "Unsure"],
}

# Axes where the rater MUST actively pick a value (no pre-selection).
# Platform is deliberately not in this set — it's pre-selected to CAR-T
# for ergonomics. Pre-selection bias on Platform is disclosed in methods.
AXES_REQUIRE_ACTIVE_PICK = {
    "Branch", "DiseaseCategory", "DiseaseEntity", "TrialDesign",
    "TargetCategory", "ProductType", "SponsorType",
}
PLATFORM_DEFAULT = "CAR-T"

# Human-readable labels — replaces the camelCase axis keys when shown
# to raters. Keeps the storage schema (_pipeline keys, JSON keys) on
# the canonical CamelCase form.
AXIS_LABEL = {
    "Branch": "Branch",
    "DiseaseCategory": "Disease category",
    "DiseaseEntity": "Disease entity",
    "TrialDesign": "Trial design",
    "Platform": "Platform",
    "TargetCategory": "Target category",
    "ProductType": "Product type",
    "SponsorType": "Sponsor type",
}

# Layout — order matches the rater's natural reading flow.
# Empirical analysis of 12 sample titles (NCT04796441, NCT02846584,
# NCT05066646, NCT05587543, NCT04503980, NCT04237428, NCT06090864,
# NCT06010862, NCT07193628, NCT04420754, NCT06355908, NCT05990621):
# 11 of 12 follow the pattern
#   "[Antigen] + [Cell type] in/for [Disease]"
# So the rater's eye captures, in order:
#   target → platform → disease entity → (then derives category, branch)
#   → trial design (from conditions count) → product type → sponsor
# Click order is reordered to MATCH this:
#
#   row 1: OBSERVATIONS   — Target · Platform · Trial design
#                           (what's directly visible in the title)
#   row 2: DISEASE DRILL  — Disease entity · Disease category · Branch
#                           (leaf → broad; rater types what they read,
#                            then derives the wider buckets)
#   row 3: SUMMARY DETAILS — Product type · Sponsor type
#                           (read once in the brief summary / metadata)
#
# Trial design stays in row 1 (also an observation — basket count
# from conditions list) so it's answered BEFORE the entity widget
# in row 2, preserving the multi-select-on-basket behavior.
#
# Branch in row 2 right cell needs a wider column for its 5
# horizontal radio options — see AXIS_ROW_WIDTHS.
AXIS_LAYOUT = [
    ["TargetCategory", "Platform", "TrialDesign"],
    ["DiseaseEntity", "DiseaseCategory", "Branch"],
    ["ProductType", "SponsorType"],
]

# Per-row column-width overrides — None means equal columns.
# Tuned to give horizontal-radio axes (Branch, Platform) enough room.
AXIS_ROW_WIDTHS: dict[int, list[float] | None] = {
    0: [0.30, 0.40, 0.30],   # Target dropdown | Platform 6 radios | TrialDesign 3 radios
    1: [0.32, 0.30, 0.38],   # Entity dropdown | Category dropdown | Branch 5 radios
    2: [0.50, 0.50],          # Product 5 radios | Sponsor 5 radios
}

AXIS_HELP = {
    "Branch": "The trial's primary indication: hematologic, solid, mixed, "
              "or unknown.",
    "DiseaseCategory": "Mid-level disease grouping (e.g. B-NHL, GI, CNS). "
                       "Pick the dominant category if multiple apply.",
    "DiseaseEntity": "Every disease the trial enrols. For a single-"
                     "disease trial, one entity (sub-entity like DLBCL, "
                     "GBM, HCC, OR the category name itself like AML, "
                     "Breast, MM if the trial doesn't drill past the "
                     "category). For a basket trial, pick every entity "
                     "the cohort spans — components are commonly listed "
                     "at the category level (AML, Sarcoma, Breast). "
                     "Both categories and sub-entities are selectable.",
    "TrialDesign": "Single disease = enrols one diagnosis only. "
                   "Multi-disease = a basket trial spanning ≥ 2 diagnoses.",
    "Platform": "What kind of cell therapy: CAR-T (default — αβ T cells, "
                "the modal class), CAR-NK (natural-killer cells), CAAR-T "
                "(chimeric autoantibody receptor T), CAR-γδ T (gamma-delta "
                "T), or CAR-Treg (regulatory T cells). Pre-selected to "
                "CAR-T because ~85% of trials in the dataset are CAR-T; "
                "change as needed.",
    "TargetCategory": "The CAR antigen — the receptor on the tumor cell "
                      "that the construct recognizes (e.g. CD19, BCMA, "
                      "CD123, GD2). For ligand-based CARs, record the "
                      "RECEPTOR (on the tumor), NOT the ligand (the "
                      "construct's binding domain): IL3 CAR → CD123, "
                      "APRIL CAR → BCMA/TACI, BAFF CAR → BAFF-R/BCMA/"
                      "TACI, NKG2D CAR → NKG2D-L. For non-antigen "
                      "constructs, use the construct family (CAAR-T, "
                      "etc.).",
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
    /* ────────────────────────────────────────────────────────────────────
       Zen design system — inspired by Linear, Things 3, Stripe Atlas,
       Arc, Apple Mail. Five rules:

         1. ONE thing has visual primacy at a time. Everything else is
            peripheral.
         2. Whitespace is the only divider. Cards/borders/shadows are
            grudging — used only when content groups would otherwise
            merge visually.
         3. Typography carries hierarchy. Size + weight + tracking
            replace borders.
         4. ONE accent color (#1e40af), used sparingly. The accent
            is precious — primary CTA + progress fill, nothing else.
         5. Calm motion. 200-300ms cubic-bezier transitions, never
            snappy or bouncy.

       For the rater: the TRIAL is the page. Heatmap is a thin
       progress strip at the top. Inputs feel inline, not boxed.
       Submit lives where the eye lands after the last input.
       ─────────────────────────────────────────────────────────────────── */

    /* System font on body content. Scoped narrowly so Streamlit's
       icon font (Material Symbols Outlined, used for expander
       chevrons + similar) is NOT overridden. The previous
       [class*="st-"] selector was too greedy and caused icon
       names ("arrow_right") to render as raw text. */
    html, body {
        font-family: -apple-system, BlinkMacSystemFont, "Inter",
                     "SF Pro Text", "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    .stApp, .stMarkdown, .stText, .stDataFrame,
    [data-testid="stMarkdownContainer"] {
        font-family: -apple-system, BlinkMacSystemFont, "Inter",
                     "SF Pro Text", "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
    }
    /* Explicitly preserve Streamlit's icon font so expanders + tabs
       continue to render their chevrons/arrows correctly. */
    .material-symbols-outlined,
    [class*="material-symbols"],
    span[data-testid*="icon"] {
        font-family: 'Material Symbols Outlined', 'Material Icons' !important;
    }

    .block-container {
        max-width: 1100px;
        padding-top: 0.6rem;
        padding-bottom: 4rem;
    }

    /* Hide Streamlit's default header/footer chrome for editorial feel */
    header[data-testid="stHeader"] { background: transparent; }
    footer { display: none; }

    /* ───── Top progress bar — sticky, peripheral, glanceable ───── */
    .top-bar {
        display: flex; align-items: center; gap: 16px;
        padding: 10px 0 12px 0; margin: -8px 0 28px 0;
        border-bottom: 1px solid #f0f0f0;
        position: sticky; top: 0; z-index: 50;
        background: #ffffff;
    }
    .top-bar .label {
        font-size: 11px; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.08em;
        color: #737373; flex: 0 0 auto;
    }
    .top-bar .progress-track {
        flex: 1 1 auto;
        height: 4px;
        background: #f0f0f0;
        border-radius: 2px;
        overflow: hidden;
        position: relative;
    }
    .top-bar .progress-fill {
        height: 100%;
        background: #1e40af;
        border-radius: 2px;
        transition: width 400ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .top-bar .stats {
        flex: 0 0 auto; display: flex; align-items: baseline; gap: 8px;
        font-variant-numeric: tabular-nums;
    }
    .top-bar .stats .pct {
        font-size: 13px; font-weight: 600; color: #0a0a0a;
        letter-spacing: -0.01em;
    }
    .top-bar .stats .count {
        font-size: 11px; color: #737373;
    }
    .top-bar .stats .stale {
        color: #b91c1c; font-weight: 600; font-size: 10px;
        background: #fef2f2; padding: 1px 6px; border-radius: 3px;
        margin-left: 6px;
    }

    /* ───── Trial — page-as-content, no card frame ───── */
    .trial-title {
        font-size: 24px; font-weight: 600; color: #0a0a0a;
        line-height: 1.25; margin: 0 0 10px 0;
        letter-spacing: -0.022em;
    }
    .trial-meta {
        font-size: 13px; color: #737373;
        margin-bottom: 24px; line-height: 1.6;
    }
    .trial-meta a {
        color: #1e40af; text-decoration: none; font-weight: 500;
        border-bottom: 1px solid transparent;
        transition: border-color 150ms ease;
    }
    .trial-meta a:hover {
        border-bottom-color: #1e40af;
    }
    .trial-meta strong {
        color: #171717; font-weight: 600;
    }
    .trial-meta .sep {
        color: #d4d4d8; margin: 0 6px;
    }
    .trial-evidence {
        display: grid; grid-template-columns: 1fr 1fr;
        gap: 24px; margin-bottom: 22px;
    }
    .trial-cond {
        font-size: 13px; color: #171717; line-height: 1.55;
    }
    .trial-cond .lbl {
        display: block;
        color: #737373; font-weight: 600;
        text-transform: uppercase; font-size: 10px;
        letter-spacing: 0.08em; margin-bottom: 6px;
    }
    .trial-summary {
        font-size: 14.5px; color: #404040;
        line-height: 1.65; font-style: italic;
        padding: 0 12px 0 16px;
        max-height: 124px; overflow-y: auto;
        margin: 0 0 28px 0;
        border-left: 1px solid #e5e5e5;
        white-space: pre-wrap;
    }

    /* ───── Axis layers — subtle 3-tier demarcation ─────
       Middle layer (row 2) gets a faint slate tint so the eye reads
       three distinct stages: identification → disease classification →
       mechanism. Outer rows stay pure white. The shading is barely
       perceptible (#fafbfc on white) — enough to anchor each row as
       its own visual unit without breaking the calm aesthetic. */
    [data-testid="stKey-axis_row_1"] {
        background: #fafbfc;
        border-radius: 8px;
        padding: 14px 16px;
        margin: 4px 0 4px 0;
    }
    [data-testid="stKey-axis_row_0"],
    [data-testid="stKey-axis_row_2"] {
        padding: 14px 16px;
        margin: 4px 0 4px 0;
    }

    /* Axis section divider line (legacy — kept in case _render_rater
       still references it; safe to keep) */
    .axis-divider {
        border: none;
        border-top: 1px solid #f0f0f0;
        margin: 0 0 18px 0;
    }
    /* Override Streamlit's default selectbox/radio chrome to feel inline */
    .stSelectbox > label, .stRadio > label, .stTextInput > label {
        font-size: 10px !important; font-weight: 600 !important;
        text-transform: uppercase !important; letter-spacing: 0.08em !important;
        color: #737373 !important; margin-bottom: 4px !important;
    }
    .stSelectbox > div > div {
        border-radius: 6px !important;
        border: 1px solid #e5e5e5 !important;
        background: #ffffff !important;
        min-height: 36px !important;
    }
    .stSelectbox > div > div:focus-within {
        border-color: #1e40af !important;
        box-shadow: 0 0 0 3px rgba(30, 64, 175, 0.08) !important;
    }
    .stTextInput > div > div > input {
        border-radius: 6px !important;
        border: 1px solid #e5e5e5 !important;
        font-size: 13px !important;
        padding: 8px 12px !important;
        background: #ffffff !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #1e40af !important;
        box-shadow: 0 0 0 3px rgba(30, 64, 175, 0.08) !important;
    }
    /* Compact radio buttons (horizontal axes) */
    .stRadio > div {
        gap: 14px !important;
    }
    .stRadio label {
        font-size: 13px !important;
        color: #171717 !important;
    }

    /* ───── Buttons ───── */
    /* Primary: the only solid accent on the page */
    .stButton > button[kind="primary"] {
        background: #1e40af !important;
        border: 1px solid #1e40af !important;
        color: #ffffff !important; font-weight: 600 !important;
        border-radius: 6px !important;
        font-size: 13px !important;
        padding: 8px 18px !important;
        transition: background 200ms ease !important;
        letter-spacing: -0.005em !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: #1e3a8a !important;
        border-color: #1e3a8a !important;
    }
    /* Secondary: text-button, no background until hover */
    .stButton > button[kind="secondary"] {
        background: transparent !important;
        border: 1px solid transparent !important;
        color: #737373 !important; font-weight: 500 !important;
        border-radius: 6px !important;
        font-size: 13px !important;
        padding: 8px 14px !important;
    }
    .stButton > button[kind="secondary"]:hover {
        background: #f4f4f5 !important;
        color: #171717 !important;
    }

    /* ───── Tabs (used in More-context expander) ───── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px; border-bottom: 1px solid #f0f0f0;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 12px !important;
        color: #737373 !important;
        padding: 6px 10px !important;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: #0a0a0a !important;
        font-weight: 600 !important;
    }

    /* ───── Trial nav strip — between top bar and trial card ───── */
    .nav-status {
        text-align: center;
        font-size: 12px; color: #525252;
        font-variant-numeric: tabular-nums;
        line-height: 38px;     /* match adjacent button height */
        letter-spacing: 0.01em;
    }

    /* ───── Footer keyboard hints ───── */
    .kbd-hints {
        font-size: 11px; color: #a3a3a3;
        margin-top: 32px; text-align: center;
        letter-spacing: 0.02em;
    }
    .kbd-hints kbd {
        background: #f4f4f5; border: 1px solid #e5e5e5;
        border-bottom-width: 2px;
        border-radius: 4px; padding: 1px 5px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 10px; color: #404040;
        margin: 0 2px;
    }
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


def _legacy_backup_path(rater_id: str) -> Path:
    """Pre-2026-04-27 /tmp path; read-only fallback for orphaned data."""
    return LEGACY_BACKUP_DIR / f"{rater_id}.json"


def _committed_responses_path(rater_id: str) -> Path:
    return RESPONSES_DIR / f"{rater_id}.json"


def _audit_log_path(rater_id: str) -> Path:
    """Append-only JSONL — one line per submission. Recovery trail."""
    return AUDIT_LOG_DIR / f"{rater_id}.jsonl"


def _append_audit_entry(rater_id: str, entry: dict) -> None:
    """Append one JSON line to the per-rater audit log.

    The log is append-only and survives state-JSON corruption. Each
    entry captures (timestamp, NCT, full labels dict, source). If the
    state JSON is ever lost, `_replay_audit_log()` reconstructs the
    rater's submissions from this trail.
    """
    path = _audit_log_path(rater_id)
    path.parent.mkdir(exist_ok=True, parents=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    # Open in append mode with line buffering — atomic at the OS level
    # for writes < PIPE_BUF (4096 bytes on Linux), which a single rating
    # comfortably is. No tmp-then-rename needed for an append.
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _audit_log_count(rater_id: str) -> int:
    """Return number of audit entries for this rater (zero if no log)."""
    path = _audit_log_path(rater_id)
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _replay_audit_log(rater_id: str) -> dict:
    """Reconstruct state from the audit log. Recovery utility.

    Used when the state JSON is missing/corrupted. Each NCT keeps its
    LATEST entry (per-NCT last-write-wins), so re-rates are handled
    correctly. Returns an empty state if no audit log exists.
    """
    state = _empty_state(rater_id)
    path = _audit_log_path(rater_id)
    if not path.exists():
        return state
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip corrupt line, keep going
            nct = entry.get("nct")
            if not nct:
                continue
            state["ratings"][nct] = {
                "labels": entry.get("labels", {}),
                "notes": entry.get("notes", ""),
                "duration_seconds": entry.get("duration_seconds", 0),
                "timestamp": entry.get("timestamp", ""),
                "skipped": entry.get("skipped", False),
            }
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    return state


def _load_persisted_responses(rater_id: str) -> dict:
    """Return the most recent persisted state for this rater.

    Resolution priority (latest `last_updated` wins):
      1. New durable backup (~/.validation_responses/{rater}.json)
      2. Legacy /tmp backup (read-only, pre-2026-04-27 migration)
      3. Committed canonical store (validation_study/responses/)
      4. Audit-log replay (last-resort recovery trail)

    Schema-validated; bad files return empty state with a warning so
    the rater isn't blocked.
    """
    sources: list[tuple[Path, dict]] = []
    for p in (
        _local_backup_path(rater_id),
        _legacy_backup_path(rater_id),
        _committed_responses_path(rater_id),
    ):
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
        # Last-resort: try to recover from audit log
        replayed = _replay_audit_log(rater_id)
        if replayed["ratings"]:
            st.info(
                f"Reconstructed {len(replayed['ratings'])} ratings from "
                f"the audit log (state JSON was missing). Your work is "
                "preserved — please click 'Download progress' to back it "
                "up to your machine."
            )
            return replayed
        return _empty_state(rater_id)

    sources.sort(key=lambda t: t[1].get("last_updated", ""), reverse=True)
    chosen = sources[0][1]

    # Cross-check against audit log — if audit has more entries than
    # state, the state JSON may be stale or partial. Surface this so
    # the rater can recover if needed.
    audit_n = _audit_log_count(rater_id)
    state_n = len(chosen.get("ratings", {}))
    if audit_n > state_n:
        st.warning(
            f"Audit log has {audit_n} entries but loaded state has only "
            f"{state_n}. There may be lost ratings — go to "
            "Settings → Resume from audit log to recover."
        )
    return chosen


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


def _persist(state: dict, *, audit_nct: str | None = None) -> None:
    """Write state to durable backup + (optionally) append to audit log.

    Two-tier durability:
      1. State JSON snapshot: full state, atomic-rewritten every call
         (~/.validation_responses/{rater}.json) — survives /tmp eviction
      2. Audit log JSONL: one append-only line per submission
         (~/.validation_responses/audit/{rater}.jsonl) — recovery trail
         that survives state-JSON corruption

    Pass `audit_nct` to also append the just-submitted/skipped rating
    to the audit log. Omitting it (e.g. on bulk-resume merges) writes
    only the state snapshot.
    """
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state["app_version"] = APP_VERSION
    rater_id = state.get("rater_id", "anon")
    _atomic_write_json(_local_backup_path(rater_id), state)
    if audit_nct and audit_nct in state.get("ratings", {}):
        rating = state["ratings"][audit_nct]
        try:
            _append_audit_entry(rater_id, {
                "ts": datetime.now(timezone.utc).isoformat(),
                "nct": audit_nct,
                "labels": rating.get("labels", {}),
                "notes": rating.get("notes", ""),
                "duration_seconds": rating.get("duration_seconds", 0),
                "skipped": rating.get("skipped", False),
                "timestamp": rating.get("timestamp", ""),
                "app_version": APP_VERSION,
            })
        except (OSError, PermissionError) as e:
            # Audit-log failure must NOT block the submission. Surface
            # to the rater so they know to download immediately.
            st.warning(
                f"Audit log write failed ({e}). Your rating is in the "
                "main state file but the recovery trail did not update. "
                "Please click 'Download progress' for a manual backup."
            )


# ---------------------------------------------------------------------------
# Garden gamification
# ---------------------------------------------------------------------------

def _top_progress_bar_html(state: dict, sample: dict,
                              *, save_meta_html: str = "") -> str:
    """Sticky top progress bar — always visible, never demanding.

    Layout: thin 4px progress fill on the left + percentage + count
    on the right. Total height ~30px including the bottom divider.
    This is the rater's only progress indicator (no secondary heatmap).
    """
    n_total = len(sample["trials"])
    n_done = len(state.get("ratings", {}))
    pct = (n_done / n_total * 100) if n_total else 0
    return (
        f'<div class="top-bar">'
        f'  <div class="label">Validation</div>'
        f'  <div class="progress-track">'
        f'    <div class="progress-fill" style="width:{pct:.1f}%"></div>'
        f'  </div>'
        f'  <div class="stats">'
        f'    <span class="pct">{pct:.0f}%</span>'
        f'    <span class="count">{n_done} / {n_total}</span>'
        f'    {save_meta_html}'
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

    Single-page-fits design: title + 1-line metadata + tight
    conditions/interventions row + compact 100px summary scrollbox +
    ONE consolidated "Full trial context" expander housing all
    long-form fields. The previous 5 separate expanders cost ~150px
    of stacked headers; folding into one drops that to ~30px.
    """
    nct = trial["NCTId"]
    title = trial.get("BriefTitle") or "(no title)"

    # Title — 24px / 600 weight / -0.022em tracking. Reads like a
    # New Yorker article header. The page IS the trial; this is the
    # thing the eye lands on first.
    st.markdown(
        f'<div class="trial-title">{_html_escape(title)}</div>',
        unsafe_allow_html=True,
    )

    # Metadata — pipe-separated muted gray, with explicit · separators
    # styled in even-fainter gray for typographic rhythm.
    #
    # BLIND-METHODOLOGY RULE: only raw CT.gov fields appear here.
    # `TrialDesign` was previously rendered (commit ahead) but it is
    # pipeline-classified at pipeline.py:1084 AND is one of the 8 axes
    # the rater is asked to label — showing it anchors the answer.
    # `LeadSponsorClass` IS shown because it is CT.gov's own sponsor
    # categorization (raw field), not our `SponsorType` axis output.
    sponsor_str = trial.get("LeadSponsor") or "—"
    if trial.get("LeadSponsorClass"):
        sponsor_str = f"{sponsor_str} ({trial['LeadSponsorClass']})"
    _meta_bits = [
        f'<a href="https://clinicaltrials.gov/study/{nct}" target="_blank">{nct}</a>',
        f"<strong>{trial.get('Phase') or '—'}</strong>",
        trial.get('OverallStatus') or "—",
        _html_escape(sponsor_str),
    ]
    if trial.get("EnrollmentCount"):
        _meta_bits.append(f"n = {trial['EnrollmentCount']}")
    if trial.get("Countries"):
        _meta_bits.append(_html_escape(trial['Countries']))
    _sep = '<span class="sep">·</span>'
    st.markdown(
        f'<div class="trial-meta">{_sep.join(_meta_bits)}</div>',
        unsafe_allow_html=True,
    )

    # Evidence row — Conditions + Interventions side-by-side, no boxes,
    # type-driven. CSS Grid handles the 2-col layout (st.columns adds
    # extra margin chrome that breaks the rhythm).
    cond = _html_escape(trial.get("Conditions") or "—")
    interv = _html_escape(trial.get("Interventions") or "—")
    st.markdown(
        f'<div class="trial-evidence">'
        f'  <div class="trial-cond">'
        f'    <span class="lbl">Conditions</span>{cond}'
        f'  </div>'
        f'  <div class="trial-cond">'
        f'    <span class="lbl">Interventions</span>{interv}'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Brief summary — italic body, indented, single thin left border.
    # Reads as text, not data. Generous 1.65 line-height invites
    # reading rather than scanning.
    if trial.get("BriefSummary"):
        st.markdown(
            f'<div class="trial-summary">{_html_escape(trial["BriefSummary"])}</div>',
            unsafe_allow_html=True,
        )

    # ---- ONE consolidated expander — all long-form context ----
    # Was 5 separate expanders eating ~150px of headers. Folded into
    # one for single-page density. Tabs inside for fast switching
    # when the rater needs more context for a hard call.
    _has_long_form = any(trial.get(k) for k in [
        "DetailedDescription", "InterventionDescription",
        "EligibilityCriteria", "PrimaryEndpoints",
        "ArmGroupDescriptions", "CollaboratorNames",
        "ResponsiblePartyType",
    ])
    if _has_long_form:
        with st.expander("Full trial context (detailed description, "
                          "eligibility, intervention, design, sponsor)",
                          expanded=False):
            _ctx_tabs = st.tabs([
                "Detailed description", "Intervention", "Eligibility",
                "Endpoints + design", "Sponsor + collaborators",
            ])
            with _ctx_tabs[0]:
                if trial.get("DetailedDescription"):
                    _scrollbox("", trial["DetailedDescription"],
                                max_height=320, accent="#3b82f6")
                else:
                    st.caption("_(none provided in CT.gov record)_")
            with _ctx_tabs[1]:
                if trial.get("InterventionDescription"):
                    _scrollbox("", trial["InterventionDescription"],
                                max_height=240, accent="#10b981")
                if trial.get("ArmGroupDescriptions"):
                    _scrollbox("Arm groups", trial["ArmGroupDescriptions"],
                                max_height=200, accent="#10b981")
                if not trial.get("InterventionDescription") and not trial.get("ArmGroupDescriptions"):
                    st.caption("_(none provided)_")
            with _ctx_tabs[2]:
                if trial.get("EligibilityCriteria"):
                    _scrollbox("", trial["EligibilityCriteria"],
                                max_height=320, accent="#f59e0b")
                else:
                    st.caption("_(none provided)_")
            with _ctx_tabs[3]:
                if trial.get("PrimaryEndpoints"):
                    _scrollbox("", trial["PrimaryEndpoints"],
                                max_height=200, accent="#8b5cf6")
                _design_bits = []
                if trial.get("StudyType"):
                    _design_bits.append(f"**Study type:** {trial['StudyType']}")
                if trial.get("Allocation"):
                    _design_bits.append(f"**Allocation:** {trial['Allocation']}")
                if trial.get("InterventionModel"):
                    _design_bits.append(
                        f"**Intervention model:** {trial['InterventionModel']}"
                    )
                if trial.get("Masking"):
                    _design_bits.append(f"**Masking:** {trial['Masking']}")
                if _design_bits:
                    st.markdown(" · ".join(_design_bits))
                if not trial.get("PrimaryEndpoints") and not _design_bits:
                    st.caption("_(none provided)_")
            with _ctx_tabs[4]:
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
                if not (trial.get("LeadSponsorClass") or
                        trial.get("CollaboratorNames") or
                        trial.get("ResponsiblePartyType")):
                    st.caption("_(none provided)_")

    # Sponsor / collaborators / CT.gov link all live inside the
    # consolidated "Full trial context" tabs above. NCT link is already
    # in the metadata row. No trailing chrome on this card — every
    # pixel below this point belongs to the rating widgets.


def _render_axis_input(
    axis: str, sample: dict, key: str, *, nct: str | None = None,
) -> str:
    """Render a single axis input. Returns the chosen value (or "").

    Uses the friendly AXIS_LABEL (e.g. "Disease category") for the
    visible label; the canonical CamelCase axis key is preserved
    for storage / analysis.

    DiseaseEntity behavior (always-multi-select, redesigned 2026-04-27):
    Was previously a single-select that switched to multi-select only
    on basket signals (TrialDesign=Multi-disease OR DiseaseCategory ∈
    a basket-categories set). That gate added cognitive friction
    — the rater had to pre-classify the trial as basket before the
    widget rendered correctly — and broke the natural case where a
    basket trial enrols entries at the *category* level (e.g. "AML"
    or "Breast cancer" as part of a multi-disease cohort). Now:
      - Always rendered as multi-select
      - Vocab includes BOTH canonical sub-entities AND the disease
        categories from the sample (so "AML", "Breast", "MM" appear
        as picks alongside "R/R AML", "TNBC", "R/R MM")
      - Pre-filled with [picked_category] on first render so the
        common "category-as-entity" case is zero-click
      - Pipe-joined for storage (matches DiseaseEntities pipeline format)
    """
    options = AXIS_OPTIONS.get(axis)
    label = AXIS_LABEL.get(axis, axis)
    helptext = AXIS_HELP[axis]

    if options == "_dynamic":
        # DiseaseCategory — always-multi-select with accept_new_options.
        # Was a single-select dropdown until 2026-04-27; refactored when
        # cross-category basket trials (GD2-targeted basket spanning
        # Pediatric solid + Sarcoma + Breast + a melanoma) revealed
        # the single-pick was reductive — forced the rater to mash a
        # multi-category trial into one bucket, losing the structure.
        cats = sorted({
            t["_pipeline"].get("DiseaseCategory") or ""
            for t in sample["trials"]
        } - {""})
        canonical_choices = cats + ["Unsure"]
        multi_key = f"{key}_multi"

        # ---- Auto-sync: entity → category (forward propagation) ----
        # When the rater adds a sub-entity (e.g. "Neuroblastoma"), its
        # parent category ("Pediatric solid") is auto-added to the
        # category multi-select. Uses the sample's pipeline-classified
        # entity→category lookup as the source of truth.
        # Removal is one-way only — if the rater removes a category,
        # it stays removed even when an implied entity is still picked.
        # `seen_ents` tracks which entities were processed last render,
        # so the same entity isn't re-propagated into a category the
        # rater explicitly removed.
        if nct:
            ent_to_cat = {}
            for t in sample["trials"]:
                c = t["_pipeline"].get("DiseaseCategory")
                e = t["_pipeline"].get("DiseaseEntity")
                if c and e:
                    ent_to_cat[e] = c
            ent_picks = (st.session_state.get(
                f"input_{nct}_DiseaseEntity_multi") or [])
            seen_key = f"input_{nct}_DiseaseEntity_seen_for_catsync"
            seen_ents = set(st.session_state.get(seen_key, []))
            new_ents = set(ent_picks) - seen_ents
            if new_ents:
                cat_state = list(st.session_state.get(multi_key, []) or [])
                for e in new_ents:
                    parent = ent_to_cat.get(e)
                    if parent and parent not in cat_state:
                        cat_state.append(parent)
                st.session_state[multi_key] = cat_state
            st.session_state[seen_key] = list(ent_picks)

        picks = st.multiselect(
            f"{label} · pick every category the trial spans",
            options=canonical_choices,
            key=multi_key,
            help=(helptext + " — multi-select. Categories are auto-"
                   "added when you pick a sub-entity (e.g. picking "
                   "'Neuroblastoma' as entity also adds 'Pediatric "
                   "solid' as category). Type to search or add a new "
                   "category inline."),
            placeholder="Type to search or add a category…",
            accept_new_options=True,
        )
        return "|".join(p for p in picks if p)

    if options is None:
        # Free-text-with-suggestions axes: DiseaseEntity (always-multi)
        # and TargetCategory (single-select). Streamlit's
        # accept_new_options=True lets the rater:
        #   - type to search the canonical vocab (filters live)
        #   - type a new value + Enter to add it inline
        vocab = list(sample.get("autocomplete_vocab", {}).get(axis, []))

        # ---- DiseaseEntity: always-multi with unified category+entity vocab ----
        if axis == "DiseaseEntity":
            # Build vocab = (categories ∪ sub-entities). Categories are
            # added because basket trials often list components at the
            # category level ("AML", "Breast cancer", "Sarcoma") rather
            # than sub-entity level — without them in the vocab, the
            # rater would have to type each as free-text addition.
            all_categories = sorted({
                t["_pipeline"].get("DiseaseCategory") or ""
                for t in sample["trials"]
            } - {""})
            unified_vocab = sorted(set(vocab) | set(all_categories))
            # Pin the picked categories at the top so they're the first
            # options the rater sees (not buried alphabetically). Read
            # from the new multi-select key (DiseaseCategory was
            # converted from single → multi-select 2026-04-27).
            category_top: list[str] = []
            if nct:
                cat_picks = (st.session_state.get(
                    f"input_{nct}_DiseaseCategory_multi") or [])
                category_top = [
                    c for c in cat_picks
                    if c and c not in ("Other (specify)", "Unsure")
                ]
                unified_vocab = [
                    v for v in unified_vocab if v not in category_top
                ]
            canonical_choices = category_top + unified_vocab + ["Unsure"]

            # Use a multi-suffixed key so the always-multi state (list)
            # doesn't collide with any pre-existing single-select state
            # (string) from older session caches.
            multi_key = f"{key}_multi"
            # ---- First-render pre-fill (single-category case only) ----
            # When the multi-select is empty AND exactly one category
            # is picked, pre-fill with [that category]. Zero-click
            # for the common single-disease case (rater picks AML →
            # entity is AML). For multi-category baskets we DON'T
            # pre-fill — the rater is explicitly indicating multi-
            # disease, and pre-filling all categories as entities
            # would be wrong (rater wants sub-entities like
            # Neuroblastoma + Osteosarcoma, not Pediatric solid +
            # Sarcoma duplicated as entity-level picks).
            if (multi_key not in st.session_state
                    and len(category_top) == 1):
                st.session_state[multi_key] = [category_top[0]]

            picks = st.multiselect(
                f"{label} · pick every entity the trial enrols",
                options=canonical_choices,
                key=multi_key,
                help=(helptext + " — pick one entity for a single-disease "
                       "trial, or every entity the cohort enrols for a "
                       "basket. Categories like 'AML', 'Breast' are "
                       "selectable as entities for the common case where "
                       "the trial doesn't drill into a sub-entity. Type "
                       "to search or add a new entity inline."),
                placeholder="Type to search or add an entity…",
                accept_new_options=True,
            )
            # Pipe-join for storage (matches DiseaseEntities pipeline format)
            return "|".join(p for p in picks if p)

        # ---- TargetCategory (single-select, searchable, addable) ----
        canonical_choices = sorted(vocab) + ["Unsure"]
        choice = st.selectbox(
            label,
            options=canonical_choices,
            key=key,
            help=helptext + " — type to search the canonical vocab, "
                            "or type a new value and press Enter to add it.",
            index=None,
            placeholder="Type to search or add a value…",
            accept_new_options=True,
        )
        return choice or ""

    # Enumerable axis — horizontal radio for tightness.
    # Most axes have no pre-selection (index=None) — rater must
    # actively pick. Platform is the exception: pre-selected to
    # CAR-T (modal class) for ergonomics, with the bias trade-off
    # disclosed in methods.
    if axis == "Platform":
        default_idx = (
            options.index(PLATFORM_DEFAULT)
            if PLATFORM_DEFAULT in options else 0
        )
        return st.radio(
            label, options=options, key=key, horizontal=True,
            help=helptext, index=default_idx,
        ) or PLATFORM_DEFAULT

    # ---- TrialDesign auto-detection ----
    # If the rater multi-picked categories or entities, the trial is
    # by definition multi-disease. Auto-set TrialDesign to
    # "Multi-disease" so the rater doesn't have to explicitly pick it.
    # Non-destructive: only fires when TrialDesign is currently empty;
    # if the rater explicitly picked Single disease (e.g. believes the
    # multi picks are different stages of one disease, not multi-
    # disease), the explicit pick is preserved.
    if axis == "TrialDesign" and nct and not st.session_state.get(key):
        cat_picks = (st.session_state.get(
            f"input_{nct}_DiseaseCategory_multi") or [])
        ent_picks = (st.session_state.get(
            f"input_{nct}_DiseaseEntity_multi") or [])
        distinct_cats = {
            c for c in cat_picks
            if c and c not in ("Other (specify)", "Unsure")
        }
        distinct_ents = {
            e for e in ent_picks
            if e and e not in ("Other (specify)", "Unsure")
        }
        if len(distinct_cats) > 1 or len(distinct_ents) > 1:
            if "Multi-disease" in options:
                st.session_state[key] = "Multi-disease"

    return st.radio(
        label, options=options, key=key, horizontal=True,
        help=helptext, index=None,
    ) or ""


def _render_rater(rater_id: str) -> None:
    """Main rater workflow: one trial at a time + garden + safety nets."""
    sample = _load_sample()
    if "state" not in st.session_state:
        st.session_state["state"] = _load_persisted_responses(rater_id)
    state = st.session_state["state"]

    n_done = len(state["ratings"])
    n_total = len(sample["trials"])

    # ---- Sticky top progress bar — always visible, never demanding ----
    # Thin 4px progress fill + percentage + count. Save-stale warning
    # appears INLINE only when stale (>2 min). No secondary heatmap —
    # the thin top bar is the rater's only progress indicator so their
    # attention stays on the trial card.
    _save_meta = ""
    last_save = state.get("last_updated", "")
    try:
        dt = datetime.fromisoformat(last_save.replace("Z", "+00:00"))
        secs_ago = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs_ago > 120:
            _save_meta = (
                f'<span class="stale">'
                f'unsaved {int(secs_ago)}s'
                f'</span>'
            )
    except Exception:
        pass
    st.markdown(
        _top_progress_bar_html(state, sample, save_meta_html=_save_meta),
        unsafe_allow_html=True,
    )

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

    # ---- Current trial selection (with forward/back navigation) ----
    # `current_trial_idx` is the rater's current position in sample
    # order. Defaults to the first unrated trial. Forward/back buttons
    # let the rater revisit any trial — already-rated ones are
    # editable (widgets pre-filled from the saved labels).
    if "current_trial_idx" not in st.session_state:
        rated_ncts_init = set(state["ratings"].keys())
        first_unrated_idx = next(
            (i for i, t in enumerate(sample["trials"])
             if t["NCTId"] not in rated_ncts_init),
            len(sample["trials"]) - 1,  # all rated → land on last
        )
        st.session_state["current_trial_idx"] = first_unrated_idx

    idx = max(0, min(st.session_state["current_trial_idx"],
                     len(sample["trials"]) - 1))
    st.session_state["current_trial_idx"] = idx  # clamp echo-back
    trial = sample["trials"][idx]
    nct = trial["NCTId"]

    # ---- Pre-fill widget state when revisiting an already-rated trial ----
    # Streamlit preserves widget state by key across reruns within the
    # same session, but if the rater navigates to a trial whose widgets
    # haven't been instantiated yet (e.g. a trial rated in a previous
    # session, just resumed), we have to seed the widget keys from the
    # saved labels so the rater sees their prior answers.
    _SEEDED_KEY = f"_seeded_widgets_{nct}"
    if nct in state["ratings"] and not st.session_state.get(_SEEDED_KEY):
        saved_labels = state["ratings"][nct].get("labels", {}) or {}
        for axis, val in saved_labels.items():
            base_key = f"input_{nct}_{axis}"
            # Multi-select axes store as pipe-joined strings
            if axis in ("DiseaseEntity", "DiseaseCategory"):
                multi_key = f"{base_key}_multi"
                if multi_key not in st.session_state:
                    if isinstance(val, list):
                        st.session_state[multi_key] = val
                    elif isinstance(val, str) and val:
                        st.session_state[multi_key] = [
                            v for v in val.split("|") if v
                        ]
            else:
                if base_key not in st.session_state and val:
                    st.session_state[base_key] = val
        # Also seed notes
        notes_key = f"notes_{nct}"
        saved_notes = state["ratings"][nct].get("notes", "")
        if saved_notes and notes_key not in st.session_state:
            st.session_state[notes_key] = saved_notes
        st.session_state[_SEEDED_KEY] = True

    # ---- Navigation strip (above the trial card) ----
    _nav_prev, _nav_status, _nav_next = st.columns([0.18, 0.64, 0.18])
    with _nav_prev:
        if st.button(
            "← Previous", disabled=(idx == 0),
            key=f"nav_prev_{idx}", use_container_width=True,
            help="Go back one trial without submitting. Use to review or edit prior ratings.",
        ):
            st.session_state["current_trial_idx"] = idx - 1
            st.rerun()
    with _nav_status:
        already_rated = nct in state["ratings"]
        marker = " · already rated · editable" if already_rated else ""
        st.markdown(
            f'<div class="nav-status">Trial {idx + 1} of {n_total}{marker}</div>',
            unsafe_allow_html=True,
        )
    with _nav_next:
        if st.button(
            "Next →", disabled=(idx >= n_total - 1),
            key=f"nav_next_{idx}", use_container_width=True,
            help="Go forward one trial without submitting. Use to defer this trial and come back.",
        ):
            st.session_state["current_trial_idx"] = idx + 1
            st.rerun()

    _format_trial_for_rater(trial)

    # Track time-on-trial — start the clock when this trial is first shown
    timer_key = f"timer_{nct}"
    if timer_key not in st.session_state:
        st.session_state[timer_key] = time.time()

    # Axis layout — reading-flow order, see AXIS_LAYOUT comment.
    # Each row wrapped in a keyed st.container so CSS can tint the
    # middle layer (data-testid="stKey-axis_row_1"). Per-row column
    # widths come from AXIS_ROW_WIDTHS (None = equal).
    user_labels: dict[str, str | list[str]] = {}
    for i, row in enumerate(AXIS_LAYOUT):
        with st.container(key=f"axis_row_{i}"):
            if len(row) == 1:
                user_labels[row[0]] = _render_axis_input(
                    row[0], sample, key=f"input_{nct}_{row[0]}",
                    nct=nct,
                )
            else:
                widths = AXIS_ROW_WIDTHS.get(i)
                cols = st.columns(widths if widths else len(row))
                for col, axis in zip(cols, row):
                    with col:
                        user_labels[axis] = _render_axis_input(
                            axis, sample, key=f"input_{nct}_{axis}",
                            nct=nct,
                        )

    # Inline notes + submit row — was 2 separate rows, now 1
    _n_col, _skip_col, _submit_col = st.columns([0.55, 0.18, 0.27])
    with _n_col:
        notes = st.text_input(
            "Notes (optional)",
            key=f"notes_{nct}",
            placeholder="Rationale, ambiguity, adjudication notes…",
            label_visibility="collapsed",
        )
    with _skip_col:
        skip = st.button(
            "Skip", key=f"skip_{nct}",
            help="Use sparingly — every skip reduces κ power.",
            use_container_width=True,
        )
    with _submit_col:
        submit = st.button(
            f"Submit + next ({n_done + 1}/{n_total}) →",
            key=f"submit_{nct}",
            type="primary",
            use_container_width=True,
        )

    def _advance_to_next_unrated() -> None:
        """Move current_trial_idx to the next unrated trial after the
        current one (search forward, then wrap to find any unrated).
        Used by Submit/Skip after recording a rating, so the rater
        always lands on something productive next.
        """
        rated = set(state["ratings"].keys())
        n = len(sample["trials"])
        # Forward search from idx+1
        for i in range(idx + 1, n):
            if sample["trials"][i]["NCTId"] not in rated:
                st.session_state["current_trial_idx"] = i
                return
        # Wrap to find any unrated (rater navigated mid-pass)
        for i in range(0, n):
            if sample["trials"][i]["NCTId"] not in rated:
                st.session_state["current_trial_idx"] = i
                return
        # All rated — leave idx where it is; _render_done handles next render

    if skip:
        # Record the skip (still durable; lets us report skip rate)
        state["ratings"][nct] = {
            "labels": {ax: "Skipped" for ax in AXIS_OPTIONS},
            "notes": "[skipped by rater]",
            "duration_seconds": int(time.time() - st.session_state[timer_key]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skipped": True,
        }
        _persist(state, audit_nct=nct)
        st.session_state.pop(timer_key, None)
        _advance_to_next_unrated()
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
        _persist(state, audit_nct=nct)
        st.session_state.pop(timer_key, None)
        _advance_to_next_unrated()

        # Auto-prompt for backup every 10 ratings
        if (n_done + 1) % 10 == 0:
            st.toast(
                f"{n_done + 1} done — please click 'Download progress' "
                f"as a backup. Takes 2 sec.",
            )
        st.rerun()

    # ---- Keyboard hints — quiet bottom line ----
    st.markdown(
        '<div class="kbd-hints">'
        'Tip · pick <kbd>Unsure</kbd> if the trial text doesn\'t support a '
        'confident call · skip sparingly (every skip lowers κ power)'
        '</div>',
        unsafe_allow_html=True,
    )

    # ---- Footer (collapsed by default to preserve single-page view) ----
    with st.expander("Settings · session pace · backup · resume",
                      expanded=False):
        _render_footer(state, rater_id)


def _render_footer(state: dict, rater_id: str) -> None:
    """Bottom-of-page utilities: median time, email backup, resume upload.

    Lives inside a collapsed expander so the rater session is single-page
    by default. The above-the-fold view is purely the thin top
    progress bar + trial card + classification widgets.
    """
    durations = [r.get("duration_seconds", 0) for r in state["ratings"].values()
                 if not r.get("skipped")]
    if durations:
        med = sorted(durations)[len(durations) // 2]
        n_left = 200 - len(state["ratings"])
        eta_min = (med * n_left) / 60
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
