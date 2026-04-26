import os
import re
import subprocess
import numpy as np
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from datetime import date, datetime, timezone

from pipeline import (
    build_all_from_api,
    load_snapshot,
    list_snapshots,
    save_snapshot,
    BASE_URL,
    _LLM_OVERRIDES,
    _LLM_EXCLUDED_NCT_IDS,
    compute_classification_rationale,
    compute_confidence_factors,
)
from config import (
    ONTOLOGY,
    CATEGORY_TO_BRANCH,
    ENTITY_TO_CATEGORY,
    HEME_CATEGORIES,
    SOLID_CATEGORIES,
    BASKET_MULTI_LABEL,
    HEME_BASKET_LABEL,
    SOLID_BASKET_LABEL,
    UNCLASSIFIED_LABEL,
    ENTITY_TERMS,
    CATEGORY_FALLBACK_TERMS,
    HEME_BASKET_TERMS,
    SOLID_BASKET_TERMS,
    EXCLUDED_INDICATION_TERMS,
    HARD_EXCLUDED_NCT_IDS,
    CAR_CORE_TERMS,
    CAR_NK_TERMS,
    CAAR_T_TERMS,
    CAR_TREG_TERMS,
    ALLOGENEIC_MARKERS,
    AUTOL_MARKERS,
    HEME_TARGET_TERMS,
    SOLID_TARGET_TERMS,
    DUAL_TARGET_LABELS,
    NAMED_PRODUCT_TARGETS,
    NAMED_PRODUCT_TYPES,
    AMBIGUOUS_ENTITY_TOKENS,
    AMBIGUOUS_TARGET_TOKENS,
    MODALITY_ORDER,
)

st.set_page_config(
    page_title="CAR-T Oncology Trials Monitor",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


def _resolve_classifier_git_sha() -> str:
    """Return the short git SHA of the deployed classifier code, for
    embedding in CSV provenance headers. A reviewer downloading a CSV
    later can join (snapshot date, classifier SHA) to reproduce the
    classification deterministically. Falls back to "dev" outside a
    git checkout."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip() or "dev"
    except Exception:
        return "dev"


CLASSIFIER_GIT_SHA = _resolve_classifier_git_sha()


STATUS_OPTIONS = [
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "COMPLETED",
    "TERMINATED",
    "SUSPENDED",
    "WITHDRAWN",
    "UNKNOWN",
]

STATUS_DISPLAY = {
    "RECRUITING":              "Recruiting",
    "NOT_YET_RECRUITING":      "Not yet recruiting",
    "ACTIVE_NOT_RECRUITING":   "Active, not recruiting",
    "ENROLLING_BY_INVITATION": "By invitation",
    "COMPLETED":               "Completed",
    "TERMINATED":              "Terminated",
    "SUSPENDED":               "Suspended",
    "WITHDRAWN":               "Withdrawn",
    "UNKNOWN":                 "Unknown",
}

OPEN_SITE_STATUSES = {
    "RECRUITING", "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING",
}

PHASE_ORDER = [
    "EARLY_PHASE1", "PHASE1", "PHASE1|PHASE2",
    "PHASE2", "PHASE2|PHASE3", "PHASE3", "PHASE4", "Unknown",
]

PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase I",
    "PHASE1": "Phase I",
    "PHASE1|PHASE2": "Phase I/II",
    "PHASE2": "Phase II",
    "PHASE2|PHASE3": "Phase II/III",
    "PHASE3": "Phase III",
    "PHASE4": "Phase IV",
    "Unknown": "Unknown",
}

_PLATFORM_LABELS = {"CAR-NK", "CAR-Treg", "CAAR-T", "CAR-γδ T"}

# ---------------------------------------------------------------------------
# Approved CAR-T products — used for Fig 1's regulatory-milestone strip.
# ---------------------------------------------------------------------------
# Curated manually: no clean public API covers CAR-T biologics across FDA,
# EMA, and NMPA. Scheduled refresh cadence is quarterly — see the
# "Quarterly approvals review" issue template for sources + update checklist.
#
# Last reviewed: 2026-04-24
APPROVED_PRODUCTS_LAST_REVIEWED = "2026-04-24"
APPROVED_PRODUCTS = [
    # FDA approvals (primary — drawn as prominent vertical lines)
    {"year": 2017, "name": "tisa-cel (Kymriah)",   "target": "CD19", "regulator": "FDA"},
    {"year": 2017, "name": "axi-cel (Yescarta)",   "target": "CD19", "regulator": "FDA"},
    {"year": 2020, "name": "brexu-cel (Tecartus)", "target": "CD19", "regulator": "FDA"},
    {"year": 2021, "name": "liso-cel (Breyanzi)",  "target": "CD19", "regulator": "FDA"},
    {"year": 2021, "name": "ide-cel (Abecma)",     "target": "BCMA", "regulator": "FDA"},
    {"year": 2022, "name": "cilta-cel (Carvykti)", "target": "BCMA", "regulator": "FDA"},
    {"year": 2024, "name": "obe-cel (Aucatzyl)",   "target": "CD19", "regulator": "FDA"},
    # NMPA approvals (China — listed in caption only, no chart line)
    {"year": 2021, "name": "relma-cel (Carteyva)", "target": "CD19", "regulator": "NMPA"},
    {"year": 2023, "name": "eque-cel (Fucaso)",    "target": "BCMA", "regulator": "NMPA"},
    {"year": 2024, "name": "zevor-cel",            "target": "BCMA", "regulator": "NMPA"},
    # EMA approvals (EU — listed in caption only, no chart line)
    {"year": 2018, "name": "tisa-cel (Kymriah)",   "target": "CD19", "regulator": "EMA"},
    {"year": 2018, "name": "axi-cel (Yescarta)",   "target": "CD19", "regulator": "EMA"},
    {"year": 2020, "name": "brexu-cel (Tecartus)", "target": "CD19", "regulator": "EMA"},
    {"year": 2021, "name": "ide-cel (Abecma)",     "target": "BCMA", "regulator": "EMA"},
    {"year": 2022, "name": "liso-cel (Breyanzi)",  "target": "CD19", "regulator": "EMA"},
    {"year": 2022, "name": "cilta-cel (Carvykti)", "target": "BCMA", "regulator": "EMA"},
    {"year": 2025, "name": "obe-cel (Aucatzyl)",   "target": "CD19", "regulator": "EMA"},
]

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
THEME = {
    "bg":      "#ffffff",
    "surface": "#ffffff",
    "surf2":   "#f8fafc",
    "surf3":   "#e5e7eb",
    "text":    "#0b1220",
    "muted":   "#475569",
    "faint":   "#94a3b8",
    "border":  "#e5e7eb",
    "primary": "#0b3d91",
    "teal":    "#0f766e",
    "amber":   "#92400e",
    "shadow":  "none",
    "grid":    "#f1f5f9",
}

# Heme vs Solid palette (publication-ready; not the primary navy)
HEME_COLOR  = "#0b3d91"   # deep navy — heme stories
SOLID_COLOR = "#b45309"   # amber-700 — solid stories (complementary warm tone)
MIXED_COLOR = "#475569"   # slate-600 — neutral (replaces indigo per style guide)
UNKNOWN_COLOR = "#94a3b8" # slate-400

BRANCH_COLORS = {
    "Heme-onc": HEME_COLOR,
    "Solid-onc": SOLID_COLOR,
    "Mixed": MIXED_COLOR,
    "Unknown": UNKNOWN_COLOR,
}

_MODALITY_COLORS: dict[str, str] = {}  # populated below once NEJM palette defined

# ---------------------------------------------------------------------------
# Shared UI constants — single source of truth (Rheum × Onc style guide).
# Reference these in new code instead of hard-coding heights or fonts.
# ---------------------------------------------------------------------------
PANEL_HEIGHT         = 440  # overview panels (horizontal bars)
TABLE_HEIGHT_DEFAULT = 360  # st.dataframe default when not auto-sized
HAIRLINE             = THEME["border"]
FONT_FAMILY          = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


# ---------------------------------------------------------------------------
# Country name → ISO-3 mapping for Plotly choropleth. The library behind
# `locationmode="country names"` is being deprecated (DeprecationWarning
# on every app load); ISO-3 codes are the stable replacement. Covers
# every country appearing in CT.gov trial records for CAR-T oncology.
# ---------------------------------------------------------------------------
COUNTRY_TO_ISO3: dict[str, str] = {
    # Americas
    "United States": "USA", "Canada": "CAN", "Mexico": "MEX",
    "Brazil": "BRA", "Argentina": "ARG", "Chile": "CHL",
    "Colombia": "COL", "Peru": "PER", "Uruguay": "URY",
    "Costa Rica": "CRI", "Panama": "PAN", "Guatemala": "GTM",
    "Cuba": "CUB", "Puerto Rico": "PRI",
    # Europe
    "United Kingdom": "GBR", "Germany": "DEU", "France": "FRA",
    "Italy": "ITA", "Spain": "ESP", "Netherlands": "NLD",
    "Belgium": "BEL", "Switzerland": "CHE", "Austria": "AUT",
    "Sweden": "SWE", "Denmark": "DNK", "Norway": "NOR",
    "Finland": "FIN", "Poland": "POL", "Czechia": "CZE",
    "Czech Republic": "CZE", "Hungary": "HUN", "Greece": "GRC",
    "Portugal": "PRT", "Ireland": "IRL",
    "Romania": "ROU", "Slovakia": "SVK", "Slovenia": "SVN",
    "Bulgaria": "BGR", "Croatia": "HRV", "Serbia": "SRB",
    "Ukraine": "UKR", "Belarus": "BLR", "Estonia": "EST",
    "Latvia": "LVA", "Lithuania": "LTU", "Luxembourg": "LUX",
    "Iceland": "ISL", "Malta": "MLT", "Cyprus": "CYP",
    # Russia (both spellings)
    "Russia": "RUS", "Russian Federation": "RUS",
    # UK aliases
    "United Kingdom of Great Britain and Northern Ireland": "GBR",
    # Asia-Pacific
    "China": "CHN", "Japan": "JPN", "South Korea": "KOR",
    "Korea, Republic of": "KOR", "Korea, South": "KOR",
    "Taiwan": "TWN", "Hong Kong": "HKG",
    "Singapore": "SGP", "Malaysia": "MYS", "Thailand": "THA",
    "Indonesia": "IDN", "Philippines": "PHL", "Vietnam": "VNM",
    "Viet Nam": "VNM", "India": "IND", "Pakistan": "PAK",
    "Bangladesh": "BGD", "Sri Lanka": "LKA", "Nepal": "NPL",
    "Australia": "AUS", "New Zealand": "NZL",
    # Middle East / Africa
    "Israel": "ISR", "Turkey": "TUR", "Turkey (Türkiye)": "TUR",
    "Türkiye": "TUR", "Saudi Arabia": "SAU",
    "United Arab Emirates": "ARE", "Iran": "IRN",
    "Iran, Islamic Republic of": "IRN",
    "Egypt": "EGY", "South Africa": "ZAF", "Nigeria": "NGA",
    "Kenya": "KEN", "Morocco": "MAR", "Tunisia": "TUN",
    "Jordan": "JOR", "Lebanon": "LBN",
}


def _to_iso3(country: str | None) -> str | None:
    """Return the ISO-3 code for a country name, or None if not mapped.
    Ignoring unknowns drops them from the choropleth but keeps the bar chart."""
    if not country:
        return None
    c = str(country).strip()
    return COUNTRY_TO_ISO3.get(c)


# ---------------------------------------------------------------------------
# Table-config helpers — every st.dataframe in the app should route through
# one of these to keep column labels, widths, and formatting consistent
# (Rheum × Onc style guide). Helpers are shared utilities and do not touch
# data logic.
# ---------------------------------------------------------------------------

def _landscape_table_cols(dim_key: str, dim_label: str) -> dict:
    """Summary / 'landscape by …' tables (by disease / product / sponsor / …)."""
    _enroll_help = (
        "Planned enrollment from CT.gov (self-reported target, not actual accrual)."
    )
    return {
        dim_key:            st.column_config.TextColumn(dim_label),
        "Trials":           st.column_config.NumberColumn("Trials", format="%d"),
        "Open":             st.column_config.NumberColumn("Open / recruiting", format="%d"),
        "Sponsors":         st.column_config.NumberColumn("Distinct sponsors", format="%d"),
        "TotalEnrolled":    st.column_config.NumberColumn(
            "Total planned enrollment", format="%,d", help=_enroll_help),
        "MedianEnrollment": st.column_config.NumberColumn(
            "Median enrollment", format="%d", help=_enroll_help),
    }


def _trial_detail_cols(extra: dict | None = None) -> dict:
    """Drilldown 'Trials' detail tables — configure every shown column."""
    cfg = {
        "NCTId":           st.column_config.TextColumn("NCT ID"),
        "NCTLink":         st.column_config.LinkColumn("Trial link", display_text="Open trial"),
        "BriefTitle":      st.column_config.TextColumn("Title", width="large"),
        "Branch":          st.column_config.TextColumn("Branch"),
        "DiseaseCategory": st.column_config.TextColumn("Category"),
        "DiseaseEntity":   st.column_config.TextColumn("Disease"),
        "DiseaseEntities": st.column_config.TextColumn("Disease(s)", width="medium"),
        "TargetCategory":  st.column_config.TextColumn("Target"),
        "ProductType":     st.column_config.TextColumn("Product"),
        "ProductName":     st.column_config.TextColumn("Named product", width="small"),
        "Phase":           st.column_config.TextColumn("Phase"),
        "OverallStatus":   st.column_config.TextColumn("Status"),
        "LeadSponsor":     st.column_config.TextColumn("Lead sponsor", width="medium"),
        "SponsorType":     st.column_config.TextColumn("Sponsor type", width="small"),
        "AgeGroup":        st.column_config.TextColumn("Age group", width="small"),
        "StartYear":       st.column_config.NumberColumn("Start year", format="%d"),
        "Countries":       st.column_config.TextColumn("Countries", width="medium"),
        "ClassificationConfidence": st.column_config.TextColumn("Conf.", width="small"),
    }
    if extra:
        cfg.update(extra)
    return cfg


def _mini_count_cols(label: str) -> dict:
    """2-col count tables ('Antigen targets', 'Products', 'Top sponsors', …)."""
    return {
        label:    st.column_config.TextColumn(label, width="medium"),
        "Trials": st.column_config.NumberColumn("Trials", format="%d", width="small"),
    }


def _render_trial_drilldown(record, *, key_suffix: str = "") -> None:
    """Render the per-trial detail card.

    Conforms to UI_DRILLDOWN_SPEC v1.0
    (`docs/internal/UI_DRILLDOWN_SPEC.md`). Used by the Data tab,
    Geography city-trials table, and every Deep Dive sub-tab. The
    rheum sister app implements the same spec for cross-app UI parity.

    Layout (top → bottom):
      1. Flag banner          (_render_flag_banner)
      2. CT.gov external link (placed BEFORE metadata so a rater can
                                verify against the live record without
                                scrolling)
      3. 3-column metadata grid (Disease / Product / Sponsor)
         with inline `*(via Source)*` tags on Target + ProductType
      4. Free-text payload (Endpoints, Conditions, Interventions,
                            BriefSummary in block-quote)
      5. "How was this classified?" expander
         (_render_classification_rationale)
      6. "Suggest a classification correction" expander
         (_render_suggest_correction)

    Parameters
    ----------
    record : pd.Series or dict-like
        A single trial row. Accessed via .get(); missing fields render as "—".
    key_suffix : str
        Disambiguator for any session_state-keyed widgets inside the card.
        Required when multiple drilldowns appear on the same page.
    """
    _sel_nct = record.get("NCTId", "")
    _title = record.get("BriefTitle", "")
    with st.expander(f"**{_sel_nct}** — {_title}", expanded=True):
        # ---- 1. Flag banner ----
        try:
            _render_flag_banner(record)
        except NameError:
            pass

        # ---- 2. External link (spec v1.0: placed before metadata) ----
        _link = (
            record.get("NCTLink")
            or (f"https://clinicaltrials.gov/study/{_sel_nct}"
                if _sel_nct else None)
        )
        if _link:
            st.markdown(f"**[Open on ClinicalTrials.gov ↗]({_link})**")

        # ---- 3. Three-column metadata grid (spec v1.2) ----
        # Each column carries a bold section header ("Disease" / "Product" /
        # "Sponsor") so the visual structure is unmissable when scrolling
        # through many drilldowns. Inline `*(via Source)*` tags on Target
        # and ProductType for at-a-glance audit.
        d1, d2, d3 = st.columns(3)
        with d1:
            # DISEASE column
            _start_year = record.get("StartYear")
            _start_disp = (
                int(_start_year) if pd.notna(_start_year) else "—"
            )
            _all_ents = record.get("DiseaseEntities") or record.get("DiseaseEntity") or "—"
            _all_ents = str(_all_ents).replace("|", ", ")
            st.markdown("### Disease")
            st.markdown(
                f"**Branch:** {record.get('Branch', '—')}  \n"
                f"**Category:** {record.get('DiseaseCategory', '—')}  \n"
                f"**Entity:** {record.get('DiseaseEntity', '—')}  \n"
                f"**All entities:** {_all_ents}  \n"
                f"**Trial design:** {record.get('TrialDesign', '—')}  \n"
                f"**Phase:** {record.get('Phase', '—')}  \n"
                f"**Status:** {record.get('OverallStatus', '—')}  \n"
                f"**Start year:** {_start_disp}"
            )
        with d2:
            # PRODUCT column with inline source tags
            _target = record.get("TargetCategory", "—")
            _target_src = record.get("TargetSource", "")
            _target_str = (
                f"**Target:** {_target}  *(via `{_target_src}`)*"
                if _target_src else f"**Target:** {_target}"
            )
            _ptype = record.get("ProductType", "—")
            _ptype_src = record.get("ProductTypeSource", "")
            _ptype_str = (
                f"**Product type:** {_ptype}  *(via `{_ptype_src}`)*"
                if _ptype_src else f"**Product type:** {_ptype}"
            )
            _named = record.get("ProductName")
            _named_str = f"**Named product:** {_named}  \n" if _named else ""
            _llm_str = (
                "**LLM override applied**  \n"
                if bool(record.get("LLMOverride", False)) else ""
            )
            st.markdown("### Product")
            st.markdown(
                f"{_target_str}  \n"
                f"{_ptype_str}  \n"
                f"**Modality:** {record.get('Modality', '—')}  \n"
                f"{_named_str}"
                f"{_llm_str}"
                f"**Confidence:** {record.get('ClassificationConfidence', '—')}"
            )
        with d3:
            # SPONSOR column
            _enroll_raw = record.get("EnrollmentCount")
            _enroll_display = (
                int(_enroll_raw) if pd.notna(_enroll_raw) else "—"
            )
            st.markdown("### Sponsor")
            st.markdown(
                f"**Lead sponsor:** {record.get('LeadSponsor', '—')}  \n"
                f"**Sponsor type:** {record.get('SponsorType', '—')}  \n"
                f"**Enrollment:** {_enroll_display}  \n"
                f"**Countries:** {record.get('Countries', '') or '—'}  \n"
                f"**Age group:** {record.get('AgeGroup', '—')}"
            )

        # ---- 4. Free-text payload ----
        # Pipe → comma substitution for human readability on multi-valued
        # fields; block-quote for BriefSummary so it visually separates
        # from the metadata above.
        if record.get("PrimaryEndpoints"):
            st.markdown(
                f"**Primary endpoints:** "
                f"{str(record['PrimaryEndpoints']).replace('|', '; ')}"
            )
        if record.get("Conditions"):
            st.markdown(
                f"**Conditions:** "
                f"{str(record['Conditions']).replace('|', ', ')}"
            )
        if record.get("Interventions"):
            st.markdown(
                f"**Interventions:** "
                f"{str(record['Interventions']).replace('|', ', ')}"
            )
        if record.get("BriefSummary"):
            st.markdown("**Brief summary**")
            st.markdown(f"> {record['BriefSummary']}")

        # ---- 5. "How was this classified?" ----
        try:
            _render_classification_rationale(record, key_suffix=key_suffix)
        except Exception as _e:  # noqa: BLE001
            st.caption(f"_(classification rationale unavailable: {_e})_")

        # ---- 6. Suggest-correction ----
        try:
            _render_suggest_correction(record, key_suffix=key_suffix)
        except NameError:
            pass


# ---------------------------------------------------------------------------
# Community quality-improvement: Suggest-correction form
# ---------------------------------------------------------------------------
# Architecture (per design discussion 2026-04-25):
#   - Public flags submitted via GitHub Issues API
#   - Auth handled by GitHub (link-out to a pre-filled issue) — zero auth
#     code on our side, no tokens stored, GitHub username = identity
#   - Configurable N-reviewer consensus before promotion to llm_overrides.
#     Default N=1 at current low community volume (single-reviewer surfaces
#     to moderator); raisable to 2 or 3 once enough independent reviewers
#     exist that crowd-vetting actually filters noise.
#   - Moderator-approval gate on top of consensus (Peter only, for now) —
#     this is the real quality bar; consensus just decides what reaches
#     the moderator's queue.
#   - Helper (this function) runs INSIDE _render_trial_drilldown so the
#     affordance appears on every trial card across the app
# ---------------------------------------------------------------------------

GITHUB_REPO_SLUG = "ptjeong/ONC-CAR-T-Trials-Monitor"

# Per-axis option lists shown in the form. Restricted to canonical labels
# already used by the classifier so submitted corrections feed cleanly back
# into the override schema.
_FLAG_AXIS_OPTIONS: dict[str, list[str]] = {
    "Branch":           ["Heme-onc", "Solid-onc", "Mixed", "Unknown"],
    "DiseaseCategory":  sorted(set(VALID_CATEGORIES)) if (
        "VALID_CATEGORIES" in dir() and VALID_CATEGORIES
    ) else [],
    "DiseaseEntity":    [],   # free text — too many leaves to enumerate cleanly
    "TargetCategory":   [],   # free text — antigen list is dynamic
    "ProductType":      ["Autologous", "Allogeneic/Off-the-shelf", "In vivo", "Unclear"],
    "SponsorType":      ["Industry", "Academic", "Government", "Other"],
}


def _build_flag_issue_url(record, *, axes: list[str], corrections: dict[str, str],
                            notes: str) -> str:
    """Construct a GitHub issue URL with title + labels + structured YAML
    body pre-filled. The user lands on github.com with everything ready;
    they review and click Submit. Auth is handled by GitHub.

    The body uses an HTML-comment-bracketed YAML block so the
    consensus-detection GitHub Action can parse it back without needing
    a custom front-matter convention. Free-form notes appear AFTER the
    machine-readable block.
    """
    import urllib.parse as _up

    nct = record.get("NCTId", "")
    title_axes = ", ".join(axes) if axes else "general"
    title = f"[Flag] {nct} — {title_axes}"

    # Machine-readable block first
    yaml_lines = [
        "<!-- BEGIN_FLAG_DATA",
        f"nct_id: {nct}",
        f"flagged_axes:",
    ]
    for axis in axes:
        pipeline_label = record.get(axis, "")
        yaml_lines += [
            f"  - axis: {axis}",
            f"    pipeline_label: \"{pipeline_label}\"",
            f"    proposed_correction: \"{corrections.get(axis, '')}\"",
        ]
    yaml_lines.append("END_FLAG_DATA -->")
    yaml_block = "\n".join(yaml_lines)

    body_md = f"""## Trial classification correction

**Trial**: [{nct}](https://clinicaltrials.gov/study/{nct})
**Title**: {record.get("BriefTitle", "")}

### Current pipeline classification
| Axis | Current label |
|---|---|
"""
    for axis in axes:
        body_md += f"| {axis} | `{record.get(axis, '')}` |\n"

    body_md += "\n### Proposed correction\n"
    body_md += "| Axis | Proposed |\n|---|---|\n"
    for axis in axes:
        body_md += f"| {axis} | `{corrections.get(axis, '')}` |\n"

    if notes:
        body_md += f"\n### Reviewer notes\n\n{notes}\n"

    body_md += f"""
### Reviewer information
- **Submitted via**: dashboard at https://onc-car-t-trial-monitor.streamlit.app
- **GitHub identity**: this issue was created by your GitHub login (visible above)

### Moderator workflow
1. Reviewers can add their own assessment as a comment using the same axis schema.
2. The issue is auto-labelled `consensus-reached` once at least
   `CONSENSUS_THRESHOLD` reviewers agree (currently 1 — single-reviewer
   suffices to surface to the moderator at the dashboard's current
   community volume; raisable as the reviewer pool grows).
3. The moderator (@ptjeong) reviews the consensus in the dashboard's
   Moderation tab. Approve → promotes the correction to
   `llm_overrides.json` via `scripts/promote_consensus_flags.py`.

---

{yaml_block}

<sub>This issue was pre-filled by the dashboard's Suggest-correction
affordance. See `docs/methods.md` § 4.4 for the validation methodology.</sub>
"""

    labels = ["classification-flag", "needs-review"]
    for axis in axes:
        labels.append(f"axis-{axis}")

    params = {
        "title": title,
        "body":  body_md,
        "labels": ",".join(labels),
    }
    return (
        f"https://github.com/{GITHUB_REPO_SLUG}/issues/new?"
        + _up.urlencode(params)
    )


def _render_classification_rationale(record, *, key_suffix: str = "") -> None:
    """Per-trial 'How was this classified?' expander.

    Re-runs `compute_classification_rationale` on the trial row to
    surface, per axis: the assigned label + source tag + matched
    terms + a one-sentence human-readable explanation.

    The matched-term lists let a reviewer immediately see WHICH
    text bits drove a classification — turning a black-box label
    into an auditable evidence chain. If they disagree they can
    click through to the Suggest-correction expander right below.
    """
    if record is None:
        return
    # Convert pd.Series to dict for the pure-function rationale helper
    row = (record.to_dict()
           if hasattr(record, "to_dict") else dict(record))
    nct = row.get("NCTId", "")
    if not nct:
        return

    with st.expander("How was this classified?", expanded=False):
        st.caption(
            "Re-runs the classifier on this trial's text and surfaces the "
            "matched terms + source tag per axis. Use this to audit a "
            "label before flagging it. If you disagree, scroll down to "
            "*Suggest a classification correction*."
        )

        # Multi-factor confidence panel — composite + per-axis sub-scores
        # via st.metric tiles. Lets a reviewer see at-a-glance which axis
        # drove a "low" confidence rather than guessing from the legacy
        # 3-bucket label alone.
        try:
            cf = compute_confidence_factors(row)
            # NEJM-clean text label — no traffic-light emojis. Word + percent.
            _level_word = {
                "high": "High", "medium": "Moderate", "low": "Limited",
            }.get(cf["level"], cf["level"].title())
            st.markdown(
                f"#### Composite confidence: "
                f"**{_level_word}** ({cf['score']*100:.0f}%)"
            )
            _cols = st.columns(len(cf["factors"]))
            for col, (axis, info) in zip(_cols, cf["factors"].items()):
                with col:
                    st.metric(
                        axis,
                        f"{info['score']*100:.0f}%",
                        help=info["driver"],
                    )
            # Drivers — surface the lowest-scoring axes' explanations
            if cf["drivers"]:
                drv_lines = [f"- **{a}**: {d}" for a, d in cf["drivers"]
                              if d]
                if drv_lines:
                    st.caption(
                        "**What's holding the score down:**\n"
                        + "\n".join(drv_lines)
                    )
            st.divider()
        except Exception as _e:  # noqa: BLE001
            st.caption(f"_(confidence panel unavailable: {_e})_")

        try:
            rationale = compute_classification_rationale(row)
        except Exception as e:
            st.error(f"Could not compute rationale: {e}")
            return

        rows = []
        for axis, info in rationale.items():
            matched = info.get("matched_terms") or []
            rows.append({
                "Axis": axis,
                "Label": info.get("label") or "—",
                "Source": info.get("source") or "—",
                "Matched terms": (", ".join(str(m) for m in matched[:6])
                                  if matched else "—"),
                "Explanation": info.get("explanation") or "",
            })
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True, width="stretch",
            column_config={
                "Axis": st.column_config.TextColumn(width="small"),
                "Label": st.column_config.TextColumn(width="small"),
                "Source": st.column_config.TextColumn(
                    width="small",
                    help=("How the label was determined. `llm_override` = "
                          "manual entry in llm_overrides.json; everything "
                          "else is rule-based (term match, default, etc.)."),
                ),
                "Matched terms": st.column_config.TextColumn(width="medium"),
                "Explanation": st.column_config.TextColumn(width="large"),
            },
        )

        # Surface the LLM-override note prominently when present
        if any(r["Source"] == "llm_override" for r in rows):
            override_entry = _LLM_OVERRIDES.get(nct, {})
            if override_entry.get("notes"):
                st.info(f"**LLM-override note:** {override_entry['notes']}")


def _render_suggest_correction(record, *, key_suffix: str = "") -> None:
    """Suggest-correction form inside the trial drilldown.

    Renders an expander with a per-axis correction form. On submit,
    builds a pre-filled GitHub issue URL and surfaces a button that
    opens it in a new tab. Submission completes on github.com — the
    user authenticates via GitHub and clicks Submit there.

    Why link-out instead of in-app POST: zero auth code in this app,
    no PAT to manage, identity verified by GitHub. The "extra click"
    is also a feature — kills spam at the entry point.
    """
    nct = record.get("NCTId", "")
    if not nct:
        return  # nothing to flag against

    with st.expander("Suggest a classification correction", expanded=False):
        st.caption(
            "If you think the classifier got an axis wrong, propose a correction "
            "below. Submission opens a pre-filled GitHub issue — you'll log in "
            "(or sign up) on GitHub and click Submit there. The flag is then "
            "queued for moderator review and, if approved, promoted to "
            "`llm_overrides.json` so the next pipeline reload reflects the fix."
        )

        # Axis multiselect — only enumerable axes; free-text fallback for
        # entity / target where the option space is too wide.
        _selected_axes = st.multiselect(
            "Which axis is wrong?",
            options=list(_FLAG_AXIS_OPTIONS.keys()),
            key=f"flag_axes_{nct}_{key_suffix}",
            help="Pick every axis you'd like to suggest a correction on.",
        )

        corrections: dict[str, str] = {}
        if _selected_axes:
            for axis in _selected_axes:
                _current = record.get(axis, "")
                _options = _FLAG_AXIS_OPTIONS.get(axis, [])
                _label = f"{axis} should be (current: `{_current}`)"
                if _options:
                    corrections[axis] = st.selectbox(
                        _label,
                        options=[""] + _options,
                        key=f"flag_correction_{axis}_{nct}_{key_suffix}",
                    )
                else:
                    corrections[axis] = st.text_input(
                        _label,
                        value="",
                        key=f"flag_correction_{axis}_{nct}_{key_suffix}",
                        placeholder="Type the correct label",
                    )

        notes = st.text_area(
            "Notes (optional)",
            value="",
            key=f"flag_notes_{nct}_{key_suffix}",
            height=80,
            placeholder="Briefly explain your reasoning, cite the trial text or a "
                        "reference if helpful. Visible publicly in the GitHub issue.",
        )

        ready = bool(_selected_axes) and any(
            corrections.get(a) for a in _selected_axes
        )

        if not ready:
            st.caption(
                "Pick at least one axis and provide a proposed correction to "
                "enable the submit button."
            )
        else:
            # Filter to only axes with a non-empty correction
            _final_axes = [a for a in _selected_axes if corrections.get(a)]
            _url = _build_flag_issue_url(
                record,
                axes=_final_axes,
                corrections={a: corrections[a] for a in _final_axes},
                notes=notes,
            )
            st.link_button(
                "Open as GitHub issue ↗",
                _url,
                type="primary",
                help="Opens a pre-filled GitHub issue in a new tab. You'll need a "
                     "GitHub account (free, fast to register).",
            )
            st.caption(
                "After clicking Submit on GitHub, the issue enters the moderator "
                "review queue. You can track all open flags at "
                f"[github.com/{GITHUB_REPO_SLUG}/issues?q=label%3Aclassification-flag]"
                f"(https://github.com/{GITHUB_REPO_SLUG}/issues?q=label%3Aclassification-flag)."
            )


@st.cache_data(ttl=60 * 5, show_spinner=False)
def _load_active_flags() -> dict:
    """Fetch open classification-flag GitHub issues and group by NCT ID.

    Returns {nct_id: {"count": int, "consensus": bool, "issue_urls": [...]}}.
    Cached 5 minutes so a single page render doesn't hit the API per-trial.

    Uses the GitHub public-issues API (no auth needed, 60 requests/hour
    rate limit unauthenticated — fine for a 5-minute cache and ~1 fetch
    per session). On any error (network, rate limit, JSON parse), returns
    {} so badge rendering silently degrades rather than crashing the page.
    """
    try:
        import requests
        url = (
            f"https://api.github.com/repos/{GITHUB_REPO_SLUG}/issues"
            "?state=open&labels=classification-flag&per_page=100"
        )
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {}
        issues = resp.json()
        flags: dict[str, dict] = {}
        import re as _re_flag
        nct_re = _re_flag.compile(r"NCT\d{8}")
        for issue in issues:
            title = issue.get("title", "")
            labels = {lbl.get("name", "") for lbl in (issue.get("labels") or [])}
            # Try to extract NCT from title first (we put it there); fall back
            # to issue body if needed.
            m = nct_re.search(title) or nct_re.search(issue.get("body", "") or "")
            if not m:
                continue
            nct = m.group(0)
            entry = flags.setdefault(nct, {
                "count": 0, "consensus": False, "issue_urls": [],
            })
            entry["count"] += 1
            entry["issue_urls"].append(issue.get("html_url", ""))
            if "consensus-reached" in labels:
                entry["consensus"] = True
        return flags
    except Exception:
        return {}


_FLAG_EMOJI = "🚩"


def _attach_flag_column(
    df: "pd.DataFrame", show_cols: list[str]
) -> "tuple[pd.DataFrame, list[str]]":
    """Inline-flag indicator: prepend 🚩 to BriefTitle for flagged trials.

    Replaces the earlier `_Flag` column approach (which reserved a fixed
    width even when no trials were flagged — wasted screen real estate
    in the common case). Now the indicator is invisible until a flag
    exists, and clicking the row opens the drilldown which renders
    `_render_flag_banner` with full proposal details + GH link.

    Returns (df_copy, show_cols) — show_cols is unchanged. The function
    name is kept stable so the call sites in every trial table don't
    need to be touched again.

    Idempotent: re-running on an already-prefixed BriefTitle is a no-op.
    """
    flags = _load_active_flags()
    out = df.copy()
    if not flags or "NCTId" not in out.columns or "BriefTitle" not in out.columns:
        return out, show_cols

    def _prefix(row):
        nct = row.get("NCTId", "")
        title = str(row.get("BriefTitle", ""))
        if title.startswith(f"{_FLAG_EMOJI} "):
            return title  # already prefixed (idempotent)
        entry = flags.get(nct)
        if entry and entry.get("count", 0) > 0:
            return f"{_FLAG_EMOJI} {title}"
        return title

    out["BriefTitle"] = out.apply(_prefix, axis=1)
    return out, show_cols


@st.cache_data(ttl=60 * 5, show_spinner=False)
def _load_flag_issue_details(issue_url: str) -> dict:
    """Fetch a single flag issue's body + parse out proposal blocks.

    Called from the drilldown banner so we can show the actual proposed
    corrections inline (not just a count). Cached 5 minutes to match
    `_load_active_flags`. Returns {} on any failure so the banner
    silently degrades to a plain GitHub link rather than crashing.
    """
    if not issue_url:
        return {}
    import re as _re_det
    m = _re_det.match(
        r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)", issue_url
    )
    if not m:
        return {}
    api_url = f"https://api.github.com/repos/{m.group(1)}/issues/{m.group(2)}"
    try:
        import requests
        r = requests.get(api_url, timeout=8)
        if r.status_code != 200:
            return {}
        issue = r.json()
        body = issue.get("body", "") or ""
        # Pull each BEGIN_FLAG_DATA block; tolerant of malformed YAML.
        proposals: list[dict] = []
        block_re = _re_det.compile(
            r"<!--\s*BEGIN_FLAG_DATA\s*\n(.*?)END_FLAG_DATA\s*-->",
            _re_det.DOTALL,
        )
        try:
            import yaml as _yaml_det
            for blk in block_re.finditer(body):
                try:
                    data = _yaml_det.safe_load(blk.group(1))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                for ax in (data.get("flagged_axes") or []):
                    if isinstance(ax, dict):
                        proposals.append(ax)
        except ImportError:
            # pyyaml not installed — fall back to a regex scrape so the
            # banner still shows the proposed values, just less robustly.
            pair_re = _re_det.compile(
                r"axis:\s*(\w+).*?pipeline_label:\s*\"?([^\"\n]*)\"?.*?"
                r"proposed_correction:\s*\"?([^\"\n]*)\"?",
                _re_det.DOTALL,
            )
            for blk in block_re.finditer(body):
                for axm in pair_re.finditer(blk.group(1)):
                    proposals.append({
                        "axis": axm.group(1).strip(),
                        "pipeline_label": axm.group(2).strip(),
                        "proposed_correction": axm.group(3).strip(),
                    })
        return {
            "title": issue.get("title", ""),
            "html_url": issue.get("html_url", issue_url),
            "author": (issue.get("user") or {}).get("login", ""),
            "created_at": issue.get("created_at", ""),
            "proposals": proposals,
        }
    except Exception:
        return {}


def _render_flag_banner(record) -> None:
    """Render the per-trial flag banner at the top of the drilldown card.

    Invisible when the trial has no open flags. Otherwise renders:
      - st.error (consensus) or st.warning (open) status header
      - inline table of proposed corrections (axis | current | proposed)
        with direct links to the originating GitHub issue
      - explicit "View discussion on GitHub" link button(s)

    Called from `_render_trial_drilldown` for every trial-detail render.
    Safe to call when `_load_active_flags()` returned {} (no-op).
    """
    nct = record.get("NCTId", "") if record is not None else ""
    if not nct:
        return
    flags = _load_active_flags()
    entry = flags.get(nct)
    if not entry or entry.get("count", 0) == 0:
        return

    n = entry["count"]
    is_consensus = bool(entry.get("consensus"))
    issue_urls = entry.get("issue_urls", [])

    if is_consensus:
        st.error(
            f"{_FLAG_EMOJI} **Awaiting moderator review** — the community "
            "has reached the consensus threshold on this trial's "
            "classification. Moderator decision pending."
        )
    else:
        plural = "s" if n > 1 else ""
        st.warning(
            f"{_FLAG_EMOJI} **{n} open classification flag{plural}** — "
            "community has suggested a correction to this trial's labels. "
            "Awaiting consensus before moderator review."
        )

    # Pull proposals from each linked issue and show them inline so the
    # reader sees what's being challenged without having to click through.
    all_proposals: list[dict] = []
    for url in issue_urls:
        details = _load_flag_issue_details(url)
        for prop in details.get("proposals", []):
            all_proposals.append({
                "Axis": prop.get("axis", ""),
                "Current label": prop.get("pipeline_label", ""),
                "Proposed correction": prop.get("proposed_correction", ""),
                "Discussion": url,
            })

    if all_proposals:
        st.markdown("**Proposed corrections:**")
        st.dataframe(
            pd.DataFrame(all_proposals),
            hide_index=True, width="stretch",
            column_config={
                "Discussion": st.column_config.LinkColumn(
                    "Discussion",
                    display_text="View ↗",
                    help="Open the GitHub issue thread for this proposal.",
                ),
            },
        )
    else:
        # YAML parse failed or yet-unfetched — give the link(s) anyway.
        for url in issue_urls:
            st.markdown(f"- [View flag discussion on GitHub ↗]({url})")


# ---------------------------------------------------------------------------
# Moderator-validation pool helpers
#   The Moderation tab writes one append-only JSON record per moderator
#   action (accept/reject a flag, or annotate a randomly-sampled trial)
#   into MODERATOR_VALIDATIONS_PATH. That file is the substrate for:
#     - per-axis Cohen's κ between pipeline and moderator labels
#     - the override-promotion pipeline (scripts/promote_consensus_flags.py)
#     - long-term audit trail (every label change carries a timestamp,
#       moderator handle, source — flag-issue or random-sample — and rationale)
# ---------------------------------------------------------------------------

MODERATOR_VALIDATIONS_PATH = "moderator_validations.json"
_MODERATOR_AXES = ("Branch", "DiseaseCategory", "DiseaseEntity",
                   "TargetCategory", "ProductType", "SponsorType")


def _load_moderator_validations() -> list[dict]:
    """Read the moderator-validations log from disk.

    Returns [] if the file is missing or unparseable. Each record is a
    flat dict with keys: nct_id, axis, pipeline_label, moderator_label,
    timestamp, source ('flag' | 'random'), moderator, rationale, issue_url.
    """
    import json
    try:
        with open(MODERATOR_VALIDATIONS_PATH, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _append_moderator_validation(record: dict) -> None:
    """Append one validation event. Writes the whole list back atomically
    enough for our single-moderator workflow (no concurrent writers)."""
    import json
    log = _load_moderator_validations()
    log.append(record)
    with open(MODERATOR_VALIDATIONS_PATH, "w") as fh:
        json.dump(log, fh, indent=2)


def _cohens_kappa(rater_a: list[str], rater_b: list[str]) -> float | None:
    """Cohen's κ between two equal-length label sequences.

    Returns None when N<2 or the categories collapse (κ undefined).
    Implemented inline (not via sklearn) to keep the dependency footprint
    tiny — this is a simple closed-form computation.
    """
    if len(rater_a) != len(rater_b) or len(rater_a) < 2:
        return None
    n = len(rater_a)
    categories = sorted(set(rater_a) | set(rater_b))
    if len(categories) < 2:
        return None
    # observed agreement
    observed = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    # expected agreement under independence
    from collections import Counter
    ca = Counter(rater_a)
    cb = Counter(rater_b)
    expected = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


px.defaults.template = "plotly_white"


def _modality(row) -> str:
    """Mechanistic modality bucket for each trial (kept for external callers)."""
    t = str(row.get("TargetCategory", ""))
    p = str(row.get("ProductType", ""))
    _txt = " ".join([
        str(row.get("BriefTitle", "")),
        str(row.get("BriefSummary", "")),
        str(row.get("Interventions", "")),
    ]).lower()
    has_gd_t = (
        "γδ" in _txt or "gamma delta" in _txt or "gamma-delta" in _txt
        or "-gdt" in _txt or " gdt " in _txt
    )
    has_nk = "car-nk" in _txt or "car nk" in _txt or t.startswith("CAR-NK")
    if has_nk:
        return "CAR-NK"
    if t == "CAAR-T":
        return "CAAR-T"
    if t == "CAR-Treg":
        return "CAR-Treg"
    if has_gd_t or t == "CAR-γδ T":
        return "CAR-γδ T"
    if p == "In vivo":
        return "In vivo CAR"
    if p == "Autologous":
        return "Auto CAR-T"
    if p == "Allogeneic/Off-the-shelf":
        return "Allo CAR-T"
    return "CAR-T (unclear)"


def _add_modality_vectorized(frame: pd.DataFrame) -> pd.DataFrame:
    """Vectorised equivalent of applying _modality row-wise.

    Row-wise `df.apply(_modality, axis=1)` on ~2.5k trials is one of the
    single biggest lag sources on rerun — Streamlit re-executes the script
    on every widget click. Using vectorised pandas string ops + np.select
    collapses this from ~1-2s to ~15ms.
    """
    if frame.empty:
        frame = frame.copy()
        frame["Modality"] = pd.Series(dtype=object)
        return frame

    frame = frame.copy()
    tc = frame.get("TargetCategory", pd.Series(index=frame.index, dtype=object)).astype(str).fillna("")
    pt = frame.get("ProductType",    pd.Series(index=frame.index, dtype=object)).astype(str).fillna("")
    _title = frame.get("BriefTitle",    pd.Series(index=frame.index, dtype=object)).astype(str).fillna("")
    _summ  = frame.get("BriefSummary",  pd.Series(index=frame.index, dtype=object)).astype(str).fillna("")
    _intv  = frame.get("Interventions", pd.Series(index=frame.index, dtype=object)).astype(str).fillna("")
    txt = (_title + " " + _summ + " " + _intv).str.lower()

    has_gd = (
        txt.str.contains("γδ", regex=False, na=False)
        | txt.str.contains("gamma delta", regex=False, na=False)
        | txt.str.contains("gamma-delta", regex=False, na=False)
        | txt.str.contains("-gdt", regex=False, na=False)
        | txt.str.contains(" gdt ", regex=False, na=False)
    )
    has_nk = (
        txt.str.contains("car-nk", regex=False, na=False)
        | txt.str.contains("car nk", regex=False, na=False)
        | tc.str.startswith("CAR-NK")
    )

    conditions = [
        has_nk,
        tc == "CAAR-T",
        tc == "CAR-Treg",
        has_gd | (tc == "CAR-γδ T"),
        pt == "In vivo",
        pt == "Autologous",
        pt == "Allogeneic/Off-the-shelf",
    ]
    choices = [
        "CAR-NK", "CAAR-T", "CAR-Treg", "CAR-γδ T",
        "In vivo CAR", "Auto CAR-T", "Allo CAR-T",
    ]
    frame["Modality"] = np.select(conditions, choices, default="CAR-T (unclear)")
    return frame


# ---------------------------------------------------------------------------
# CSS — NEJM-flat, light canvas
# ---------------------------------------------------------------------------

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }}
    .stApp {{ background: {THEME["bg"]}; color: {THEME["text"]}; }}
    .block-container {{
        max-width: 1320px;
        padding-top: 1.2rem;
        padding-bottom: 2.4rem;
        line-height: 1.55;
    }}
    h1 {{ color: {THEME["text"]}; font-weight: 600; letter-spacing: -0.022em; line-height: 1.2; }}
    h2 {{ color: {THEME["text"]}; font-weight: 600; letter-spacing: -0.018em; line-height: 1.25; }}
    h3 {{ color: {THEME["text"]}; font-weight: 600; letter-spacing: -0.012em; line-height: 1.3; }}

    ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: {THEME["surf3"]}; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: {THEME["faint"]}; }}

    .hero {{
        padding: 1.6rem 0 1.4rem;
        border-top: 3px solid {THEME["primary"]};
        border-bottom: 1px solid {THEME["border"]};
        background: transparent;
        margin-bottom: 1.4rem;
    }}
    .hero-eyebrow {{
        display: flex; align-items: center; gap: 0.5rem;
        font-size: 0.66rem; font-weight: 600;
        letter-spacing: 0.16em; text-transform: uppercase;
        color: {THEME["primary"]};
        margin-bottom: 0.55rem;
    }}
    .hero-eyebrow::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px;
        background: {THEME["primary"]}; flex-shrink: 0;
    }}
    .hero-title {{
        font-size: 1.7rem; font-weight: 600;
        letter-spacing: -0.022em; line-height: 1.2;
        color: {THEME["text"]}; margin-bottom: 0.55rem;
    }}
    .hero-sub {{
        font-size: 0.86rem; line-height: 1.6;
        color: {THEME["muted"]}; max-width: 820px;
        font-weight: 400;
    }}

    .section-card {{
        background: transparent; border: none;
        border-top: 1px solid {THEME["border"]};
        border-radius: 0; padding: 1.0rem 0 0.8rem;
        box-shadow: none; margin-bottom: 0.6rem;
    }}

    .metric-card {{
        background: transparent; border: none;
        border-top: 2px solid {THEME["primary"]};
        border-radius: 0; padding: 0.7rem 0.1rem 0.4rem;
        box-shadow: none;
    }}
    .metric-label {{
        font-size: 0.66rem; font-weight: 600;
        color: {THEME["muted"]}; letter-spacing: 0.12em;
        text-transform: uppercase; margin-bottom: 0.45rem;
    }}
    .metric-value {{
        font-size: 1.65rem; font-weight: 600;
        letter-spacing: -0.02em; color: {THEME["text"]};
        line-height: 1.05; font-variant-numeric: tabular-nums;
    }}
    .metric-foot {{
        margin-top: 0.35rem; font-size: 0.72rem;
        color: {THEME["faint"]}; font-weight: 400; line-height: 1.4;
    }}
    .small-note {{
        color: {THEME["muted"]}; font-size: 0.84rem;
        line-height: 1.6; margin-top: 0.3rem; margin-bottom: 0.55rem;
        letter-spacing: -0.01em;
    }}

    div[data-testid="stSidebar"] {{
        background: {THEME["surf2"]};
        border-right: 1px solid {THEME["border"]};
    }}
    [data-testid="stSidebar"] > div:first-child {{
        border-top: 2px solid {THEME["primary"]};
    }}
    div[data-testid="stSidebar"] h1,
    div[data-testid="stSidebar"] h2,
    div[data-testid="stSidebar"] h3 {{
        font-size: 0.59rem !important; font-weight: 700 !important;
        letter-spacing: 0.14em !important; text-transform: uppercase !important;
        color: {THEME["faint"]} !important;
        margin-top: 1.3rem !important; margin-bottom: 0.1rem !important;
        padding-top: 0.9rem !important; padding-bottom: 0.1rem !important;
        border-top: 1px solid {THEME["border"]} !important;
        border-bottom: none !important;
    }}
    div[data-testid="stSidebar"] label {{
        font-size: 0.73rem !important; font-weight: 500 !important;
        color: {THEME["muted"]} !important; letter-spacing: -0.01em !important;
    }}
    div[data-testid="stSidebar"] p {{ color: {THEME["text"]}; font-size: 0.75rem; }}
    div[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
        background: {THEME["surface"]} !important;
        border: 1px solid {THEME["border"]} !important;
        border-radius: 2px !important;
        min-height: 28px !important; font-size: 0.75rem !important;
    }}
    div[data-testid="stSidebar"] div[data-baseweb="select"] > div:focus-within {{
        border-color: {THEME["primary"]} !important;
        box-shadow: none !important;
    }}
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label {{
        border-radius: 0 !important; padding: 0.28rem 0.45rem !important;
        transition: background 0.1s !important; margin-bottom: 0.06rem !important;
    }}
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {{
        background: {THEME["surface"]} !important;
    }}

    .stButton > button, .stDownloadButton > button {{
        background: {THEME["surface"]}; color: {THEME["text"]};
        border: 1px solid {THEME["border"]}; border-radius: 2px;
        padding: 0.42rem 0.95rem; font-size: 0.82rem; font-weight: 500;
        letter-spacing: -0.005em; box-shadow: none;
        transition: background 0.12s, border-color 0.12s;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover {{
        background: {THEME["surf2"]}; border-color: {THEME["primary"]};
        box-shadow: none; color: {THEME["primary"]};
    }}

    div[data-testid="stTabs"] [data-baseweb="tab-list"] {{
        background: transparent; border: none;
        border-bottom: 1px solid {THEME["border"]};
        border-radius: 0; padding: 0; gap: 0;
    }}
    div[data-testid="stTabs"] [data-baseweb="tab"] {{
        border-radius: 0; padding: 10px 18px;
        font-size: 0.84rem; font-weight: 500;
        letter-spacing: -0.005em; color: {THEME["muted"]};
        background: transparent; border: none !important;
        border-bottom: 2px solid transparent !important;
        margin-bottom: -1px; transition: color 0.12s, border-color 0.12s;
    }}
    div[data-testid="stTabs"] [data-baseweb="tab"]:hover {{
        background: transparent; color: {THEME["text"]};
    }}
    div[data-testid="stTabs"] button[aria-selected="true"] {{
        background: transparent !important;
        color: {THEME["primary"]} !important; font-weight: 600 !important;
        border-bottom: 2px solid {THEME["primary"]} !important;
        box-shadow: none;
    }}
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
    div[data-testid="stTabs"] [data-baseweb="tab-border"] {{
        display: none !important;
    }}

    div[data-testid="stDataFrame"] {{
        border: 1px solid {THEME["border"]}; border-radius: 2px;
        overflow: hidden; background: {THEME["surface"]};
    }}
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {{
        background-color: {THEME["surface"]};
        border-color: {THEME["border"]} !important;
        color: {THEME["text"]}; border-radius: 2px;
    }}
    .stTextInput input, .stNumberInput input {{
        background: {THEME["surface"]};
        border-color: {THEME["border"]}; border-radius: 2px;
        color: {THEME["text"]};
    }}
    div[data-testid="stExpander"] {{
        background: transparent; border: none;
        border-top: 1px solid {THEME["border"]};
        border-radius: 0; box-shadow: none;
    }}
    div[data-baseweb="tag"] {{
        background-color: {THEME["surf2"]} !important;
        border: 1px solid {THEME["border"]} !important;
        border-radius: 2px !important;
    }}
    div[data-baseweb="tag"] span {{ color: {THEME["text"]} !important; font-weight: 500; }}
    div[data-baseweb="tag"] [role="button"] {{ color: {THEME["muted"]} !important; opacity: 0.8; }}

    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li,
    div[data-testid="stMarkdownContainer"] span {{ color: {THEME["text"]}; }}
    div[data-testid="stCaptionContainer"] p, .stCaption {{ color: {THEME["muted"]} !important; }}
    div[data-testid="stAlert"] p {{ color: {THEME["text"]}; }}

    div[data-testid="stSidebarContent"] {{ background-color: {THEME["surface"]} !important; }}

    div[data-testid="stVerticalBlock"],
    div[data-testid="stHorizontalBlock"],
    div[data-testid="stColumn"] > div,
    div[data-testid="block-container"] > div,
    div[data-testid="element-container"] {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }}

    div[data-testid="stMetric"] {{
        background: transparent !important; border: none !important;
        box-shadow: none !important; padding: 0.4rem 0 !important;
        border-radius: 0 !important;
    }}
    div[data-testid="stMetricValue"] > div {{
        color: {THEME["text"]} !important;
        font-size: 1.4rem !important; font-weight: 600 !important;
        letter-spacing: -0.02em !important;
        font-variant-numeric: tabular-nums;
    }}
    div[data-testid="stMetricLabel"] > div {{
        color: {THEME["muted"]} !important;
        font-size: 0.7rem !important; font-weight: 600 !important;
        letter-spacing: 0.10em !important; text-transform: uppercase !important;
    }}

    div[data-testid="stAlert"] {{
        background: rgba(11,61,145,0.04) !important;
        border: 1px solid rgba(11,61,145,0.14) !important;
        border-left: 3px solid {THEME["primary"]} !important;
        border-radius: 8px !important;
        box-shadow: none !important;
    }}
    div[data-testid="stAlert"] p {{ color: {THEME["text"]} !important; }}

    div[data-testid="stVerticalBlock"] h3 {{
        margin-top: 0.5rem !important;
        padding-top: 1.1rem !important;
        padding-bottom: 0.55rem !important;
        border-top: 1px solid {THEME["border"]} !important;
        letter-spacing: -0.03em !important;
    }}

    .pub-fig-header {{
        margin-top: 1.6rem; padding-top: 1.1rem;
        padding-bottom: 0.55rem;
        border-top: 1px solid {THEME["border"]};
    }}
    .pub-fig-eyebrow {{
        font-size: 0.66rem; font-weight: 700;
        letter-spacing: 0.16em; text-transform: uppercase;
        color: {THEME["primary"]}; margin-bottom: 0.35rem;
    }}
    .pub-fig-title {{
        font-size: 1.05rem; font-weight: 600;
        letter-spacing: -0.012em; line-height: 1.3;
        color: {THEME["text"]}; margin-bottom: 0.2rem;
    }}
    .pub-fig-sub {{
        font-size: 0.78rem; font-weight: 400; line-height: 1.5;
        color: {THEME["muted"]}; margin-top: 0.15rem;
    }}
    .pub-fig-caption {{
        font-size: 0.72rem; font-style: italic;
        color: {THEME["faint"]};
        margin: 0.4rem 0 0.8rem 0; line-height: 1.45;
    }}
    .pub-fig-header + div h3,
    .pub-fig-header ~ div[data-testid="stVerticalBlock"] h3 {{
        border-top: none !important; padding-top: 0 !important;
    }}

    .metric-card {{ background: {THEME["surface"]} !important; }}
    div[data-testid="stDataFrame"],
    div[data-testid="stDataFrame"] > div {{
        background-color: {THEME["surface"]} !important;
    }}
    div[data-testid="stExpander"] {{
        background-color: {THEME["surface"]} !important;
        border: 1px solid {THEME["border"]} !important;
        border-radius: 8px !important;
        box-shadow: none !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_live(max_records: int = 5000, statuses: tuple[str, ...] = ()) -> tuple:
    """Fetch from CT.gov; cache for 24 hours.

    With a 24h TTL the first user of the day pays the cold-start cost
    (~30–60s for ~2.5k trials) and everyone else in the same day gets an
    instant warm cache. This makes live-mode the natural default and
    removes the need for users to trigger a 'refresh' step.
    """
    statuses_list = list(statuses) if statuses else None
    return build_all_from_api(max_records=max_records, statuses=statuses_list)


@st.cache_data
def load_frozen(snapshot_date: str) -> tuple:
    return load_snapshot(snapshot_date)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def metric_card(label: str, value, foot: str = ""):
    """Deprecated — forwards to st.metric() per the Rheum × Onc style guide.
    All in-app call-sites have been migrated; kept as a compat shim in case
    external code / snapshots reference it."""
    st.metric(label, value, help=foot or None)


def make_bar(df_plot, x, y, height=360, color=HEME_COLOR):
    fig = px.bar(
        df_plot, x=x, y=y, height=height,
        color_discrete_sequence=[color], template="plotly_white",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=8),
        font=dict(family="Inter, sans-serif", size=12, color=THEME["text"]),
        xaxis_title=None, yaxis_title=None, showlegend=False, bargap=0.35,
    )
    fig.update_traces(marker_line_width=0, opacity=0.90)
    fig.update_xaxes(showgrid=False, color=THEME["muted"], tickfont_size=11)
    fig.update_yaxes(
        gridcolor=THEME["grid"], gridwidth=1,
        color=THEME["muted"], tickfont_size=11, zeroline=False,
    )
    fig.update_layout(bargap=0.4)
    return fig


def uniq_join(series):
    vals = []
    for v in series.dropna():
        v = str(v).strip()
        if v and v not in vals:
            vals.append(v)
    return " | ".join(vals)


def split_pipe_values(series: pd.Series) -> list[str]:
    values = []
    for item in series.dropna():
        for part in str(item).split("|"):
            part = part.strip()
            if part:
                values.append(part)
    return values


def normalize_phase_value(x):
    if pd.isna(x):
        return "Unknown"
    s = str(x).strip()
    if not s:
        return "Unknown"
    s_upper = s.upper().replace(" ", "").replace("/", "|")
    mapping = {
        "EARLYPHASE1": "EARLY_PHASE1", "EARLYPHASEI": "EARLY_PHASE1",
        "PHASE1": "PHASE1", "PHASEI": "PHASE1",
        "PHASE1|PHASE2": "PHASE1|PHASE2", "PHASEI|PHASEII": "PHASE1|PHASE2",
        "PHASE12": "PHASE1|PHASE2", "PHASE1PHASE2": "PHASE1|PHASE2",
        "PHASE2": "PHASE2", "PHASEII": "PHASE2",
        "PHASE2|PHASE3": "PHASE2|PHASE3", "PHASEII|PHASEIII": "PHASE2|PHASE3",
        "PHASE23": "PHASE2|PHASE3", "PHASE2PHASE3": "PHASE2|PHASE3",
        "PHASE3": "PHASE3", "PHASEIII": "PHASE3",
        "PHASE4": "PHASE4", "PHASEIV": "PHASE4",
        "N/A": "Unknown", "NA": "Unknown",
    }
    return mapping.get(s_upper, s_upper if s_upper in PHASE_ORDER else "Unknown")


def add_phase_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["Phase"] = out["Phase"].fillna("Unknown")
    out["PhaseNormalized"] = out["Phase"].apply(normalize_phase_value)
    out["PhaseOrdered"] = pd.Categorical(out["PhaseNormalized"], categories=PHASE_ORDER, ordered=True)
    out["PhaseLabel"] = out["PhaseNormalized"].map(PHASE_LABELS).fillna(out["Phase"])
    return out


def _first_meaningful_year(counts_df: pd.DataFrame, year_col: str = "StartYear",
                            count_col: str = "Count", threshold: int = 5) -> int | None:
    """Earliest year where the total count (summed across stacked groups)
    reaches `threshold`. Used to trim near-empty leading years from temporal
    charts — underlying data is unchanged; only the visible x-axis range is
    tightened so 2-trial-years don't render as visually empty against the
    100+-trial peak years."""
    if counts_df is None or counts_df.empty:
        return None
    totals = counts_df.groupby(year_col)[count_col].sum().sort_index()
    meaningful = totals[totals >= threshold]
    if meaningful.empty:
        return int(totals.index.min())
    return int(meaningful.index.min())


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <div class="hero-eyebrow">ClinicalTrials.gov &middot; Live pipeline</div>
        <div class="hero-title">CAR-T &amp; Cell Therapies<br>in Oncology — Heme and Solid Tumors</div>
        <div class="hero-sub">
            Systematic landscape analysis of CAR-T, CAR-NK, CAAR-T, and CAR-γδ T trials
            across hematologic and solid tumors — with disease, target-antigen, and
            cell-therapy modality classification; global site-level geography; and
            publication-ready figures.
            <span style="display:block; margin-top:0.5rem; opacity:0.85;">
                Use the <b>sidebar filters</b> to narrow to a subgroup of interest — every
                chart, table, map, and CSV export on every tab respects the active filter
                state.
            </span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar — data source
# ---------------------------------------------------------------------------
#
# Live-first architecture:
#   - Default: live CT.gov pull cached 24h. First visitor of the day pays the
#     cold-start cost; everyone else gets an instant warm cache. No manual
#     refresh step.
#   - Opt-in: pin a specific dated snapshot for publication reproducibility
#     (e.g., "pin to the dataset cited in the paper"). Hidden behind an
#     "Advanced" expander so casual viewers never see the mode toggle.
#   - Safety net: if CT.gov is unreachable, fall back to the most recent
#     frozen snapshot automatically.
#
# Previous architecture defaulted to frozen-by-default + manual Save snapshot,
# which forced every schema change to require a re-freeze and manual backfill.

st.sidebar.header("Data source")

available_snapshots = list_snapshots()
prisma_counts: dict = {}

# Detect an explicit user opt-in to pin a frozen snapshot. Stored in
# session_state so the Refresh button can clear it.
_pin_key = "pinned_snapshot"
_pinned = st.session_state.get(_pin_key)
if _pinned and _pinned not in available_snapshots:
    _pinned = None
    st.session_state[_pin_key] = None

if _pinned:
    with st.spinner(f"Loading pinned snapshot {_pinned}..."):
        df, df_sites, prisma_counts = load_frozen(_pinned)
    st.sidebar.success(
        f"Pinned to frozen snapshot **{_pinned}** ({len(df):,} trials)."
    )
    if st.sidebar.button("Unpin — switch back to live data"):
        st.session_state[_pin_key] = None
        st.cache_data.clear()
        st.rerun()
else:
    selected_statuses: list[str] = []
    try:
        with st.spinner("Fetching live ClinicalTrials.gov data (cached 24h)..."):
            df, df_sites, prisma_counts = load_live(statuses=tuple(selected_statuses))
        st.sidebar.caption(
            f"Live from CT.gov · {len(df):,} trials · cached 24h"
        )
        if st.sidebar.button("Refresh now"):
            st.cache_data.clear()
            st.rerun()
    except Exception as api_err:
        st.sidebar.error(
            "ClinicalTrials.gov API is currently unreachable. "
            "Falling back to the most recent snapshot if available."
        )
        st.sidebar.caption(f"Error: {type(api_err).__name__}: {str(api_err)[:120]}")
        if available_snapshots:
            fallback = available_snapshots[0]
            with st.spinner(f"Loading snapshot {fallback}..."):
                df, df_sites, prisma_counts = load_frozen(fallback)
            st.sidebar.info(
                f"Loaded frozen snapshot **{fallback}** (offline fallback)."
            )
        else:
            st.error(
                "Cannot load data: the ClinicalTrials.gov API is unreachable and no local "
                "snapshots exist. Please try again later or check the API status at "
                "https://clinicaltrials.gov/."
            )
            st.stop()

    # Reproducibility escape hatch — hidden by default so casual users never see it.
    with st.sidebar.expander("Reproducibility — pin a frozen dataset", expanded=False):
        if not available_snapshots:
            st.caption(
                "No frozen snapshots available. Click **Save current as snapshot** "
                "below to create one from the live data for citation."
            )
        else:
            _pin_choice = st.selectbox(
                "Pin a dated snapshot (for citing in a paper)",
                options=["— live data —"] + available_snapshots,
                index=0,
                key="pin_snapshot_select",
            )
            if _pin_choice != "— live data —":
                if st.button(f"Pin snapshot {_pin_choice}"):
                    st.session_state[_pin_key] = _pin_choice
                    st.rerun()
        if st.button("Save current as snapshot"):
            statuses_list = selected_statuses if selected_statuses else None
            snap_date = save_snapshot(df, df_sites, prisma_counts, statuses=statuses_list)
            st.success(f"Saved snapshot: {snap_date}")
            st.cache_data.clear()

# Post-processing that was previously applied on every rerun (including every
# filter click) — add_phase_columns + row-wise _modality apply on ~2.5k trials.
# Cached here so it runs once per live-data pull, cutting widget-click latency
# from ~1-2s to effectively free.
@st.cache_data(show_spinner=False)
def _post_process_trials(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df
    out = add_phase_columns(raw_df)
    out = _add_modality_vectorized(out)
    # Bake NCTLink here instead of via per-rerun df_filt.apply(lambda) —
    # it's purely a function of NCTId so it never needs to be recomputed
    # on filter changes.
    _nct = out["NCTId"].astype("string")
    out["NCTLink"] = np.where(
        _nct.notna(),
        "https://clinicaltrials.gov/study/" + _nct.fillna(""),
        None,
    )
    return out


df = _post_process_trials(df)

if df.empty:
    st.error("No studies were returned. Try broadening the status filters.")
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar — cascading disease filter + other filters
# ---------------------------------------------------------------------------

st.sidebar.header("Filters")

# Reset button — clears every filter widget's state so defaults (all options
# selected) re-apply on the next rerun. Explicit keys on each multiselect below
# let us target them selectively without affecting the data-source radio.
_FILTER_KEYS = [
    "filter_branch", "filter_category", "filter_entity",
    "filter_design", "filter_phase", "filter_target",
    "filter_status", "filter_product", "filter_modality",
    "filter_country", "filter_agegroup", "filter_sponsortype",
    "filter_confidence",
]
if st.sidebar.button("↺ Reset all filters", use_container_width=True):
    for _k in _FILTER_KEYS:
        if _k in st.session_state:
            del st.session_state[_k]
    st.rerun()

st.sidebar.caption("Disease filter cascades: Branch → Category → Entity.")

branch_options_all = sorted(df["Branch"].dropna().unique().tolist())
branch_sel = st.sidebar.multiselect(
    "Branch",
    options=branch_options_all,
    default=branch_options_all,
    help="Heme-onc, Solid-onc, Mixed, Unknown.",
    key="filter_branch",
)

df_after_branch = df[df["Branch"].isin(branch_sel)] if branch_sel else df

category_options_all = sorted(df_after_branch["DiseaseCategory"].dropna().unique().tolist())
category_sel = st.sidebar.multiselect(
    "Disease category",
    options=category_options_all,
    default=category_options_all,
    help="Options narrow based on the selected branch(es).",
    key="filter_category",
)

df_after_cat = (
    df_after_branch[df_after_branch["DiseaseCategory"].isin(category_sel)]
    if category_sel else df_after_branch
)

_entities: set[str] = set()
for val in df_after_cat["DiseaseEntities"].dropna():
    for e in str(val).split("|"):
        e = e.strip()
        if e:
            _entities.add(e)
for val in df_after_cat["DiseaseEntity"].dropna():
    _entities.add(str(val))
entity_options_all = sorted(_entities)
entity_sel = st.sidebar.multiselect(
    "Disease entity",
    options=entity_options_all,
    default=entity_options_all,
    help="Basket/multi-disease trials appear under every entity they enroll.",
    key="filter_entity",
)

# Trial design
design_options = sorted(df["TrialDesign"].dropna().unique().tolist())
design_sel = st.sidebar.multiselect(
    "Trial design", options=design_options, default=design_options,
    help="Single-disease vs basket/multi-disease trials.",
    key="filter_design",
)

# Phase
phase_options = [PHASE_LABELS[p] for p in PHASE_ORDER if p in set(df["PhaseNormalized"].astype(str))]
phase_sel = st.sidebar.multiselect("Phase", options=phase_options, default=phase_options, key="filter_phase")

# Target category (exclude platform labels — those live in modality filter)
target_options = sorted(
    t for t in df["TargetCategory"].dropna().unique() if t not in _PLATFORM_LABELS
)
target_sel = st.sidebar.multiselect(
    "Antigen target", options=target_options, default=target_options, key="filter_target",
)

# Status
status_options = sorted(df["OverallStatus"].dropna().unique().tolist())
status_sel = st.sidebar.multiselect(
    "Overall status", options=status_options, default=status_options, key="filter_status",
)

# Product type
product_options = sorted(df["ProductType"].dropna().unique().tolist())
product_sel = st.sidebar.multiselect(
    "Product type", options=product_options, default=product_options, key="filter_product",
)

# Modality
modality_options = [m for m in MODALITY_ORDER if m in set(df["Modality"])]
modality_sel = st.sidebar.multiselect(
    "Cell therapy modality", options=modality_options, default=modality_options,
    key="filter_modality",
)

# Country
all_countries: set[str] = set()
for cs in df["Countries"].dropna():
    for c in str(cs).split("|"):
        c = c.strip()
        if c:
            all_countries.add(c)
country_options = sorted(all_countries)
country_sel = st.sidebar.multiselect(
    "Country", options=country_options, default=country_options, key="filter_country",
)

# Age group (Pediatric / Adult / Both / Unknown)
age_options = sorted(df["AgeGroup"].dropna().unique().tolist()) if "AgeGroup" in df.columns else []
age_sel = st.sidebar.multiselect(
    "Age group", options=age_options, default=age_options, key="filter_agegroup",
    help="Derived from the trial's StdAges / MinAge / MaxAge fields.",
)

# Sponsor type (Academic / Industry / Government / Unknown)
sponsor_options = sorted(df["SponsorType"].dropna().unique().tolist()) if "SponsorType" in df.columns else []
sponsor_sel = st.sidebar.multiselect(
    "Sponsor type", options=sponsor_options, default=sponsor_options, key="filter_sponsortype",
    help="From CT.gov LeadSponsor.class; name-token fallback for uncategorised sponsors.",
)

# Classification confidence (high / medium / low)
conf_options = ["high", "medium", "low"]
conf_present = [c for c in conf_options if c in set(df["ClassificationConfidence"].dropna())]
conf_sel = st.sidebar.multiselect(
    "Classification confidence", options=conf_present, default=conf_present, key="filter_confidence",
    help="Filter to high-confidence rows for strict analyses (see Methods §Classification Confidence).",
)


# ---------------------------------------------------------------------------
# CSV provenance helper
# ---------------------------------------------------------------------------

def _csv_with_provenance(
    df_export: pd.DataFrame, title: str, include_filters: bool = True,
) -> str:
    snap = (
        df["SnapshotDate"].iloc[0]
        if "SnapshotDate" in df.columns and not df.empty
        else date.today().isoformat()
    )
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        f"# {title}",
        f"# Exported (UTC): {now_utc}",
    ]
    # Provenance tag: pinned snapshot if user explicitly selected one, else live.
    _pinned_for_export = st.session_state.get("pinned_snapshot")
    if _pinned_for_export:
        lines.append(
            f"# Data source: ClinicalTrials.gov API v2 — pinned frozen snapshot {_pinned_for_export}"
        )
    else:
        lines.append(
            f"# Data source: ClinicalTrials.gov API v2 — live fetch (cached 24h, pulled on {snap})"
        )
    lines.append(f"# Source URL: {BASE_URL}")
    # Classifier git SHA — lets a reviewer downloading this CSV pin the
    # exact pipeline version that produced the labels. Without this,
    # downloading the same snapshot through two different code revisions
    # could produce different classifications and the CSV is
    # indistinguishable.
    lines.append(f"# Classifier code: ptjeong/ONC-CAR-T-Trials-Monitor @ {CLASSIFIER_GIT_SHA}")

    if include_filters:
        def _fmt(sel, opts) -> str:
            if not sel or set(sel) == set(opts):
                return "all"
            return "; ".join(str(s) for s in sel)
        lines += [
            f"# Filter — branch: {_fmt(branch_sel, branch_options_all)}",
            f"# Filter — disease category: {_fmt(category_sel, category_options_all)}",
            f"# Filter — disease entity: {_fmt(entity_sel, entity_options_all)}",
            f"# Filter — trial design: {_fmt(design_sel, design_options)}",
            f"# Filter — phase: {_fmt(phase_sel, phase_options)}",
            f"# Filter — antigen target: {_fmt(target_sel, target_options)}",
            f"# Filter — overall status: {_fmt(status_sel, status_options)}",
            f"# Filter — product type: {_fmt(product_sel, product_options)}",
            f"# Filter — cell therapy modality: {_fmt(modality_sel, modality_options)}",
            f"# Filter — country: {_fmt(country_sel, country_options)}",
        ]
    lines += [
        f"# Rows: {len(df_export)}",
        "# Read with: pd.read_csv(path, comment='#')",
        "",
    ]
    return "\n".join(lines) + df_export.to_csv(index=False)


# Data-quality expander
with st.sidebar.expander("Data quality / missing classifications", expanded=False):
    cols_to_check = ["Branch", "DiseaseCategory", "DiseaseEntity", "Phase", "TargetCategory", "OverallStatus", "Countries"]
    rows = []
    ambiguous_disease = [t.lower() for t in AMBIGUOUS_ENTITY_TOKENS] + [
        "basket/multidisease", "advanced solid tumors", "heme basket",
    ]
    ambiguous_target = [t.lower() for t in AMBIGUOUS_TARGET_TOKENS]
    for col in cols_to_check:
        s = df[col].astype("string")
        missing = int(df[col].isna().sum() + (s.str.strip() == "").sum())
        if col in {"Branch", "DiseaseCategory", "DiseaseEntity"}:
            ambiguous = int(s.str.lower().fillna("").isin(ambiguous_disease).sum())
        elif col == "TargetCategory":
            ambiguous = int(s.str.lower().fillna("").isin(ambiguous_target).sum())
        else:
            ambiguous = 0
        rows.append({"Column": col, "Missing / empty": missing, "Ambiguous labels": ambiguous})
    quality_df = pd.DataFrame(rows)
    st.dataframe(quality_df, width='stretch', hide_index=True)

    # ClassificationConfidence band summary.
    if "ClassificationConfidence" in df.columns:
        conf_counts = df["ClassificationConfidence"].value_counts()
        n_high = int(conf_counts.get("high", 0))
        n_med = int(conf_counts.get("medium", 0))
        n_low = int(conf_counts.get("low", 0))
        total = max(1, len(df))
        st.caption(
            f"**Classification confidence** (see Methods): "
            f"high = {n_high} ({100*n_high/total:.0f}%) · "
            f"medium = {n_med} ({100*n_med/total:.0f}%) · "
            f"low = {n_low} ({100*n_low/total:.0f}%)."
        )

    n_llm = int(df["LLMOverride"].sum()) if "LLMOverride" in df.columns else 0
    if n_llm:
        st.caption(
            f"LLM-assisted: **{n_llm}** trial(s) reclassified via `llm_overrides.json` "
            "(two-round Claude Opus validation; see Methods § LLM-Assisted Curation Loop). "
            "Run `python validate.py` to expand coverage."
        )
    else:
        st.caption(
            "No LLM overrides active. Run `python validate.py` to classify ambiguous trials "
            "and write `llm_overrides.json`."
        )


# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------

mask = pd.Series(True, index=df.index)

if branch_sel:
    mask &= df["Branch"].isin(branch_sel)
if category_sel:
    mask &= df["DiseaseCategory"].isin(category_sel)
if entity_sel:
    entity_set = set(entity_sel)
    primary_match = df["DiseaseEntity"].isin(entity_set)
    list_match = df["DiseaseEntities"].fillna("").apply(
        lambda s: any(e.strip() in entity_set for e in str(s).split("|") if e.strip())
    )
    mask &= (primary_match | list_match)
if design_sel:
    mask &= df["TrialDesign"].isin(design_sel)
if phase_sel:
    selected_phase_norm = [k for k, v in PHASE_LABELS.items() if v in phase_sel]
    mask &= df["PhaseNormalized"].isin(selected_phase_norm)
if target_sel:
    mask &= df["TargetCategory"].isin(target_sel) | df["TargetCategory"].isin(_PLATFORM_LABELS)
if status_sel:
    mask &= df["OverallStatus"].isin(status_sel)
if product_sel:
    mask &= df["ProductType"].isin(product_sel)
if modality_sel:
    mask &= df["Modality"].isin(modality_sel)
if country_sel:
    country_pattern = "|".join([re.escape(c) for c in country_sel])
    mask &= df["Countries"].fillna("").str.contains(country_pattern, case=False, na=False, regex=True)
if age_sel:
    mask &= df["AgeGroup"].isin(age_sel)
if sponsor_sel:
    mask &= df["SponsorType"].isin(sponsor_sel)
if conf_sel:
    mask &= df["ClassificationConfidence"].isin(conf_sel)

_df_filt = df[mask].copy()
df_filt = add_phase_columns(_df_filt)
df_filt["OverallStatus"] = df_filt["OverallStatus"].fillna("Unknown")
# NCTLink is now baked into `df` by _post_process_trials, so df_filt
# inherits the column via the row-subset — no per-rerun .apply() needed.


# ---------------------------------------------------------------------------
# Germany deep-dive
# ---------------------------------------------------------------------------

germany_sites_all = pd.DataFrame()
germany_open_sites = pd.DataFrame()
germany_study_view = pd.DataFrame()


def _build_germany_subset(sites: pd.DataFrame, nct_ids: pd.Series) -> tuple:
    """Build Germany-specific site + trial subsets. Cached in session_state
    keyed by the NCT filter signature so it doesn't rebuild on unrelated
    widget clicks (pill toggles, chart-mode changes, etc.)."""
    if sites.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    key = tuple(sorted(nct_ids.tolist()))
    cached_key = st.session_state.get("_germany_key")
    if cached_key == key:
        return (
            st.session_state.get("_germany_sites_all", pd.DataFrame()),
            st.session_state.get("_germany_open_sites", pd.DataFrame()),
            st.session_state.get("_germany_study_view", pd.DataFrame()),
        )
    g_all = sites[sites["Country"].fillna("").str.lower() == "germany"].copy()
    g_open = g_all[
        g_all["SiteStatus"].fillna("").str.upper().isin(OPEN_SITE_STATUSES)
    ]
    g_open = g_open[g_open["NCTId"].isin(nct_ids)].copy()
    g_view = pd.DataFrame()
    if not g_open.empty:
        g_trials = df_filt[df_filt["NCTId"].isin(g_open["NCTId"])].copy()
        g_view = (
            g_open.groupby("NCTId", as_index=False)
            .agg(GermanCities=("City", uniq_join),
                 GermanSiteStatuses=("SiteStatus", uniq_join))
        )
        g_view = g_view.merge(
            g_trials[[
                "NCTId", "NCTLink", "BriefTitle",
                "Branch", "DiseaseCategory", "DiseaseEntity",
                "TargetCategory", "ProductType",
                "Phase", "PhaseNormalized", "PhaseOrdered", "PhaseLabel",
                "OverallStatus", "LeadSponsor",
            ]].drop_duplicates(subset=["NCTId"]),
            on="NCTId", how="left",
        )
        g_view["Phase"] = g_view["PhaseLabel"].fillna(g_view["Phase"])
        g_view = g_view[[
            "NCTId", "NCTLink", "BriefTitle",
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType",
            "Phase", "PhaseNormalized", "PhaseOrdered",
            "OverallStatus", "LeadSponsor",
            "GermanCities", "GermanSiteStatuses",
        ]].sort_values(
            ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"],
            na_position="last",
        )
    st.session_state["_germany_key"] = key
    st.session_state["_germany_sites_all"] = g_all
    st.session_state["_germany_open_sites"] = g_open
    st.session_state["_germany_study_view"] = g_view
    return g_all, g_open, g_view


germany_sites_all, germany_open_sites, germany_study_view = _build_germany_subset(
    df_sites, df_filt["NCTId"]
)


# ---------------------------------------------------------------------------
# Sites-by-city helpers (country-selectable)
# ---------------------------------------------------------------------------
# Open / recruiting sites across ALL countries, restricted to trials visible
# under the current filter. Both "Sites by city" (Geography tab) and
# "Studies active in …" (Data tab) pick one country via a selectbox from
# this shared pool.

def _build_all_open_sites(sites: pd.DataFrame, nct_ids: pd.Series) -> pd.DataFrame:
    """Open-site slice of df_sites restricted to trials in the current filter.
    Cached in session_state keyed by NCT filter set so it doesn't rebuild on
    unrelated widget interactions (pill toggles, chart-mode changes, etc.)."""
    if sites.empty:
        return pd.DataFrame()
    key = tuple(sorted(nct_ids.tolist()))
    if st.session_state.get("_all_open_sites_key") == key:
        return st.session_state.get("_all_open_sites_df", pd.DataFrame())
    _os = sites[
        sites["SiteStatus"].fillna("").str.upper().isin(OPEN_SITE_STATUSES)
    ]
    _os = _os[_os["NCTId"].isin(nct_ids)].copy()
    _os["Country"] = _os["Country"].fillna("Unknown").astype(str).str.strip()
    _os = _os[_os["Country"] != ""]
    st.session_state["_all_open_sites_key"] = key
    st.session_state["_all_open_sites_df"] = _os
    return _os


all_open_sites = _build_all_open_sites(df_sites, df_filt["NCTId"])


def _get_geo_sites_cached(open_sites: pd.DataFrame, filt: pd.DataFrame) -> pd.DataFrame:
    """Precomputed site-level view for the global map (dropna + merge Branch +
    drop_duplicates by trial×facility×city). Cached via st.session_state so
    widget clicks that don't change the NCT filter don't force a rebuild —
    the merge + drop_duplicates on ~10k sites was the dominant lag source
    on the Geography tab.
    """
    if (
        open_sites.empty
        or "Latitude" not in open_sites.columns
        or open_sites["Latitude"].isna().all()
    ):
        return pd.DataFrame()
    key = (tuple(sorted(filt["NCTId"].tolist())), len(open_sites))
    if st.session_state.get("_geo_sites_key") == key:
        return st.session_state.get("_geo_sites_df", pd.DataFrame())
    geo = open_sites.dropna(subset=["Latitude", "Longitude"]).copy()
    geo = geo.merge(
        filt[["NCTId", "Branch", "BriefTitle"]].drop_duplicates("NCTId"),
        on="NCTId", how="left",
    )
    geo["Branch"] = geo["Branch"].fillna("Unknown")
    geo = geo.drop_duplicates(["NCTId", "Facility", "City"]).reset_index(drop=True)
    st.session_state["_geo_sites_key"] = key
    st.session_state["_geo_sites_df"] = geo
    return geo


def _country_study_view(country: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (open site rows for this country, per-trial study view)."""
    if all_open_sites.empty or not country:
        return pd.DataFrame(), pd.DataFrame()
    c_sites = all_open_sites[
        all_open_sites["Country"].str.lower() == country.lower()
    ].copy()
    if c_sites.empty:
        return c_sites, pd.DataFrame()
    c_trials = df_filt[df_filt["NCTId"].isin(c_sites["NCTId"])].copy()
    sv = (
        c_sites.groupby("NCTId", as_index=False)
        .agg(Cities=("City", uniq_join), SiteStatuses=("SiteStatus", uniq_join))
    )
    merge_cols = [c for c in [
        "NCTId", "BriefTitle",
        "Branch", "DiseaseCategory", "DiseaseEntity",
        "TargetCategory", "ProductType", "ProductName",
        "AgeGroup", "SponsorType",
        "Phase", "PhaseNormalized", "PhaseOrdered", "PhaseLabel",
        "OverallStatus", "LeadSponsor",
    ] if c in c_trials.columns]
    sv = sv.merge(
        c_trials[merge_cols].drop_duplicates(subset=["NCTId"]),
        on="NCTId", how="left",
    )
    sv["NCTLink"] = sv["NCTId"].apply(
        lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
    )
    if "PhaseLabel" in sv.columns:
        sv["Phase"] = sv["PhaseLabel"].fillna(sv.get("Phase"))
    sort_cols = [c for c in ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"] if c in sv.columns]
    if sort_cols:
        sv = sv.sort_values(sort_cols, na_position="last")
    return c_sites, sv


def _countries_by_activity() -> list[str]:
    """Countries with at least one open / recruiting site, ranked by unique trials."""
    if all_open_sites.empty:
        return []
    order = (
        all_open_sites.groupby("Country")["NCTId"].nunique()
        .sort_values(ascending=False)
    )
    return order.index.tolist()


# ---------------------------------------------------------------------------
# Metric row
# ---------------------------------------------------------------------------

total_trials = len(df_filt)
recruiting_trials = int(df_filt["OverallStatus"].isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())
german_trials_count = germany_study_view["NCTId"].nunique() if not germany_study_view.empty else 0
heme_count = int((df_filt["Branch"] == "Heme-onc").sum())
solid_count = int((df_filt["Branch"] == "Solid-onc").sum())
_tc_for_top = df_filt.loc[~df_filt["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"].dropna()
top_target = _tc_for_top.value_counts().idxmax() if not _tc_for_top.empty else "—"
_enroll_known = pd.to_numeric(df_filt["EnrollmentCount"], errors="coerce").dropna()
total_enrolled = int(_enroll_known.sum()) if not _enroll_known.empty else 0
median_enrolled = int(_enroll_known.median()) if not _enroll_known.empty else 0

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Filtered trials", f"{total_trials:,}", help="Trials matching current filters")
with m2:
    st.metric("Open / recruiting", f"{recruiting_trials:,}", help="Recruiting or not yet recruiting")
with m3:
    st.metric("Heme · Solid", f"{heme_count} · {solid_count}", help="Heme-onc / Solid-onc split")
with m4:
    st.metric("Median enrollment", f"{median_enrolled:,}",
              help=f"{total_enrolled:,} patients across {len(_enroll_known)} trials")
with m5:
    st.metric("Top antigen target", top_target, help="Most common non-platform target")

st.markdown(
    f"""
    <div class="small-note">
        {len(df)} total trials after processing. Current view shows {len(df_filt)} filtered trials.
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

# Moderator gate — the Moderation tab only appears when the visitor passes
# `?mod=<token>` matching the MODERATOR_TOKEN env var (or
# st.secrets["moderator_token"]). The tab triages community
# classification-flag issues and runs a random-validation loop that
# extends the moderator-validated ground-truth pool. Public visitors
# never see the tab — there's no UI hint that it exists, and the
# token check is server-side so query-string brute force buys nothing
# unless the token leaks.
def _moderator_mode_active() -> bool:
    """True when the current session is moderator-authorized.

    Two-step gate:
      1. Server has MODERATOR_TOKEN env var (or st.secrets["moderator_token"])
      2. URL has ?mod=<token> matching exactly

    Both must pass. Without the env var the tab simply never appears
    (failsafe: no token → no moderator mode → no public surface area).
    Wraps st.secrets in try/except because secrets.toml is optional in
    local dev / CI and accessing missing keys raises StreamlitSecretNotFoundError.
    """
    expected = os.environ.get("MODERATOR_TOKEN")
    if not expected:
        try:
            expected = st.secrets.get("moderator_token", None)
        except Exception:
            expected = None
    if not expected:
        return False
    try:
        provided = st.query_params.get("mod", "")
    except Exception:
        provided = ""
    return bool(provided) and provided == expected


_MODERATOR_MODE = _moderator_mode_active()

_tab_labels = ["Overview", "Geography / Map", "Data", "Deep Dive",
               "Publication Figures", "Methods & Appendix", "About"]
if _MODERATOR_MODE:
    _tab_labels.append("Moderation")

_tabs = st.tabs(_tab_labels)
tab_overview, tab_geo, tab_data, tab_deep, tab_pub, tab_methods, tab_about = _tabs[:7]
tab_moderation = _tabs[7] if _MODERATOR_MODE else None


# ---------------------------------------------------------------------------
# TAB: Overview
# ---------------------------------------------------------------------------

with tab_overview:
    # Shared branch colour key — used across every panel on this tab
    # (sunburst, trials-by-category, phase, temporal). Rendered once at the
    # top as a compact chip row so we can drop per-chart branch legends.
    _branches_present = (
        df_filt["Branch"].dropna().unique().tolist() if not df_filt.empty else []
    )
    _branch_key_order = ["Heme-onc", "Solid-onc", "Mixed", "Unknown"]
    _branches_in_view = [b for b in _branch_key_order if b in _branches_present]
    if _branches_in_view:
        _chips = []
        for _br in _branches_in_view:
            _col = BRANCH_COLORS.get(_br, THEME["primary"])
            _chips.append(
                f'<span style="display:inline-flex; align-items:center; '
                f'gap:0.4rem; margin-right:1.4rem; font-size:0.86rem; '
                f'color:{THEME["text"]};">'
                f'<span style="display:inline-block; width:14px; height:14px; '
                f'border-radius:3px; background:{_col};"></span>'
                f'{_br}</span>'
            )
        st.markdown(
            '<div style="margin: 0.2rem 0 1.2rem 0; padding-bottom: 0.4rem; '
            'border-bottom: 1px solid #e5e7eb;">'
            '<div style="font-size:0.78rem; color:#64748b; '
            'margin-bottom:0.35rem;">'
            "All panels on this tab share the branch colour key below."
            "</div>"
            + "".join(_chips)
            + "</div>",
            unsafe_allow_html=True,
        )

    # Disease hierarchy sunburst (Branch → Category → Entity)
    st.subheader("Disease hierarchy at a glance")
    st.caption(
        "Branch → Disease category → Disease entity, with wedge size proportional "
        "to trial count. Click any wedge to zoom in; publication version in Figure 5."
    )
    if not df_filt.empty:
        _ov_sun = (
            df_filt[["Branch", "DiseaseCategory", "DiseaseEntity"]]
            .fillna("Unknown").assign(Count=1)
            .groupby(["Branch", "DiseaseCategory", "DiseaseEntity"], as_index=False).sum()
        )
        fig_ov_sun = px.sunburst(
            _ov_sun, path=["Branch", "DiseaseCategory", "DiseaseEntity"],
            values="Count", color="Branch", color_discrete_map=BRANCH_COLORS,
            height=460, template="plotly_white",
        )
        fig_ov_sun.update_traces(
            insidetextorientation="radial",
            marker=dict(line=dict(color="white", width=1.2)),
        )
        fig_ov_sun.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=8, r=8, t=8, b=8),
            font=dict(family="Inter, sans-serif", size=12, color=THEME["text"]),
        )
        st.plotly_chart(fig_ov_sun, width='stretch')
    else:
        st.info("No trials for the current filter selection.")

    # Row 1: Branch summary + Heme vs Solid targets
    ov_r1c1, ov_r1c2 = st.columns(2)

    with ov_r1c1:
        st.subheader("Trials by disease category")
        st.caption(
            "Grouped by disease family (heme, solid, other) and sorted by count "
            "within each group; cross-cutting baskets sit at the far right."
        )
        counts_cat = (
            df_filt.groupby(["DiseaseCategory", "Branch"], as_index=False)
            .size().rename(columns={"size": "Count"})
        )
        if not counts_cat.empty:
            # Semantic ordering instead of pure count-descending. Baskets
            # (especially the cross-branch "Basket/Multidisease") aren't
            # disease categories — they're spanning buckets — so sorting them
            # in-line with single-disease categories misleads the reader.
            # Group totals for ordering decisions.
            _total_by_cat = counts_cat.groupby("DiseaseCategory")["Count"].sum()
            _branch_by_cat = (
                counts_cat.groupby("DiseaseCategory")["Branch"]
                .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "Unknown")
            )

            _basket_labels = {HEME_BASKET_LABEL, SOLID_BASKET_LABEL, BASKET_MULTI_LABEL}
            _heme_regular, _solid_regular, _other_regular = [], [], []
            for cat in _total_by_cat.index:
                if cat in _basket_labels or cat == UNCLASSIFIED_LABEL:
                    continue
                br = _branch_by_cat.get(cat, "Unknown")
                if br == "Heme-onc":
                    _heme_regular.append(cat)
                elif br == "Solid-onc":
                    _solid_regular.append(cat)
                else:
                    _other_regular.append(cat)

            def _by_count_desc(cats):
                return sorted(cats, key=lambda c: -_total_by_cat.get(c, 0))

            category_order = (
                _by_count_desc(_heme_regular)
                + _by_count_desc(_solid_regular)
                + _by_count_desc(_other_regular)
                # Cross-cutting baskets at the right, regardless of count.
                + [lbl for lbl in (HEME_BASKET_LABEL, SOLID_BASKET_LABEL, BASKET_MULTI_LABEL)
                   if lbl in _total_by_cat.index]
                + ([UNCLASSIFIED_LABEL] if UNCLASSIFIED_LABEL in _total_by_cat.index else [])
            )

            fig_cat = px.bar(
                counts_cat, x="DiseaseCategory", y="Count", color="Branch",
                color_discrete_map=BRANCH_COLORS, template="plotly_white", height=380,
                category_orders={"DiseaseCategory": category_order},
            )
            fig_cat.update_layout(
                barmode="stack",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
                showlegend=False,  # shared key at top of Overview carries this
            )
            fig_cat.update_xaxes(color=THEME["muted"])
            fig_cat.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_cat, width='stretch')
        else:
            st.info("No trials for the current filter selection.")

    with ov_r1c2:
        st.subheader("Trials by antigen target")
        counts_target = (
            df_filt.loc[~df_filt["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"]
            .fillna("Unknown").value_counts().rename_axis("TargetCategory")
            .reset_index(name="Count").head(20)
        )
        _n_shown_targets = len(counts_target)
        st.caption(
            f"Top {_n_shown_targets} antigen{'s' if _n_shown_targets != 1 else ''}. "
            "Platforms (CAR-NK, CAAR-T, …) shown in the Modality figure."
        )
        if not counts_target.empty:
            st.plotly_chart(
                make_bar(counts_target, "TargetCategory", "Count", color=THEME["primary"], height=380),
                width='stretch',
            )
        else:
            st.info("No trials for the current filter selection.")

    # Row 2: Phase by Branch + Temporal
    ov_r2c1, ov_r2c2 = st.columns(2)

    with ov_r2c1:
        st.subheader("Trials by phase")
        st.caption("Phase distribution of trials in the current filter, stacked by branch.")
        phase_counts = (
            df_filt.groupby(["PhaseOrdered", "Branch"], observed=False).size().reset_index(name="Count")
        )
        phase_counts["PhaseNormalized"] = phase_counts["PhaseOrdered"].astype(str)
        phase_counts["Phase"] = phase_counts["PhaseNormalized"].map(PHASE_LABELS)
        phase_counts = phase_counts[phase_counts["Count"] > 0].copy()
        phase_counts["Phase"] = pd.Categorical(
            phase_counts["Phase"],
            categories=[PHASE_LABELS[p] for p in PHASE_ORDER], ordered=True,
        )
        phase_counts = phase_counts.sort_values("Phase")
        if not phase_counts.empty:
            fig_phase = px.bar(
                phase_counts, x="Phase", y="Count", color="Branch",
                color_discrete_map=BRANCH_COLORS, template="plotly_white", height=320,
            )
            fig_phase.update_layout(
                barmode="stack",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
                showlegend=False,
            )
            fig_phase.update_xaxes(color=THEME["muted"], categoryorder="array",
                                    categoryarray=[PHASE_LABELS[p] for p in PHASE_ORDER])
            fig_phase.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_phase, width='stretch')
        else:
            st.info("No trials for the current filter selection.")

    with ov_r2c2:
        st.subheader("Trials by start year")
        st.caption("Annual trial starts in the current filter, stacked area by branch.")
        year_df = df_filt.copy()
        year_df["StartYear"] = pd.to_numeric(year_df["StartYear"], errors="coerce")
        year_df = year_df.dropna(subset=["StartYear"])
        year_df["StartYear"] = year_df["StartYear"].astype(int)
        counts_year = (
            year_df.groupby(["StartYear", "Branch"], as_index=False)
            .size().rename(columns={"size": "Count"})
        )
        if not counts_year.empty:
            # plotly 6.x: px.area no longer auto-stacks. Use go.Scatter with
            # stackgroup="one" so Heme and Solid stack instead of overdraw.
            fig_year = go.Figure()
            for _branch in sorted(counts_year["Branch"].unique()):
                _bd = counts_year[counts_year["Branch"] == _branch].sort_values("StartYear")
                fig_year.add_trace(go.Scatter(
                    x=_bd["StartYear"], y=_bd["Count"],
                    name=_branch, mode="lines",
                    stackgroup="one",
                    line=dict(width=0.5, color=BRANCH_COLORS.get(_branch, THEME["primary"])),
                    fillcolor=BRANCH_COLORS.get(_branch, THEME["primary"]),
                ))
            fig_year.update_layout(template="plotly_white", height=320)
            fig_year.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
                showlegend=False,
            )
            _ov_first = _first_meaningful_year(counts_year) or int(counts_year["StartYear"].min())
            _ov_last = int(counts_year["StartYear"].max())
            fig_year.update_xaxes(
                color=THEME["muted"], tickmode="linear", dtick=1, tickformat="d",
                range=[_ov_first - 0.5, _ov_last + 0.5],
            )
            fig_year.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_year, width='stretch')
        else:
            st.info("No trials with a valid start year for the current filter selection.")

    # Methodological backing — collapsed by default so the insight-first flow
    # above isn't blocked. Full PRISMA narrative also lives in the Methods tab.
    if prisma_counts:
        with st.expander("Study selection (PRISMA flow)", expanded=False):
            prisma_rows = [
                {"Step": "Records identified via ClinicalTrials.gov API", "n": prisma_counts.get("n_fetched", "—"), "Note": ""},
                {"Step": "Duplicate records removed", "n": prisma_counts.get("n_duplicates_removed", "—"), "Note": "Same NCT ID"},
                {"Step": "Records screened", "n": prisma_counts.get("n_after_dedup", "—"), "Note": ""},
                {"Step": "Excluded: pre-specified NCT IDs", "n": prisma_counts.get("n_hard_excluded", "—"), "Note": "Manually curated exclusion list"},
                {"Step": "Excluded: autoimmune-only indications", "n": prisma_counts.get("n_indication_excluded", "—"), "Note": "Keyword-based exclusion"},
                {"Step": "Studies included in analysis", "n": prisma_counts.get("n_included", "—"), "Note": "Final dataset"},
            ]
            prisma_df = pd.DataFrame(prisma_rows)
            st.dataframe(
                prisma_df, width='stretch', hide_index=True,
                column_config={
                    "Step": st.column_config.TextColumn("Step", width="large"),
                    "n": st.column_config.NumberColumn("n", width="small"),
                    "Note": st.column_config.TextColumn("Note", width="medium"),
                },
            )
            st.caption("Full PRISMA narrative and classification methodology in the Methods & Appendix tab.")


# ---------------------------------------------------------------------------
# TAB: Geography / Map
# ---------------------------------------------------------------------------

with tab_geo:
    st.subheader("Global studies by country")

    countries_long = split_pipe_values(df_filt["Countries"])
    if not countries_long:
        st.info("No country information available for the current filter selection.")
    else:
        country_df = pd.DataFrame({"Country": countries_long})
        country_counts = (
            country_df["Country"].value_counts().rename_axis("Country").reset_index(name="Count")
        )
        country_counts_iso = country_counts.copy()
        country_counts_iso["ISO3"] = country_counts_iso["Country"].map(_to_iso3)
        country_counts_iso = country_counts_iso.dropna(subset=["ISO3"])

        # Session-cached — rebuilds only when the NCT filter set changes.
        _geo_sites = _get_geo_sites_cached(all_open_sites, df_filt)
        _has_coords = not _geo_sites.empty

        # Compact controls row above the map. Pill-chip style matches the
        # Fig 1 overlay toggles for visual consistency across the app.
        if _has_coords:
            _c_ctrl1, _c_ctrl2 = st.columns([0.55, 0.45])
            with _c_ctrl1:
                _layer_labels = ["Country shading", "Open-site dots"]
                _active_layers = st.pills(
                    "Map layers",
                    options=_layer_labels,
                    default=_layer_labels,
                    selection_mode="multi",
                    key="world_map_layers",
                    label_visibility="collapsed",
                ) or []
                _show_shading = "Country shading" in _active_layers
                _show_sites = "Open-site dots" in _active_layers
            with _c_ctrl2:
                if _show_sites:
                    _dot_mode = st.pills(
                        "Dot colour",
                        options=["Branch", "Single"],
                        default="Branch",
                        key="world_sites_color_by",
                        label_visibility="collapsed",
                    ) or "Branch"
                    _site_color = _dot_mode
                    st.caption(
                        f"<span style='color:#64748b;'>"
                        f"{len(_geo_sites):,} sites · "
                        f"{_geo_sites['NCTId'].nunique():,} trials"
                        f"</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    _site_color = "Branch"
                    st.caption(
                        "<span style='color:#64748b;'>Country shading = trial count</span>",
                        unsafe_allow_html=True,
                    )
        else:
            _show_shading = True
            _show_sites = False
            _site_color = "Branch"
            st.caption(
                "<span style='color:#64748b;'>Country shading = trial count · "
                "site-level coordinates unavailable — click **Refresh now** "
                "in the sidebar to enable site dots.</span>",
                unsafe_allow_html=True,
            )

        # Base choropleth.
        fig_world = go.Figure()
        if _show_shading:
            fig_world.add_trace(go.Choropleth(
                locations=country_counts_iso["ISO3"],
                locationmode="ISO-3",
                z=country_counts_iso["Count"],
                text=country_counts_iso["Country"],
                hovertemplate="<b>%{text}</b><br>%{z} trials<extra></extra>",
                colorscale=[
                    [0.00, "#eff6ff"], [0.25, "#bfdbfe"],
                    [0.50, "#60a5fa"], [0.75, "#2563eb"], [1.00, "#1e3a8a"],
                ],
                colorbar=dict(
                    thickness=8, len=0.45, x=1.0, xanchor="left",
                    tickfont=dict(size=10, color="#64748b"),
                    outlinewidth=0, ticks="outside", ticklen=3,
                ),
                marker_line_color="rgba(0,0,0,0.10)", marker_line_width=0.3,
                name="",
                showscale=True,
            ))

        # Site dots overlay.
        if _show_sites and not _geo_sites.empty:
            if _site_color == "Branch":
                for _branch in sorted(_geo_sites["Branch"].unique()):
                    _sub = _geo_sites[_geo_sites["Branch"] == _branch]
                    fig_world.add_trace(go.Scattergeo(
                        lat=_sub["Latitude"], lon=_sub["Longitude"],
                        mode="markers",
                        name=_branch,
                        marker=dict(
                            size=5.5, opacity=0.78, line=dict(width=0.5, color="white"),
                            color=BRANCH_COLORS.get(_branch, THEME["primary"]),
                        ),
                        customdata=_sub[["NCTId", "Facility", "City", "Country", "SiteStatus"]].fillna(""),
                        hovertemplate=(
                            "<b>%{customdata[1]}</b><br>"
                            "%{customdata[2]}, %{customdata[3]}<br>"
                            "%{customdata[0]} · %{customdata[4]}"
                            "<extra>" + _branch + "</extra>"
                        ),
                    ))
            else:
                fig_world.add_trace(go.Scattergeo(
                    lat=_geo_sites["Latitude"], lon=_geo_sites["Longitude"],
                    mode="markers",
                    name="Open sites",
                    marker=dict(
                        size=5.5, opacity=0.75, line=dict(width=0.5, color="white"),
                        color=THEME["primary"],  # style-guide primary navy
                    ),
                    customdata=_geo_sites[["NCTId", "Facility", "City", "Country", "SiteStatus"]].fillna(""),
                    hovertemplate=(
                        "<b>%{customdata[1]}</b><br>"
                        "%{customdata[2]}, %{customdata[3]}<br>"
                        "%{customdata[0]} · %{customdata[4]}<extra></extra>"
                    ),
                ))

        fig_world.update_layout(
            margin=dict(l=0, r=0, t=4, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=THEME["text"], family="Inter, sans-serif"),
            geo=dict(
                # scope="world" + explicit lataxis/lonaxis range prevents
                # plotly from auto-fitting to the subset of ISO3s with data
                # (which cropped the map to Europe when Americas/Asia dots
                # weren't shown).
                scope="world",
                bgcolor="rgba(0,0,0,0)",
                lakecolor="#e0f2fe", landcolor="#f1f5f9",
                showframe=False, showcoastlines=False,
                showcountries=True, countrycolor="rgba(0,0,0,0.08)",
                projection=dict(type="natural earth"),
                lataxis=dict(range=[-55, 78]),
                lonaxis=dict(range=[-165, 180]),
            ),
            legend=dict(
                orientation="h", yanchor="top", y=0.02,
                xanchor="center", x=0.5,
                font=dict(size=10, color="#475569"),
                bgcolor="rgba(255,255,255,0.82)", borderwidth=0, title=None,
                itemsizing="constant",
            ),
            height=460,
        )

        # Map + top-countries horizontal bar side-by-side. Horizontal reads
        # country names left-to-right with no rotation, much cleaner.
        _c_map, _c_bar = st.columns([0.68, 0.32])
        with _c_map:
            st.plotly_chart(fig_world, width='stretch')
        with _c_bar:
            _top_countries = country_counts.head(12).iloc[::-1]  # reverse so biggest on top
            fig_top = go.Figure()
            fig_top.add_trace(go.Bar(
                x=_top_countries["Count"],
                y=_top_countries["Country"],
                orientation="h",
                marker=dict(color=THEME["primary"], line=dict(width=0)),
                text=_top_countries["Count"],
                textposition="outside",
                textfont=dict(size=10, color="#475569"),
                hovertemplate="<b>%{y}</b><br>%{x} trials<extra></extra>",
            ))
            fig_top.update_layout(
                title=dict(
                    text="Top countries by trial count",
                    font=dict(size=13, color=THEME["text"]),
                    x=0.02, xanchor="left", y=0.98, yanchor="top",
                ),
                height=460,
                margin=dict(l=4, r=28, t=36, b=4),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif", size=11, color=THEME["text"]),
                xaxis=dict(
                    showgrid=False, showticklabels=False, zeroline=False,
                    range=[0, _top_countries["Count"].max() * 1.18],
                ),
                yaxis=dict(
                    showgrid=False, tickfont=dict(size=11, color="#475569"),
                    ticks="",
                ),
                bargap=0.35, showlegend=False,
            )
            st.plotly_chart(fig_top, width='stretch')

        # Country-counts table spans full width below.
        st.markdown(
            '<div style="font-size:0.85rem; font-weight:600; color:#334155; '
            'margin: 0.25rem 0 0.15rem 0;">All countries</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            country_counts, width='stretch', height=260, hide_index=True,
            column_config={
                "Country": st.column_config.TextColumn("Country", width="medium"),
                "Count":   st.column_config.NumberColumn("Trials", format="%d"),
            },
        )

    st.subheader("Sites by city")

    _countries_avail = _countries_by_activity()
    if not _countries_avail:
        st.info("No open or recruiting study sites in the current filter selection.")
    else:
        # Default to most active country, but preserve user's last selection
        # via session state so the Geography + Data tabs stay in sync.
        _prev = st.session_state.get("sites_country", _countries_avail[0])
        _default_idx = _countries_avail.index(_prev) if _prev in _countries_avail else 0
        selected_country = st.selectbox(
            "Country",
            options=_countries_avail,
            index=_default_idx,
            key="sites_country",
            help="Pick any country with at least one open or recruiting site in the current filter.",
        )

        country_open_sites, country_study_view = _country_study_view(selected_country)

        if country_open_sites.empty:
            st.info(f"No open or recruiting sites found in {selected_country}.")
        else:
            country_city_counts = (
                country_open_sites["City"].fillna("Unknown").value_counts()
                .rename_axis("City").reset_index(name="OpenSiteCount")
                .sort_values(["OpenSiteCount", "City"], ascending=[False, True], na_position="last")
                .reset_index(drop=True)
            )

            g1, g2, g3 = st.columns(3)
            with g1:
                st.metric(f"{selected_country} site rows", f"{len(country_open_sites):,}",
                          help=f"Recruiting / active {selected_country} site rows")
            with g2:
                st.metric("Cities", country_open_sites["City"].dropna().nunique(),
                          help="Cities with open sites")
            with g3:
                st.metric(
                    "Unique trials",
                    country_study_view["NCTId"].nunique() if not country_study_view.empty else 0,
                    help=f"NCT IDs with at least one open {selected_country} site",
                )

            # Mirror the Global-view pattern: map + top-cities bar side by
            # side (primary visuals), then the full city table below spans
            # full width (lookup surface). This keeps the country's map next
            # to its ranking instead of floating at the bottom disconnected.
            _has_country_coords = (
                "Latitude" in country_open_sites.columns
                and not country_open_sites["Latitude"].isna().all()
            )
            _cgeo = pd.DataFrame()
            if _has_country_coords:
                _cgeo = country_open_sites.dropna(subset=["Latitude", "Longitude"]).copy()
                _cgeo = (
                    _cgeo.groupby(["City", "Latitude", "Longitude"], dropna=False)
                    .agg(Trials=("NCTId", "nunique"), Sites=("NCTId", "count"))
                    .reset_index()
                )

            _primary_h = 420
            _tbl_key = f"city_table_{selected_country}"
            _map_key = f"city_map_{selected_country}"
            _map_last_key = f"last_map_pi_{selected_country}"

            _c_cmap, _c_cbar = st.columns([0.60, 0.40])
            with _c_cmap:
                st.markdown(f"**{selected_country} site map** "
                            "<span style='color:#64748b; font-weight:400;'>"
                            "— click a dot to select its city below</span>",
                            unsafe_allow_html=True)
                if _has_country_coords and not _cgeo.empty:
                    _c_fig = go.Figure()
                    _c_fig.add_trace(go.Scattergeo(
                        lat=_cgeo["Latitude"], lon=_cgeo["Longitude"],
                        mode="markers",
                        marker=dict(
                            size=(_cgeo["Trials"].astype(float).pow(0.6) * 4).clip(lower=5, upper=30),
                            sizemode="diameter",
                            color=THEME["primary"], opacity=0.65,
                            line=dict(width=0.5, color="white"),
                        ),
                        customdata=_cgeo[["City", "Trials", "Sites"]].fillna(""),
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]} trials · %{customdata[2]} site entries"
                            "<extra></extra>"
                        ),
                    ))
                    _c_fig.update_layout(
                        margin=dict(l=0, r=0, t=4, b=0),
                        paper_bgcolor="rgba(0,0,0,0)",
                        geo=dict(
                            bgcolor="rgba(0,0,0,0)",
                            lakecolor="#ddeeff", landcolor="#eef2f7",
                            showframe=False, showcoastlines=False,
                            showcountries=True, countrycolor="rgba(0,0,0,0.12)",
                            fitbounds="locations",
                            projection_type="natural earth",
                        ),
                        height=_primary_h,
                    )
                    _map_event = st.plotly_chart(
                        _c_fig, width='stretch',
                        on_select="rerun", key=_map_key,
                        selection_mode=("points",),
                    )

                    # If the user clicked a dot (and it's a NEW click —
                    # compare against the last-seen point_index so a
                    # stale click from an earlier rerun doesn't fight
                    # a fresh table click), push the matching city row
                    # into the city table's selection state. Must happen
                    # BEFORE the st.dataframe below is instantiated.
                    try:
                        _points = (_map_event.selection.points
                                   if _map_event and _map_event.selection else None)
                    except Exception:
                        _points = None
                    if _points:
                        _pi = _points[0].get("point_index")
                        _last_pi = st.session_state.get(_map_last_key)
                        if _pi is not None and _pi != _last_pi and _pi < len(_cgeo):
                            _clicked_city = _cgeo.iloc[_pi]["City"]
                            _match = country_city_counts.index[
                                country_city_counts["City"] == _clicked_city
                            ]
                            if len(_match) > 0:
                                st.session_state[_tbl_key] = {
                                    "selection": {
                                        "rows": [int(_match[0])],
                                        "columns": [],
                                    }
                                }
                            st.session_state[_map_last_key] = _pi
                else:
                    st.info(
                        "Site-level coordinates unavailable for this country "
                        "in the current data. Click **Refresh now** in the "
                        "sidebar to enable site dots."
                    )
            with _c_cbar:
                # Cap the bar to top 15 so dense countries (China, US, …)
                # don't produce an unreadable crammed x-axis. Full list is
                # in the table below.
                _top_cities = country_city_counts.head(15)
                st.markdown(
                    f"**Top cities** "
                    f"<span style='color:#64748b; font-weight:400;'>"
                    f"(showing {len(_top_cities)} of {len(country_city_counts)})</span>",
                    unsafe_allow_html=True,
                )
                st.plotly_chart(
                    make_bar(_top_cities, "City", "OpenSiteCount",
                             height=_primary_h, color=THEME["primary"]),
                    width='stretch',
                )

            # Full city table below — spans full width. Click any row for
            # the trial drilldown.
            st.markdown(
                f"**{selected_country} city table** "
                f"<span style='color:#64748b; font-weight:400;'>"
                f"— click a row to see its trials</span>",
                unsafe_allow_html=True,
            )
            city_event = st.dataframe(
                country_city_counts, width='stretch',
                height=min(340, max(200, len(country_city_counts) * 32 + 48)),
                hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key=f"city_table_{selected_country}",
                column_config={
                    "City": st.column_config.TextColumn("City", width="medium"),
                    "OpenSiteCount": st.column_config.NumberColumn(
                        "Open sites", format="%d",
                        help="Recruiting / active site rows in this city.",
                    ),
                },
            )

            if city_event and city_event.selection.rows:
                selected_idx = city_event.selection.rows[0]
                selected_city = country_city_counts.iloc[selected_idx]["City"]

                st.markdown(
                    f"### Trials with open {selected_country} sites in {selected_city} "
                    "<span style='color:#64748b; font-weight:400;'>"
                    "— click any row to open the full trial record below</span>",
                    unsafe_allow_html=True,
                )

                city_nct_ids = (
                    country_open_sites.loc[
                        country_open_sites["City"].fillna("Unknown") == selected_city, "NCTId",
                    ].dropna().unique()
                )

                city_trial_view = country_study_view[
                    country_study_view["NCTId"].isin(city_nct_ids)
                ].copy()

                if city_trial_view.empty:
                    st.info(f"No study rows found for {selected_city}.")
                else:
                    _cols = [c for c in [
                        "NCTId", "NCTLink", "BriefTitle",
                        "Branch", "DiseaseCategory", "DiseaseEntity",
                        "TargetCategory", "ProductType", "Phase",
                        "OverallStatus", "LeadSponsor",
                        "Cities", "SiteStatuses",
                    ] if c in city_trial_view.columns]
                    city_trial_view, _cols = _attach_flag_column(city_trial_view, _cols)
                    _city_trial_event = st.dataframe(
                        city_trial_view[_cols],
                        width='stretch', height=320, hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"city_trial_table_{selected_country}_{selected_city}",
                        column_config={
                            "NCTId": st.column_config.TextColumn("NCT ID"),
                            "NCTLink": st.column_config.LinkColumn("Trial link", display_text="Open trial"),
                            "BriefTitle": st.column_config.TextColumn("Title", width="large"),
                            "Branch": st.column_config.TextColumn("Branch"),
                            "DiseaseCategory": st.column_config.TextColumn("Category"),
                            "DiseaseEntity": st.column_config.TextColumn("Entity"),
                            "TargetCategory": st.column_config.TextColumn("Target"),
                            "ProductType": st.column_config.TextColumn("Product"),
                            "Phase": st.column_config.TextColumn("Phase"),
                            "OverallStatus": st.column_config.TextColumn("Status"),
                            "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
                            "Cities": st.column_config.TextColumn(f"{selected_country} cities", width="large"),
                            "SiteStatuses": st.column_config.TextColumn("Site status", width="medium"),
                        },
                    )

                    # Row-click drilldown — same shared helper used by Data tab
                    # and Deep Dive sub-tabs. Look up the full record in df_filt
                    # (which has Modality, AgeGroup, ClassificationConfidence,
                    # BriefSummary, etc.) since country_study_view is a subset.
                    _selected_trial_rows = (
                        _city_trial_event.selection.rows
                        if _city_trial_event and hasattr(_city_trial_event, "selection")
                        else []
                    )
                    if _selected_trial_rows:
                        _sel_nct = city_trial_view.iloc[_selected_trial_rows[0]]["NCTId"]
                        _full_rec = df_filt[df_filt["NCTId"] == _sel_nct]
                        if not _full_rec.empty:
                            _render_trial_drilldown(
                                _full_rec.iloc[0],
                                key_suffix=f"geo_city_{selected_country}_{selected_city}",
                            )
                        else:
                            # Fallback: use the country_study_view row if df_filt
                            # doesn't have it (unlikely but defensive).
                            _render_trial_drilldown(
                                city_trial_view.iloc[_selected_trial_rows[0]],
                                key_suffix=f"geo_city_{selected_country}_{selected_city}",
                            )
            else:
                st.caption("Select a city row in the table to open the related trial list below.")


# ---------------------------------------------------------------------------
# TAB: Data
# ---------------------------------------------------------------------------

with tab_data:
    st.subheader("Trial table")

    show_cols = [
        "NCTId", "NCTLink", "BriefTitle",
        "Branch", "DiseaseCategory", "DiseaseEntities",
        "TrialDesign", "TargetCategory", "ProductType",
        "ClassificationConfidence",
        "Phase", "OverallStatus", "StartYear", "Countries", "LeadSponsor",
    ]

    table_df = df_filt.sort_values(
        ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"],
        ascending=[True, True, True, True],
    ).copy()
    table_df["Phase"] = table_df["PhaseLabel"]
    table_df["OverallStatus"] = table_df["OverallStatus"].map(STATUS_DISPLAY).fillna(table_df["OverallStatus"])

    # Flag-badge column — surfaces open community classification-flag GitHub
    # issues so reviewers see at a glance which trials have been challenged.
    # `_load_active_flags` is cached 5min so this is one API call per render.
    table_df, show_cols = _attach_flag_column(table_df, show_cols)

    # Search + country-zoom header ------------------------------------------------
    _ALL_COUNTRIES_LABEL = "All countries"
    _zoom_countries = _countries_by_activity()
    _country_options = [_ALL_COUNTRIES_LABEL] + _zoom_countries
    _prev_zoom = st.session_state.get("data_country_zoom", _ALL_COUNTRIES_LABEL)
    _zoom_idx = (
        _country_options.index(_prev_zoom) if _prev_zoom in _country_options else 0
    )

    _c_search, _c_country, _c_refresh = st.columns([0.62, 0.30, 0.08])
    with _c_search:
        search_q = st.text_input(
            "Search",
            value=st.session_state.get("data_search", ""),
            key="data_search",
            placeholder="Title, NCT, sponsor, intervention…",
            label_visibility="collapsed",
        )
    with _c_country:
        _zoom_country = st.selectbox(
            "Zoom into country",
            options=_country_options,
            index=_zoom_idx,
            key="data_country_zoom",
            label_visibility="collapsed",
        )
    with _c_refresh:
        # Public refresh of the GitHub flag cache. The fetch is otherwise
        # cached 5 min (60 req/hr unauthenticated rate limit), but a user
        # who just filed a flag wants to see the 🚩 indicator immediately,
        # not 5 min from now. `.clear()` busts BOTH the open-flags fetch
        # and the per-issue detail fetch so the drilldown banner also
        # reflects the latest issue body.
        if st.button(
            "Refresh ↻",
            key="data_refresh_flags",
            help="Refresh community flags from GitHub. Use this right "
                 "after filing a flag to see the 🚩 indicator appear "
                 "immediately (otherwise the cache lags up to 5 min).",
            use_container_width=True,
        ):
            _load_active_flags.clear()
            _load_flag_issue_details.clear()
            st.rerun()
    _zoom_active = _zoom_country != _ALL_COUNTRIES_LABEL

    # Apply text search across the columns users actually scan
    if search_q:
        q = search_q.lower().strip()
        _search_cols = [c for c in ["NCTId", "BriefTitle", "LeadSponsor", "Interventions"]
                        if c in table_df.columns]
        mask = pd.Series(False, index=table_df.index)
        for _c in _search_cols:
            mask = mask | table_df[_c].astype(str).str.lower().str.contains(q, na=False)
        table_df = table_df[mask].copy()

    # Apply country zoom — swap Countries for Cities + SiteStatuses
    if _zoom_active:
        if "Countries" in show_cols:
            _ci = show_cols.index("Countries")
            show_cols = show_cols[:_ci] + ["Cities", "SiteStatuses"] + show_cols[_ci + 1:]
        else:
            show_cols = show_cols + ["Cities", "SiteStatuses"]
        _country_sites, _country_sv = _country_study_view(_zoom_country)
        if _country_sv.empty:
            table_df = table_df.iloc[0:0]
        else:
            _nct_in_country = set(_country_sv["NCTId"])
            table_df = table_df[table_df["NCTId"].isin(_nct_in_country)].copy()
            _merge_bits = (
                _country_sv[["NCTId", "Cities", "SiteStatuses"]]
                .drop_duplicates("NCTId")
            )
            table_df = table_df.merge(_merge_bits, on="NCTId", how="left")
        st.caption(
            f"Zoomed to **{_zoom_country}** · {len(table_df)} trial"
            f"{'s' if len(table_df) != 1 else ''} with at least one site there"
        )

    st.caption(
        f"{len(table_df):,} trials · click any row to open the full trial record below."
    )
    _table_event = st.dataframe(
        table_df[show_cols],
        width='stretch', height=460, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key="data_table_sel",
        column_config=_trial_detail_cols({
            "ClassificationConfidence": st.column_config.TextColumn(
                "Conf.", width="small",
                help="high = explicit markers / LLM-validated; medium = defaults or weak markers; low = Unknown branch/entity or combined Unclear.",
            ),
            "Cities": st.column_config.TextColumn(
                f"{_zoom_country} cities" if _zoom_active else "Cities",
                width="large",
            ),
            "SiteStatuses": st.column_config.TextColumn(
                "Site status", width="medium",
            ),
        }),
    )

    # Row-click trial detail — scales to any dataset size (a selectbox would
    # balloon once the filtered set passes 100+ rows). All trial-level views
    # across the app render via _render_trial_drilldown so the layout, links,
    # and (in C7+) Suggest-correction form stay consistent everywhere.
    _selected_rows = (
        _table_event.selection.rows
        if _table_event and hasattr(_table_event, "selection") else []
    )
    if _selected_rows:
        _render_trial_drilldown(table_df.iloc[_selected_rows[0]],
                                 key_suffix="data_tab")
    else:
        st.info(
            "Select a row in the table above to see the full trial record "
            "and classification breakdown."
        )

    # Three-button download row — current view + all filtered + site-level.
    _view_bits = []
    if _zoom_active:
        _view_bits.append(_zoom_country.lower().replace(" ", "_"))
    if search_q:
        _view_bits.append(
            "search_" + search_q.lower().strip().replace(" ", "_")[:32]
        )
    _view_suffix = "_" + "_".join(_view_bits) if _view_bits else ""
    _view_label = (
        f"Download current view ({len(table_df)} trial"
        f"{'s' if len(table_df) != 1 else ''}) as CSV"
    )

    _d1, _d2, _d3 = st.columns(3)
    with _d1:
        st.download_button(
            label=_view_label,
            data=_csv_with_provenance(table_df[show_cols], "Current view"),
            file_name=f"car_t_onc_view{_view_suffix}.csv",
            mime="text/csv",
            disabled=table_df.empty,
        )
    with _d2:
        st.download_button(
            label="Download all filtered trials as CSV",
            data=_csv_with_provenance(df_filt, "All filtered trials"),
            file_name="car_t_oncology_trials_filtered.csv",
            mime="text/csv",
        )
    with _d3:
        if not df_sites.empty:
            st.download_button(
                label="Download site-level data as CSV",
                data=_csv_with_provenance(df_sites, "Site-level data"),
                file_name="car_t_oncology_sites.csv",
                mime="text/csv",
            )


# ---------------------------------------------------------------------------
# Publication figure styling
# ---------------------------------------------------------------------------

# Categorical palette — navy / amber / green / red / teal / cyan / slate.
# No purple / violet / indigo per the Rheum × Onc style guide.
NEJM = ["#0b3d91", "#b45309", "#059669", "#dc2626", "#0f766e", "#0891b2", "#0d9488", "#475569"]
NEJM_BLUE    = HEME_COLOR
NEJM_AMBER   = SOLID_COLOR
NEJM_GREEN   = "#059669"
NEJM_RED     = "#dc2626"
NEJM_TEAL    = "#0f766e"  # replaces the former purple slot

_MODALITY_COLORS.update({
    "Auto CAR-T":      NEJM_BLUE,
    "Allo CAR-T":      "#0891b2",
    "CAR-T (unclear)": "#a1a1aa",
    "CAR-γδ T":        "#0d9488",
    "CAR-NK":          NEJM_GREEN,
    "CAR-Treg":        "#6b7280",   # gray-500 (was indigo)
    "CAAR-T":          NEJM_AMBER,
    "In vivo CAR":     NEJM_RED,
})

_AX_COLOR  = "#1a1a1a"
_GRID_CLR  = "#c8c8c8"
_TICK_SZ   = 11
_TITLE_SZ  = 14
_LAB_SZ    = 12

PUB_FONT = dict(family="Arial, Helvetica, sans-serif", size=_TICK_SZ, color=_AX_COLOR)
PUB_BASE = dict(template="plotly_white", paper_bgcolor="white", plot_bgcolor="white", font=PUB_FONT)
PUB_EXPORT = {"toImageButtonOptions": {"format": "png", "width": 1600, "height": 900, "scale": 2}}


def _pub_header(figure_num: str, title: str, subtitle: str | None = None) -> None:
    sub_html = f'<div class="pub-fig-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="pub-fig-header">'
        f'<div class="pub-fig-eyebrow">Figure {figure_num}</div>'
        f'<div class="pub-fig-title">{title}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _pub_caption(n: int, extra: str | None = None) -> None:
    extra_html = f" {extra}" if extra else ""
    st.markdown(
        f'<div class="pub-fig-caption">n = {n:,} trials in the filtered set. '
        f'Full filter state and data source recorded in the CSV export header.'
        f'{extra_html}</div>',
        unsafe_allow_html=True,
    )


_V_XAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR, mirror=False,
    showgrid=False, ticks="outside", ticklen=6, tickwidth=1.2,
    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
)
_V_YAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR, mirror=False,
    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
    ticks="outside", ticklen=6, tickwidth=1.2,
    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
    zeroline=False,
)
PUB_LAYOUT = dict(**PUB_BASE, margin=dict(l=72, r=36, t=24, b=72), xaxis=_V_XAXIS, yaxis=_V_YAXIS)

_H_XAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
    ticks="outside", ticklen=6, tickwidth=1.2,
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
    zeroline=False,
)
_H_YAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
    showgrid=False,
    ticks="outside", ticklen=4, tickwidth=1.2,
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
)


def _cagr(first_count: int, last_count: int, n_years: int) -> float | None:
    if n_years <= 0 or first_count <= 0:
        return None
    return (last_count / first_count) ** (1 / n_years) - 1


# ---------------------------------------------------------------------------
# TAB: Deep Dive  (disease-entity focused view + per-product aggregation)
# ---------------------------------------------------------------------------

with tab_deep:
    st.markdown(
        '<p class="small-note">Four focused views that complement the aggregate dashboards: '
        "(1) drill into a single disease entity (category or Tier-3 leaf) to see all trials, "
        "sponsors, phases and targets in one place; (2) drill into a single antigen target "
        "to see how its pipeline spreads across diseases, phases, modalities and sponsors; "
        "(3) aggregate trials by named CAR-T product to track each product's portfolio across "
        "indications and phases; (4) break the landscape down by sponsor type (Industry / "
        "Academic / Government / Other) to compare who is running what. Every trial-list table "
        "supports row-click drilldown to a full trial record.</p>",
        unsafe_allow_html=True,
    )

    (deep_sub_disease, deep_sub_target, deep_sub_product,
     deep_sub_sponsor) = st.tabs(
        ["By disease", "By target", "By product", "By sponsor type"]
    )

    # ===== By-disease focus =====
    with deep_sub_disease:
        st.subheader("Disease-entity focus")

        # Use the full (unfiltered) df so users can switch entity independently of filters.
        _branch_opts = sorted(df["Branch"].dropna().unique().tolist())
        _cat_opts = sorted(df["DiseaseCategory"].dropna().unique().tolist())
        _ent_opts = set()
        for _s in df["DiseaseEntity"].dropna():
            _ent_opts.add(str(_s))
        for _s in df["DiseaseEntities"].dropna():
            for _e in str(_s).split("|"):
                _e = _e.strip()
                if _e:
                    _ent_opts.add(_e)
        _ent_opts = sorted(_ent_opts)

        cdd1, cdd2, cdd3 = st.columns([1, 1, 1.2])
        with cdd1:
            dd_branch = st.selectbox("Branch", ["(any)"] + _branch_opts, key="dd_branch")
        _cat_filtered = (
            [c for c in _cat_opts if CATEGORY_TO_BRANCH.get(c, "Unknown") == dd_branch or dd_branch == "(any)"]
            if dd_branch != "(any)" else _cat_opts
        )
        with cdd2:
            dd_cat = st.selectbox("Category", ["(any)"] + _cat_filtered, key="dd_cat")
        # Entities scoped by the chosen category if any
        if dd_cat != "(any)":
            _ent_in_cat = sorted(
                [e for e in _ent_opts
                 if ENTITY_TO_CATEGORY.get(e) == dd_cat or e == dd_cat]
            )
            _ent_choices = ["(any)"] + _ent_in_cat
        else:
            _ent_choices = ["(any)"] + _ent_opts
        with cdd3:
            dd_ent = st.selectbox("Entity (leaf)", _ent_choices, key="dd_ent")

        # Build the focus cohort
        focus = df.copy()
        if dd_branch != "(any)":
            focus = focus[focus["Branch"] == dd_branch]
        if dd_cat != "(any)":
            focus = focus[focus["DiseaseCategory"] == dd_cat]
        if dd_ent != "(any)":
            _mask = focus["DiseaseEntity"] == dd_ent
            _mask |= focus["DiseaseEntities"].fillna("").apply(
                lambda s: dd_ent in [e.strip() for e in str(s).split("|") if e.strip()]
            )
            focus = focus[_mask]

        focus = add_phase_columns(focus)

        if focus.empty:
            st.info("No trials match this disease selection. Broaden the filters above.")
        else:
            st.caption(f"**{len(focus)}** trials in focus.")

            # Headline metrics for the focus cohort
            n_focus = len(focus)
            _rec = int(focus["OverallStatus"].isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())
            _sponsors = focus["LeadSponsor"].dropna().nunique()
            _countries = set()
            for cs in focus["Countries"].dropna():
                for c in str(cs).split("|"):
                    c = c.strip()
                    if c:
                        _countries.add(c)
            _enroll = pd.to_numeric(focus["EnrollmentCount"], errors="coerce").dropna()
            _enroll = _enroll[_enroll <= 1000]  # clip outliers per enrollment convention
            med_e = int(_enroll.median()) if not _enroll.empty else 0

            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("Trials", f"{n_focus:,}", help="Matching this disease focus")
            with m2: st.metric("Open / recruiting", f"{_rec:,}")
            with m3: st.metric("Unique sponsors", f"{_sponsors:,}")
            with m4: st.metric("Median enrollment", f"{med_e:,}", help=f"across {len(_countries)} countries")

            dc1, dc2 = st.columns(2)

            with dc1:
                st.markdown("**Phase distribution**")
                _phase_counts = (
                    focus.groupby("PhaseOrdered", observed=False).size()
                    .reset_index(name="Count")
                )
                _phase_counts["Phase"] = _phase_counts["PhaseOrdered"].astype(str).map(PHASE_LABELS)
                _phase_counts = _phase_counts[_phase_counts["Count"] > 0]
                if not _phase_counts.empty:
                    st.plotly_chart(
                        make_bar(_phase_counts, "Phase", "Count", color=HEME_COLOR, height=280),
                        width='stretch',
                    )
                else:
                    st.info("No phase data.")

                st.markdown("**Antigen target breakdown (top 12)**")
                _tgt = (
                    focus.loc[~focus["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"]
                    .fillna("Unknown").value_counts().head(12)
                    .rename_axis("Target").reset_index(name="Count")
                )
                if not _tgt.empty:
                    st.plotly_chart(
                        make_bar(_tgt, "Target", "Count", color=SOLID_COLOR, height=280),
                        width='stretch',
                    )

            with dc2:
                st.markdown("**Trials by start year**")
                _yr = pd.to_numeric(focus["StartYear"], errors="coerce").dropna().astype(int)
                if not _yr.empty:
                    _yr_counts = _yr.value_counts().sort_index().rename_axis("StartYear").reset_index(name="Count")
                    st.plotly_chart(
                        make_bar(_yr_counts, "StartYear", "Count", color=HEME_COLOR, height=280),
                        width='stretch',
                    )
                else:
                    st.info("No start-year data.")

                st.markdown("**Top sponsors (top 10)**")
                _sp = focus["LeadSponsor"].dropna().value_counts().head(10).rename_axis("Sponsor").reset_index(name="Count")
                if not _sp.empty:
                    _sp_sorted = _sp.sort_values("Count", ascending=True)
                    import plotly.express as _px2
                    _sp_fig = _px2.bar(
                        _sp_sorted, x="Count", y="Sponsor", orientation="h",
                        height=max(280, len(_sp_sorted) * 28 + 60),
                        color_discrete_sequence=[MIXED_COLOR], template="plotly_white",
                    )
                    _sp_fig.update_traces(marker_line_width=0, opacity=0.9)
                    _sp_fig.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=160, r=16, t=8, b=8),
                        font=dict(family="Inter, sans-serif", size=11, color=THEME["text"]),
                        xaxis_title=None, yaxis_title=None, showlegend=False,
                    )
                    st.plotly_chart(_sp_fig, width='stretch')

            st.markdown(
                "**Trial list (focus cohort)** "
                "<span style='color:#64748b; font-weight:400;'>"
                "— click any row to open the full trial record below</span>",
                unsafe_allow_html=True,
            )
            focus_show = focus.copy()
            focus_show["NCTLink"] = focus_show["NCTId"].apply(
                lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
            )
            focus_show["Phase"] = focus_show["PhaseLabel"].fillna(focus_show["Phase"])
            focus_show["OverallStatus"] = focus_show["OverallStatus"].map(STATUS_DISPLAY).fillna(focus_show["OverallStatus"])
            show_cols_focus = [
                "NCTId", "NCTLink", "BriefTitle",
                "Branch", "DiseaseCategory", "DiseaseEntity",
                "TargetCategory", "ProductType", "ProductName",
                "AgeGroup", "SponsorType", "Phase", "OverallStatus",
                "StartYear", "Countries", "LeadSponsor",
            ]
            # Sort first (needs PhaseOrdered), then subset columns for display.
            focus_sorted = focus_show.sort_values(
                ["PhaseOrdered", "StartYear", "NCTId"], na_position="last",
            ).reset_index(drop=True)
            focus_sorted, show_cols_focus = _attach_flag_column(focus_sorted, show_cols_focus)
            _focus_event = st.dataframe(
                focus_sorted[[c for c in show_cols_focus if c in focus_sorted.columns]],
                width='stretch', height=420, hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"deep_disease_focus_{dd_branch}_{dd_cat}_{dd_ent}",
                column_config={
                    "NCTLink": st.column_config.LinkColumn("Trial link", display_text="Open trial"),
                    "BriefTitle": st.column_config.TextColumn("Title", width="large"),
                    "ProductName": st.column_config.TextColumn("Product", width="medium"),
                    "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
                    "Countries": st.column_config.TextColumn("Countries", width="medium"),
                },
            )
            _focus_rows = (
                _focus_event.selection.rows
                if _focus_event and hasattr(_focus_event, "selection") else []
            )
            if _focus_rows:
                _render_trial_drilldown(
                    focus_sorted.iloc[_focus_rows[0]],
                    key_suffix=f"deep_disease_{dd_branch}_{dd_cat}_{dd_ent}",
                )

            st.download_button(
                "Download focus cohort as CSV",
                data=_csv_with_provenance(focus, f"Deep-dive: {dd_branch} / {dd_cat} / {dd_ent}", include_filters=False),
                file_name=f"deep_dive_{dd_branch}_{dd_cat}_{dd_ent}.csv".replace("(any)", "all").replace(" ", "_"),
                mime="text/csv",
            )

    # ===== By-target focus =====
    with deep_sub_target:
        st.subheader("Antigen target focus")
        st.caption(
            "Pick an antigen to see how its pipeline spreads across diseases, "
            "phases, modalities, and sponsors. Same row-click drilldown as the "
            "other Deep-Dive sub-tabs."
        )

        # Target options — full list from snapshot, excluding catch-all /
        # platform labels so the picker is just antigens. Platform labels
        # (CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T) are modality-level metadata,
        # not antigens, and are filterable elsewhere via the Modality sidebar.
        _all_targets_raw = sorted(set(df["TargetCategory"].dropna().unique()))
        _hidden = set(_PLATFORM_LABELS) | {"Other_or_unknown", "CAR-T_unspecified"}
        _antigens_only = [t for t in _all_targets_raw if t not in _hidden]
        # Trial-count map for ordering (most-tested antigens first)
        _target_counts = (
            df.loc[df["TargetCategory"].isin(_antigens_only), "TargetCategory"]
            .value_counts().to_dict()
        )
        _target_options_sorted = sorted(
            _antigens_only, key=lambda t: -_target_counts.get(t, 0)
        )

        ct1, ct2 = st.columns([0.7, 0.3])
        with ct1:
            target_pick = st.selectbox(
                "Antigen target",
                ["(any — show landscape)"] + _target_options_sorted,
                key="dd_target_pick",
                format_func=lambda t: (
                    t if t == "(any — show landscape)"
                    else f"{t}  ({_target_counts.get(t, 0)} trials)"
                ),
            )
        with ct2:
            st.metric(
                "Antigens in dataset",
                f"{len(_antigens_only)}",
                help="Excludes platforms (CAR-NK, CAAR-T, …) and catch-all buckets",
            )

        if target_pick == "(any — show landscape)":
            # Landscape mode — top antigens overall, no single-target focus.
            st.markdown(
                "**Top antigens by trial count** "
                "<span style='color:#64748b; font-weight:400;'>"
                "— pick a specific antigen above to drill in</span>",
                unsafe_allow_html=True,
            )
            _top_n = 25
            _landscape = (
                df.loc[df["TargetCategory"].isin(_antigens_only)]
                .groupby("TargetCategory")
                .agg(
                    Trials=("NCTId", "nunique"),
                    Sponsors=("LeadSponsor", "nunique"),
                    Branches=("Branch", lambda s: ", ".join(sorted(set(s.dropna())))),
                    Categories=("DiseaseCategory",
                                lambda s: ", ".join(sorted(set(s.dropna()))[:6])),
                )
                .reset_index()
                .sort_values("Trials", ascending=False)
                .head(_top_n)
            )
            st.dataframe(
                _landscape,
                width="stretch", height=460, hide_index=True,
                column_config={
                    "TargetCategory": st.column_config.TextColumn("Antigen", width="medium"),
                    "Trials":         st.column_config.NumberColumn("Trials", format="%d", width="small"),
                    "Sponsors":       st.column_config.NumberColumn("# Sponsors", format="%d", width="small"),
                    "Branches":       st.column_config.TextColumn("Branches", width="small"),
                    "Categories":     st.column_config.TextColumn("Disease categories (top)", width="large"),
                },
            )
            st.caption(
                f"Showing top {len(_landscape)} of {len(_antigens_only)} antigens. "
                "Pick a specific antigen above to see its full focus view."
            )
        else:
            focus = df[df["TargetCategory"] == target_pick].copy()
            focus = add_phase_columns(focus)

            if focus.empty:
                st.info(
                    f"No trials match target = {target_pick}. "
                    "Broaden the upstream sidebar filters if a category is excluded."
                )
            else:
                # Headline metrics
                _n = len(focus)
                _rec = int(focus["OverallStatus"].isin(
                    ["RECRUITING", "NOT_YET_RECRUITING"]).sum())
                _sponsors = focus["LeadSponsor"].dropna().nunique()
                _countries = set()
                for cs in focus["Countries"].dropna():
                    for c in str(cs).split("|"):
                        c = c.strip()
                        if c:
                            _countries.add(c)
                _enroll = pd.to_numeric(focus["EnrollmentCount"], errors="coerce").dropna()
                _enroll = _enroll[_enroll <= 1000]
                _med_e = int(_enroll.median()) if not _enroll.empty else 0

                m1, m2, m3, m4 = st.columns(4)
                with m1: st.metric("Trials", f"{_n:,}", help=f"Targeting {target_pick}")
                with m2: st.metric("Open / recruiting", f"{_rec:,}")
                with m3: st.metric("Distinct sponsors", f"{_sponsors:,}")
                with m4: st.metric("Median enrollment", f"{_med_e:,}",
                                    help=f"across {len(_countries)} countries")

                # 2x2 panel grid: disease breakdown, phase, modality, branch
                ta1, ta2 = st.columns(2)
                with ta1:
                    st.markdown("**Disease category breakdown**")
                    _cats = (
                        focus["DiseaseCategory"].fillna("Unknown")
                        .value_counts().head(15)
                        .rename_axis("Category").reset_index(name="Trials")
                    )
                    if not _cats.empty:
                        st.plotly_chart(
                            make_bar(_cats, "Category", "Trials", color=HEME_COLOR, height=280),
                            width="stretch",
                        )

                    st.markdown("**Modality breakdown**")
                    _mods = (
                        focus["Modality"].fillna("Unknown")
                        .value_counts()
                        .rename_axis("Modality").reset_index(name="Trials")
                    )
                    if not _mods.empty:
                        st.dataframe(
                            _mods, width="stretch", hide_index=True,
                            column_config=_mini_count_cols("Modality"),
                        )

                with ta2:
                    st.markdown("**Phase distribution**")
                    _phase_counts = (
                        focus.groupby("PhaseOrdered", observed=False).size()
                        .reset_index(name="Count")
                    )
                    _phase_counts["Phase"] = (
                        _phase_counts["PhaseOrdered"].astype(str).map(PHASE_LABELS)
                    )
                    _phase_counts = _phase_counts[_phase_counts["Count"] > 0]
                    if not _phase_counts.empty:
                        st.plotly_chart(
                            make_bar(_phase_counts, "Phase", "Count",
                                      color=SOLID_COLOR, height=280),
                            width="stretch",
                        )

                    st.markdown("**Branch split**")
                    _br = (
                        focus["Branch"].fillna("Unknown")
                        .value_counts()
                        .rename_axis("Branch").reset_index(name="Trials")
                    )
                    if not _br.empty:
                        st.dataframe(
                            _br, width="stretch", hide_index=True,
                            column_config=_mini_count_cols("Branch"),
                        )

                # Top sponsors developing this antigen
                st.markdown(
                    f"**Top sponsors developing {target_pick}** "
                    f"<span style='color:#64748b; font-weight:400;'>"
                    f"({_sponsors} distinct sponsors total)</span>",
                    unsafe_allow_html=True,
                )
                _spon_top = (
                    focus["LeadSponsor"].dropna().value_counts().head(15)
                    .rename_axis("Lead sponsor").reset_index(name="Trials")
                )
                st.dataframe(
                    _spon_top, width="stretch", hide_index=True,
                    column_config=_mini_count_cols("Lead sponsor"),
                )

                # Trial list with row-click → drilldown
                st.markdown(
                    f"### Trials targeting **{target_pick}** "
                    f"<span style='color:#64748b; font-weight:400;'>"
                    f"({_n} trials · click any row for full details)</span>",
                    unsafe_allow_html=True,
                )
                _focus_show = focus.copy()
                _focus_show["NCTLink"] = _focus_show["NCTId"].apply(
                    lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
                )
                _focus_show["Phase"] = _focus_show["PhaseLabel"].fillna(_focus_show["Phase"])
                _focus_show["OverallStatus"] = _focus_show["OverallStatus"].map(
                    STATUS_DISPLAY).fillna(_focus_show["OverallStatus"])
                _focus_sorted = _focus_show.sort_values(
                    ["PhaseOrdered", "StartYear", "NCTId"], na_position="last",
                ).reset_index(drop=True)
                _target_trial_cols = [c for c in [
                    "NCTId", "NCTLink", "BriefTitle",
                    "Branch", "DiseaseCategory", "DiseaseEntity",
                    "ProductType", "ProductName", "Phase",
                    "OverallStatus", "StartYear", "Countries", "LeadSponsor",
                ] if c in _focus_sorted.columns]
                _focus_sorted, _target_trial_cols = _attach_flag_column(
                    _focus_sorted, _target_trial_cols
                )
                _target_event = st.dataframe(
                    _focus_sorted[_target_trial_cols],
                    width="stretch", height=420, hide_index=True,
                    on_select="rerun", selection_mode="single-row",
                    key=f"deep_target_trial_table_{target_pick}",
                    column_config=_trial_detail_cols(),
                )
                _target_rows = (
                    _target_event.selection.rows
                    if _target_event and hasattr(_target_event, "selection")
                    else []
                )
                if _target_rows:
                    _render_trial_drilldown(
                        _focus_sorted.iloc[_target_rows[0]],
                        key_suffix=f"deep_target_{target_pick}",
                    )

                st.download_button(
                    f"Download trials targeting {target_pick} (CSV)",
                    data=_csv_with_provenance(
                        focus,
                        f"Deep-dive by target: {target_pick}",
                        include_filters=False,
                    ),
                    file_name=f"deep_dive_target_{target_pick}.csv".replace(
                        "/", "_").replace(" ", "_"),
                    mime="text/csv",
                )

    # ===== By-product aggregation =====
    with deep_sub_product:
        st.subheader("Per-product pipeline view")
        st.caption(
            "Each row is one named CAR-T product (from NAMED_PRODUCT_TARGETS). "
            "Shows the product's portfolio across the filtered dataset: number of trials, "
            "targets, modality, phase distribution, sponsor, countries, median enrollment."
        )

        prod_df = df_filt.dropna(subset=["ProductName"]).copy()
        if prod_df.empty:
            st.info("No named-product trials in the current filter selection.")
        else:
            prod_df["EnrollmentCount"] = pd.to_numeric(prod_df["EnrollmentCount"], errors="coerce")
            prod_df_clean = prod_df.copy()
            prod_df_clean["EnrollCapped"] = prod_df_clean["EnrollmentCount"].where(
                prod_df_clean["EnrollmentCount"] <= 1000
            )

            def _phase_max_rank(phases: "pd.Series") -> str:
                """Return the most-advanced phase label among a set of phase labels."""
                try:
                    cat = pd.Categorical(phases.dropna(), categories=PHASE_ORDER, ordered=True)
                    if len(cat) == 0:
                        return "—"
                    return PHASE_LABELS.get(str(cat.max()), str(cat.max()))
                except Exception:
                    return "—"

            pivot = (
                prod_df_clean.groupby("ProductName")
                .agg(
                    Trials=("NCTId", "nunique"),
                    Target=("TargetCategory", lambda s: s.value_counts().index[0] if not s.empty else "—"),
                    Modality=("Modality", lambda s: s.value_counts().index[0] if not s.empty else "—"),
                    ProductType=("ProductType", lambda s: s.value_counts().index[0] if not s.empty else "—"),
                    FurthestPhase=("PhaseNormalized", _phase_max_rank),
                    Sponsors=("LeadSponsor", lambda s: s.dropna().nunique()),
                    Branches=("Branch", lambda s: ", ".join(sorted(set(s.dropna())))),
                    Categories=("DiseaseCategory", lambda s: ", ".join(sorted(set(s.dropna())))),
                    Countries=("Countries", lambda s: ", ".join(sorted(set(split_pipe_values(s)))[:8])),
                    MedianEnroll=("EnrollCapped", lambda s: int(s.median()) if s.notna().any() else 0),
                )
                .reset_index()
                .sort_values("Trials", ascending=False)
            )

            m1, m2, m3 = st.columns(3)
            with m1: st.metric("Named products", f"{len(pivot):,}", help="In the current filter")
            with m2: st.metric("Total trials", f"{int(pivot['Trials'].sum()):,}")
            with m3: st.metric(
                "Top product",
                pivot.iloc[0]["ProductName"] if not pivot.empty else "—",
                help=f"{int(pivot.iloc[0]['Trials'])} trials" if not pivot.empty else "",
            )

            st.caption(
                f"{len(pivot):,} named products · sorted by trial count · "
                "click any row to see that product's trial list, then click a trial for full details"
            )
            _prod_event = st.dataframe(
                pivot, width='stretch', height=460, hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key="deep_product_pivot",
                column_config={
                    "ProductName": st.column_config.TextColumn("Product", width="medium"),
                    "Target": st.column_config.TextColumn("Primary target", width="small"),
                    "Modality": st.column_config.TextColumn("Modality", width="small"),
                    "ProductType": st.column_config.TextColumn("Product type", width="small"),
                    "FurthestPhase": st.column_config.TextColumn("Furthest phase", width="small"),
                    "Sponsors": st.column_config.NumberColumn("# Sponsors", width="small"),
                    "Branches": st.column_config.TextColumn("Branches", width="small"),
                    "Categories": st.column_config.TextColumn("Categories", width="medium"),
                    "Countries": st.column_config.TextColumn("Countries (top)", width="large"),
                    "MedianEnroll": st.column_config.NumberColumn("Median enrollment", width="small"),
                },
            )

            st.download_button(
                "Download per-product CSV",
                data=_csv_with_provenance(pivot, "Per-product pipeline view", include_filters=True),
                file_name="per_product_pipeline.csv",
                mime="text/csv",
            )

            # --- Drilldown: pick a product → see its trials → click a trial
            _prod_rows = (
                _prod_event.selection.rows
                if _prod_event and hasattr(_prod_event, "selection") else []
            )
            if _prod_rows:
                _picked_product = pivot.iloc[_prod_rows[0]]["ProductName"]
                _prod_trials = prod_df[prod_df["ProductName"] == _picked_product].copy()
                _prod_trials["NCTLink"] = _prod_trials["NCTId"].apply(
                    lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
                )
                _prod_trials["Phase"] = _prod_trials["PhaseLabel"].fillna(_prod_trials["Phase"])
                _prod_trials["OverallStatus"] = _prod_trials["OverallStatus"].map(
                    STATUS_DISPLAY).fillna(_prod_trials["OverallStatus"])
                _prod_trials = _prod_trials.sort_values(
                    ["PhaseOrdered", "StartYear", "NCTId"], na_position="last",
                ).reset_index(drop=True)

                st.markdown(
                    f"### Trials for **{_picked_product}** "
                    f"<span style='color:#64748b; font-weight:400;'>"
                    f"({len(_prod_trials)} trials · click any row for full details)</span>",
                    unsafe_allow_html=True,
                )
                _prod_trial_cols = [c for c in [
                    "NCTId", "NCTLink", "BriefTitle",
                    "Branch", "DiseaseCategory", "DiseaseEntity",
                    "TargetCategory", "Phase", "OverallStatus",
                    "StartYear", "Countries", "LeadSponsor",
                ] if c in _prod_trials.columns]
                _prod_trials, _prod_trial_cols = _attach_flag_column(
                    _prod_trials, _prod_trial_cols
                )
                _prod_trial_event = st.dataframe(
                    _prod_trials[_prod_trial_cols],
                    width='stretch', height=320, hide_index=True,
                    on_select="rerun", selection_mode="single-row",
                    key=f"deep_product_trial_table_{_picked_product}",
                    column_config=_trial_detail_cols(),
                )
                _prod_trial_rows = (
                    _prod_trial_event.selection.rows
                    if _prod_trial_event and hasattr(_prod_trial_event, "selection")
                    else []
                )
                if _prod_trial_rows:
                    _render_trial_drilldown(
                        _prod_trials.iloc[_prod_trial_rows[0]],
                        key_suffix=f"deep_product_{_picked_product}",
                    )

    # ===== By-sponsor-type aggregation =====
    with deep_sub_sponsor:
        st.subheader("Landscape by sponsor type")
        st.caption(
            "Aggregates the filtered dataset by sponsor type "
            "(Industry / Academic / Government / Other). Drill into any "
            "bucket to see its top sponsors, antigen targets, and product mix."
        )

        # Defensive: re-derive SponsorType if a stale cached snapshot lacks it.
        if "SponsorType" not in df_filt.columns and "LeadSponsor" in df_filt.columns:
            try:
                from pipeline import _classify_sponsor as _cs
                df_filt["SponsorType"] = df_filt.apply(
                    lambda r: _cs(r.get("LeadSponsor"), r.get("LeadSponsorClass")),
                    axis=1,
                )
            except Exception:
                pass

        if "SponsorType" not in df_filt.columns:
            st.info("Sponsor type not available in the current snapshot.")
        elif df_filt.empty:
            st.info("No trials in the current filter.")
        else:
            sp_agg = (
                df_filt.groupby("SponsorType")
                .agg(
                    Trials=("NCTId", "nunique"),
                    Open=("OverallStatus", lambda s: int(s.isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())),
                    Sponsors=("LeadSponsor", "nunique"),
                    TotalEnrolled=("EnrollmentCount",
                                   lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0)
                                                 .where(lambda x: x <= 1000, 0).sum())),
                    MedianEnrollment=("EnrollmentCount",
                                      lambda s: pd.to_numeric(s, errors="coerce")
                                                .where(lambda x: x <= 1000).median()),
                )
                .reset_index()
                .sort_values("Trials", ascending=False)
            )
            sp_agg["MedianEnrollment"] = sp_agg["MedianEnrollment"].fillna(0).astype(int)

            st.caption(f"{len(sp_agg)} sponsor types · sorted by trial count")
            st.dataframe(
                sp_agg, width='stretch', hide_index=True,
                column_config=_landscape_table_cols("SponsorType", "Sponsor type"),
            )

            sp_choices = sp_agg["SponsorType"].tolist()
            pick = st.selectbox(
                "Drill into sponsor type", options=["—"] + sp_choices, key="dd_sponsor_pick",
            )
            if pick and pick != "—":
                sub = df_filt[df_filt["SponsorType"] == pick]

                st.markdown(
                    f"**Sponsors in *{pick}*** "
                    f"<span style='color:#64748b; font-weight:400;'>"
                    f"({len(sub)} trials, {sub['LeadSponsor'].nunique()} distinct sponsors)"
                    f"</span>",
                    unsafe_allow_html=True,
                )

                # Sponsor list — searchable + scrollable, NOT capped at top-N.
                # User wanted ability to scroll through every sponsor in the
                # selected class (was previously capped at top-10) and to
                # filter by name. Table dimension stays the same; the data
                # source changes from .head(10) to the full list.
                _sponsor_search = st.text_input(
                    "Search sponsors",
                    value="",
                    key=f"dd_sponsor_search_{pick}",
                    placeholder="Filter by sponsor name (case-insensitive substring)",
                    label_visibility="collapsed",
                )
                all_sponsors = (
                    sub["LeadSponsor"].dropna().value_counts()
                    .rename_axis("Lead sponsor").reset_index(name="Trials")
                )
                if _sponsor_search:
                    _q = _sponsor_search.strip().lower()
                    all_sponsors = all_sponsors[
                        all_sponsors["Lead sponsor"].astype(str).str.lower().str.contains(_q, na=False)
                    ]

                st.caption(
                    f"{len(all_sponsors)} sponsor"
                    f"{'s' if len(all_sponsors) != 1 else ''} "
                    f"{'(filtered) ' if _sponsor_search else ''}"
                    "· click a sponsor row to see its trials below"
                )
                _sponsor_event = st.dataframe(
                    all_sponsors, width='stretch', hide_index=True,
                    height=320,  # fixed height keeps the layout tidy regardless of N
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"dd_sponsor_table_{pick}",
                    column_config=_mini_count_cols("Lead sponsor"),
                )

                # Antigen target and product-type breakdowns for this sponsor class
                cA, cB = st.columns(2)
                with cA:
                    st.markdown("**Antigen targets**")
                    _tgt_sub = (
                        sub.loc[~sub["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"]
                        .fillna("Unknown").value_counts().head(15)
                        .rename_axis("Target").reset_index(name="Trials")
                    )
                    st.caption(f"{len(_tgt_sub)} antigens · top 15")
                    st.dataframe(
                        _tgt_sub, width='stretch', hide_index=True,
                        column_config=_mini_count_cols("Target"),
                    )
                with cB:
                    st.markdown("**Product types**")
                    _prod_sub = (
                        sub["ProductType"].fillna("Unclear").value_counts()
                        .rename_axis("Product type").reset_index(name="Trials")
                    )
                    st.caption(f"{len(_prod_sub)} product types")
                    st.dataframe(
                        _prod_sub, width='stretch', hide_index=True,
                        column_config=_mini_count_cols("Product type"),
                    )

                # Branch split (useful signal: is industry concentrating on heme or solid?)
                _branch_sub = (
                    sub["Branch"].fillna("Unknown").value_counts()
                    .rename_axis("Branch").reset_index(name="Trials")
                )
                st.markdown("**Branch split**")
                st.caption(f"{len(_branch_sub)} branches")
                st.dataframe(
                    _branch_sub, width='stretch', hide_index=True,
                    column_config=_mini_count_cols("Branch"),
                )

                # --- Sponsor → trials → trial drilldown ---
                _sponsor_rows = (
                    _sponsor_event.selection.rows
                    if _sponsor_event and hasattr(_sponsor_event, "selection") else []
                )
                if _sponsor_rows:
                    _picked_sponsor = all_sponsors.iloc[_sponsor_rows[0]]["Lead sponsor"]
                    _spon_trials = sub[sub["LeadSponsor"] == _picked_sponsor].copy()
                    _spon_trials["NCTLink"] = _spon_trials["NCTId"].apply(
                        lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
                    )
                    _spon_trials["Phase"] = _spon_trials["PhaseLabel"].fillna(_spon_trials["Phase"])
                    _spon_trials["OverallStatus"] = _spon_trials["OverallStatus"].map(
                        STATUS_DISPLAY).fillna(_spon_trials["OverallStatus"])
                    _spon_trials = _spon_trials.sort_values(
                        ["PhaseOrdered", "StartYear", "NCTId"], na_position="last",
                    ).reset_index(drop=True)

                    st.markdown(
                        f"### Trials sponsored by **{_picked_sponsor}** "
                        f"<span style='color:#64748b; font-weight:400;'>"
                        f"({len(_spon_trials)} trials · click any row for full details)</span>",
                        unsafe_allow_html=True,
                    )
                    _spon_trial_cols = [c for c in [
                        "NCTId", "NCTLink", "BriefTitle",
                        "Branch", "DiseaseCategory", "DiseaseEntity",
                        "TargetCategory", "ProductType", "Phase",
                        "OverallStatus", "StartYear", "Countries",
                    ] if c in _spon_trials.columns]
                    _spon_trials, _spon_trial_cols = _attach_flag_column(
                        _spon_trials, _spon_trial_cols
                    )
                    _spon_trial_event = st.dataframe(
                        _spon_trials[_spon_trial_cols],
                        width='stretch', height=320, hide_index=True,
                        on_select="rerun", selection_mode="single-row",
                        key=f"dd_sponsor_trial_table_{pick}_{_picked_sponsor}",
                        column_config=_trial_detail_cols(),
                    )
                    _spon_trial_rows = (
                        _spon_trial_event.selection.rows
                        if _spon_trial_event and hasattr(_spon_trial_event, "selection")
                        else []
                    )
                    if _spon_trial_rows:
                        _render_trial_drilldown(
                            _spon_trials.iloc[_spon_trial_rows[0]],
                            key_suffix=f"deep_sponsor_{pick}_{_picked_sponsor}",
                        )

            st.download_button(
                "Download sponsor-type aggregation (CSV)",
                data=_csv_with_provenance(sp_agg, "Landscape by sponsor type", include_filters=True),
                file_name="deep_dive_by_sponsor_type.csv",
                mime="text/csv",
            )


# ---------------------------------------------------------------------------
# TAB: Publication Figures  (oncology-specific set, 8 figures)
# ---------------------------------------------------------------------------

with tab_pub:
    st.markdown(
        '<p class="small-note" style="color:#555">Publication-ready figures with white backgrounds. '
        "Use the camera icon (▷ toolbar) on each chart to download a high-resolution PNG; "
        "each chart has a CSV export below it with a provenance header capturing the active "
        "filter state so downloads are reproducibly tagged. "
        "Heme-onc shown in navy, Solid-onc in amber throughout.</p>",
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Fig 1 — Temporal trends, split by Branch, with approved-product overlay
    # ------------------------------------------------------------------
    years_raw = pd.to_numeric(df_filt["StartYear"], errors="coerce").dropna().astype(int)
    _yr_min = int(years_raw.min()) if len(years_raw) else None
    _yr_max = int(years_raw.max()) if len(years_raw) else None
    _fig1_sub = (
        f"Annual trial starts by branch, {_yr_min}–{_yr_max}, for the current "
        "filter. Bottom strip: FDA / EMA / NMPA approvals by product and year "
        f"(last reviewed {APPROVED_PRODUCTS_LAST_REVIEWED})."
        if _yr_min is not None else "Annual trial starts by branch."
    )
    _pub_header("1", "Temporal trends by branch, with approved-product overlay", _fig1_sub)

    year_branch = (
        df_filt.dropna(subset=["StartYear"])
        .assign(StartYear=lambda d: d["StartYear"].astype(int))
        .groupby(["StartYear", "Branch"], as_index=False).size()
        .rename(columns={"size": "Trials"})
    )

    if not year_branch.empty:
        # Trim leading sparse years (<5 trials total) to avoid a long
        # visually-empty left tail; data itself is preserved for CSV export.
        _fig1_first = _first_meaningful_year(year_branch, count_col="Trials") or int(year_branch["StartYear"].min())
        _fig1_last = int(year_branch["StartYear"].max())

        # Two-panel design: annual-trial-starts trend on top, regulatory
        # milestone strip on the bottom, sharing the x-axis. This lets the
        # reader see WHEN approvals landed relative to trial-start trends
        # without cluttering the trend panel itself.
        import re as _re_overlay
        _brand_re = _re_overlay.compile(r"\(([^)]+)\)")

        def _brand_of(full_name: str) -> str:
            m = _brand_re.search(full_name)
            return m.group(1).strip() if m else full_name.strip()

        def _generic_of(full_name: str) -> str:
            return full_name.split("(")[0].strip() if "(" in full_name else full_name.strip()

        # Regulator palette — deliberately distinct from the branch palette
        # (Heme-onc navy / Solid-onc amber) so readers don't conflate an
        # FDA dot with a Heme-onc area or an NMPA dot with Solid-onc amber.
        # Marker shapes are also varied (circle / diamond / square) so the
        # distinction survives greyscale printing.
        _REG_COLOR  = {"FDA": "#059669", "EMA": "#0891b2", "NMPA": "#dc2626"}
        _REG_SYMBOL = {"FDA": "circle",   "EMA": "diamond",  "NMPA": "square"}

        _reg_labels = ["FDA", "EMA", "NMPA"]

        # Enumerate approvals and their brand canonicalisation.
        # Everything from here through _brand_to_y is pure data prep: depends
        # only on APPROVED_PRODUCTS, not on the pill selection. Computed once
        # outside the fragment so pill clicks don't redo it.
        _approvals = []
        for p in APPROVED_PRODUCTS:
            _approvals.append({
                "year": p["year"],
                "regulator": p["regulator"],
                "brand": _brand_of(p["name"]),
                "generic": _generic_of(p["name"]),
                "target": p.get("target", ""),
                "full": p["name"],
            })
        _appr_df = pd.DataFrame(_approvals)

        _brand_order_key = {}
        for b, grp in _appr_df.groupby("brand"):
            fda_years = grp.loc[grp["regulator"] == "FDA", "year"]
            any_years = grp["year"]
            _brand_order_key[b] = (
                fda_years.min() if not fda_years.empty else 9999,
                any_years.min(),
                b,
            )
        _brands_ordered = sorted(_brand_order_key, key=_brand_order_key.get)
        _brands_display = list(reversed(_brands_ordered))
        _brand_to_y = {b: i for i, b in enumerate(_brands_display)}

        @st.fragment
        def _render_fig1() -> None:
            # Fragment-scoped rerun: pill clicks below only re-execute this
            # function, not the whole Publication Figures tab.
            _active_regs = st.session_state.get("fig1_approval_regs", _reg_labels) or []

            # Filter approvals by pill selection.
            _appr_active = _appr_df[_appr_df["regulator"].isin(_active_regs)].copy()
            _has_any_active = not _appr_active.empty

            # Subplot — fixed 0.72 / 0.28 split. The strip grows/shrinks only
            # when the pill set is empty (entire bottom panel hidden).
            _panel_heights = [0.80, 0.20] if not _has_any_active else [0.72, 0.28]
            fig1 = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=_panel_heights,
                vertical_spacing=0.04,
            )

            # --- Top panel: trial-start trend area ------------------------
            for _branch in sorted(year_branch["Branch"].unique()):
                _bd = year_branch[year_branch["Branch"] == _branch].sort_values("StartYear")
                _color = BRANCH_COLORS.get(_branch, THEME["primary"])
                fig1.add_trace(
                    go.Scatter(
                        x=_bd["StartYear"], y=_bd["Trials"],
                        name=_branch, mode="lines",
                        stackgroup="one",
                        line=dict(width=0.5, color=_color),
                        fillcolor=_color, opacity=0.85,
                    ),
                    row=1, col=1,
                )

            # --- Bottom panel: approval milestones strip ------------------
            if _has_any_active:
                for reg in _reg_labels:
                    if reg not in _active_regs:
                        continue
                    _sub = _appr_active[_appr_active["regulator"] == reg]
                    if _sub.empty:
                        continue
                    fig1.add_trace(
                        go.Scatter(
                            x=_sub["year"],
                            y=_sub["brand"].map(_brand_to_y),
                            mode="markers",
                            name=reg,
                            marker=dict(
                                size=13,
                                color=_REG_COLOR[reg],
                                opacity=0.92,
                                line=dict(width=1.2, color="white"),
                                symbol=_REG_SYMBOL[reg],
                            ),
                            customdata=_sub[["brand", "generic", "target", "regulator", "year"]].values,
                            hovertemplate=(
                                "<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
                                "%{customdata[3]} approval · %{customdata[4]}<br>"
                                "Target: %{customdata[2]}"
                                "<extra></extra>"
                            ),
                            legendgroup=reg,
                            showlegend=True,
                        ),
                        row=2, col=1,
                    )

            # --- Layout ---------------------------------------------------
            fig1.update_yaxes(
                row=1, col=1,
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Number of trials",
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                zeroline=False, rangemode="tozero",
            )
            fig1.update_yaxes(
                row=2, col=1,
                tickmode="array",
                tickvals=list(_brand_to_y.values()) if _has_any_active else [],
                ticktext=list(_brand_to_y.keys())  if _has_any_active else [],
                tickfont=dict(size=11, color=THEME["text"]),
                showgrid=False,
                showline=True, linewidth=1.2, linecolor=_AX_COLOR,
                zeroline=False,
                range=[-0.6, (len(_brands_display) - 0.4) if _has_any_active else 1],
                fixedrange=True,
                title=None,
                ticks="",
            )
            if _has_any_active:
                for _i in range(0, len(_brands_display), 2):
                    fig1.add_hrect(
                        y0=_i - 0.5, y1=_i + 0.5,
                        fillcolor="rgba(15, 23, 42, 0.025)", line_width=0,
                        layer="below", row=2, col=1,
                    )
            fig1.update_xaxes(
                row=2, col=1,
                tickmode="linear", dtick=1, tickformat="d", showgrid=False,
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Start year",
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                range=[_fig1_first - 0.5, _fig1_last + 0.5],
            )
            fig1.update_xaxes(
                row=1, col=1,
                showgrid=False, showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                ticks="", showticklabels=False,
                range=[_fig1_first - 0.5, _fig1_last + 0.5],
            )

            _current_year = pd.Timestamp.now().year
            if _yr_max is not None and _yr_max >= _current_year:
                for _row in (1, 2):
                    fig1.add_vrect(
                        x0=_current_year - 0.5, x1=_current_year + 0.5,
                        fillcolor="rgba(0,0,0,0.05)", line_width=0,
                        row=_row, col=1,
                    )
                _max_trials = year_branch.groupby("StartYear")["Trials"].sum().max()
                fig1.add_annotation(
                    x=_current_year, y=_max_trials * 0.96,
                    xref="x", yref="y",
                    text=f"<i>{_current_year}: partial year</i>",
                    showarrow=False,
                    font=dict(size=10, color=THEME["muted"]),
                    xanchor="center", yanchor="top",
                    row=1, col=1,
                )

            fig1.update_layout(
                **PUB_BASE,
                height=560 if _has_any_active else 440,
                margin=dict(l=140, r=36, t=24, b=130),
                legend=dict(
                    orientation="h",
                    yanchor="top", y=-0.22,
                    xanchor="center", x=0.5,
                    font=dict(size=11, color=_AX_COLOR),
                    bgcolor="rgba(0,0,0,0)", borderwidth=0,
                    title=None,
                    itemsizing="constant",
                    traceorder="normal",
                ),
            )

            st.plotly_chart(fig1, width='stretch', config=PUB_EXPORT)

            # Pill row — filters which regulators' dots appear in the strip.
            st.pills(
                "Regulators",
                options=_reg_labels,
                default=_reg_labels,
                selection_mode="multi",
                key="fig1_approval_regs",
                label_visibility="collapsed",
            )

        _render_fig1()

        total_t = len(df_filt)
        fig1_yearly = year_branch.groupby("StartYear")["Trials"].sum().sort_index()
        peak_year = int(fig1_yearly.idxmax())
        peak_n = int(fig1_yearly.max())
        first_yr = int(fig1_yearly.index.min())
        last_yr = int(fig1_yearly.index.max())
        cagr = _cagr(int(fig1_yearly.iloc[0]), int(fig1_yearly.iloc[-1]), last_yr - first_yr)
        cagr_str = f"{cagr * 100:.1f}%" if cagr is not None else "N/A"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total included trials", total_t)
        c2.metric("Year range", f"{first_yr}–{last_yr}")
        c3.metric("Peak year", f"{peak_year} (n={peak_n})")
        c4.metric("CAGR (overall)", cagr_str)

        _pub_caption(len(df_filt))
        st.download_button("Fig 1 data (CSV)",
                           _csv_with_provenance(year_branch, "Fig 1 — Temporal trends by branch"),
                           "fig1_temporal_trends.csv", "text/csv")
    else:
        st.info("No start year data available.")

    # ------------------------------------------------------------------
    # Fig 2 — Phase distribution, stacked by Branch
    # ------------------------------------------------------------------
    _pub_header("2", "Distribution of clinical trial phases, by branch",
                "Number of trials at each phase in the current filter, stacked by branch.")

    phase_counts = (
        df_filt.groupby(["PhaseOrdered", "Branch"], observed=False).size().reset_index(name="Trials")
    )
    phase_counts["Phase"] = phase_counts["PhaseOrdered"].astype(str).map(PHASE_LABELS)
    phase_counts = phase_counts[phase_counts["Trials"] > 0].copy()
    phase_counts["Phase"] = pd.Categorical(
        phase_counts["Phase"], categories=[PHASE_LABELS[p] for p in PHASE_ORDER], ordered=True,
    )
    phase_counts = phase_counts.sort_values("Phase")

    if not phase_counts.empty:
        fig2 = px.bar(
            phase_counts, x="Phase", y="Trials", color="Branch",
            color_discrete_map=BRANCH_COLORS, barmode="stack",
            template="plotly_white", height=420, text="Trials",
        )
        fig2.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                           textfont=dict(size=10, color="white"))
        fig2.update_layout(
            **PUB_LAYOUT,
            xaxis_title="Phase", yaxis_title="Number of trials",
            legend=dict(
                orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                borderwidth=0, title=None,
            ),
        )
        fig2.update_xaxes(categoryorder="array", categoryarray=[PHASE_LABELS[p] for p in PHASE_ORDER])
        st.plotly_chart(fig2, width='stretch', config=PUB_EXPORT)

        total_ph = int(phase_counts["Trials"].sum())
        heme_ph = int(phase_counts.loc[phase_counts["Branch"] == "Heme-onc", "Trials"].sum())
        solid_ph = int(phase_counts.loc[phase_counts["Branch"] == "Solid-onc", "Trials"].sum())
        late_mask = phase_counts["Phase"].isin(["Phase II", "Phase II/III", "Phase III"])
        heme_late = int(phase_counts.loc[late_mask & (phase_counts["Branch"] == "Heme-onc"), "Trials"].sum())
        solid_late = int(phase_counts.loc[late_mask & (phase_counts["Branch"] == "Solid-onc"), "Trials"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Late-phase (II+)", f"{heme_late + solid_late} of {total_ph}")
        c2.metric("Heme late-phase", f"{heme_late} of {heme_ph}" if heme_ph else "—")
        c3.metric("Solid late-phase", f"{solid_late} of {solid_ph}" if solid_ph else "—")

        fig2_csv = phase_counts[["Phase", "Branch", "Trials"]].copy()
        _pub_caption(len(df_filt))
        st.download_button("Fig 2 data (CSV)",
                           _csv_with_provenance(fig2_csv, "Fig 2 — Phase distribution by branch"),
                           "fig2_phase_by_branch.csv", "text/csv")
    else:
        st.info("No phase data available.")

    # ------------------------------------------------------------------
    # Fig 3 — Geography, with Heme vs Solid split
    # ------------------------------------------------------------------
    _pub_header("3", "Global distribution of trial sites",
                "Country-level trial counts for the current filter. Panel 3b stratifies the top countries by branch when more than one branch is present.")

    def _country_branch_long(df_in: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df_in.iterrows():
            cs = str(r.get("Countries") or "")
            for c in cs.split("|"):
                c = c.strip()
                if c:
                    rows.append({"Country": c, "Branch": r["Branch"]})
        return pd.DataFrame(rows)

    geo_long = _country_branch_long(df_filt)
    if not geo_long.empty:
        geo_counts = (
            geo_long["Country"].value_counts().rename_axis("Country")
            .reset_index(name="Trials")
        )

        # Use ISO-3 codes — "country names" locationmode is deprecated.
        geo_counts_iso = geo_counts.copy()
        geo_counts_iso["ISO3"] = geo_counts_iso["Country"].map(_to_iso3)
        geo_counts_iso = geo_counts_iso.dropna(subset=["ISO3"])

        fig3_map = px.choropleth(
            geo_counts_iso, locations="ISO3", locationmode="ISO-3",
            color="Trials", hover_name="Country",
            color_continuous_scale=[[0, "#dce9f5"], [0.3, "#5aafd6"], [0.65, "#1c6faf"], [1, "#08306b"]],
            projection="natural earth", template="plotly_white",
        )
        fig3_map.update_layout(
            paper_bgcolor="white", plot_bgcolor="white",
            font=PUB_FONT, margin=dict(l=0, r=0, t=10, b=0),
            geo=dict(
                bgcolor="white", lakecolor="#ddeeff", landcolor="#eeeeee",
                showframe=False,
                showcoastlines=True, coastlinecolor="#999999", coastlinewidth=0.6,
                showcountries=True, countrycolor="#cccccc", countrywidth=0.4,
            ),
            coloraxis_colorbar=dict(
                title=dict(text="Trials", font=dict(size=11, color=_AX_COLOR)),
                tickfont=dict(size=10, color=_AX_COLOR),
                thickness=14, len=0.55, outlinewidth=0.5, outlinecolor="#aaaaaa",
            ),
        )
        st.plotly_chart(fig3_map, width='stretch', config=PUB_EXPORT)

        # 3b — Top 10 countries split by Branch
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">3b — Top 10 countries, stratified by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        top_countries = geo_counts.head(10)["Country"].tolist()
        country_branch = (
            geo_long[geo_long["Country"].isin(top_countries)]
            .groupby(["Country", "Branch"]).size().reset_index(name="Trials")
        )
        # Order by total
        order = geo_counts[geo_counts["Country"].isin(top_countries)].sort_values("Trials", ascending=True)["Country"].tolist()
        country_branch["Country"] = pd.Categorical(country_branch["Country"], categories=order, ordered=True)
        country_branch = country_branch.sort_values("Country")

        fig3_bar = px.bar(
            country_branch, x="Trials", y="Country", color="Branch",
            color_discrete_map=BRANCH_COLORS, orientation="h",
            template="plotly_white", height=420, text="Trials",
        )
        fig3_bar.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                               textfont=dict(size=10, color="white"), insidetextanchor="middle")
        fig3_bar.update_layout(
            **PUB_BASE,
            barmode="stack",
            xaxis_title="Number of trials", yaxis_title=None,
            margin=dict(l=120, r=56, t=24, b=130),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS,
            legend=dict(
                orientation="h", yanchor="top", y=-0.28, xanchor="center", x=0.5,
                font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                borderwidth=0, title=None,
            ),
        )
        st.plotly_chart(fig3_bar, width='stretch', config=PUB_EXPORT)

        total_geo = int(geo_counts["Trials"].sum())
        top3 = geo_counts.head(3)
        c1, c2, c3 = st.columns(3)
        for col, (_, row) in zip([c1, c2, c3], top3.iterrows()):
            col.metric(row["Country"], f"{row['Trials']} ({100*row['Trials']/total_geo:.0f}%)")

        fig3_csv = geo_counts.copy()
        fig3_csv["% of total"] = (fig3_csv["Trials"] / total_geo * 100).round(1)
        _pub_caption(len(df_filt),
                     extra="Multi-country trials are counted once per country.")
        st.download_button("Fig 3 data (CSV)",
                           _csv_with_provenance(fig3_csv, "Fig 3 — Geographic distribution"),
                           "fig3_geographic_distribution.csv", "text/csv")
    else:
        st.info("No country data available.")

    # ------------------------------------------------------------------
    # Fig 4 — Enrollment landscape with Heme/Solid stratification
    # ------------------------------------------------------------------
    _pub_header("4", "Trial enrollment landscape",
                "Distribution and median planned enrollment for the current filter, with subgroup panels by phase, disease category, branch and geography.")

    # Enrollment outlier handling: ClinicalTrials.gov lets registries and
    # real-world-data studies report absurd counts (e.g., 99,999,999 sentinel
    # for the CIBMTR database; 160,602 for a claims-data DLBCL cost study).
    # A prospective CAR-T trial tops out around ~800 patients (CARTITUDE).
    # We cap at 1,000 for the enrollment panels and report the exclusion.
    ENROLL_PLAUSIBLE_CAP = 1000

    df_enroll = df_filt.copy()
    df_enroll["EnrollmentCount"] = pd.to_numeric(df_enroll["EnrollmentCount"], errors="coerce")
    df_enroll_all = df_enroll.dropna(subset=["EnrollmentCount"]).copy()
    df_enroll_all["EnrollmentCount"] = df_enroll_all["EnrollmentCount"].astype(int)
    df_enroll_known = df_enroll_all[df_enroll_all["EnrollmentCount"] <= ENROLL_PLAUSIBLE_CAP].copy()
    n_excluded_outliers = len(df_enroll_all) - len(df_enroll_known)

    if len(df_enroll_known) >= 3:
        pct_known = 100 * len(df_enroll_known) / len(df_enroll)
        total_pts = int(df_enroll_known["EnrollmentCount"].sum())
        med_pts   = int(df_enroll_known["EnrollmentCount"].median())
        p25 = int(df_enroll_known["EnrollmentCount"].quantile(0.25))
        p75 = int(df_enroll_known["EnrollmentCount"].quantile(0.75))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trials with reported enrollment", f"{len(df_enroll_known)} ({pct_known:.0f}%)")
        c2.metric("Total enrolled patients", f"{total_pts:,}")
        c3.metric("Median enrollment", med_pts)
        c4.metric("IQR", f"{p25}–{p75}")

        if n_excluded_outliers > 0:
            st.caption(
                f"Note: {n_excluded_outliers} trial(s) with EnrollmentCount > {ENROLL_PLAUSIBLE_CAP:,} "
                "(registries, real-world-data studies, or sentinel values like 99,999,999) "
                "are excluded from the enrollment panels below but remain in all other analyses."
            )

        # 4a — Enrollment distribution split by Branch (overlaid)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">4a — Distribution of planned enrollment, by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        # Log-scale x-axis — enrollment is right-skewed (many 10–40 patient
        # dose-escalation trials, few 500+ Phase III). Linear axis crams the
        # bulk of trials at the left. Log-spaced bins + log axis spread the
        # distribution so every decade of enrollment size is legible.
        # 100%-stacked horizontal bar — each branch becomes one 0–100% bar
        # composed of five clinically-named size buckets in a sequential
        # navy ramp (light = small, dark = pivotal). Single chart, single
        # insight: reader sees trial-size composition AND compares branches
        # side-by-side without decoding a median / IQR / ECDF.
        _size_buckets = [
            ("Dose-escalation (≤ 20)",   0,   20),
            ("Small cohort (21–50)",    21,   50),
            ("Expansion (51–100)",      51,  100),
            ("Mid-size (101–300)",     101,  300),
            ("Pivotal (> 300)",        301, 10_000),
        ]
        # Single-hue sequential ramp — ordinal perception (small → large).
        _BUCKET_COLORS = {
            "Dose-escalation (≤ 20)":  "#dbeafe",  # blue-100
            "Small cohort (21–50)":    "#93c5fd",  # blue-300
            "Expansion (51–100)":      "#3b82f6",  # blue-500
            "Mid-size (101–300)":      "#1d4ed8",  # blue-700
            "Pivotal (> 300)":         "#0b3d91",  # primary navy
        }

        def _bucketise(series: pd.Series) -> dict[str, int]:
            out = {}
            for label, lo, hi in _size_buckets:
                out[label] = int(((series >= lo) & (series <= hi)).sum())
            return out

        _bar_rows = []
        _branch_meta = []   # for caption: median, n
        for _branch in ["Heme-onc", "Solid-onc"]:
            _vals = df_enroll_known[df_enroll_known["Branch"] == _branch]["EnrollmentCount"]
            if _vals.empty:
                continue
            _counts = _bucketise(_vals)
            _total = sum(_counts.values()) or 1
            for label, _, _ in _size_buckets:
                _bar_rows.append({
                    "Branch":          _branch,
                    "Enrollment size": label,
                    "Pct":             100 * _counts[label] / _total,
                    "Trials":          _counts[label],
                })
            _branch_meta.append(
                f"**{_branch}**: n={_total:,} · median {int(_vals.median())} patients"
            )
        _bar_df = pd.DataFrame(_bar_rows)

        if _bar_df.empty:
            st.info("No enrollment data for Heme-onc or Solid-onc under the current filter.")
        else:
            # Short summary strip above the chart so median / n are at hand
            st.markdown(" &nbsp;&nbsp;·&nbsp;&nbsp; ".join(_branch_meta))

            fig4a = px.bar(
                _bar_df,
                x="Pct", y="Branch",
                color="Enrollment size",
                color_discrete_map=_BUCKET_COLORS,
                orientation="h",
                template="plotly_white",
                category_orders={
                    "Branch":          ["Solid-onc", "Heme-onc"],   # Heme on top visually
                    "Enrollment size": [b[0] for b in _size_buckets],
                },
                text="Pct",
                custom_data=["Trials", "Enrollment size"],
                height=240,
            )
            fig4a.update_traces(
                texttemplate="%{text:.0f}%",
                textposition="inside",
                textfont=dict(size=11, color="white"),
                insidetextanchor="middle",
                marker_line_width=0,
                hovertemplate=(
                    "%{y} · %{customdata[1]}<br>"
                    "%{customdata[0]} trials (%{x:.1f}%)<extra></extra>"
                ),
            )
            fig4a.update_layout(
                **PUB_BASE,
                barmode="stack",
                # Bottom margin needs to fit: x-ticks + tick labels ("0%"…
                # "100%") + horizontal legend stack. At y=-0.18 the legend
                # landed on the same visual row as the tick labels; push
                # it further down with a matching bottom margin bump.
                margin=dict(l=100, r=24, t=16, b=110),
                xaxis=dict(
                    title=None,
                    range=[0, 100],
                    ticksuffix="%",
                    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                    ticks="outside", ticklen=6, tickwidth=1.2,
                    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                    zeroline=False,
                ),
                yaxis=dict(
                    title=None,
                    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                    ticks="outside", ticklen=4, tickwidth=1.2,
                    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                ),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.35,
                    xanchor="center", x=0.5,
                    font=dict(size=10, color=_AX_COLOR),
                    bgcolor="rgba(0,0,0,0)", borderwidth=0, title=None,
                    traceorder="normal",
                ),
            )
            st.plotly_chart(fig4a, width='stretch', config=PUB_EXPORT)
            st.caption(
                "Each bar totals 100%. Size buckets reflect standard CAR-T trial "
                "archetypes (dose-escalation → pivotal). Mixed and Unknown branches "
                "excluded; their enrollment data is preserved in the CSV export."
            )

        # 4b — Median enrollment by phase × branch
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">4b — Median enrollment by phase and branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        _phb_enroll = (
            df_enroll_known.groupby(["PhaseNormalized", "Branch"], observed=False)["EnrollmentCount"]
            .median().reset_index(name="Median")
        )
        _phb_enroll = _phb_enroll[_phb_enroll["Median"].notna()].copy()
        _phb_enroll["Median"] = _phb_enroll["Median"].astype(int)
        _phb_enroll["Phase"] = _phb_enroll["PhaseNormalized"].map(PHASE_LABELS)
        _phb_enroll["Phase"] = pd.Categorical(
            _phb_enroll["Phase"], categories=[PHASE_LABELS[p] for p in PHASE_ORDER], ordered=True,
        )
        _phb_enroll = _phb_enroll.sort_values("Phase")

        fig4b = px.bar(
            _phb_enroll, x="Phase", y="Median", color="Branch",
            color_discrete_map=BRANCH_COLORS, barmode="group",
            template="plotly_white", height=380, text="Median",
        )
        fig4b.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                            textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
        fig4b.update_layout(
            **PUB_LAYOUT,
            xaxis_title="Phase",
            yaxis_title="Median planned enrollment (patients)",
            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig4b, width='stretch', config=PUB_EXPORT)

        # 4c — Total enrolled patients by disease category
        _dis_enroll_rows = []
        for _, row in df_enroll_known.iterrows():
            _dis_enroll_rows.append({
                "Category": row.get("DiseaseCategory", UNCLASSIFIED_LABEL),
                "Branch": row.get("Branch", "Unknown"),
                "Enrollment": row["EnrollmentCount"],
            })
        if _dis_enroll_rows:
            _dis_enroll_df = pd.DataFrame(_dis_enroll_rows)
            _dis_enroll_agg = (
                _dis_enroll_df.groupby(["Category", "Branch"])["Enrollment"]
                .agg(TotalEnrolled="sum", Trials="count").reset_index()
                .sort_values("TotalEnrolled", ascending=True)
            )
            _dis_enroll_agg["TotalEnrolled"] = _dis_enroll_agg["TotalEnrolled"].astype(int)

            st.markdown(
                '<div class="pub-fig-sub" style="margin-top: 1rem; '
                'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
                '<strong style="color: #0b1220;">4c — Total planned enrollment by disease category</strong>'
                '</div>',
                unsafe_allow_html=True,
            )
            _cat_order = (
                _dis_enroll_agg.groupby("Category")["TotalEnrolled"].sum()
                .sort_values(ascending=True).index.tolist()
            )
            _dis_enroll_agg["Category"] = pd.Categorical(
                _dis_enroll_agg["Category"], categories=_cat_order, ordered=True,
            )
            fig4c = px.bar(
                _dis_enroll_agg.sort_values("Category"),
                x="TotalEnrolled", y="Category", color="Branch",
                color_discrete_map=BRANCH_COLORS, orientation="h",
                height=max(380, len(_cat_order) * 26 + 100),
                template="plotly_white", text="TotalEnrolled",
            )
            fig4c.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                                textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
            fig4c.update_layout(
                **PUB_BASE, barmode="stack",
                xaxis_title="Total planned patients (reported trials)",
                yaxis_title=None, showlegend=True,
                margin=dict(l=155, r=72, t=24, b=130),
                yaxis=_H_YAXIS, xaxis=_H_XAXIS,
                legend=dict(orientation="h", yanchor="top", y=-0.28, xanchor="center", x=0.5,
                            font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                            borderwidth=0, title=None),
            )
            st.plotly_chart(fig4c, width='stretch', config=PUB_EXPORT)

        # Fig 4d (forest plot by subgroup) was removed — 4a/4b/4c already
        # cover the enrollment landscape cleanly, and once a user filter
        # collapsed one axis the forest-plot rows duplicated each other.

        # Tag every trial with a GeoGroup label so the CSV export below
        # still carries the China / Non-China stratification.
        def _geo_group(countries_str) -> str:
            if not countries_str or pd.isna(countries_str):
                return "Unknown"
            return "China" if "China" in str(countries_str).split("|") else "Non-China"
        df_enroll_known["GeoGroup"] = df_enroll_known["Countries"].apply(_geo_group)

        fig4_csv = df_enroll_known[[
            "NCTId", "BriefTitle", "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "Phase", "EnrollmentCount", "GeoGroup",
            "SponsorType",
        ]].sort_values("EnrollmentCount", ascending=False)
        _pub_caption(len(df_filt),
                     extra=f"Enrollment panels restricted to {len(df_enroll_known):,} trials with a numeric enrollment target.")
        st.download_button("Fig 4 data (CSV)",
                           _csv_with_provenance(fig4_csv, "Fig 4 — Enrollment by branch / phase / category"),
                           "fig4_enrollment.csv", "text/csv")
    else:
        st.info("Insufficient enrollment data available.")

    # ------------------------------------------------------------------
    # Fig 5 — Branch → Category → Entity sunburst (signature oncology figure)
    # ------------------------------------------------------------------
    _pub_header("5", "Disease hierarchy (Branch → Category → Entity)",
                "Sunburst of Branch → Category → Entity for trials in the current filter. Click a wedge to zoom.")

    if not df_filt.empty:
        sun_df = (
            df_filt[["Branch", "DiseaseCategory", "DiseaseEntity"]]
            .fillna("Unknown").assign(Count=1)
            .groupby(["Branch", "DiseaseCategory", "DiseaseEntity"], as_index=False).sum()
        )
        fig5 = px.sunburst(
            sun_df, path=["Branch", "DiseaseCategory", "DiseaseEntity"],
            values="Count", color="Branch", color_discrete_map=BRANCH_COLORS,
            height=600, template="plotly_white",
        )
        fig5.update_traces(
            insidetextorientation="radial",
            marker=dict(line=dict(color="white", width=1.2)),
        )
        fig5.update_layout(
            paper_bgcolor="white", plot_bgcolor="white",
            margin=dict(l=8, r=8, t=8, b=8), font=PUB_FONT,
        )
        st.plotly_chart(fig5, width='stretch', config=PUB_EXPORT)

        # Companion: top categories side-by-side
        c1, c2 = st.columns(2)
        with c1:
            heme_cat = (
                df_filt[df_filt["Branch"] == "Heme-onc"]["DiseaseCategory"]
                .value_counts().head(10).reset_index()
            )
            heme_cat.columns = ["Category", "Trials"]
            if not heme_cat.empty:
                st.markdown("**Top heme-onc categories**")
                st.plotly_chart(make_bar(heme_cat.sort_values("Trials", ascending=True),
                                          "Trials", "Category", height=320, color=HEME_COLOR).update_traces(orientation="h"),
                                width='stretch')
        with c2:
            solid_cat = (
                df_filt[df_filt["Branch"] == "Solid-onc"]["DiseaseCategory"]
                .value_counts().head(10).reset_index()
            )
            solid_cat.columns = ["Category", "Trials"]
            if not solid_cat.empty:
                st.markdown("**Top solid-onc categories**")
                st.plotly_chart(make_bar(solid_cat.sort_values("Trials", ascending=True),
                                          "Trials", "Category", height=320, color=SOLID_COLOR).update_traces(orientation="h"),
                                width='stretch')

        _pub_caption(len(df_filt),
                     extra="Basket/Multidisease trials are shown as their own category slice under the inferred branch.")
        st.download_button("Fig 5 data (CSV)",
                           _csv_with_provenance(sun_df, "Fig 5 — Disease hierarchy"),
                           "fig5_disease_hierarchy.csv", "text/csv")
    else:
        st.info("No disease data available.")

    # ------------------------------------------------------------------
    # Fig 6 — Heme vs Solid antigen panels (side-by-side)
    # ------------------------------------------------------------------
    _pub_header("6", "Antigen target landscape, heme vs solid",
                "Top antigens among trials in the current filter. Heme-onc and solid-onc panels render when each has data. Long tail of low-count antigens aggregated as 'Other (N antigens)'.")

    _UNCLEAR_BUCKET = "Undisclosed / unclear"

    def _target_counts(df_in: pd.DataFrame, include_unclear: bool = False) -> pd.DataFrame:
        s = df_in.loc[~df_in["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"].fillna("Unknown")
        s = s.replace({
            "CAR-T_unspecified": _UNCLEAR_BUCKET,
            "Other_or_unknown":  _UNCLEAR_BUCKET,
            "Unknown":           _UNCLEAR_BUCKET,
        })
        if not include_unclear:
            s = s[s != _UNCLEAR_BUCKET]
        return s.value_counts().rename_axis("Target").reset_index(name="Trials")

    heme_tgt = _target_counts(df_filt[df_filt["Branch"] == "Heme-onc"])
    solid_tgt = _target_counts(df_filt[df_filt["Branch"] == "Solid-onc"])

    col_h, col_s = st.columns(2)

    def _top_n_with_other(df_in: pd.DataFrame, n: int = 15) -> pd.DataFrame:
        """Keep the top-n targets by trial count; aggregate the rest into an
        'Other (k antigens)' row so the long tail doesn't crowd the chart."""
        if len(df_in) <= n:
            return df_in.sort_values("Trials", ascending=False)
        top = df_in.sort_values("Trials", ascending=False).head(n)
        tail = df_in.sort_values("Trials", ascending=False).iloc[n:]
        tail_total = int(tail["Trials"].sum())
        tail_row = pd.DataFrame([{
            "Target": f"Other ({len(tail)} antigens)",
            "Trials": tail_total,
        }])
        return pd.concat([top, tail_row], ignore_index=True)

    def _target_hbar(df_in, color, title, height):
        df_in = _top_n_with_other(df_in, n=15)
        # For a horizontal bar chart the largest value should sit at the top —
        # Plotly renders y-categories bottom-up, so sort ascending *after*
        # truncation (NOT before, which caused CD19 to be dropped entirely).
        df_in = df_in.sort_values("Trials", ascending=True)
        fig = px.bar(
            df_in, x="Trials", y="Target", orientation="h",
            color_discrete_sequence=[color], template="plotly_white",
            height=max(height, len(df_in) * 28 + 80), text="Trials",
        )
        fig.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                          textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
        fig.update_layout(
            **PUB_BASE,
            xaxis_title="Number of trials", yaxis_title=None, showlegend=False,
            margin=dict(l=170, r=48, t=40, b=56),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS, title=dict(text=title, x=0, font=dict(size=12, color=_AX_COLOR)),
        )
        return fig

    with col_h:
        if not heme_tgt.empty:
            st.plotly_chart(_target_hbar(heme_tgt, HEME_COLOR, "Heme-onc targets", 380),
                            width='stretch', config=PUB_EXPORT)
        else:
            st.info("No heme-onc trials in filter.")
    with col_s:
        if not solid_tgt.empty:
            st.plotly_chart(_target_hbar(solid_tgt, SOLID_COLOR, "Solid-onc targets", 380),
                            width='stretch', config=PUB_EXPORT)
        else:
            st.info("No solid-onc trials in filter.")

    # Summary metrics (based on disclosed antigens only — unclear excluded)
    total_h = int(heme_tgt["Trials"].sum()) if not heme_tgt.empty else 0
    total_s = int(solid_tgt["Trials"].sum()) if not solid_tgt.empty else 0
    cd19_h = int(heme_tgt.loc[heme_tgt["Target"] == "CD19", "Trials"].sum()) if not heme_tgt.empty else 0
    bcma_h = int(heme_tgt.loc[heme_tgt["Target"] == "BCMA", "Trials"].sum()) if not heme_tgt.empty else 0
    # iloc[0] = largest (value_counts returns descending order)
    top_s = solid_tgt.iloc[0] if not solid_tgt.empty else None
    solid_diverse = solid_tgt["Target"].nunique() if not solid_tgt.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Heme CD19", f"{cd19_h} ({100*cd19_h/total_h:.0f}%)" if total_h else "—")
    c2.metric("Heme BCMA", f"{bcma_h} ({100*bcma_h/total_h:.0f}%)" if total_h else "—")
    c3.metric("Solid top antigen", f"{top_s['Target']} ({top_s['Trials']})" if top_s is not None else "—")
    c4.metric("Distinct solid antigens", solid_diverse)

    # ------------------------------------------------------------------
    # Approved-product overlay panel — onc-only (rheum has zero approvals).
    # Shows the reader where the field is past validation vs still
    # exploratory. The "approved antigen plus N follow-on trials"
    # pattern is itself an insight: approval doesn't close research,
    # it opens a new wave of refinements.
    # ------------------------------------------------------------------
    _approved_targets = sorted({p["target"] for p in APPROVED_PRODUCTS
                                 if p.get("target")})
    _approval_rows = []
    for tgt in _approved_targets:
        fda_n = sum(
            1 for p in APPROVED_PRODUCTS
            if p["target"] == tgt and p["regulator"] == "FDA"
        )
        ema_n = sum(
            1 for p in APPROVED_PRODUCTS
            if p["target"] == tgt and p["regulator"] == "EMA"
        )
        nmpa_n = sum(
            1 for p in APPROVED_PRODUCTS
            if p["target"] == tgt and p["regulator"] == "NMPA"
        )
        # Current ongoing trial counts (from the filtered data — respects sidebar)
        current_h = int(heme_tgt.loc[heme_tgt["Target"] == tgt, "Trials"].sum()) if not heme_tgt.empty else 0
        current_s = int(solid_tgt.loc[solid_tgt["Target"] == tgt, "Trials"].sum()) if not solid_tgt.empty else 0
        # Earliest approval year for context
        first_year = min(
            (p["year"] for p in APPROVED_PRODUCTS if p["target"] == tgt),
            default=None,
        )
        _approval_rows.append({
            "Antigen": tgt,
            "First approval": first_year,
            "FDA": fda_n,
            "EMA": ema_n,
            "NMPA": nmpa_n,
            "Trials in current view": current_h + current_s,
        })

    if _approval_rows:
        st.markdown(
            '<div class="pub-fig-caption" style="margin-top: 1rem;">'
            '<b>Approved CAR-T products by antigen.</b> '
            'CD19 and BCMA are the only antigens with regulatory '
            'approval to date (last reviewed '
            f'{APPROVED_PRODUCTS_LAST_REVIEWED}). Trial counts in the '
            'rightmost column reflect the current sidebar filter — '
            'ongoing investigation continues in earlier-line, '
            'longer-follow-up, and head-to-head settings well after '
            'first approval.'
            '</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            pd.DataFrame(_approval_rows),
            hide_index=True, width="stretch",
            column_config={
                "First approval": st.column_config.NumberColumn(
                    "First approval", format="%d",
                    help="Earliest approval year across all regulators.",
                ),
                "FDA": st.column_config.NumberColumn(
                    "FDA approvals", format="%d",
                ),
                "EMA": st.column_config.NumberColumn(
                    "EMA approvals", format="%d",
                ),
                "NMPA": st.column_config.NumberColumn(
                    "NMPA approvals", format="%d",
                ),
                "Trials in current view": st.column_config.NumberColumn(
                    "Trials in current view", format="%d",
                    help="Total ongoing CAR-T trials targeting this "
                         "antigen in the currently-filtered cohort.",
                ),
            },
        )

    fig6_csv = pd.concat(
        [heme_tgt.assign(Branch="Heme-onc"), solid_tgt.assign(Branch="Solid-onc")],
        ignore_index=True,
    ) if (not heme_tgt.empty or not solid_tgt.empty) else pd.DataFrame()
    _pub_caption(len(df_filt),
                 extra="Undisclosed / unclear merges CAR-T_unspecified and Other_or_unknown; both preserved in CSV.")
    if not fig6_csv.empty:
        st.download_button("Fig 6 data (CSV)",
                           _csv_with_provenance(fig6_csv, "Fig 6 — Antigen targets by branch"),
                           "fig6_targets_by_branch.csv", "text/csv")

    # ------------------------------------------------------------------
    # Fig 7 — Innovation signals (product type + modality over time)
    # ------------------------------------------------------------------
    _pub_header("7", "Innovation signals — product type and cell-therapy modality",
                "Trial composition over time, by manufacturing approach (autologous / allogeneic / in vivo) and by cell-therapy platform.")

    df_innov = df_filt[df_filt["StartYear"].notna()].copy()
    df_innov["StartYear"] = df_innov["StartYear"].astype(int)

    if not df_innov.empty:
        # Modality is already baked into df by _post_process_trials (via the
        # vectorised path), so df_innov inherits the column — no per-rerun
        # row-wise apply needed.

        # 7a — Modality by branch (renumbered from former 7b)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">7a — Cell-therapy modality distribution, by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        mod_branch = (
            df_innov.groupby(["Modality", "Branch"]).size().reset_index(name="Trials")
        )
        mod_branch["Modality"] = pd.Categorical(mod_branch["Modality"], categories=MODALITY_ORDER, ordered=True)
        mod_branch = mod_branch.sort_values("Modality")
        fig7b = px.bar(
            mod_branch, x="Trials", y="Modality", color="Branch",
            color_discrete_map=BRANCH_COLORS, orientation="h",
            template="plotly_white",
            height=max(340, len(mod_branch["Modality"].unique()) * 44 + 160),
            text="Trials",
        )
        fig7b.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                            textfont=dict(size=10, color="white"), insidetextanchor="middle")
        fig7b.update_layout(
            **PUB_BASE, barmode="stack",
            xaxis_title="Number of trials", yaxis_title=None,
            margin=dict(l=120, r=56, t=24, b=130),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS,
            legend=dict(orientation="h", yanchor="top", y=-0.32, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig7b, width='stretch', config=PUB_EXPORT)

        # 7b — Modality mix by start year (renumbered from former 7c)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">7b — Modality mix by start year</strong>'
            '</div>',
            unsafe_allow_html=True,
        )

        # Data prep (outside the fragment) — runs once per script rerun, i.e.
        # when filters change. The pill toggle inside the fragment reruns only
        # this fragment when clicked, so the groupby isn't recomputed.
        _mod_year_raw = (
            df_innov.groupby(["StartYear", "Modality"]).size().reset_index(name="Trials")
        )
        _present_mods = [m for m in MODALITY_ORDER if m in _mod_year_raw["Modality"].unique()]
        _mod_year_raw = _mod_year_raw[_mod_year_raw["Modality"].isin(_present_mods)].copy()

        @st.fragment
        def _render_fig7b(mod_year_base: pd.DataFrame) -> None:
            # Small pill toggle — fragment rerun scope means clicking this
            # pill does NOT re-run the rest of the publication figures tab.
            _c7b_1, _c7b_2 = st.columns([0.30, 0.70])
            with _c7b_1:
                _mod_mode = st.pills(
                    "Y-axis mode",
                    options=["Absolute", "% share"],
                    default="Absolute",
                    key="fig7b_mode",
                    label_visibility="collapsed",
                ) or "Absolute"
            _is_pct = (_mod_mode == "% share")
            mod_year = mod_year_base.copy()

            if _is_pct:
                mod_year["Value"] = (
                    mod_year["Trials"]
                    / mod_year.groupby("StartYear")["Trials"].transform("sum")
                    * 100
                )
                _y_col = "Value"
                _y_title = "% share of trials"
                _hover_value = "%{y:.1f}%"
                _y_axis_kwargs = dict(ticksuffix="%", range=[0, 100])
            else:
                _y_col = "Trials"
                _y_title = "Number of trials"
                _hover_value = "%{y}"
                _y_axis_kwargs = dict()

            fig7c = px.bar(
                mod_year,
                x="StartYear", y=_y_col, color="Modality",
                barmode="stack", height=400, template="plotly_white",
                color_discrete_map=_MODALITY_COLORS,
                category_orders={"Modality": MODALITY_ORDER},
                labels={"StartYear": "Start year", _y_col: _y_title},
                custom_data=["Modality", "Trials"],
            )
            fig7c.update_traces(
                marker_line_width=0, opacity=1,
                hovertemplate=(
                    "%{x}<br><b>%{customdata[0]}</b><br>"
                    + _hover_value
                    + " · %{customdata[1]} trials<extra></extra>"
                ),
            )
            fig7c.update_layout(
                **PUB_BASE,
                margin=dict(l=64, r=36, t=24, b=110),
                xaxis=dict(
                    tickmode="linear", dtick=1, tickformat="d", showgrid=False,
                    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                    ticks="outside", ticklen=6, tickwidth=1.2,
                    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                    title="Start year", title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                ),
                yaxis=dict(
                    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                    ticks="outside", ticklen=6, tickwidth=1.2,
                    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                    title=_y_title,
                    title_font=dict(size=_LAB_SZ, color=_AX_COLOR), zeroline=False,
                    **_y_axis_kwargs,
                ),
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                            font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                            borderwidth=0, title=None),
            )
            _f7c_first = _first_meaningful_year(mod_year, count_col="Trials") or int(mod_year["StartYear"].min())
            _f7c_last = int(mod_year["StartYear"].max())
            fig7c.update_xaxes(range=[_f7c_first - 0.5, _f7c_last + 0.5])
            st.plotly_chart(fig7c, width='stretch', config=PUB_EXPORT)

        _render_fig7b(_mod_year_raw)

        total_prod = len(df_innov)
        auto_n = int((df_innov["ProductType"] == "Autologous").sum())
        allo_n = int((df_innov["ProductType"] == "Allogeneic/Off-the-shelf").sum())
        invivo_n = int((df_innov["Modality"] == "In vivo CAR").sum())
        carnk_n = int((df_innov["Modality"] == "CAR-NK").sum())
        gdt_n = int((df_innov["Modality"] == "CAR-γδ T").sum())
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Autologous", f"{auto_n} ({100*auto_n/total_prod:.0f}%)" if total_prod else "—")
        c2.metric("Allogeneic", f"{allo_n} ({100*allo_n/total_prod:.0f}%)" if total_prod else "—")
        c3.metric("CAR-NK", f"{carnk_n} ({100*carnk_n/total_prod:.0f}%)" if total_prod else "—")
        c4.metric("CAR-γδ T", f"{gdt_n} ({100*gdt_n/total_prod:.0f}%)" if total_prod else "—")
        c5.metric("In vivo CAR", f"{invivo_n} ({100*invivo_n/total_prod:.0f}%)" if total_prod else "—")

        # CSV export keeps both cuts (product type and modality) available
        # for downstream analysis, even though the figure only renders modality.
        _product_year = (
            df_innov.groupby(["StartYear", "ProductType"]).size().reset_index(name="n_product")
        )
        fig7_csv = pd.merge(
            _product_year.rename(columns={"ProductType": "Category"}),
            df_innov.groupby(["StartYear", "Modality"]).size().reset_index(name="n_modality"),
            left_on="StartYear", right_on="StartYear", how="outer",
        )
        _pub_caption(len(df_filt),
                     extra="Panel counts restricted to trials with a known start year.")
        st.download_button("Fig 7 data (CSV)",
                           _csv_with_provenance(fig7_csv, "Fig 7 — Innovation signals"),
                           "fig7_innovation_signals.csv", "text/csv")
    else:
        st.info("No start year data available for innovation analysis.")

    # ------------------------------------------------------------------
    # Fig 8 — Disease × Target heatmap (oncology-specific signature)
    # ------------------------------------------------------------------
    _pub_header("8", "Disease × antigen target heatmap",
                "Trial counts per (category, antigen) pair in the current filter. Up to the top 15 categories × top 18 antigens are shown; undisclosed-antigen trials are excluded from the matrix.")

    # Build disease-target matrix (top N of each for readability)
    hm_df = df_filt.copy()
    hm_df = hm_df[~hm_df["TargetCategory"].isin(_PLATFORM_LABELS)]
    hm_df["DisplayTarget"] = hm_df["TargetCategory"].replace({
        "CAR-T_unspecified": "Undisclosed",
        "Other_or_unknown":  "Undisclosed",
    })

    top_cats_hm = (
        hm_df["DiseaseCategory"].value_counts().head(15).index.tolist()
    )
    top_tgts_hm = (
        hm_df.loc[hm_df["DisplayTarget"] != "Undisclosed", "DisplayTarget"]
        .value_counts().head(18).index.tolist()
    )

    if top_cats_hm and top_tgts_hm:
        pivot = (
            hm_df[hm_df["DiseaseCategory"].isin(top_cats_hm) & hm_df["DisplayTarget"].isin(top_tgts_hm)]
            .groupby(["DiseaseCategory", "DisplayTarget"]).size().unstack(fill_value=0)
            .reindex(index=top_cats_hm, columns=top_tgts_hm, fill_value=0)
        )
        # Annotate branch by color-coding row labels
        row_colors = [
            BRANCH_COLORS["Heme-onc"] if c in HEME_CATEGORIES else
            BRANCH_COLORS["Solid-onc"] if c in SOLID_CATEGORIES else
            BRANCH_COLORS["Mixed"]
            for c in top_cats_hm
        ]

        # Sparse-matrix treatment: render zero-trial cells as white (NaN
        # masked out of z so plotly skips them) and only label cells that
        # actually have data. This is the standard publication idiom for
        # sparse heatmaps — the colour scale stays clean for the signal,
        # and the empty quadrants (heme antigens × solid categories etc.)
        # become pre-attentively obvious as the headline finding.
        _z_dense = pivot.values.astype(float)
        _z_masked = np.where(_z_dense == 0, np.nan, _z_dense)
        _text_masked = np.where(_z_dense == 0, "", _z_dense.astype(int).astype(str))

        fig8 = go.Figure(data=go.Heatmap(
            z=_z_masked,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            text=_text_masked,
            texttemplate="%{text}",
            textfont=dict(size=10, color="#0b1220"),
            colorscale=[[0, "#dbeafe"], [0.4, "#93c5fd"], [0.7, "#1d4ed8"], [1, "#0b3d91"]],
            colorbar=dict(title=dict(text="Trials", font=dict(size=11, color=_AX_COLOR)),
                           tickfont=dict(size=10, color=_AX_COLOR), thickness=14, len=0.55),
            hovertemplate="Category: %{y}<br>Target: %{x}<br>Trials: %{z}<extra></extra>",
            hoverongaps=False,
        ))
        fig8.update_layout(
            **PUB_BASE,
            height=max(420, len(top_cats_hm) * 28 + 120),
            margin=dict(l=170, r=40, t=40, b=100),
            xaxis=dict(
                title="Antigen target",
                tickfont=dict(size=11, color=_AX_COLOR),
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                tickangle=-35, side="bottom",
            ),
            yaxis=dict(
                title="Disease category",
                tickfont=dict(size=11, color=_AX_COLOR),
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                autorange="reversed",
            ),
        )
        # Color-code the y-axis tick labels by branch (via annotations behind y-axis)
        # Plotly doesn't natively support per-tick-label colors, so we emulate with annotations.
        st.plotly_chart(fig8, width='stretch', config=PUB_EXPORT)

        st.markdown(
            '<div class="pub-fig-caption" style="margin-top: 0.1rem;">'
            '<b>White cells = no trials</b> (every shaded cell is labelled with its count). '
            f'Up to the top {len(top_cats_hm)} categor'
            f"{'y' if len(top_cats_hm) == 1 else 'ies'} × top "
            f"{len(top_tgts_hm)} antigen{'s' if len(top_tgts_hm) != 1 else ''} shown."
            '</div>',
            unsafe_allow_html=True,
        )
        _pub_caption(len(df_filt))

        fig8_csv = pivot.reset_index().melt(
            id_vars="DiseaseCategory", var_name="Target", value_name="Trials"
        )
        fig8_csv = fig8_csv[fig8_csv["Trials"] > 0]
        st.download_button("Fig 8 data (CSV)",
                           _csv_with_provenance(fig8_csv, "Fig 8 — Disease × target heatmap"),
                           "fig8_disease_target_heatmap.csv", "text/csv")
    else:
        st.info("Insufficient disease-target data for heatmap.")

    # ---------------------------------------------------------------------------
    # FIG 9 — Antigen × Branch heatmap with phase encoding
    # ---------------------------------------------------------------------------
    # Three-row × N-antigen matrix (Heme / Solid / Mixed). Cell value = trial
    # count; cell text = "N · ph X" where X is the furthest phase reached.
    # Designed to answer the question Fig 8 only hints at via row-coloring:
    # "which antigens are heme-restricted, which are solid-restricted, which
    # cross both branches".
    #
    # Pipeline-unique because it requires the closed-vocab antigen list AND
    # the binary heme/solid Branch split AND the ordinal Phase mapping.

    _pub_header(
        "9", "Antigen × Branch matrix with phase encoding",
        "Trial counts per (antigen × branch) cell in the current filter, "
        "annotated with the furthest phase reached. Shows which antigens "
        "are restricted to heme, restricted to solid, or crossing both "
        "branches. Antigens sorted by total trial count; platform labels "
        "(CAR-NK / CAR-Treg / CAAR-T / CAR-γδ T) excluded so the matrix "
        "shows specific antigens only.",
    )

    # Build the matrix
    _ab_df = df_filt.copy()
    _ab_df = _ab_df[~_ab_df["TargetCategory"].isin(_PLATFORM_LABELS)]
    _ab_df = _ab_df[~_ab_df["TargetCategory"].isin(
        ["CAR-T_unspecified", "Other_or_unknown"]
    )]
    if _ab_df.empty:
        st.info("Insufficient antigen-branch data for heatmap.")
    else:
        _branch_order = ["Heme-onc", "Solid-onc", "Mixed"]
        _ab_df = _ab_df[_ab_df["Branch"].isin(_branch_order)]
        # Top-N antigens by total trial count
        _top_ab_targets = (
            _ab_df["TargetCategory"].value_counts().head(25).index.tolist()
        )
        _ab_df = _ab_df[_ab_df["TargetCategory"].isin(_top_ab_targets)]

        # Pivot for trial counts
        _ab_counts = (
            _ab_df.groupby(["Branch", "TargetCategory"], observed=True)
            .size().unstack(fill_value=0)
            .reindex(index=_branch_order, columns=_top_ab_targets, fill_value=0)
        )
        # Furthest phase per (Branch, TargetCategory) — used for cell labels
        _phase_rank = {p: i for i, p in enumerate(PHASE_ORDER) if p != "Unknown"}
        def _max_phase(grp: pd.DataFrame) -> str:
            ranks = [_phase_rank.get(p, -1) for p in grp["PhaseNormalized"]]
            valid = [r for r in ranks if r >= 0]
            if not valid:
                return ""
            top = max(valid)
            for p, r in _phase_rank.items():
                if r == top:
                    return PHASE_LABELS.get(p, p).replace("Phase ", "ph ")
            return ""
        _phase_pivot = (
            _ab_df.groupby(["Branch", "TargetCategory"], observed=True)
            .apply(_max_phase, include_groups=False)
            .unstack(fill_value="")
            .reindex(index=_branch_order, columns=_top_ab_targets, fill_value="")
        )

        # Cell text: "N · ph X" (omit phase if N == 0)
        _ab_text = np.empty_like(_ab_counts.values, dtype=object)
        for i in range(_ab_counts.shape[0]):
            for j in range(_ab_counts.shape[1]):
                n = int(_ab_counts.iat[i, j])
                ph = _phase_pivot.iat[i, j]
                if n == 0:
                    _ab_text[i, j] = ""
                elif ph:
                    _ab_text[i, j] = f"{n}<br><span style='font-size:9px'>{ph}</span>"
                else:
                    _ab_text[i, j] = str(n)

        _z = _ab_counts.values.astype(float)
        _z_masked = np.where(_z == 0, np.nan, _z)

        fig9 = go.Figure(data=go.Heatmap(
            z=_z_masked,
            x=_top_ab_targets,
            y=_branch_order,
            text=_ab_text,
            texttemplate="%{text}",
            textfont=dict(size=11, color="#0b1220"),
            colorscale=[[0, "#dbeafe"], [0.4, "#93c5fd"],
                         [0.7, "#1d4ed8"], [1, "#0b3d91"]],
            colorbar=dict(
                title=dict(text="Trials", font=dict(size=11, color=_AX_COLOR)),
                tickfont=dict(size=10, color=_AX_COLOR),
                thickness=14, len=0.55,
            ),
            hovertemplate="Branch: %{y}<br>Antigen: %{x}<br>Trials: %{z}<extra></extra>",
            hoverongaps=False,
        ))
        fig9.update_layout(
            **PUB_BASE,
            height=320,
            margin=dict(l=110, r=40, t=40, b=120),
            xaxis=dict(
                tickangle=-45, tickfont=dict(size=11, color=_AX_COLOR),
                showgrid=False,
            ),
            yaxis=dict(
                tickfont=dict(size=12, color=_AX_COLOR), showgrid=False,
            ),
        )
        st.plotly_chart(fig9, width="stretch", config=PUB_EXPORT)

        # Quick summary callout — "X heme-locked / Y solid-locked / Z crossing"
        _heme_locked = []
        _solid_locked = []
        _crossing = []
        for tgt in _top_ab_targets:
            heme_n = int(_ab_counts.at["Heme-onc", tgt])
            solid_n = int(_ab_counts.at["Solid-onc", tgt])
            mixed_n = int(_ab_counts.at["Mixed", tgt]) if "Mixed" in _ab_counts.index else 0
            if heme_n > 0 and solid_n == 0 and mixed_n == 0:
                _heme_locked.append(tgt)
            elif solid_n > 0 and heme_n == 0 and mixed_n == 0:
                _solid_locked.append(tgt)
            elif heme_n > 0 and solid_n > 0:
                _crossing.append(tgt)

        st.markdown(
            '<div class="pub-fig-caption" style="margin-top: 0.1rem;">'
            '<b>White cells = no trials</b> (every shaded cell labelled with '
            'count and furthest phase reached). '
            f'Heme-restricted antigens (top 25): {", ".join(_heme_locked) or "—"}. '
            f'Solid-restricted antigens: {", ".join(_solid_locked) or "—"}. '
            f'Crossing both branches: {", ".join(_crossing) or "—"}.'
            '</div>',
            unsafe_allow_html=True,
        )
        _pub_caption(len(df_filt))

        # CSV export
        _fig9_csv = (
            _ab_counts.reset_index().melt(
                id_vars="Branch", var_name="Antigen", value_name="Trials",
            )
        )
        _fig9_csv = _fig9_csv[_fig9_csv["Trials"] > 0]
        # Add furthest phase as a column
        _fig9_csv["FurthestPhase"] = _fig9_csv.apply(
            lambda r: _phase_pivot.at[r["Branch"], r["Antigen"]],
            axis=1,
        )
        st.download_button(
            "Fig 9 data (CSV)",
            _csv_with_provenance(_fig9_csv, "Fig 9 — Antigen × Branch matrix"),
            "fig9_antigen_branch_matrix.csv", "text/csv",
        )

    # ---------------------------------------------------------------------------
    # FIG 10 — Solid-tumour antigen timeline
    # ---------------------------------------------------------------------------
    # Strip plot, x = StartYear of first CAR-T trial in onc using that
    # (antigen, solid-disease-category) pair, y = antigen sorted by year of
    # first appearance. Faceted by solid-tumour DiseaseCategory. Tracks the
    # field's expansion frontier — when each antigen × indication barrier fell.
    #
    # Pipeline-unique: requires the closed-vocab antigen list × Tier-3 disease
    # entity × StartYear, joined into a "first appearance per (antigen,
    # category)" matrix. The editorial-grade narrative ("the field crossed
    # each barrier in this order") that nothing else can produce.

    _pub_header(
        "10", "Solid-tumour antigen × indication frontier",
        "First clinical appearance per (antigen × disease category) pair "
        "in the solid-tumour cohort. Each marker is the StartYear of the "
        "first CAR-T trial registering that combination on CT.gov. "
        "Antigens sorted by year of first solid-tumour appearance; "
        "disease categories color-coded.",
    )

    _solid_df = df_filt[df_filt["Branch"] == "Solid-onc"].copy()
    _solid_df = _solid_df[~_solid_df["TargetCategory"].isin(_PLATFORM_LABELS)]
    _solid_df = _solid_df[~_solid_df["TargetCategory"].isin(
        ["CAR-T_unspecified", "Other_or_unknown"]
    )]
    _solid_df = _solid_df.dropna(subset=["StartYear", "DiseaseCategory"])

    if _solid_df.empty:
        st.info("Insufficient solid-tumour data for the antigen-frontier view.")
    else:
        # First-appearance matrix: (antigen, category) → first StartYear
        _first = (
            _solid_df.groupby(["TargetCategory", "DiseaseCategory"])["StartYear"]
            .min().reset_index()
            .rename(columns={"StartYear": "FirstYear"})
        )
        # Total trials per (antigen, category) → marker size
        _counts = (
            _solid_df.groupby(["TargetCategory", "DiseaseCategory"])
            .size().reset_index(name="Trials")
        )
        _first = _first.merge(_counts, on=["TargetCategory", "DiseaseCategory"])

        # Sort antigens by year of first solid appearance (ascending)
        _antigen_first = (
            _first.groupby("TargetCategory")["FirstYear"].min()
            .sort_values().index.tolist()
        )
        _first["TargetCategory"] = pd.Categorical(
            _first["TargetCategory"], categories=_antigen_first, ordered=True,
        )
        _first = _first.sort_values("TargetCategory")

        # Build the strip plot — one trace per disease category for color legend
        _solid_cats = sorted(_first["DiseaseCategory"].unique())
        # NEJM-grade categorical palette (no neon, no rainbow — earth + jewel tones)
        _cat_palette = [
            "#0b3d91", "#b45309", "#0f766e", "#7c3aed", "#be123c",
            "#15803d", "#a16207", "#1e40af", "#7e22ce", "#9f1239",
            "#0e7490", "#854d0e",
        ]
        _cat_color_map = {
            cat: _cat_palette[i % len(_cat_palette)]
            for i, cat in enumerate(_solid_cats)
        }

        fig10 = go.Figure()
        for cat in _solid_cats:
            sub = _first[_first["DiseaseCategory"] == cat]
            fig10.add_trace(go.Scatter(
                x=sub["FirstYear"],
                y=sub["TargetCategory"].astype(str),
                mode="markers",
                marker=dict(
                    size=np.clip(sub["Trials"].values * 2 + 8, 8, 32),
                    color=_cat_color_map[cat],
                    line=dict(width=1, color="white"),
                    opacity=0.85,
                ),
                name=cat,
                hovertemplate=(
                    f"<b>{cat}</b><br>"
                    "Antigen: %{y}<br>"
                    "First trial: %{x:.0f}<br>"
                    "Total trials: %{marker.size}<extra></extra>"
                ),
            ))

        # Compute year-axis range from data
        _min_yr = int(_first["FirstYear"].min())
        _max_yr = int(_first["FirstYear"].max())
        fig10.update_layout(
            **PUB_BASE,
            height=max(360, len(_antigen_first) * 28 + 120),
            margin=dict(l=140, r=40, t=40, b=80),
            xaxis=dict(
                title=dict(text="Year of first CAR-T trial in solid tumour",
                           font=dict(size=_LAB_SZ, color=_AX_COLOR)),
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                range=[_min_yr - 1, _max_yr + 1],
                showgrid=True, gridcolor=_GRID_CLR,
                dtick=2,
            ),
            yaxis=dict(
                title=dict(text="Antigen (sorted by first appearance)",
                           font=dict(size=_LAB_SZ, color=_AX_COLOR)),
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                showgrid=False,
                autorange="reversed",
            ),
            legend=dict(
                title=dict(text="Disease category",
                           font=dict(size=_LAB_SZ, color=_AX_COLOR)),
                font=dict(size=10, color=_AX_COLOR),
                orientation="v", x=1.02, y=1.0,
            ),
            showlegend=True,
        )
        st.plotly_chart(fig10, width="stretch", config=PUB_EXPORT)

        # Editorial caption — auto-derives the year-by-year frontier
        _frontier_summary = []
        for yr in sorted(_first["FirstYear"].unique())[:6]:
            antigens_that_year = sorted(
                _first[_first["FirstYear"] == yr]["TargetCategory"]
                .astype(str).unique()
            )
            if antigens_that_year:
                _frontier_summary.append(
                    f"<b>{int(yr)}</b>: {', '.join(antigens_that_year[:5])}"
                    + (f" (+{len(antigens_that_year) - 5} more)"
                       if len(antigens_that_year) > 5 else "")
                )
        st.markdown(
            '<div class="pub-fig-caption" style="margin-top: 0.1rem;">'
            'Marker size proportional to total trial count for that '
            '(antigen × indication) pair. Frontier expansion: '
            + " · ".join(_frontier_summary)
            + ".</div>",
            unsafe_allow_html=True,
        )
        _pub_caption(len(_solid_df))

        # CSV export
        _fig10_csv = _first.copy()
        _fig10_csv["TargetCategory"] = _fig10_csv["TargetCategory"].astype(str)
        st.download_button(
            "Fig 10 data (CSV)",
            _csv_with_provenance(
                _fig10_csv,
                "Fig 10 — Solid-tumour antigen × indication frontier",
            ),
            "fig10_solid_antigen_frontier.csv", "text/csv",
        )

    # ---------------------------------------------------------------------------
    # FIG 12 — Sponsor crowding by antigen
    # ---------------------------------------------------------------------------
    # For each top-15 antigen, count distinct industry sponsors. Reveals where
    # the field is racing (15+ sponsors on CD19) vs lonely (3 on B7-H3).
    # The competitive-landscape chart for industry readers.
    #
    # Pipeline-unique because it requires the closed-vocab antigen list ×
    # the SponsorType classifier (Industry/Academic/Government/Other).

    _pub_header(
        "12", "Industry sponsor crowding by antigen",
        "Count of distinct industry-classified lead sponsors per top-15 "
        "antigen in the current filter. Top sponsor per antigen annotated "
        "where one player runs ≥3 trials. Identifies where the field is "
        "racing (multi-sponsor) vs lonely (single-sponsor early-stage).",
    )

    _sc_df = df_filt[df_filt["SponsorType"] == "Industry"].copy()
    _sc_df = _sc_df[~_sc_df["TargetCategory"].isin(_PLATFORM_LABELS)]
    _sc_df = _sc_df[~_sc_df["TargetCategory"].isin(
        ["CAR-T_unspecified", "Other_or_unknown"]
    )]
    _sc_df = _sc_df.dropna(subset=["LeadSponsor"])

    if _sc_df.empty:
        st.info("Insufficient industry-sponsor data for crowding view.")
    else:
        # Top-15 antigens by total industry trial count
        _top_sc_targets = (
            _sc_df["TargetCategory"].value_counts().head(15).index.tolist()
        )
        _sc_df = _sc_df[_sc_df["TargetCategory"].isin(_top_sc_targets)]

        # For each antigen: distinct sponsor count + top sponsor name
        _crowding = []
        for tgt in _top_sc_targets:
            tgt_df = _sc_df[_sc_df["TargetCategory"] == tgt]
            sponsor_counts = tgt_df["LeadSponsor"].value_counts()
            n_sponsors = len(sponsor_counts)
            top_sponsor = sponsor_counts.index[0] if not sponsor_counts.empty else "—"
            top_sponsor_n = int(sponsor_counts.iloc[0]) if not sponsor_counts.empty else 0
            _crowding.append({
                "Antigen": tgt,
                "DistinctSponsors": n_sponsors,
                "TopSponsor": top_sponsor,
                "TopSponsorTrials": top_sponsor_n,
                "TotalTrials": len(tgt_df),
            })
        _crowd_df = pd.DataFrame(_crowding).sort_values(
            "DistinctSponsors", ascending=True,  # Plotly h-bar reads bottom-up
        )

        # Build hover + bar text — show top sponsor where they own ≥3 trials
        _bar_text = []
        for _, row in _crowd_df.iterrows():
            n = int(row["DistinctSponsors"])
            label = f"{n}"
            if row["TopSponsorTrials"] >= 3:
                label += f"  · top: {row['TopSponsor']} ({row['TopSponsorTrials']})"
            _bar_text.append(label)

        fig12 = go.Figure(go.Bar(
            x=_crowd_df["DistinctSponsors"].values,
            y=_crowd_df["Antigen"].values,
            orientation="h",
            marker=dict(color=HEME_COLOR, line=dict(width=0)),
            text=_bar_text,
            textposition="outside",
            textfont=dict(size=10, color=_AX_COLOR),
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Distinct industry sponsors: %{x}<br>"
                "<extra></extra>"
            ),
        ))
        fig12.update_layout(
            **PUB_BASE,
            height=max(360, len(_crowd_df) * 28 + 80),
            margin=dict(l=140, r=200, t=40, b=56),
            xaxis=dict(
                title=dict(text="Distinct industry sponsors",
                           font=dict(size=_LAB_SZ, color=_AX_COLOR)),
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                showgrid=True, gridcolor=_GRID_CLR, zeroline=False,
            ),
            yaxis=dict(
                title=None,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                showgrid=False,
            ),
            showlegend=False,
        )
        st.plotly_chart(fig12, width="stretch", config=PUB_EXPORT)

        # Summary callout — racing vs lonely
        _racing = _crowd_df[_crowd_df["DistinctSponsors"] >= 5]["Antigen"].tolist()
        _lonely = _crowd_df[_crowd_df["DistinctSponsors"] <= 2]["Antigen"].tolist()
        st.markdown(
            '<div class="pub-fig-caption" style="margin-top: 0.1rem;">'
            f'Industry-crowded antigens (≥5 distinct sponsors): '
            f'<b>{", ".join(_racing) or "—"}</b>. '
            f'Single- or two-sponsor antigens (potential strategic '
            f'opportunities or early-stage frontiers): '
            f'<b>{", ".join(_lonely) or "—"}</b>. '
            'Top-sponsor annotations shown where one player runs ≥3 '
            'industry trials on that antigen.'
            '</div>',
            unsafe_allow_html=True,
        )
        _pub_caption(len(_sc_df))

        # CSV export
        _fig12_csv = _crowd_df.copy()
        st.download_button(
            "Fig 12 data (CSV)",
            _csv_with_provenance(
                _fig12_csv,
                "Fig 12 — Industry sponsor crowding by antigen",
            ),
            "fig12_sponsor_crowding.csv", "text/csv",
        )


# ---------------------------------------------------------------------------
# TAB: Methods & Appendix
# ---------------------------------------------------------------------------

def _build_methods_text(prisma: dict, snapshot_date: str, n_included: int) -> str:
    n_heme = sum(len(ents) for ents in ONTOLOGY["Heme-onc"].values())
    n_solid = sum(len(ents) for ents in ONTOLOGY["Solid-onc"].values())
    n_cats = sum(len(cats) for cats in ONTOLOGY.values())
    n_entities = n_heme + n_solid
    n_hard = len(HARD_EXCLUDED_NCT_IDS)
    n_indication = len(EXCLUDED_INDICATION_TERMS)
    n_fetched = prisma.get("n_fetched", "N/A")
    n_dedup = prisma.get("n_after_dedup", "N/A")
    n_hard_excl = prisma.get("n_hard_excluded", "N/A")
    n_indic_excl = prisma.get("n_indication_excluded", "N/A")

    # Live-derive antigen counts + lists from config so the Methods text
    # never goes stale relative to the actual classifier. Previously these
    # were hand-maintained and drifted (had "16 heme / 25 solid" while the
    # tables held 22 / 28 after the 2026-04-25 IL-5/CD1a/CD4/FAP/MET/FGFR4
    # additions). REVIEW.md risk #1.
    heme_antigen_list = ", ".join(HEME_TARGET_TERMS.keys())
    solid_antigen_list = ", ".join(SOLID_TARGET_TERMS.keys())
    n_heme_antigens = len(HEME_TARGET_TERMS)
    n_solid_antigens = len(SOLID_TARGET_TERMS)
    n_dual_combos = len(DUAL_TARGET_LABELS)
    dual_combo_list = ", ".join(label for _pair, label in DUAL_TARGET_LABELS)
    n_named_products = len(NAMED_PRODUCT_TARGETS)
    n_llm_overrides_active = len(_LLM_OVERRIDES) if _LLM_OVERRIDES else 0
    n_llm_overrides_excluded = len(_LLM_EXCLUDED_NCT_IDS) if _LLM_EXCLUDED_NCT_IDS else 0

    # Quantify the LLM curation layer on the current dataset.
    n_llm_override = int(df.get("LLMOverride", pd.Series(dtype=bool)).sum()) if hasattr(df, "get") else 0

    text = f"""\
METHODS
=======

Data Source and Search Strategy
--------------------------------
Clinical trial data were retrieved from the ClinicalTrials.gov public registry using the
API (v2; {BASE_URL}; accessed {snapshot_date}). A deliberately broad query was applied
using only CAR-based cell-therapy terms ("CAR T", "CAR-T", "chimeric antigen receptor",
"CAR-NK", "CAR NK", "CAAR-T", "CAR-Treg", "gamma delta CAR", "CAR gamma delta"). No
AREA[ConditionSearch] restriction was applied so that trials registered under generic
labels such as "Hematological Malignancies", "Neoplasms", "B-Cell Malignancies", or
"Cancer" — commonly missed by specific-disease keyword queries — are captured. Scope
is enforced downstream by the three-tier classifier and the autoimmune-exclusion filter
(see Inclusion / Exclusion Criteria below). No restriction was placed on study phase,
recruitment status, or geographic location at the query stage.

Inclusion Criteria
------------------
Studies were included if they: (1) described a CAR-based cellular therapy (CAR-T
[autologous, allogeneic, or in vivo], CAR-NK, CAAR-T, CAR-Treg, or CAR-γδ T); and
(2) targeted a hematologic or solid malignancy. No restriction was applied to study
phase, sponsor type, or country. TCR-T products (e.g., afami-cel, NY-ESO-1-directed
TCRs) are out of scope for this v1 dashboard.

Exclusion Criteria
------------------
Studies were excluded if they met any of the following criteria:
    (1) The NCT identifier appeared on a curated hard-exclusion list ({n_hard}
        pre-specified identifiers) OR on the LLM-generated exclusion list (see
        "LLM-Assisted Curation Loop" below). Exclusions cover non-CAR-T
        interventions (bispecifics, mAbs, chemo/TKI, TIL, TCR-T, mRNA vaccines),
        supportive-care / patient-reported-outcome (PRO) studies, long-term
        follow-up registries, observational / biomarker / device trials, and
        out-of-scope indications (COVID-19, non-malignant blood disorders,
        transplant-rejection prophylaxis, etc.).
    (2) Text fields (conditions, title, brief summary, interventions) contained
        one or more of {n_indication} predefined autoimmune / rheumatologic
        keywords and no oncology-adjacent hit. This is the inverse of the sister
        rheumatology app; trials are excluded only when autoimmune is the *sole*
        indication. Generic autoimmune wrappers ("autoimmune diseases",
        "rheumatic diseases") and meta-therapeutic conditions ("cytokine release
        syndrome", "neurotoxicity", "nephrotic syndrome") are also on the list.

Study Selection (PRISMA)
------------------------
    Records identified via database search  : {n_fetched}
    Duplicate records removed               : {prisma.get("n_duplicates_removed", "N/A")}
    Records screened                        : {n_dedup}
    Excluded — hard list + LLM exclusions   : {n_hard_excl}
    Excluded — autoimmune-only keywords     : {n_indic_excl}
    Studies included in final analysis      : {n_included}

Three-tier Disease Ontology
---------------------------
Each trial is assigned three hierarchical labels:
  • Branch — Heme-onc / Solid-onc / Mixed / Unknown
  • DiseaseCategory — {n_cats} Tier-2 categories spanning {len(ONTOLOGY["Heme-onc"])} heme
    (B-NHL, B-ALL, CLL_SLL, T-cell, Multiple myeloma, Hodgkin, AML, MDS_MPN,
    Heme-onc_other) and {len(ONTOLOGY["Solid-onc"])} solid (CNS, Thoracic, GI, GU, Gyn,
    Breast, H&N, Skin, Sarcoma, Pediatric solid, Solid-onc_other).
  • DiseaseEntity — {n_entities} Tier-3 leaves (e.g., DLBCL, Ph+ B-ALL, GBM, HCC,
    Gastric/GEJ, TNBC, Neuroblastoma).
Basket trials spanning ≥2 categories are labelled "Basket/Multidisease" and retain
the full list of matched entities in the DiseaseEntities column (pipe-joined).
Branch-level baskets are labelled "Heme basket" or "Advanced solid tumors".

Hybrid Classification Architecture
----------------------------------
Classification combines rule-based keyword matching, curated named-product lookups,
calibrated defaults, and a two-round LLM validation layer. The resolution order for
each trial is:

1. **LLM override** (if the trial's NCT ID appears in llm_overrides.json with
   confidence "high" or "medium") — trusted wholesale.
2. **Leaf-level term match** — ENTITY_TERMS applied per condition chunk and to the
   combined text (conditions | title | brief summary | interventions). ≥2 leaves
   across different categories → "Basket/Multidisease".
3. **Category-level fallback** — CATEGORY_FALLBACK_TERMS (generic tumor-type
   wordings) match to Tier-2 labels.
4. **Branch-level basket terms** — HEME_BASKET_TERMS / SOLID_BASKET_TERMS.
5. **Fall-through** — "Unclassified" (Branch: Unknown).

Target Classification (Priority Order)
--------------------------------------
1. LLM override.
2. Named-product short-circuit (NAMED_PRODUCT_TARGETS) — maps approved and
   late-stage products to their disclosed antigen (tisa-cel, axi-cel, brexu-cel,
   liso-cel, ide-cel, cilta-cel, obe-cel, relma-cel, eque-cel, zevor-cel, GC012F,
   CT041 / satri-cel, BOXR1030, MT027, HBI0101, CT0596, JY231, Meta10-19, …).
3. Platform detection — CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T (text-level match
   with word-boundary enforcement).
4. Antigen detection:
   • Heme-typical ({n_heme_antigens}): {heme_antigen_list}.
   • Solid-typical ({n_solid_antigens}): {solid_antigen_list}.
5. Dual-target combos ({n_dual_combos} explicit pairs): {dual_combo_list}.
6. Residual: "CAR-T_unspecified" (CAR mentioned but antigen not in public text)
   or "Other_or_unknown" (no CAR-T confirmation).

Word-boundary matching is used for all term lengths, so prefix collisions
(e.g., EGFR vs EGFRvIII; hodgkin vs non-hodgkin) do not produce false positives.

Product Type Classification with Calibrated Default
----------------------------------------------------
Labels: Autologous / Allogeneic/Off-the-shelf / In vivo / Unclear. Priority:

1. LLM override.
2. "in vivo" in the title; or IN_VIVO_TERMS in the combined text
   (circular RNA, mRNA-LNP, lentiviral nanoparticle, vivovec).
3. Explicit autologous markers: "autoleucel", "autologous".
4. Explicit allogeneic markers: UCART, "off the shelf", "universal CAR-T",
   "universal CD19", "healthy donor", "donor-derived".
5. Named-product lookup (NAMED_PRODUCT_TYPES).
6. Weak autologous/allogeneic keywords (ALLOGENEIC_MARKERS, AUTOL_MARKERS).
7. **Calibrated default** — if the trial is confirmed as CAR-T but no
   product-type marker surfaces, default to "Autologous". This is a calibrated
   choice: autologous cells are the dominant modality in the current
   CAR-T landscape (~85 % of approvals and ongoing trials). Each assignment
   carries a ProductTypeSource tag ("explicit_autologous", "named_product",
   "default_autologous_no_allo_markers", "weak_autologous_marker",
   "llm_override", "no_signal") so downstream users can distinguish high-signal
   from inferred labels.

Classification Confidence
-------------------------
Every trial carries a ClassificationConfidence label (high / medium / low)
combining the above signals:
  • high   — LLM-validated OR explicit markers + known branch/entity/target.
  • medium — default rules (Autologous fallback) OR unclear antigen target
             but known branch/entity.
  • low    — Branch = Unknown OR DiseaseEntity = Unclassified (rare after LLM).

The column is surfaced in the Data tab and can be used to filter analyses
to high-confidence rows only.

LLM Curation and Independent-LLM Validation
-------------------------------------------
The pipeline's deterministic keyword layer is supplemented by two LLM
mechanisms — initial curation of low-confidence trials, then ongoing
independent cross-validation against a different vendor's LLM.

1. Initial curation (Claude Opus, 2-round, recorded in llm_overrides.json):
   the Methods & Appendix tab exports `curation_loop.csv` listing every
   trial with any field in {{Branch=Unknown, DiseaseEntity=Unclassified,
   TargetCategory ∈ [CAR-T_unspecified, Other_or_unknown], ProductType=Unclear}}.
   A batched subagent workflow processed every flagged trial; results merged
   into llm_overrides.json. The current snapshot has {n_llm_overrides_active}
   active per-trial overrides plus {n_llm_overrides_excluded} trials flagged
   for exclusion (PRO studies, registries, bispecifics/mAbs, device trials,
   out-of-scope indications). At pipeline load the overrides populate two
   caches:
     _LLM_OVERRIDES         — per-trial classification overrides
                              (confidence ∈ {{high, medium}}, exclude=false).
     _LLM_EXCLUDED_NCT_IDS  — trials flagged exclude=true; dropped at the
                              PRISMA hard-exclusion stage alongside the
                              manually curated hard-exclusion list.

2. Independent cross-validation (scripts/validate_independent_llm.py):
   stratified samples of N trials are sent to a non-Claude LLM (Gemini
   2.5 Flash Lite, Llama 3.3 70B via Groq, or others) for blind re-
   classification — choosing a different vendor breaks the Claude-curates-
   Claude agreement bias of the initial curation. Per-axis Cohen's κ is
   computed against the live pipeline; the report's "Consensus
   disagreements" section lists trials where every reviewer agrees on a
   label different from the pipeline (the highest-signal triage list,
   since two independent vendors converging on the same non-pipeline
   label cannot be one model's quirk).

3. Locked regression benchmark (tests/benchmark_set.csv +
   tests/test_benchmark.py): a hand-curated set of pivotal CAR-T trials
   with known ground-truth labels across every classification axis.
   Per-axis F1 floor enforced; CI fails on regression. This catches any
   classifier change that quietly degrades a previously-correct
   classification.

4. Snapshot-to-snapshot diff (scripts/snapshot_diff.py): compares two
   dated snapshots and categorises every reclassification as
   "expected (LLM override)" / "hard-listed" / "unexplained". The
   unexplained bucket surfaces pipeline / config edits with wider blast
   radius than intended.

The `LLMOverride` boolean column in the trial dataframe flags which rows
were reclassified by the curation LLM ({n_llm_override} of {n_included} in
the current dataset). Users can independently verify any override by
inspecting the corresponding entry in llm_overrides.json alongside the
ClinicalTrials.gov record.

This hybrid (rules + defaults + LLM curation + independent-LLM validation
+ locked benchmark) approach avoids brittleness (a pure keyword system)
and avoids cost/irreproducibility (a pure LLM system):
deterministic rules handle the bulk, the calibrated Autologous default
cleans up cases where information is genuinely absent, and the LLM layer
resolves the residual ambiguous cases with full reasoning and explicit
confidence tags.

Cell-therapy Modality
---------------------
Each trial is assigned to one of eight mechanistically distinct modality categories:
Auto CAR-T, Allo CAR-T, CAR-T (unclear), CAR-γδ T, CAR-NK, CAR-Treg, CAAR-T,
In vivo CAR. Modality is derived from TargetCategory + ProductType + text-level
γδ-T detection.

Sponsor Classification
----------------------
Lead sponsors are classified into four categories — Industry, Academic, Government,
Other — using a hierarchical heuristic that combines CT.gov's LeadSponsorClass
with keyword matching on the sponsor name. Resolution order:
  1. Strong government signals (word-boundary acronyms NIH / NCI / FDA / EMA /
     DOD / VA / CDC, plus full-phrase anchors "National Institutes of Health",
     "Department of Veterans Affairs", etc.) — these override academic markers
     because agencies like NCI are genuine federal funders despite containing
     "institute" in the name.
  2. Academic markers in the name (hospital, university, medical center, cancer
     center, klinik, affiliated hospital, PLA hospital, memorial Sloan, Dana-Farber,
     MD Anderson, …) — override CT.gov's OTHER_GOV class, which over-applies to
     Chinese provincial hospitals and Russian "Federal Research Institute"
     entries that function academically.
  3. CT.gov LeadSponsorClass for unambiguous codes (INDUSTRY → Industry; NIH /
     FED → Government; INDIV → Academic). OTHER_GOV is deliberately dropped
     (an audit reduced Government from 147 misclassified trials to 36 genuine NCI
     entries).
  4. Known pharma brand names without a corporate suffix (Novartis, Kite, Gilead,
     Janssen, Legend, Autolus, …).
  5. Industry corporate suffixes and industry-language keywords (Inc, GmbH, AG,
     S.p.A, Pharma, Biotech, Therapeutics, …).
  6. Secondary academic hints ("Institute of …", "Research Institute", Inserm,
     provincial, fondazione).
  7. PI detection (`_looks_like_personal_name`) — investigator-initiated trials
     where the sponsor field is the PI name ("Carl June, M.D.", "Stephan Grupp")
     get explicit routing to Academic based on degree markers + 2–4 short
     alphabetical tokens with no institutional keyword.
  8. Default to Academic for non-empty, unclassified names (overwhelmingly
     investigator-initiated in practice); "Other" reserved for truly empty strings.

Enrollment Analysis
-------------------
Planned enrollment counts were extracted from the EnrollmentCount field
(type = Anticipated or Actual) and coerced to numeric; missing or non-numeric
values were excluded from enrollment analyses (Figure 4). To remove data-entry
artifacts (registry placeholders like 99,999,999; real-world-data cost studies
with 160,000+ rows), enrollment is capped at 1,000 patients — a threshold safely
above the largest prospective CAR-T trial (cilta-cel CARTITUDE, n≈790). Excluded
outliers are reported in a caption.

Figure 4 presents a three-panel enrollment landscape:
  4a — Branch-stratified trial-size composition across five clinical buckets:
       Dose-escalation (≤ 20), Small cohort (21–50), Expansion (51–100),
       Mid-size (101–300), Pivotal (> 300). Rendered as a 100%-stacked
       horizontal bar (one bar per branch, single-hue sequential navy ramp so
       bucket order is pre-attentively readable), which shows trial-size
       composition and inter-branch comparison in a single chart without
       requiring readers to decode a histogram, ECDF, or IQR.
  4b — Median planned enrollment by Phase × Branch.
  4c — Per-trial enrollment dot plot, phase-ordered.

Data Processing
---------------
All processing was performed in Python (pandas {pd.__version__}) using a custom ETL
pipeline. Text normalisation includes lowercasing, Unicode normalisation, R/R →
"relapsed refractory" expansion, hyphen-to-space conversion (so "b-cell",
"chromosome-positive" match the space-separated forms), and "non hodgkin" →
"nonhodgkin" collapse to prevent "hodgkin lymphoma" from matching inside
"non-Hodgkin lymphoma" context. Term matching uses whole-word boundary regex for
all term lengths, so prefix collisions (EGFR vs EGFRvIII, CD19 vs CD190) do not
produce false positives. Classification rules, term dictionaries, and named-product
lookups are versioned in config.py and iteratively updated via the curation loop.

Dataset Snapshot
----------------
The frozen dataset used for all analyses was generated on {snapshot_date}. CSV exports of
the trial-level dataset (trials.csv) and site-level dataset (sites.csv) are available
via the Data tab. All analyses are reproducible from the frozen snapshot using the
published code and configuration files.
"""
    return text


def _build_ontology_df() -> pd.DataFrame:
    rows = []
    for branch, cats in ONTOLOGY.items():
        for cat, ents in cats.items():
            rows.append({
                "Tier": "Category",
                "Branch": branch,
                "Label": cat,
                "Terms (sample)": "; ".join(CATEGORY_FALLBACK_TERMS.get(cat, [])[:6]) or "—",
                "N entities": len(ents),
            })
            for ent in ents:
                terms = ENTITY_TERMS.get(ent, [])
                rows.append({
                    "Tier": "Entity",
                    "Branch": branch,
                    "Label": f"{cat} / {ent}",
                    "Terms (sample)": "; ".join(terms[:6]) + ("…" if len(terms) > 6 else ""),
                    "N entities": 0,
                })
    rows.append({"Tier": "Special", "Branch": "—", "Label": BASKET_MULTI_LABEL,
                  "Terms (sample)": "≥2 categories matched", "N entities": 0})
    rows.append({"Tier": "Special", "Branch": "Heme-onc", "Label": HEME_BASKET_LABEL,
                  "Terms (sample)": "; ".join(HEME_BASKET_TERMS[:4]) + "…", "N entities": 0})
    rows.append({"Tier": "Special", "Branch": "Solid-onc", "Label": SOLID_BASKET_LABEL,
                  "Terms (sample)": "; ".join(SOLID_BASKET_TERMS[:4]) + "…", "N entities": 0})
    rows.append({"Tier": "Target (heme antigens)", "Branch": "—", "Label": f"{len(HEME_TARGET_TERMS)} antigens",
                  "Terms (sample)": ", ".join(list(HEME_TARGET_TERMS.keys())[:10]) + "…", "N entities": 0})
    rows.append({"Tier": "Target (solid antigens)", "Branch": "—", "Label": f"{len(SOLID_TARGET_TERMS)} antigens",
                  "Terms (sample)": ", ".join(list(SOLID_TARGET_TERMS.keys())[:10]) + "…", "N entities": 0})
    rows.append({"Tier": "Target (dual)", "Branch": "—", "Label": f"{len(DUAL_TARGET_LABELS)} combos",
                  "Terms (sample)": ", ".join([lbl for _p, lbl in DUAL_TARGET_LABELS][:4]) + "…", "N entities": 0})
    rows.append({"Tier": "Named products (approved/clinical)", "Branch": "—",
                  "Label": f"{sum(len(v) for v in NAMED_PRODUCT_TARGETS.values())} product terms",
                  "Terms (sample)": "tisagenlecleucel, axicabtagene ciloleucel, ide-cel, cilta-cel, GC012F, …",
                  "N entities": 0})
    rows.append({"Tier": "Exclusion", "Branch": "—", "Label": "Autoimmune/meta keyword exclusion",
                  "Terms (sample)": "; ".join(EXCLUDED_INDICATION_TERMS[:6]) + "…",
                  "N entities": len(EXCLUDED_INDICATION_TERMS)})
    rows.append({"Tier": "LLM curation",
                  "Branch": "—",
                  "Label": "Classification overrides (llm_overrides.json)",
                  "Terms (sample)": "Per-trial Branch/Category/Entity/Target/Product overrides from two-round Claude Opus validation.",
                  "N entities": 0})
    rows.append({"Tier": "LLM curation",
                  "Branch": "—",
                  "Label": "ClassificationConfidence",
                  "Terms (sample)": "high / medium / low band per trial, combining LLM validation, rule strength, and ProductTypeSource.",
                  "N entities": 0})
    return pd.DataFrame(rows)


with tab_methods:
    snap_date = df["SnapshotDate"].iloc[0] if "SnapshotDate" in df.columns and not df.empty else date.today().isoformat()
    n_inc = len(df_filt)

    # ------------------------------------------------------------------
    # FIG 11 — PRISMA flow as a Sankey diagram
    # ------------------------------------------------------------------
    # Renders the same PRISMA counts as the existing flow table (Overview
    # tab expander), but as a left-to-right Sankey so the reader sees
    # WHERE every trial went visually. Methods-paper-grade reproducibility
    # — most CAR-T reviews give "we screened N, included M" with no
    # audit trail; this is the audit trail.

    if prisma_counts:
        st.subheader("Figure 11 — PRISMA selection flow")
        st.markdown(
            '<p class="small-note">Left-to-right Sankey of trial flow '
            'through the selection pipeline. Width of each link is '
            'proportional to the number of trials traversing that step. '
            'Dataset audit trail at the per-stage granularity rarely '
            'reported in published CAR-T reviews.</p>',
            unsafe_allow_html=True,
        )

        n_fetched_p = int(prisma_counts.get("n_fetched", 0) or 0)
        n_dups_p = int(prisma_counts.get("n_duplicates_removed", 0) or 0)
        n_dedup_p = int(prisma_counts.get("n_after_dedup", 0) or 0)
        n_hard_p = int(prisma_counts.get("n_hard_excluded", 0) or 0)
        n_indic_p = int(prisma_counts.get("n_indication_excluded", 0) or 0)
        n_inc_p = int(prisma_counts.get("n_included", n_inc) or n_inc)

        if n_fetched_p > 0:
            # Custom HTML/CSS PRISMA flowchart — NEJM-style.
            # Plotly Sankey labels are notoriously small + ugly; this
            # gives us full typography control. Big legible numbers,
            # clear inclusion vs exclusion path, sleek navy palette.
            n_after_hard = max(0, n_dedup_p - n_hard_p)
            n_after_indic = max(0, n_dedup_p - n_hard_p - n_indic_p)

            st.markdown("""
            <style>
                .prisma-wrap {
                    background: linear-gradient(180deg, #ffffff 0%, #fafbfc 100%);
                    border: 1px solid #e2e8f0; border-radius: 10px;
                    padding: 14px 16px 10px 16px; margin: 4px 0 12px 0;
                    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03),
                                0 2px 6px rgba(15, 23, 42, 0.025);
                }
                .prisma-row {
                    display: grid;
                    grid-template-columns: minmax(0, 1.1fr) 18px minmax(0, 1fr);
                    align-items: center; gap: 6px;
                    margin-bottom: 4px;
                }
                .prisma-stage, .prisma-excl {
                    border-radius: 6px; padding: 7px 12px;
                    font-family: Arial, Helvetica, sans-serif;
                    line-height: 1.2;
                    display: flex; align-items: center;
                    justify-content: space-between; gap: 12px;
                }
                .prisma-stage {
                    background: #1e3a8a; color: #ffffff;
                    border: 1px solid #1e3a8a;
                }
                .prisma-stage.endpoint {
                    background: #0b3d91; border-color: #0b3d91;
                    box-shadow: 0 1px 3px rgba(11, 61, 145, 0.3);
                }
                .prisma-excl {
                    background: #f1f5f9; color: #475569;
                    border: 1px solid #e2e8f0;
                }
                .prisma-num {
                    font-size: 16px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    letter-spacing: -0.01em; line-height: 1;
                    flex: 0 0 auto;
                }
                .prisma-lbl {
                    font-size: 10px; text-transform: uppercase;
                    letter-spacing: 0.5px; font-weight: 600;
                    line-height: 1.2;
                    text-align: right; flex: 1 1 auto;
                    min-width: 0;
                }
                /* Explicit color rules per state — avoids inherited
                   black showing through on navy bg in some browsers. */
                .prisma-stage .prisma-num,
                .prisma-stage .prisma-lbl,
                .prisma-stage * { color: #ffffff !important; }
                .prisma-excl .prisma-num,
                .prisma-excl .prisma-lbl,
                .prisma-excl * { color: #334155 !important; }
                .prisma-stage.endpoint .prisma-num { font-size: 18px; }
                .prisma-arrow {
                    color: #cbd5e1; font-size: 14px; text-align: center;
                    line-height: 1; user-select: none;
                }
                .prisma-arrow-down {
                    grid-column: 1 / 2; text-align: center;
                    color: #cbd5e1; font-size: 11px; font-weight: 700;
                    margin: -1px 0; letter-spacing: 1px;
                    line-height: 1;
                }
            </style>
            """, unsafe_allow_html=True)

            # Compact PRISMA flowchart. Each row = one stage of the
            # main inclusion path on the left, optional exclusion on
            # the right. Number + label inline horizontally for density.
            _rows_html = f"""
            <div class="prisma-wrap">
              <div class="prisma-row">
                <div class="prisma-stage">
                  <span class="prisma-num">{n_fetched_p:,}</span>
                  <span class="prisma-lbl">Records identified · CT.gov v2 API</span>
                </div>
                <div></div>
                <div></div>
              </div>
              <div class="prisma-arrow-down">↓</div>
              <div class="prisma-row">
                <div class="prisma-stage">
                  <span class="prisma-num">{n_dedup_p:,}</span>
                  <span class="prisma-lbl">After de-duplication</span>
                </div>
                <div class="prisma-arrow">→</div>
                <div class="prisma-excl">
                  <span class="prisma-num">{n_dups_p:,}</span>
                  <span class="prisma-lbl">Duplicates removed</span>
                </div>
              </div>
              <div class="prisma-arrow-down">↓</div>
              <div class="prisma-row">
                <div class="prisma-stage">
                  <span class="prisma-num">{n_after_hard:,}</span>
                  <span class="prisma-lbl">After hard-exclusion list</span>
                </div>
                <div class="prisma-arrow">→</div>
                <div class="prisma-excl">
                  <span class="prisma-num">{n_hard_p:,}</span>
                  <span class="prisma-lbl">Hard-excluded · curated</span>
                </div>
              </div>
              <div class="prisma-arrow-down">↓</div>
              <div class="prisma-row">
                <div class="prisma-stage">
                  <span class="prisma-num">{n_after_indic:,}</span>
                  <span class="prisma-lbl">After indication filter</span>
                </div>
                <div class="prisma-arrow">→</div>
                <div class="prisma-excl">
                  <span class="prisma-num">{n_indic_p:,}</span>
                  <span class="prisma-lbl">Autoimmune-only excluded</span>
                </div>
              </div>
              <div class="prisma-arrow-down">↓</div>
              <div class="prisma-row">
                <div class="prisma-stage endpoint">
                  <span class="prisma-num">{n_inc_p:,}</span>
                  <span class="prisma-lbl">Included in analysis</span>
                </div>
                <div></div>
                <div></div>
              </div>
            </div>
            """
            st.markdown(_rows_html, unsafe_allow_html=True)

            # Build a hidden Plotly Sankey for the PNG export toolbar
            # (publication submissions sometimes require a Sankey-style
            # figure file). Same data, same colors; not rendered inline.
            # Skipped for now — the HTML chart prints cleanly via the
            # browser's print-to-PDF for manuscript figures.

            # Caption with the PRISMA-style narrative
            st.markdown(
                '<div class="pub-fig-caption" style="margin-top: 0.1rem;">'
                f'Of <b>{n_fetched_p:,}</b> records identified via the '
                'ClinicalTrials.gov v2 API '
                f'({_get_methods_query_summary() if "_get_methods_query_summary" in globals() else "broad CAR-based cell-therapy term query, no condition restriction"}), '
                f'<b>{n_dups_p:,}</b> duplicates were removed, '
                f'<b>{n_hard_p:,}</b> were excluded by the curated '
                'hard-exclusion NCT list (manually-flagged off-scope '
                f'trials), and <b>{n_indic_p:,}</b> were excluded as '
                'autoimmune- or rheumatology-only indications. '
                f'<b>{n_inc_p:,}</b> trials proceeded to classification '
                'and analysis.'
                '</div>',
                unsafe_allow_html=True,
            )

            # CSV export of the underlying counts (one row per stage)
            _fig11_csv = pd.DataFrame([
                {"Stage": "Identified via CT.gov v2 API", "Path": "kept",
                 "n": n_fetched_p},
                {"Stage": "Duplicates removed", "Path": "excluded",
                 "n": n_dups_p},
                {"Stage": "After de-duplication", "Path": "kept",
                 "n": n_dedup_p},
                {"Stage": "Hard-excluded (curated NCT list)",
                 "Path": "excluded", "n": n_hard_p},
                {"Stage": "After hard-exclusion list", "Path": "kept",
                 "n": n_after_hard},
                {"Stage": "Indication-mismatch (autoimmune-only)",
                 "Path": "excluded", "n": n_indic_p},
                {"Stage": "After indication filter", "Path": "kept",
                 "n": n_after_indic},
                {"Stage": "Included in analysis", "Path": "kept",
                 "n": n_inc_p},
            ])
            st.download_button(
                "Fig 11 data (CSV)",
                _csv_with_provenance(
                    _fig11_csv,
                    "Fig 11 — PRISMA selection flow",
                ),
                "fig11_prisma_flow.csv", "text/csv",
            )
        else:
            st.info("PRISMA counts unavailable — refresh the snapshot to populate.")
    else:
        st.info("No PRISMA counts available for this dataset.")

    methods_text = _build_methods_text(prisma_counts, snap_date, n_inc)

    st.subheader("Methods section (auto-generated)")
    st.markdown(
        '<p class="small-note">Generated from config.py, pipeline.py, and the current dataset. '
        "Copy or download for use in your manuscript. Edit the journal-specific wording as needed.</p>",
        unsafe_allow_html=True,
    )
    st.text_area("Methods text", value=methods_text, height=520, label_visibility="collapsed")
    st.download_button(
        "Download methods (.txt)", data=methods_text,
        file_name=f"car_t_oncology_methods_{snap_date}.txt",
        mime="text/plain",
    )

    st.subheader("Appendix — Classification ontology")
    st.markdown(
        '<p class="small-note">Tri-level ontology and key term maps (supplementary Table S1).</p>',
        unsafe_allow_html=True,
    )
    ontology_df = _build_ontology_df()
    st.dataframe(
        ontology_df, width='stretch', hide_index=True,
        column_config={
            "Tier": st.column_config.TextColumn("Tier", width="medium"),
            "Branch": st.column_config.TextColumn("Branch", width="small"),
            "Label": st.column_config.TextColumn("Label", width="medium"),
            "Terms (sample)": st.column_config.TextColumn("Terms (sample)", width="large"),
            "N entities": st.column_config.NumberColumn("N entities", width="small"),
        },
    )
    st.download_button(
        "Download ontology table (CSV)",
        data=_csv_with_provenance(ontology_df,
                                    "Classification ontology — supplementary Table S1",
                                    include_filters=False),
        file_name=f"car_t_onco_ontology_{snap_date}.csv",
        mime="text/csv",
    )

    st.subheader("Appendix — Hard-excluded NCT IDs")
    if HARD_EXCLUDED_NCT_IDS:
        excl_df = pd.DataFrame(sorted(HARD_EXCLUDED_NCT_IDS), columns=["NCTId"])
        excl_df["ClinicalTrials.gov link"] = excl_df["NCTId"].apply(
            lambda x: f"https://clinicaltrials.gov/study/{x}"
        )
        st.dataframe(
            excl_df, width='stretch', hide_index=True,
            column_config={
                "NCTId": st.column_config.TextColumn("NCT ID"),
                "ClinicalTrials.gov link": st.column_config.LinkColumn("Link", display_text="Open"),
            },
        )
    else:
        st.info("No hard-excluded NCT IDs yet. Additions flow from the curation loop below.")

    # Curation loop
    st.subheader("Curation loop — unclear / unclassified trials")
    st.markdown(
        '<p class="small-note">Download the structured CSV, feed it to Claude Code, '
        "and the assistant will propose and apply patches to config.py / pipeline.py automatically.</p>",
        unsafe_allow_html=True,
    )
    unclear_disease_mask = (
        df_filt["Branch"].astype(str).str.lower().isin(["unknown"])
        | df_filt["DiseaseEntity"].astype(str).str.lower().isin([UNCLASSIFIED_LABEL.lower(), "heme-onc_other", "solid-onc_other"])
    )
    unclear_target_mask = df_filt["TargetCategory"].astype(str).str.lower().isin(
        ["other_or_unknown", "car-t_unspecified", "car_t_unspecified", "unclassified", "unknown"]
    )
    unclear_product_mask = df_filt["ProductType"].astype(str).str.lower() == "unclear"

    df_unclear = df_filt[unclear_disease_mask | unclear_target_mask | unclear_product_mask].copy()

    if not df_unclear.empty:
        def _unclear_fields(row):
            flags = []
            if (str(row.get("Branch", "")).lower() == "unknown"
                or str(row.get("DiseaseEntity", "")).lower() in {"unclassified", "heme-onc_other", "solid-onc_other"}):
                flags.append("Disease")
            if str(row.get("TargetCategory", "")).lower() in {"other_or_unknown", "car-t_unspecified", "car_t_unspecified", "unclassified", "unknown"}:
                flags.append("Target")
            if str(row.get("ProductType", "")).lower() == "unclear":
                flags.append("Product")
            return "|".join(flags)

        df_unclear["UnclearFields"] = df_unclear.apply(_unclear_fields, axis=1)
        export_cols = [
            "NCTId", "BriefTitle", "Conditions", "Interventions",
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "UnclearFields", "BriefSummary",
        ]
        df_export = df_unclear[[c for c in export_cols if c in df_unclear.columns]].copy()
        if "BriefSummary" in df_export.columns:
            df_export["BriefSummary"] = df_export["BriefSummary"].astype(str).str[:300]

        import io as _io
        header_lines = [
            "# CURATION_LOOP_ONCO_V1",
            "# INSTRUCTION: You are Claude Code assisting with a CAR-T oncology trial pipeline.",
            "# For each row below, read BriefTitle / Conditions / Interventions / BriefSummary.",
            "# Propose the correct Branch (Heme-onc | Solid-onc | Mixed),",
            "#   DiseaseCategory, DiseaseEntity, TargetCategory, and ProductType.",
            "# Then automatically patch config.py and/or pipeline.py to capture these cases.",
            "# UnclearFields shows which field(s) triggered inclusion (Disease|Target|Product).",
            "#",
        ]
        buf = _io.StringIO()
        for line in header_lines:
            buf.write(line + "\n")
        df_export.to_csv(buf, index=False)
        curation_csv = buf.getvalue()

        st.dataframe(
            df_export[["NCTId", "BriefTitle", "Branch", "DiseaseCategory",
                        "DiseaseEntity", "TargetCategory", "ProductType", "UnclearFields"]],
            width='stretch', height=280,
        )
        st.caption(f"{len(df_export)} trial(s) flagged for curation")

        st.download_button(
            label=f"Download curation CSV ({len(df_export)} trials)",
            data=curation_csv, file_name="curation_loop.csv", mime="text/csv",
        )
    else:
        st.success("No unclear / unclassified trials in the current filter.")

    # Validation sample + Cohen's κ
    st.subheader("Validation sample export")
    st.markdown(
        '<p class="small-note">Stratified random sample for manual classification review. '
        "Two reviewers complete independently, then compute inter-rater agreement (Cohen's κ).</p>",
        unsafe_allow_html=True,
    )

    val_n = st.slider("Target sample size", min_value=25, max_value=200, value=100, step=25)
    val_seed = st.number_input("Random seed (for reproducibility)", min_value=0, max_value=9999, value=42, step=1)

    def build_validation_sample(source_df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
        review_cols = [
            "NCTId", "BriefTitle", "Conditions", "BriefSummary",
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType",
            "Phase", "OverallStatus", "LeadSponsor", "Countries",
        ]
        available = [c for c in review_cols if c in source_df.columns]
        base = source_df[available].copy()

        strata = base["DiseaseCategory"].fillna("Unclassified")
        counts = strata.value_counts()
        total = len(base)
        per_stratum = (counts / total * n).clip(lower=1).round().astype(int)
        diff = n - per_stratum.sum()
        if diff != 0:
            largest = per_stratum.idxmax()
            per_stratum[largest] = max(1, per_stratum[largest] + diff)

        frames = []
        for entity, k in per_stratum.items():
            rows = base[strata == entity]
            k = min(k, len(rows))
            frames.append(rows.sample(n=k, random_state=int(seed), replace=False))

        sample = pd.concat(frames, ignore_index=True).sample(frac=1, random_state=int(seed)).reset_index(drop=True)
        sample.insert(0, "SampleID", range(1, len(sample) + 1))

        for col in ["Reviewer1_Branch", "Reviewer1_Category", "Reviewer1_Entity",
                    "Reviewer1_Target", "Reviewer1_Product",
                    "Reviewer2_Branch", "Reviewer2_Category", "Reviewer2_Entity",
                    "Reviewer2_Target", "Reviewer2_Product", "Notes"]:
            sample[col] = ""
        return sample

    if not df_filt.empty:
        sample_df = build_validation_sample(df_filt, val_n, int(val_seed))
        st.caption(
            f"Sample: {len(sample_df)} trials across "
            f"{df_filt['DiseaseCategory'].nunique()} category strata (seed={int(val_seed)})"
        )
        st.dataframe(
            sample_df[["SampleID", "NCTId", "Branch", "DiseaseCategory", "DiseaseEntity",
                        "TargetCategory", "ProductType", "BriefTitle"]],
            width='stretch', height=260, hide_index=True,
        )
        st.download_button(
            label="Download validation sample CSV",
            data=sample_df.to_csv(index=False),
            file_name=f"car_t_onco_validation_sample_n{len(sample_df)}_seed{int(val_seed)}.csv",
            mime="text/csv",
        )
    else:
        st.info("No trials in the current filter selection.")

    st.subheader("Inter-rater agreement (Cohen's κ)")
    st.markdown(
        '<p class="small-note">Upload the completed validation CSV to compute Cohen\'s κ for '
        "Branch, Category, Entity, Target, and Product classification.</p>",
        unsafe_allow_html=True,
    )

    def _cohen_kappa(y1: list, y2: list) -> float:
        from collections import Counter
        n = len(y1)
        if n == 0:
            return float("nan")
        p_o = sum(a == b for a, b in zip(y1, y2)) / n
        c1, c2 = Counter(y1), Counter(y2)
        all_labels = set(c1) | set(c2)
        p_e = sum((c1[k] / n) * (c2[k] / n) for k in all_labels)
        if p_e >= 1.0:
            return 1.0
        return (p_o - p_e) / (1 - p_e)

    def _kappa_label(k: float) -> str:
        if k != k:
            return "—"
        if k < 0.00: return "Poor (< 0)"
        if k < 0.20: return "Slight (< 0.20)"
        if k < 0.40: return "Fair (0.20–0.40)"
        if k < 0.60: return "Moderate (0.40–0.60)"
        if k < 0.80: return "Substantial (0.60–0.80)"
        return "Almost perfect (≥ 0.80)"

    uploaded = st.file_uploader(
        "Completed validation CSV", type="csv",
        help="Upload the filled-in validation sample with Reviewer1_* and Reviewer2_* columns.",
    )

    if uploaded is not None:
        try:
            rev_df = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            rev_df = None

        if rev_df is not None:
            required = {
                "Reviewer1_Branch", "Reviewer2_Branch",
                "Reviewer1_Category", "Reviewer2_Category",
                "Reviewer1_Entity", "Reviewer2_Entity",
                "Reviewer1_Target", "Reviewer2_Target",
                "Reviewer1_Product", "Reviewer2_Product",
            }
            missing_cols = required - set(rev_df.columns)
            if missing_cols:
                st.error(f"Missing columns: {', '.join(sorted(missing_cols))}")
            else:
                pairs = [
                    ("Branch",    "Reviewer1_Branch",   "Reviewer2_Branch"),
                    ("Category",  "Reviewer1_Category", "Reviewer2_Category"),
                    ("Entity",    "Reviewer1_Entity",   "Reviewer2_Entity"),
                    ("Target",    "Reviewer1_Target",   "Reviewer2_Target"),
                    ("Product",   "Reviewer1_Product",  "Reviewer2_Product"),
                ]
                kappa_rows = []
                for label, col1, col2 in pairs:
                    sub = rev_df[[col1, col2]].dropna()
                    sub = sub[(sub[col1].str.strip() != "") & (sub[col2].str.strip() != "")]
                    n_rated = len(sub)
                    n_agreed = int((sub[col1].str.strip() == sub[col2].str.strip()).sum())
                    k = _cohen_kappa(sub[col1].str.strip().tolist(), sub[col2].str.strip().tolist())
                    kappa_rows.append({
                        "Classification task": label, "n rated": n_rated, "n agreed": n_agreed,
                        "% agreement": f"{100 * n_agreed / n_rated:.1f}%" if n_rated else "—",
                        "κ": round(k, 3) if k == k else "—",
                        "Interpretation": _kappa_label(k),
                    })
                kappa_summary = pd.DataFrame(kappa_rows)
                st.dataframe(kappa_summary, width='stretch', hide_index=True)


# ---------------------------------------------------------------------------
# TAB: About / Impressum
# ---------------------------------------------------------------------------

def _git_version() -> tuple[str, str]:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%cs"],
            cwd=repo_root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return sha or "dev", commit_date or date.today().isoformat()
    except Exception:
        return "dev", date.today().isoformat()


with tab_about:
    sha, commit_date = _git_version()
    snap_date = (
        df["SnapshotDate"].iloc[0]
        if "SnapshotDate" in df.columns and not df.empty
        else date.today().isoformat()
    )

    st.subheader("About this dashboard")
    st.markdown(
        f"""
**CAR-T Oncology Trials Monitor** is an interactive dashboard that tracks CAR-T,
CAR-NK, CAAR-T, and CAR-γδ T clinical trials across hematologic and solid tumors,
sourced from the public ClinicalTrials.gov registry. It is the sister app to the
[Rheumatology CAR-T Trials Monitor](https://rheum-car-t-trial-monitor.streamlit.app/)
and is designed as a research and educational resource — not a medical, regulatory,
or decision-support tool.

- **Data source**: ClinicalTrials.gov API v2 ([{BASE_URL}]({BASE_URL}))
- **Current data snapshot**: {snap_date}
- **Software version**: `{sha}` &nbsp;·&nbsp; built {commit_date}
- **Archival DOI**: [10.5281/zenodo.19738097](https://doi.org/10.5281/zenodo.19738097)
- **Code license**: MIT
        """
    )

    st.markdown("---")
    st.subheader("Contact")
    st.markdown(
        f"""
<div style="
    border: 1px solid {THEME['border']};
    border-left: 3px solid {THEME['primary']};
    border-radius: 8px;
    padding: 1.1rem 1.3rem;
    background: {THEME['surface']};
    max-width: 520px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
">
    <div style="
        font-size: 1.02rem; font-weight: 600;
        color: {THEME['text']}; letter-spacing: -0.01em;
        margin-bottom: 0.35rem;
    ">Peter Jeong</div>
    <div style="
        font-size: 0.88rem; color: {THEME['text']}; line-height: 1.45;
    ">Universitätsklinikum Köln</div>
    <div style="
        font-size: 0.82rem; color: {THEME['muted']};
        line-height: 1.5; margin-bottom: 0.6rem;
    ">Klinik I für Innere Medizin<br>Hämatologie und Onkologie<br>Klinische Immunologie und Rheumatologie</div>
    <div style="
        font-size: 0.80rem; color: {THEME['muted']};
        line-height: 1.55; padding-top: 0.55rem;
        border-top: 1px dashed {THEME['border']}; margin-bottom: 0.7rem;
    ">Kerpener Straße 62<br>50937 Köln, Germany</div>
    <a href="mailto:peter.jeong@uk-koeln.de" style="
        display: inline-flex; align-items: center; gap: 0.4rem;
        font-size: 0.84rem; font-weight: 500;
        color: {THEME['primary']}; text-decoration: none;
        padding: 0.35rem 0.7rem;
        border: 1px solid {THEME['border']};
        border-radius: 6px; background: {THEME['surf2']};
        transition: background 0.12s, border-color 0.12s;
    " onmouseover="this.style.background='{THEME['surf3']}';this.style.borderColor='{THEME['primary']}'"
       onmouseout="this.style.background='{THEME['surf2']}';this.style.borderColor='{THEME['border']}'">
        Email: peter.jeong@uk-koeln.de
    </a>
</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.subheader("Suggested citation")
    citation = (
        f"Jeong P. CAR-T Oncology Trials Monitor (version {sha}) [Internet]. "
        f"Klinik I für Innere Medizin, Hämatologie und Onkologie, "
        f"Klinische Immunologie und Rheumatologie, "
        f"Universitätsklinikum Köln; {date.today().year} "
        f"[cited {date.today().isoformat()}]. "
        f"DOI: 10.5281/zenodo.19738097. "
        f"Data snapshot: {snap_date}. "
        f"Available from: https://onc-car-t-trial-monitor.streamlit.app"
    )
    st.code(citation, language="text")
    st.caption(
        "Vancouver-style citation. "
        "DOI: [10.5281/zenodo.19738097](https://doi.org/10.5281/zenodo.19738097)"
    )

    st.markdown("---")
    st.subheader("Scientific disclaimer")
    st.markdown(
        """
Trial classifications (branch, disease category, disease entity, antigen target,
cell-therapy modality, product type, geography) are produced by an automated
pipeline combining keyword matching, curated lookup tables, and — for flagged
ambiguous cases — large-language-model-assisted review. Despite careful curation,
errors, omissions, and misclassifications are possible.

For any definitive scientific, clinical, or regulatory purpose, consult the
original trial records on ClinicalTrials.gov. This dashboard does not provide
medical advice and must not be used to guide individual patient care.
        """
    )

    with st.expander("Impressum · Datenschutz · Haftungsausschluss", expanded=False):
        st.markdown(
            f"""
#### Angaben gemäß § 5 TMG

**Verantwortlich für den Inhalt im Sinne des § 18 Abs. 2 MStV**

Peter Jeong
Universitätsklinikum Köln
Klinik I für Innere Medizin
Hämatologie und Onkologie
Klinische Immunologie und Rheumatologie
Kerpener Straße 62
50937 Köln
Germany

E-Mail: peter.jeong@uk-koeln.de

---

#### Haftung für Inhalte

Die Inhalte dieses Dashboards wurden mit größtmöglicher Sorgfalt erstellt. Für die
Richtigkeit, Vollständigkeit und Aktualität der Inhalte kann jedoch keine Gewähr
übernommen werden. Die hier bereitgestellten Klassifikationen, Grafiken und
aggregierten Statistiken dienen ausschließlich wissenschaftlichen und edukativen
Zwecken. Sie stellen **keine medizinische Beratung** dar und sind nicht zur
Unterstützung individueller klinischer Entscheidungen geeignet.

#### Haftung für Links

Dieses Dashboard enthält Links zu externen Webseiten Dritter (insbesondere
ClinicalTrials.gov), auf deren Inhalte ich keinen Einfluss habe.

#### Urheberrecht

Der Quellcode dieser Anwendung steht unter der MIT-Lizenz. Die zugrunde liegenden
Studiendaten stammen aus dem öffentlichen Register ClinicalTrials.gov (U.S. National
Library of Medicine) und unterliegen deren Nutzungsbedingungen.

---

#### Datenschutz (kurz)

Diese Anwendung erhebt selbst **keine personenbezogenen Daten** von Nutzerinnen und
Nutzern. Es werden keine Tracking-Cookies, keine Analytics-Dienste und keine
Drittanbieter-Einbettungen mit Tracking-Funktion verwendet.

**Hosting-Anbieter:** Streamlit Community Cloud (Snowflake Inc., Bozeman, MT, USA).
Beim Aufruf der Anwendung werden technisch notwendige Verbindungsdaten (IP-Adresse,
Zeitstempel, User-Agent) vorübergehend durch den Hosting-Anbieter verarbeitet.
Details: [streamlit.io/privacy-policy](https://streamlit.io/privacy-policy) und
[snowflake.com/privacy-notice](https://www.snowflake.com/privacy-notice/).

**Datenquelle:** Die Anwendung ruft Studiendaten über die öffentliche API von
ClinicalTrials.gov ab ([{BASE_URL}]({BASE_URL})).

---

#### Versionierung

- **Software-Version (git commit):** `{sha}`
- **Build-Datum:** {commit_date}
- **Datensatz-Snapshot:** {snap_date}
- **Datenquelle:** ClinicalTrials.gov API v2

Stand: {date.today().isoformat()}
            """
        )


# ---------------------------------------------------------------------------
# TAB: Moderation (gated, only when MODERATOR_TOKEN matches ?mod= query param)
# ---------------------------------------------------------------------------
#
# Two-mode moderator console:
#
#   Mode A — Triage flagged trials
#     For every consensus-reached classification-flag issue, render a
#     side-by-side panel: pipeline label vs proposed correction (per axis),
#     issue link, action buttons (Approve → record + label issue
#     `moderator-approved`; Reject → record + label issue
#     `moderator-rejected`). Both actions append to
#     moderator_validations.json with provenance (timestamp, source=flag,
#     issue_url, rationale).
#
#   Mode B — Random validation (only available when no consensus issues
#     are pending). Draws a stratified random trial from the live snapshot,
#     shows pipeline predictions on every axis, and lets the moderator
#     confirm or correct each. Confirmed labels also feed
#     moderator_validations.json so that even on quiet weeks the
#     ground-truth pool keeps growing — and the per-axis Cohen's κ is
#     computed against it.
#
# A stats panel at the bottom shows agreement rates and Cohen's κ
# per axis once N≥10 validated rows exist for that axis.

if _MODERATOR_MODE and tab_moderation is not None:
    with tab_moderation:
        st.subheader("Moderation console")
        st.caption(
            "Private moderator workspace. Triage community classification "
            "flags that have hit consensus, or — when the queue is empty — "
            "burn the slack time on random-validation rounds that grow the "
            "ground-truth pool. Every action is appended to "
            f"`{MODERATOR_VALIDATIONS_PATH}` with provenance."
        )

        # Refresh the active-flags cache so brand-new consensus shows up
        # without waiting for the 5-min TTL to expire.
        if st.button("Refresh flag queue from GitHub", key="mod_refresh"):
            _load_active_flags.clear()
            st.rerun()

        active_flags = _load_active_flags()
        consensus_flags = {
            nct: e for nct, e in active_flags.items()
            if e.get("consensus")
        }
        pending_flags = {
            nct: e for nct, e in active_flags.items()
            if not e.get("consensus")
        }

        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("Awaiting moderator", len(consensus_flags))
        _c2.metric("Open flags (pre-consensus)", len(pending_flags))
        _c3.metric(
            "Validated trials",
            len({r.get("nct_id") for r in _load_moderator_validations()}),
        )

        st.divider()

        # ===== Mode A: Triage consensus-reached flags =====
        st.markdown("### Mode A — Triage consensus-reached flags")
        if not consensus_flags:
            st.info(
                "No consensus-reached flags are awaiting moderation right "
                "now. Use Mode B below to burn time on random validation; "
                "every validated row tightens the per-axis Cohen's κ "
                "estimate at the bottom of this page."
            )
        else:
            # Iterate consensus-flagged trials; for each, fetch the structured
            # YAML proposals via the existing GH API call (issue body or comments).
            import requests as _req_mod
            for nct, entry in sorted(consensus_flags.items()):
                _issue_urls = entry.get("issue_urls", [])
                with st.expander(
                    f"⚑ {nct} — {entry.get('count', 0)} flag(s) · "
                    f"consensus reached", expanded=True,
                ):
                    if _issue_urls:
                        for u in _issue_urls:
                            st.markdown(f"- [{u}]({u})")
                    pipeline_row = df[df["NCTId"] == nct] if not df.empty else pd.DataFrame()
                    if not pipeline_row.empty:
                        pr = pipeline_row.iloc[0]
                        st.markdown("**Pipeline classification:**")
                        st.dataframe(pd.DataFrame({
                            "Axis": list(_MODERATOR_AXES),
                            "Pipeline label": [pr.get(a, "—") for a in _MODERATOR_AXES],
                        }), hide_index=True, width="stretch")

                    st.markdown("**Proposed correction (from consensus):**")
                    st.caption(
                        "Open the linked issue(s) to read the reviewer rationale. "
                        "Use the form below to record your decision; it will append "
                        f"to `{MODERATOR_VALIDATIONS_PATH}` and tag the GitHub issue."
                    )

                    _decision = st.radio(
                        "Decision",
                        options=["Approve correction", "Reject correction",
                                 "Defer — needs more info"],
                        key=f"mod_decision_{nct}",
                        horizontal=True,
                    )
                    _rationale = st.text_area(
                        "Rationale (recorded with the decision; one paragraph max)",
                        key=f"mod_rationale_{nct}",
                        placeholder="e.g. confirmed via NCT registry — pediatric "
                                    "neuroblastoma trial, GD2 target verified in "
                                    "intervention description.",
                    )
                    if st.button(
                        "Record decision",
                        key=f"mod_record_{nct}",
                        type="primary",
                    ):
                        # Append a record per axis (pipeline-label remains the
                        # baseline; moderator_label is what we'll use to compute
                        # κ, ground-truth coverage, and override JSON).
                        from datetime import datetime as _dt_mod
                        ts = _dt_mod.utcnow().isoformat() + "Z"
                        for ax in _MODERATOR_AXES:
                            _pipeline_label = (
                                str(pr.get(ax, "")) if not pipeline_row.empty else ""
                            )
                            _append_moderator_validation({
                                "nct_id": nct,
                                "axis": ax,
                                "pipeline_label": _pipeline_label,
                                # For Approve we trust the consensus block;
                                # the actual proposed_correction value is in
                                # the issue body — promote_consensus_flags.py
                                # extracts it. Here we record decision + axis.
                                "moderator_label": (
                                    "<from-issue>" if _decision.startswith("Approve")
                                    else _pipeline_label  # Reject => keep pipeline
                                ),
                                "decision": _decision,
                                "timestamp": ts,
                                "source": "flag",
                                "moderator": os.environ.get("USER", "ptjeong"),
                                "rationale": _rationale,
                                "issue_url": _issue_urls[0] if _issue_urls else "",
                            })
                        st.success(
                            f"Recorded {_decision.lower()} for {nct}. Run "
                            "`scripts/promote_consensus_flags.py` to apply "
                            "approved corrections to llm_overrides.json."
                        )
                        # Light-touch label nudge: we don't have an
                        # authenticated GH session here in Streamlit, so the
                        # label tagging is the moderator's job (one click on
                        # the issue page). The promote script automates the
                        # llm_overrides.json patch + closes the issue.

        st.divider()

        # ===== Mode B: Random validation =====
        st.markdown("### Mode B — Random validation")
        st.caption(
            "Sample a random trial from the current snapshot, review every "
            "axis, and confirm or correct. Each row you submit grows the "
            "moderator-validated pool used to compute the per-axis Cohen's κ "
            "below. Stratified to upweight low-represented branches."
        )

        if df_filt.empty:
            st.info("No trials in the current filter — adjust filters to use this mode.")
        else:
            # Stratify by Branch so heme + solid + unknown each get sampled
            # in roughly equal proportions instead of dataset-natural
            # frequencies (otherwise solid/unknown trials almost never
            # surface for review).
            import random as _rand_mod
            if (
                "rand_validation_nct" not in st.session_state
                or st.button("Draw a different random trial", key="mod_redraw")
            ):
                # Stratified random pick: bucket by branch, pick a branch
                # uniformly, then pick a trial uniformly from that branch.
                _branch_buckets = {
                    b: df_filt[df_filt["Branch"] == b]["NCTId"].tolist()
                    for b in df_filt["Branch"].dropna().unique()
                }
                _branch_buckets = {b: ids for b, ids in _branch_buckets.items() if ids}
                if _branch_buckets:
                    _picked_branch = _rand_mod.choice(list(_branch_buckets.keys()))
                    st.session_state["rand_validation_nct"] = _rand_mod.choice(
                        _branch_buckets[_picked_branch]
                    )

            _rand_nct = st.session_state.get("rand_validation_nct")
            if _rand_nct:
                _rand_row = df_filt[df_filt["NCTId"] == _rand_nct]
                if not _rand_row.empty:
                    _rec = _rand_row.iloc[0]
                    st.markdown(
                        f"**[{_rand_nct}](https://clinicaltrials.gov/study/{_rand_nct})** "
                        f"— {_rec.get('BriefTitle', '')[:140]}"
                    )
                    if _rec.get("BriefSummary"):
                        with st.expander("Trial summary"):
                            st.write(str(_rec.get("BriefSummary"))[:2500])

                    # Per-axis confirm/correct widget
                    _corrections: dict[str, str] = {}
                    for ax in _MODERATOR_AXES:
                        _pl = str(_rec.get(ax, "—"))
                        _corrections[ax] = st.text_input(
                            f"{ax} (pipeline: `{_pl}`)",
                            value=_pl,
                            key=f"mod_rand_{ax}_{_rand_nct}",
                            help="Edit if the pipeline label is wrong; leave as-is to confirm.",
                        )
                    _rand_rationale = st.text_area(
                        "Optional notes",
                        key=f"mod_rand_notes_{_rand_nct}",
                    )
                    if st.button(
                        "Submit validation",
                        key=f"mod_rand_submit_{_rand_nct}",
                        type="primary",
                    ):
                        from datetime import datetime as _dt_mod2
                        ts = _dt_mod2.utcnow().isoformat() + "Z"
                        for ax, mod_lbl in _corrections.items():
                            _append_moderator_validation({
                                "nct_id": _rand_nct,
                                "axis": ax,
                                "pipeline_label": str(_rec.get(ax, "")),
                                "moderator_label": mod_lbl.strip(),
                                "decision": (
                                    "confirmed"
                                    if mod_lbl.strip() == str(_rec.get(ax, ""))
                                    else "corrected"
                                ),
                                "timestamp": ts,
                                "source": "random",
                                "moderator": os.environ.get("USER", "ptjeong"),
                                "rationale": _rand_rationale,
                                "issue_url": "",
                            })
                        st.success(
                            f"Recorded validation for {_rand_nct} across "
                            f"{len(_corrections)} axes. Drawing a fresh trial…"
                        )
                        # Force a redraw on next rerun
                        st.session_state.pop("rand_validation_nct", None)
                        st.rerun()

        st.divider()

        # ===== Stats panel: per-axis Cohen's κ =====
        st.markdown("### Per-axis agreement (pipeline vs moderator)")
        st.caption(
            "Computed across every record in `moderator_validations.json` "
            "where `moderator_label` is concrete (placeholder values from "
            "approved-flag rows are excluded). Cohen's κ reported when N ≥ 10."
        )

        validations = _load_moderator_validations()
        if not validations:
            st.info("No moderator validations recorded yet.")
        else:
            stats_rows = []
            for ax in _MODERATOR_AXES:
                ax_records = [
                    r for r in validations
                    if r.get("axis") == ax
                    and r.get("moderator_label") not in (None, "", "<from-issue>")
                ]
                if not ax_records:
                    stats_rows.append({
                        "Axis": ax, "N": 0,
                        "% agreement": "—", "Cohen's κ": "—",
                    })
                    continue
                pipe_labels = [str(r["pipeline_label"]) for r in ax_records]
                mod_labels = [str(r["moderator_label"]) for r in ax_records]
                agreement = (
                    sum(1 for a, b in zip(pipe_labels, mod_labels) if a == b)
                    / len(ax_records)
                )
                kappa = _cohens_kappa(pipe_labels, mod_labels)
                stats_rows.append({
                    "Axis": ax,
                    "N": len(ax_records),
                    "% agreement": f"{agreement*100:.1f}%",
                    "Cohen's κ": f"{kappa:.3f}" if (
                        kappa is not None and len(ax_records) >= 10
                    ) else (
                        "needs N≥10" if kappa is not None else "—"
                    ),
                })
            st.dataframe(
                pd.DataFrame(stats_rows),
                hide_index=True, width="stretch",
            )

            with st.expander("Raw validation log (newest first)"):
                _vlog_df = pd.DataFrame(validations).sort_values(
                    "timestamp", ascending=False,
                )
                st.dataframe(_vlog_df, hide_index=True, width="stretch")
                st.download_button(
                    "Download moderator_validations.json",
                    data=open(MODERATOR_VALIDATIONS_PATH, "rb").read()
                        if os.path.exists(MODERATOR_VALIDATIONS_PATH) else b"[]",
                    file_name="moderator_validations.json",
                    mime="application/json",
                )
